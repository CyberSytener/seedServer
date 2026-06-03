"""AgentSession runtime loop (Phase 7 — P7-05 / P7-07 / P7-08).

Orchestrates: user message → LLM planning → tool execution → response.

All tool execution routes through ``ActionRouter.execute_action()``
(idempotency, guardrails, saga escalation) — blocks are **never** called directly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional

from app.core.agent.budget import AgentBudget
from app.core.agent.models import (
    AgentResponse,
    AgentSessionData,
    AgentSessionMessage,
    AgentTrace,
    AgentTraceStep,
    MessageRole,
    PendingConfirmation,
    PersonaOverrides,
    SessionStatus,
)
from app.core.agent.session_store import AgentSessionStore
from app.core.agent.tool_registry import ToolRegistry
from app.core.agent.ui_context import UIContextPack

logger = logging.getLogger(__name__)

# Maximum LLM ↔ tool iterations per single ``process_message`` call.
MAX_LOOP_ITERATIONS = 5

# ---------------------------------------------------------------------------
# Tool-call parsing helpers
# ---------------------------------------------------------------------------

_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)


def parse_tool_calls(llm_text: str) -> List[Dict[str, Any]]:
    """Extract ``[{name, arguments}]`` blocks from LLM text.

    The expected format inside ``<tool_call>`` tags is JSON with
    at least ``name`` and ``arguments``.
    """
    results: List[Dict[str, Any]] = []
    for m in _TOOL_CALL_RE.finditer(llm_text):
        try:
            obj = json.loads(m.group(1))
            if "name" in obj:
                results.append(obj)
        except (json.JSONDecodeError, TypeError):
            continue
    return results


def strip_tool_calls(llm_text: str) -> str:
    """Remove ``<tool_call>…</tool_call>`` tags, returning only prose."""
    return _TOOL_CALL_RE.sub("", llm_text).strip()


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_prompt(
    *,
    system_prompt: str,
    history: List[AgentSessionMessage],
    tool_manifests: List[Dict[str, Any]],
    user_message: str,
    tool_results: Optional[List[Dict[str, Any]]] = None,
    ui_context: Optional[str] = None,
    repo_context: Optional[str] = None,
) -> str:
    """Assemble the LLM prompt including history, tools, context, and user message."""
    parts: List[str] = []

    if tool_manifests:
        tools_json = json.dumps(tool_manifests, indent=2)
        parts.append(
            "You have access to the following tools. To call a tool, "
            "output a <tool_call>{\"name\": \"tool_name\", \"arguments\": {…}}</tool_call> block.\n\n"
            f"Available tools:\n{tools_json}"
        )

    # UI context pack (latest push from client) — P7-08
    if ui_context:
        parts.append(ui_context)

    # Repo context pack (GitHub content) — P0-30
    if repo_context:
        parts.append(repo_context)

    # Conversation history (last 20 messages to stay within limits)
    for msg in history[-20:]:
        role = msg.role.value if isinstance(msg.role, MessageRole) else msg.role
        content = msg.content or ""
        sender = msg.sender_user_id
        if role == "tool_call":
            parts.append(f"[Tool Call] {msg.tool_name}: {msg.tool_input}")
        elif role == "tool_result":
            parts.append(f"[Tool Result] {msg.tool_name}: {msg.tool_output}")
        elif role == "context":
            # Context messages are handled via ui_context parameter; skip in history
            continue
        elif sender:
            parts.append(f"[{role.capitalize()} ({sender})] {content}")
        else:
            parts.append(f"[{role.capitalize()}] {content}")

    # Append fresh tool results from current iteration (not yet persisted)
    if tool_results:
        for tr in tool_results:
            parts.append(f"[Tool Result] {tr['name']}: {tr['output']}")

    parts.append(f"[User] {user_message}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# AgentSession
# ---------------------------------------------------------------------------

class AgentEventEmitter:
    """Protocol for streaming agent events to external consumers (e.g. WebSocket).

    Subclass and override ``emit`` to publish events to Redis, WS, etc.
    The default implementation is a no-op.
    """

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """Emit a single event. *event_type* is an ``AgentMessageType`` value."""

    async def emit_partial(self, session_id: str, content: str, index: int) -> None:
        await self.emit("agent.partial", {"agent_session_id": session_id, "content": content, "index": index})

    async def emit_tool_call_start(self, session_id: str, tool_name: str, input_preview: Optional[Dict[str, Any]] = None) -> None:
        await self.emit("agent.tool_call_start", {"agent_session_id": session_id, "tool_name": tool_name, "input_preview": input_preview})

    async def emit_tool_call_result(self, session_id: str, tool_name: str, output_summary: Optional[str] = None, duration_ms: Optional[float] = None, status: str = "success") -> None:
        await self.emit("agent.tool_call_result", {"agent_session_id": session_id, "tool_name": tool_name, "output_summary": output_summary, "duration_ms": duration_ms, "status": status})

    async def emit_budget_update(self, session_id: str, budget_snapshot: Dict[str, Any]) -> None:
        await self.emit("agent.budget_update", {"agent_session_id": session_id, "budget_snapshot": budget_snapshot})

    async def emit_confirmation_request(self, session_id: str, confirmation_id: str, tool_name: str, proposed_input: Dict[str, Any], description: Optional[str] = None) -> None:
        await self.emit("agent.confirmation_request", {"agent_session_id": session_id, "confirmation_id": confirmation_id, "tool_name": tool_name, "proposed_input": proposed_input, "description": description})

    async def emit_final(self, session_id: str, text: str, artifacts: Optional[List[Dict[str, Any]]] = None, trace: Optional[List[Dict[str, Any]]] = None, budget_snapshot: Optional[Dict[str, Any]] = None, stopped_reason: Optional[str] = None) -> None:
        await self.emit("agent.final", {"agent_session_id": session_id, "text": text, "artifacts": artifacts or [], "trace": trace or [], "budget_snapshot": budget_snapshot or {}, "stopped_reason": stopped_reason})

    async def emit_error(self, session_id: str, error: str, recoverable: bool = False) -> None:
        await self.emit("agent.error", {"agent_session_id": session_id, "error": error, "recoverable": recoverable})


class AgentSession:
    """High-level orchestrator for a single agent session.

    All tool execution is routed through ``ActionRouter.execute_action()``.
    """

    def __init__(
        self,
        *,
        session_store: AgentSessionStore,
        tool_registry: ToolRegistry,
        action_router: Any,          # ActionRouter (sync .execute_action)
        llm_service: Any,            # UnifiedLLMService (async .agenerate_with_metadata)
        artifact_store: Any = None,  # ArtifactStore (sync .store)
        persona_loader: Any = None,  # PersonaPromptLoader (sync .get_persona_prompt)
        auth_context: Any = None,    # UnifiedAuthContext
        audit_emitter: Optional[Callable[..., None]] = None,
        sandbox_dispatcher: Any = None,  # SandboxDispatcher (sync .dispatch)
        sandbox_enabled: bool = False,
        nesting_depth: int = 0,
        max_nesting_depth: int = 3,
        event_emitter: Optional[AgentEventEmitter] = None,
        tenant_governance: Any = None,  # TenantGovernanceService
        marketplace_service: Any = None,  # MarketplaceService
    ) -> None:
        self.session_store = session_store
        self.tool_registry = tool_registry
        self.action_router = action_router
        self.llm_service = llm_service
        self.artifact_store = artifact_store
        self.persona_loader = persona_loader
        self.auth_context = auth_context
        self.audit_emitter = audit_emitter
        self.sandbox_dispatcher = sandbox_dispatcher
        self.sandbox_enabled = sandbox_enabled
        self.nesting_depth = nesting_depth
        self.max_nesting_depth = max_nesting_depth
        self.event_emitter = event_emitter or AgentEventEmitter()
        self.tenant_governance = tenant_governance
        self.marketplace_service = marketplace_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def spawn_child_session(
        self,
        *,
        parent_session_id: str,
        persona_id: str = "seed",
        tool_scopes: Optional[List[str]] = None,
        budget_limits: Optional[Dict[str, Any]] = None,
        task_prompt: str,
        parent_budget: Optional[AgentBudget] = None,
    ) -> "AgentResponse":
        """Spawn a child session, run it to completion, return its response.

        Security invariants enforced server-side:
        - ``tool_scopes`` must be a subset of parent's ``tool_scopes``.
        - Child budget ≤ parent remaining (via ``parent_budget.create_child``).
        - Nesting depth ≤ ``max_nesting_depth``.

        Returns the child's ``AgentResponse`` (parent waits synchronously).
        """
        # --- Guard: nesting depth ---
        if self.nesting_depth >= self.max_nesting_depth:
            return AgentResponse(
                text=f"Cannot spawn child: max nesting depth ({self.max_nesting_depth}) reached.",
                stopped_reason="max_nesting_depth_exceeded",
            )

        # --- Load parent session for scope validation ---
        parent_session = await self.session_store.get_session(parent_session_id)
        if parent_session is None:
            return AgentResponse(
                text="Parent session not found.",
                stopped_reason="parent_session_not_found",
            )

        # --- Validate tool_scopes subset ---
        parent_scopes = set(parent_session.tool_scopes)
        child_scopes = list(tool_scopes) if tool_scopes else list(parent_session.tool_scopes)
        if not set(child_scopes).issubset(parent_scopes):
            escalated = set(child_scopes) - parent_scopes
            return AgentResponse(
                text=f"Scope escalation denied: {sorted(escalated)} not in parent scopes.",
                stopped_reason="scope_escalation_denied",
            )

        # --- Create child budget via parent hierarchy (P0-19) ---
        if parent_budget is not None:
            limits = budget_limits or {}
            child_budget = parent_budget.create_child(
                max_tokens=limits.get("max_total_tokens"),
                max_cost=limits.get("max_total_cost_units"),
                max_tool_calls=limits.get("max_tool_calls", 10),
                max_wall_time=limits.get("max_wall_time_seconds"),
                per_tool_limits=limits.get("per_tool_limits"),
            )
            child_budget_config = child_budget.to_config()
        else:
            child_budget_config = budget_limits or parent_session.budget_config

        # --- Create child session row ---
        child_session_data = AgentSessionData(
            user_id=parent_session.user_id,
            persona_id=persona_id,
            persona_overrides=dict(parent_session.persona_overrides),
            budget_config=child_budget_config,
            tool_scopes=child_scopes,
            parent_session_id=parent_session_id,
        )
        await self.session_store.create_session(child_session_data)

        # --- Build child AgentSession with incremented nesting depth ---
        child_agent = AgentSession(
            session_store=self.session_store,
            tool_registry=self.tool_registry,
            action_router=self.action_router,
            llm_service=self.llm_service,
            artifact_store=self.artifact_store,
            persona_loader=self.persona_loader,
            auth_context=self.auth_context,
            audit_emitter=self.audit_emitter,
            sandbox_dispatcher=self.sandbox_dispatcher,
            sandbox_enabled=self.sandbox_enabled,
            nesting_depth=self.nesting_depth + 1,
            max_nesting_depth=self.max_nesting_depth,
        )

        # --- Run child to completion (parent waits) ---
        child_response = await child_agent.process_message(
            session_id=child_session_data.session_id,
            user_message=task_prompt,
        )

        # --- Mark child session completed ---
        child_session_data.status = SessionStatus.COMPLETED
        await self.session_store.update_session(child_session_data)

        # Emit audit for sub-agent spawn
        self._emit_audit("agent_child_spawned", {
            "parent_session_id": parent_session_id,
            "child_session_id": child_session_data.session_id,
            "nesting_depth": self.nesting_depth + 1,
            "persona_id": persona_id,
            "tool_scopes": child_scopes,
        })

        return child_response

    async def delegate_parallel(
        self,
        *,
        parent_session_id: str,
        children_specs: List[Dict[str, Any]],
        parent_budget: Optional[AgentBudget] = None,
        max_parallel: int = 5,
    ) -> List["AgentResponse"]:
        """Spawn multiple child sessions and execute them in parallel.

        ``children_specs`` is a list of dicts, each with:
        - ``task`` (str): the task prompt for the child
        - ``persona_id`` (str, optional): persona for the child
        - ``tool_scopes`` (List[str], optional): scope subset
        - ``budget`` (Dict, optional): per-child budget overrides

        Returns ``List[AgentResponse]`` — one per child, in the same order
        as ``children_specs``.  If a child fails, its response carries the
        error; surviving children are unaffected.
        """
        n = len(children_specs)
        if n == 0:
            return []
        if n > max_parallel:
            return [AgentResponse(
                text=f"Too many parallel children: {n} > {max_parallel}.",
                stopped_reason="max_parallel_children_exceeded",
            )]

        # --- Guard: nesting depth ---
        if self.nesting_depth >= self.max_nesting_depth:
            return [AgentResponse(
                text=f"Cannot spawn children: max nesting depth ({self.max_nesting_depth}) reached.",
                stopped_reason="max_nesting_depth_exceeded",
            )]

        # --- Load parent session ---
        parent_session = await self.session_store.get_session(parent_session_id)
        if parent_session is None:
            return [AgentResponse(
                text="Parent session not found.",
                stopped_reason="parent_session_not_found",
            )]

        # --- Split budget among children ---
        child_budgets: Optional[List[AgentBudget]] = None
        if parent_budget is not None:
            child_budgets = parent_budget.split_budget(n)

        # --- Spawn coroutines ---
        async def _run_child(idx: int, spec: Dict[str, Any]) -> AgentResponse:
            try:
                return await self.spawn_child_session(
                    parent_session_id=parent_session_id,
                    persona_id=spec.get("persona_id", "seed"),
                    tool_scopes=spec.get("tool_scopes"),
                    budget_limits=spec.get("budget"),
                    task_prompt=spec["task"],
                    parent_budget=child_budgets[idx] if child_budgets else None,
                )
            except Exception as exc:
                logger.warning(
                    "Parallel child %d failed: %s", idx, exc, exc_info=True,
                )
                return AgentResponse(
                    text=f"Child {idx} failed: {exc}",
                    stopped_reason="child_error",
                )

        results = await asyncio.gather(
            *[_run_child(i, spec) for i, spec in enumerate(children_specs)],
        )

        self._emit_audit("agent_parallel_delegation", {
            "parent_session_id": parent_session_id,
            "child_count": n,
            "nesting_depth": self.nesting_depth + 1,
        })

        return list(results)

    async def process_message(
        self,
        session_id: str,
        user_message: str,
    ) -> AgentResponse:
        """Process a user message through the agent loop.

        Returns an ``AgentResponse`` containing the final text,
        artifacts, budget snapshot, trace steps, and pending confirmations.
        """
        # 1. Load session state + history
        session = await self.session_store.get_session(session_id)
        if session is None:
            return AgentResponse(
                text="Session not found.",
                stopped_reason="session_not_found",
            )
        if session.status != SessionStatus.ACTIVE:
            return AgentResponse(
                text=f"Session is {session.status.value}.",
                stopped_reason="session_inactive",
            )

        history = await self.session_store.get_messages(session_id)
        budget = AgentBudget.from_config(session.budget_config)

        trace: List[Dict[str, Any]] = []
        new_messages: List[AgentSessionMessage] = []
        artifacts: List[Dict[str, Any]] = []
        new_pending: List[Dict[str, Any]] = list(session.pending_confirmations)

        # Resolve sender user_id for attribution (P0-25 / P0-26)
        _sender_uid = (
            getattr(self.auth_context, "user_id", None)
            or getattr(self.auth_context, "subject", None)
        ) if self.auth_context else None

        # 2. Check for confirmation resolution
        confirm_result = self._resolve_confirmation(
            user_message, new_pending,
        )
        if confirm_result is not None:
            # User confirmed or cancelled — persist and process the result
            if confirm_result["action"] == "confirmed":
                # Execute the confirmed tool
                pc = confirm_result["confirmation"]
                tool_result = await self._execute_tool(
                    pc["tool_name"],
                    pc.get("tool_input", {}),
                    session=session,
                    budget=budget,
                    trace=trace,
                    skip_confirmation=True,
                    user_id=_sender_uid,
                )
                new_messages.append(AgentSessionMessage(
                    session_id=session_id,
                    role=MessageRole.TOOL_RESULT,
                    tool_name=pc["tool_name"],
                    tool_output=json.dumps(tool_result.get("result", "")),
                    budget_snapshot=json.dumps(budget.snapshot()),
                ))
            elif confirm_result["action"] == "cancelled":
                trace.append({
                    "step": "confirmation_cancelled",
                    "tool_name": confirm_result["confirmation"]["tool_name"],
                })
            # Update session pending confirmations
            session.pending_confirmations = new_pending
            await self.session_store.update_session(session)

        # 3. Resolve persona
        system_prompt = self._resolve_persona(session)

        # 4 + 5 + 6 + 7 + 8: Iterative LLM ↔ tool loop
        tool_manifests = self.tool_registry.list_tools_for_llm(session.tool_scopes)
        current_tool_results: List[Dict[str, Any]] = []

        # Resolve latest UI context from history (P7-08)
        ui_context_text: Optional[str] = None
        for msg in reversed(history):
            role = msg.role.value if isinstance(msg.role, MessageRole) else msg.role
            if role == "context" and msg.content:
                try:
                    pack = UIContextPack.model_validate_json(msg.content)
                    ui_context_text = pack.to_prompt_section()
                except Exception:
                    logger.warning("Failed to parse UI context pack from history")
                break

        # Resolve latest repo context from history (P0-30)
        repo_context_text: Optional[str] = None
        for msg in reversed(history):
            role = msg.role.value if isinstance(msg.role, MessageRole) else msg.role
            if role == "context" and msg.content:
                try:
                    raw = json.loads(msg.content)
                    if isinstance(raw, dict) and raw.get("type") == "repo":
                        from app.core.agent.repo_context import RepoContextPack as _RCP
                        rpack = _RCP.from_dict(raw)
                        repo_context_text = rpack.to_prompt_section()
                        break
                except Exception:
                    pass

        # Record user message
        new_messages.insert(0, AgentSessionMessage(
            session_id=session_id,
            role=MessageRole.USER,
            content=user_message,
            sender_user_id=_sender_uid,
        ))

        final_text = ""
        stopped_reason: Optional[str] = None

        # Tenant quota cache — checked once per process_message call (P0-38)
        _tenant_quota_cache: Optional[Dict[str, Any]] = None

        for iteration in range(MAX_LOOP_ITERATIONS):
            # Tenant quota gate (P0-38) — check once, cache for loop duration
            if session.tenant_id and self.tenant_governance and _tenant_quota_cache is None:
                try:
                    _tenant_quota_cache = self.tenant_governance.check_quota(
                        tenant_id=session.tenant_id,
                        operation="agent_cost_usd",
                        project_id=session.project_id,
                    )
                except Exception:
                    logger.warning(
                        "Tenant quota check failed for session %s, allowing",
                        session_id, exc_info=True,
                    )
                    _tenant_quota_cache = {"allowed": True}

            if _tenant_quota_cache and not _tenant_quota_cache.get("allowed", True):
                stopped_reason = "tenant_quota_exceeded"
                final_text = "Your organization's usage quota has been exceeded. Please contact your administrator."
                break

            # Budget pre-check
            budget_stop = budget.pre_check()
            if budget_stop:
                stopped_reason = f"budget_exceeded: {budget_stop}"
                final_text = final_text or f"I've reached my budget limit ({budget_stop}). Please start a new session or increase the budget."
                break

            # Build prompt
            prompt = build_prompt(
                system_prompt=system_prompt,
                history=history + new_messages,
                tool_manifests=tool_manifests if iteration == 0 else [],
                user_message=user_message if iteration == 0 else "",
                tool_results=current_tool_results if iteration > 0 else None,
                ui_context=ui_context_text if iteration == 0 else None,
                repo_context=repo_context_text if iteration == 0 else None,
            )

            # LLM call
            gen_result = await self.llm_service.agenerate_with_metadata(
                prompt=prompt,
                system_instruction=system_prompt,
            )

            # Consume LLM budget
            budget.consume_llm(
                tokens=gen_result.tokens_in + gen_result.tokens_out,
                cost_units=gen_result.cost_usd,
                user_id=_sender_uid,
            )

            # Record tenant usage for LLM call (P0-37)
            _llm_tokens = gen_result.tokens_in + gen_result.tokens_out
            _llm_idem_key = f"{session_id}:llm:{iteration}"
            self._record_tenant_usage_fire_and_forget(
                session=session,
                operation="agent_llm",
                quantity=float(_llm_tokens),
                cost_usd=gen_result.cost_usd,
                actor_id=_sender_uid,
                idempotency_key=_llm_idem_key,
            )

            # Emit budget update after LLM call
            await self.event_emitter.emit_budget_update(session_id, budget.snapshot())

            trace.append({
                "step": "llm_call",
                "iteration": iteration,
                "tokens_in": gen_result.tokens_in,
                "tokens_out": gen_result.tokens_out,
                "budget_snapshot": budget.snapshot(),
            })

            # Parse tool calls from response
            tool_calls = parse_tool_calls(gen_result.text)
            prose = strip_tool_calls(gen_result.text)

            if not tool_calls:
                # No more tool calls — final answer
                final_text = prose or gen_result.text
                new_messages.append(AgentSessionMessage(
                    session_id=session_id,
                    role=MessageRole.AGENT,
                    content=final_text,
                    budget_snapshot=json.dumps(budget.snapshot()),
                ))
                break

            # Execute each tool call
            current_tool_results = []
            hit_confirmation = False

            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc.get("arguments", {})

                # 7a. Check allowlist
                if not self.tool_registry.is_tool_allowed(tool_name, session.tool_scopes):
                    trace.append({"step": "tool_denied", "tool_name": tool_name})
                    current_tool_results.append({
                        "name": tool_name,
                        "output": f"Error: tool '{tool_name}' is not allowed in this session.",
                    })
                    continue

                # 7b. Budget check
                tool_budget_stop = budget.pre_check_tool(tool_name)
                if tool_budget_stop:
                    stopped_reason = f"tool_budget_exceeded: {tool_budget_stop}"
                    current_tool_results.append({
                        "name": tool_name,
                        "output": f"Error: budget exceeded for tool '{tool_name}': {tool_budget_stop}",
                    })
                    continue

                # 7c. Confirmation gate
                if self.tool_registry.permissions.requires_confirmation(tool_name):
                    # Check if this tool+args combo is already pre-confirmed
                    if not self._is_pre_confirmed(tool_name, tool_args, new_pending):
                        pc = PendingConfirmation(
                            tool_name=tool_name,
                            tool_input=tool_args,
                            explanation=f"Tool '{tool_name}' requires your confirmation before execution.",
                        )
                        new_pending.append(pc.to_dict())
                        trace.append({
                            "step": "confirmation_required",
                            "tool_name": tool_name,
                            "confirmation_id": pc.confirmation_id,
                        })
                        # Emit confirmation request event
                        await self.event_emitter.emit_confirmation_request(
                            session_id, pc.confirmation_id, tool_name,
                            tool_args, pc.explanation,
                        )
                        hit_confirmation = True
                        continue

                # Emit tool call start event
                await self.event_emitter.emit_tool_call_start(
                    session_id, tool_name,
                    {k: str(v)[:200] for k, v in (tool_args or {}).items()},
                )

                # 7d + 7e. Build action → execute via ActionRouter
                exec_result = await self._execute_tool(
                    tool_name, tool_args,
                    session=session, budget=budget, trace=trace,
                    user_id=_sender_uid,
                )

                # 7f. Record tool call + result
                new_messages.append(AgentSessionMessage(
                    session_id=session_id,
                    role=MessageRole.TOOL_CALL,
                    tool_name=tool_name,
                    tool_input=json.dumps(tool_args),
                    budget_snapshot=json.dumps(budget.snapshot()),
                ))
                new_messages.append(AgentSessionMessage(
                    session_id=session_id,
                    role=MessageRole.TOOL_RESULT,
                    tool_name=tool_name,
                    tool_output=json.dumps(exec_result.get("result", "")),
                    budget_snapshot=json.dumps(budget.snapshot()),
                ))
                current_tool_results.append({
                    "name": tool_name,
                    "output": json.dumps(exec_result.get("result", "")),
                })

                # Emit tool call result + budget update events
                _status = exec_result.get("status", "success")
                _output = str(exec_result.get("result", ""))[:500]
                _dur = trace[-1].get("duration_ms") if trace else None
                await self.event_emitter.emit_tool_call_result(
                    session_id, tool_name, _output, _dur, _status,
                )
                await self.event_emitter.emit_budget_update(session_id, budget.snapshot())

            if hit_confirmation:
                # Stop the loop — need user confirmation first
                final_text = prose or "I need your confirmation before proceeding."
                new_messages.append(AgentSessionMessage(
                    session_id=session_id,
                    role=MessageRole.CONFIRMATION_REQUEST,
                    content=json.dumps([p for p in new_pending]),
                ))
                break

            if stopped_reason:
                break

            # Continue to next iteration (re-call LLM with tool results)

        else:
            # Exhausted MAX_LOOP_ITERATIONS
            stopped_reason = "max_iterations_reached"
            if not final_text:
                final_text = "I've reached the maximum number of steps for this message."

        # 9. Persist messages
        for msg in new_messages:
            await self.session_store.append_message(msg)

        # Update session state
        session.pending_confirmations = new_pending
        session.budget_config = budget.to_config()
        await self.session_store.update_session(session)

        # 10. Store artifacts (with structured trace)
        structured_trace = self._build_structured_trace(
            session_id=session_id,
            user_id=session.user_id,
            raw_trace=trace,
            budget=budget,
            parent_session_id=session.parent_session_id,
        )

        if self.artifact_store is not None:
            try:
                art_ref = self.artifact_store.store(
                    saga_id=session_id,
                    step="agent_response",
                    kind="agent_trace",
                    payload=structured_trace.to_dict(),
                )
                artifacts.append(art_ref)
            except Exception:
                logger.warning("Failed to store agent artifact", exc_info=True)

        # Emit audit events (P7-07)
        self._emit_audit("agent_message_processed", {
            "session_id": session_id,
            "user_id": session.user_id,
            "trace_id": structured_trace.trace_id,
            "tool_calls": len([t for t in trace if t.get("step") == "tool_executed"]),
            "stopped_reason": stopped_reason,
        })

        # 11. Return response
        persona_overrides = PersonaOverrides.from_dict(session.persona_overrides)
        persona_meta: Dict[str, Any] = {"persona_id": session.persona_id}
        if persona_overrides.display_name:
            persona_meta["display_name"] = persona_overrides.display_name
        if persona_overrides.voice_id:
            persona_meta["voice_id"] = persona_overrides.voice_id

        # Emit final or error event over WS
        if stopped_reason and (
            stopped_reason.startswith("budget_exceeded")
            or stopped_reason == "tenant_quota_exceeded"
        ):
            await self.event_emitter.emit_error(session_id, stopped_reason, recoverable=False)
        else:
            await self.event_emitter.emit_final(
                session_id, final_text, artifacts, trace,
                budget.snapshot(), stopped_reason,
            )

        return AgentResponse(
            text=final_text,
            artifacts=artifacts,
            budget_snapshot=budget.snapshot(),
            trace=trace,
            pending_confirmations=new_pending,
            stopped_reason=stopped_reason,
            persona_meta=persona_meta,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_persona(self, session: AgentSessionData) -> str:
        """Resolve persona system prompt from session config.

        Applies persona overrides (P7-10):
        1. Load base prompt from PersonaPromptLoader (or use ``system_prompt`` override)
        2. Append ``system_prompt_append`` if set in overrides
        """
        overrides = PersonaOverrides.from_dict(session.persona_overrides)

        # If a full system_prompt override is set, use it as base
        if session.persona_overrides.get("system_prompt"):
            base_prompt = session.persona_overrides["system_prompt"]
        elif self.persona_loader is not None:
            try:
                result = self.persona_loader.get_persona_prompt(session.persona_id)
                base_prompt = result.prompt_text
            except Exception:
                logger.warning("Failed to load persona %s", session.persona_id)
                base_prompt = "You are a helpful assistant."
        else:
            base_prompt = "You are a helpful assistant."

        # Apply system_prompt_append overlay (P7-10)
        if overrides.system_prompt_append:
            base_prompt = base_prompt.rstrip() + "\n\n" + overrides.system_prompt_append

        return base_prompt

    def _resolve_confirmation(
        self,
        user_message: str,
        pending: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Check if user message confirms/cancels a pending confirmation.

        Returns ``{action: "confirmed"|"cancelled", confirmation: dict}``
        or ``None`` if not a confirmation message.
        """
        lower = user_message.lower().strip()

        # Simple pattern: "confirm <id>" or "cancel <id>"
        for prefix, action in [("confirm ", "confirmed"), ("cancel ", "cancelled")]:
            if lower.startswith(prefix):
                target_id = user_message[len(prefix):].strip()
                for i, p in enumerate(pending):
                    if p.get("confirmation_id") == target_id:
                        removed = pending.pop(i)
                        return {"action": action, "confirmation": removed}

        # Also accept "yes" / "no" if exactly one pending confirmation
        if lower in ("yes", "confirm", "ok", "proceed") and len(pending) == 1:
            removed = pending.pop(0)
            return {"action": "confirmed", "confirmation": removed}
        if lower in ("no", "cancel", "deny", "reject") and len(pending) == 1:
            removed = pending.pop(0)
            return {"action": "cancelled", "confirmation": removed}

        return None

    def _is_pre_confirmed(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        pending: List[Dict[str, Any]],
    ) -> bool:
        """Check if this tool call was already user-confirmed."""
        # A tool is pre-confirmed if the user already issued a confirm
        # for a matching pending confirmation (already resolved in step 2).
        # In this implementation, if a confirmation is still in pending,
        # it has NOT been confirmed yet.
        return False

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        *,
        session: AgentSessionData,
        budget: AgentBudget,
        trace: List[Dict[str, Any]],
        skip_confirmation: bool = False,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build an Action and execute it through ActionRouter or sandbox.

        If the tool has ``sandbox_required=true`` in tool_permissions and
        ``sandbox_enabled`` is set, routes via ``SandboxDispatcher``.
        Returns ``{"status": ..., "result": ...}`` dict.
        """
        budget.consume_tool_call(tool_name, user_id=user_id)

        # Record tenant usage for tool call (P0-37)
        _tool_idem_key = f"{session.session_id}:tool:{tool_name}:{int(time.monotonic() * 1000)}"
        self._record_tenant_usage_fire_and_forget(
            session=session,
            operation="agent_tool_call",
            quantity=1.0,
            actor_id=user_id,
            idempotency_key=_tool_idem_key,
        )

        permissions = self.tool_registry.permissions
        is_sandbox_required = permissions.sandbox_required(tool_name)

        # --- Sandbox routing decision ---
        if is_sandbox_required:
            if not self.sandbox_enabled or self.sandbox_dispatcher is None:
                # Sandbox required but not available → reject
                trace.append({
                    "step": "tool_rejected",
                    "tool_name": tool_name,
                    "reason": "sandbox_required_but_unavailable",
                    "budget_snapshot": budget.snapshot(),
                })
                self._emit_audit("agent_tool_rejected", {
                    "session_id": session.session_id,
                    "user_id": session.user_id,
                    "tool_name": tool_name,
                    "reason": "sandbox_required_but_unavailable",
                })
                return {
                    "status": "error",
                    "result": None,
                    "error": f"Tool '{tool_name}' requires sandbox execution but sandbox is not enabled.",
                }

            if not permissions.allowed_in_sandbox(tool_name):
                # Config contradiction: sandbox_required=true but allowed_in_sandbox=false
                trace.append({
                    "step": "tool_rejected",
                    "tool_name": tool_name,
                    "reason": "sandbox_required_but_not_allowed",
                    "budget_snapshot": budget.snapshot(),
                })
                return {
                    "status": "error",
                    "result": None,
                    "error": f"Tool '{tool_name}' requires sandbox but is not allowed in sandbox (config contradiction).",
                }

            # Dispatch to sandbox
            loop = asyncio.get_event_loop()
            t0 = time.monotonic()
            sandbox_result = await loop.run_in_executor(
                None,
                lambda: self.sandbox_dispatcher.dispatch(
                    session_id=session.session_id,
                    tool_name=tool_name,
                    tool_input=tool_args,
                ),
            )
            duration_ms = (time.monotonic() - t0) * 1000

            status = sandbox_result.get("status", "error")
            trace.append({
                "step": "tool_executed_sandbox",
                "tool_name": tool_name,
                "rpc_id": sandbox_result.get("rpc_id"),
                "status": status,
                "budget_snapshot": budget.snapshot(),
                "duration_ms": duration_ms,
            })
            self._emit_audit("agent_tool_call_sandbox", {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "tool_name": tool_name,
                "rpc_id": sandbox_result.get("rpc_id"),
                "status": status,
                "duration_ms": duration_ms,
            })
            return {
                "status": status,
                "result": sandbox_result.get("tool_output"),
                "error": sandbox_result.get("error"),
            }

        # --- Local execution (non-sandbox) ---
        action = self.tool_registry.build_action(
            tool_name,
            tool_args,
            session_id=session.session_id,
            user_id=session.user_id,
        )

        # ActionRouter.execute_action() is sync → run in executor
        loop = asyncio.get_event_loop()
        t0 = time.monotonic()
        action_result = await loop.run_in_executor(
            None,
            lambda: self.action_router.execute_action(action),
        )
        duration_ms = (time.monotonic() - t0) * 1000

        trace.append({
            "step": "tool_executed",
            "tool_name": tool_name,
            "action_id": str(action.id),
            "status": action_result.status.value if hasattr(action_result.status, "value") else str(action_result.status),
            "budget_snapshot": budget.snapshot(),
            "duration_ms": duration_ms,
        })

        # Emit tool_call audit event
        self._emit_audit("agent_tool_call", {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "tool_name": tool_name,
            "action_id": str(action.id),
            "status": action_result.status.value if hasattr(action_result.status, "value") else str(action_result.status),
            "duration_ms": duration_ms,
        })

        # Marketplace usage recording (P0-39)
        self._record_marketplace_usage(
            tool_name=tool_name,
            session=session,
            user_id=user_id,
        )

        return {
            "status": action_result.status.value if hasattr(action_result.status, "value") else str(action_result.status),
            "result": action_result.result,
            "error": action_result.error,
        }

    # ------------------------------------------------------------------
    # Telemetry helpers (P7-07)
    # ------------------------------------------------------------------

    def _emit_audit(self, action: str, details: Dict[str, Any]) -> None:
        """Emit an audit event if an audit_emitter is configured."""
        if self.audit_emitter is not None:
            try:
                self.audit_emitter(action=action, details=details)
            except Exception:
                logger.warning("Audit emission failed for %s", action, exc_info=True)

    # ------------------------------------------------------------------
    # Tenant usage recording (P0-37)
    # ------------------------------------------------------------------

    def _record_tenant_usage_fire_and_forget(
        self,
        *,
        session: AgentSessionData,
        operation: str,
        quantity: float = 1.0,
        cost_usd: float = 0.0,
        actor_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record tenant usage (fire-and-forget, never blocks agent loop).

        Skipped silently when *tenant_id* is not set on the session
        or *tenant_governance* is not configured.
        """
        if not session.tenant_id or self.tenant_governance is None:
            return
        try:
            self.tenant_governance.record_usage(
                tenant_id=session.tenant_id,
                operation=operation,
                actor_id=actor_id or session.user_id,
                project_id=session.project_id,
                quantity=quantity,
                cost_usd=cost_usd,
                enforce_quotas=False,  # recording only; enforcement is separate (P0-38)
                idempotency_key=idempotency_key,
            )
        except Exception:
            logger.warning(
                "Tenant usage recording failed for session %s operation %s",
                session.session_id, operation, exc_info=True,
            )

    # ------------------------------------------------------------------
    # Marketplace usage recording (P0-39)
    # ------------------------------------------------------------------

    def _record_marketplace_usage(
        self,
        *,
        tool_name: str,
        session: AgentSessionData,
        user_id: Optional[str] = None,
    ) -> None:
        """Record marketplace usage if the tool has a listing_id.

        Skipped silently when marketplace_service is None or the tool
        has no listing_id (not marketplace-sourced).
        """
        if self.marketplace_service is None:
            return
        try:
            meta = self.tool_registry._block_registry.get_metadata(tool_name)
            listing_id = getattr(meta, "listing_id", None)
            if not listing_id:
                return
            self.marketplace_service.record_usage_event(
                mode_id=listing_id,
                consumer_user_id=user_id or session.user_id,
                event_type="agent_tool_call",
                metadata={
                    "session_id": session.session_id,
                    "tool_name": tool_name,
                    "tenant_id": session.tenant_id,
                },
            )
        except Exception:
            logger.warning(
                "Marketplace usage recording failed for tool %s session %s",
                tool_name, session.session_id, exc_info=True,
            )

    def _build_structured_trace(
        self,
        *,
        session_id: str,
        user_id: str,
        raw_trace: List[Dict[str, Any]],
        budget: AgentBudget,
        parent_session_id: Optional[str] = None,
        parent_trace_id: Optional[str] = None,
    ) -> AgentTrace:
        """Convert the flat trace list into a structured ``AgentTrace``."""
        trace = AgentTrace(
            session_id=session_id,
            user_id=user_id,
            parent_session_id=parent_session_id,
            parent_trace_id=parent_trace_id,
        )
        for entry in raw_trace:
            step_type = entry.get("step", "unknown")
            tool_name = entry.get("tool_name")
            trace.add_step(
                step_type=step_type,
                tool_name=tool_name,
                duration_ms=entry.get("duration_ms", 0.0),
                budget_snapshot=entry.get("budget_snapshot", {}),
                scope_check_result="allowed" if step_type == "tool_executed" else (
                    "denied" if step_type == "tool_denied" else None
                ),
                extra={k: v for k, v in entry.items() if k not in (
                    "step", "tool_name", "duration_ms", "budget_snapshot",
                )},
            )
        trace.finalize(budget.snapshot())
        return trace
