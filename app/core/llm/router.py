from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from app.settings import get_settings
from app.services.llm.contracts import build_credit_ledger_event, normalize_usage_breakdown


@dataclass(frozen=True)
class ActionResult:
    provider: str
    model: str
    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    persona_id_used: str


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _build_prompt(action: str, input_text: str, options: Dict[str, Any], mode: str, persona_prompt: Optional[str] = None) -> tuple[str, str]:
    """Returns (instructions, input) for the provider.

    Keep outputs clean (no preambles).
    For 'ask' action, uses persona_prompt if provided.
    """
    # system instructions
    if action == "fix":
        instructions = "Fix grammar, spelling, and clarity. Output only the fixed text."
        inp = input_text
    elif action == "translate":
        target = str(options.get("target_lang") or options.get("to") or "English")
        instructions = f"Translate into {target}. Output only the translation."
        inp = input_text
    elif action == "summarize":
        style = str(options.get("style") or "concise")
        instructions = f"Summarize the text ({style}). Output only the summary."
        inp = input_text
    else:
        # ask - use persona prompt if provided, otherwise default
        instructions = persona_prompt or "Answer the user. Be direct."
        inp = input_text
    return instructions, inp


class ProviderError(RuntimeError):
    pass


class OpenAIProvider:
    def __init__(self, *, api_key: str, base_url: str = "https://api.openai.com") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    # -- LLMProvider protocol --------------------------------------------------

    @property
    def provider_name(self) -> str:  # noqa: D401
        return "openai"

    @property
    def is_available(self) -> bool:  # noqa: D401
        return bool(self.api_key)

    def generate(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> str:
        """Synchronous text generation (runs the async path in a thread)."""
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_asyncio.run, self.agenerate(
                    prompt=prompt, system_instruction=system_instruction,
                    model=model, temperature=temperature,
                    max_tokens=max_tokens, response_format=response_format,
                )).result()
        return _asyncio.run(self.agenerate(
            prompt=prompt, system_instruction=system_instruction,
            model=model, temperature=temperature,
            max_tokens=max_tokens, response_format=response_format,
        ))

    async def agenerate(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> str:
        """Async text generation conforming to LLMProvider protocol."""
        settings = get_settings()
        _model = model or settings.openai_model_fast or "gpt-4o-mini"
        result = await self.run(
            model=_model,
            instructions=system_instruction,
            input_text=prompt,
            max_output_tokens=max_tokens,
        )
        return result.text

    async def run(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int = 800,
        timeout_sec: int = 30,
        persona_id_used: str = "classic_tutor",
    ) -> ActionResult:
        if not self.api_key:
            raise ProviderError("missing OPENAI_API_KEY")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            # Prefer Responses API; fallback to Chat Completions if needed.
            try:
                data = await self._call_responses(
                    client=client,
                    headers=headers,
                    model=model,
                    instructions=instructions,
                    input_text=input_text,
                    max_output_tokens=max_output_tokens,
                )
                text, tokens_in, tokens_out = self._parse_responses(data)
                return ActionResult(provider="openai", model=model, text=text.strip(), tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=0.0, persona_id_used=persona_id_used)
            except ProviderError as e:
                msg = str(e)
                # Fallback conditions: endpoint not found / unsupported payload.
                if any(k in msg for k in ("openai_http_404", "openai_http_400")):
                    data = await self._call_chat_completions(
                        client=client,
                        headers=headers,
                        model=model,
                        instructions=instructions,
                        input_text=input_text,
                        max_output_tokens=max_output_tokens,
                    )
                    text, tokens_in, tokens_out = self._parse_chat_completions(data)
                    return ActionResult(provider="openai", model=model, text=text.strip(), tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=0.0, persona_id_used=persona_id_used)
                raise

    async def _call_responses(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        model: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/responses"
        payload: Dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": input_text,
            "max_output_tokens": int(max_output_tokens),
        }
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise ProviderError(f"openai_http_{resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _parse_responses(self, data: Dict[str, Any]) -> tuple[str, int, int]:
        text = ""
        try:
            if isinstance(data.get("output_text"), str):
                text = data.get("output_text") or ""
            else:
                out = data.get("output") or []
                for item in out:
                    if item.get("type") == "message":
                        content = item.get("content") or []
                        for c in content:
                            if c.get("type") in ("output_text", "text"):
                                text += c.get("text") or ""
                        break
        except Exception:
            text = ""
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        tokens_in = _safe_int(usage.get("input_tokens"))
        tokens_out = _safe_int(usage.get("output_tokens"))
        return text, tokens_in, tokens_out

    async def _call_chat_completions(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        model: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/chat/completions"
        payload: Dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": input_text},
            ],
            "max_tokens": int(max_output_tokens),
        }
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise ProviderError(f"openai_http_{resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def _parse_chat_completions(self, data: Dict[str, Any]) -> tuple[str, int, int]:
        text = ""
        try:
            choices = data.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                text = (msg.get("content") or "")
        except Exception:
            text = ""
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        tokens_in = _safe_int(usage.get("prompt_tokens"))
        tokens_out = _safe_int(usage.get("completion_tokens"))
        return text, tokens_in, tokens_out


class GeminiProvider:
    def __init__(self, *, api_key: str, base_url: str = "https://generativelanguage.googleapis.com") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    # -- LLMProvider protocol --------------------------------------------------

    @property
    def provider_name(self) -> str:  # noqa: D401
        return "gemini"

    @property
    def is_available(self) -> bool:  # noqa: D401
        return bool(self.api_key)

    def generate(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> str:
        """Synchronous text generation (runs the async path in a thread)."""
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_asyncio.run, self.agenerate(
                    prompt=prompt, system_instruction=system_instruction,
                    model=model, temperature=temperature,
                    max_tokens=max_tokens, response_format=response_format,
                )).result()
        return _asyncio.run(self.agenerate(
            prompt=prompt, system_instruction=system_instruction,
            model=model, temperature=temperature,
            max_tokens=max_tokens, response_format=response_format,
        ))

    async def agenerate(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> str:
        """Async text generation conforming to LLMProvider protocol."""
        settings = get_settings()
        _model = model or settings.gemini_model_fast or "gemini-2.0-flash-lite"
        result = await self.run(
            model=_model,
            instructions=system_instruction,
            input_text=prompt,
            max_output_tokens=max_tokens,
        )
        return result.text

    async def run(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int = 800,
        timeout_sec: int = 30,
        persona_id_used: str = "classic_tutor",
    ) -> ActionResult:
        if not self.api_key:
            raise ProviderError("missing GEMINI_API_KEY")

        # Gemini API uses x-goog-api-key header.
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        prompt = instructions + "\n\n" + input_text
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": int(max_output_tokens),
            },
        }

        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                raise ProviderError(f"gemini_http_{resp.status_code}: {resp.text[:500]}")
            data = resp.json()

        text = ""
        try:
            candidates = data.get("candidates") or []
            if candidates:
                content = candidates[0].get("content") or {}
                parts = content.get("parts") or []
                for p in parts:
                    if isinstance(p.get("text"), str):
                        text += p.get("text")
        except Exception:
            text = ""

        # Gemini does not always return token usage via REST; keep 0 if missing
        usage = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
        tokens_in = _safe_int(usage.get("promptTokenCount"))
        tokens_out = _safe_int(usage.get("candidatesTokenCount"))
        return ActionResult(provider="gemini", model=model, text=text.strip(), tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=0.0, persona_id_used=persona_id_used)


class StubProvider:
    """
    Stub LLM provider for testing and development.
    
    Returns realistic mock responses for different types of LLM operations
    without requiring actual API keys. Useful for:
    - Local development without API costs
    - CI/CD testing without secrets
    - Reproducible test results
    """

    # -- LLMProvider protocol --------------------------------------------------

    @property
    def provider_name(self) -> str:  # noqa: D401
        return "stub"

    @property
    def is_available(self) -> bool:  # noqa: D401
        return True

    def generate(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> str:
        """Synchronous stub generation."""
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_asyncio.run, self.agenerate(
                    prompt=prompt, system_instruction=system_instruction,
                    model=model, temperature=temperature,
                    max_tokens=max_tokens, response_format=response_format,
                )).result()
        return _asyncio.run(self.agenerate(
            prompt=prompt, system_instruction=system_instruction,
            model=model, temperature=temperature,
            max_tokens=max_tokens, response_format=response_format,
        ))

    async def agenerate(
        self,
        *,
        prompt: str,
        system_instruction: str = "",
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: str | None = None,
    ) -> str:
        """Async stub generation conforming to LLMProvider protocol."""
        result = await self.run(
            model=model or "stub",
            instructions=system_instruction,
            input_text=prompt,
        )
        return result.text

    async def run(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        max_output_tokens: int = 800,
        timeout_sec: int = 30,
        persona_id_used: str = "classic_tutor",
    ) -> ActionResult:
        """
        Execute stub LLM operation with realistic mock responses.
        
        Args:
            model: Model name (ignored, always uses "stub")
            instructions: System instructions/prompt
            input_text: User input text
            max_output_tokens: Maximum output length
            timeout_sec: Timeout (ignored in stub)
            persona_id_used: Persona ID for response
            
        Returns:
            ActionResult with mock response and zero cost
        """
        import json
        import re
        
        # Try to detect operation type from instructions
        instructions_lower = instructions.lower()
        
        # Estimate token counts (rough approximation)
        tokens_in = len(instructions.split()) + len(input_text.split())
        
        # Generate realistic responses based on operation type
        out = ""
        
        # Diagnostic item generation
        if "diagnostic" in instructions_lower or ("generate" in instructions_lower and "item" in instructions_lower):
            # Extract parameters from input if JSON
            try:
                params = json.loads(input_text)
                skill = params.get("skill", "grammar")
                subskill = params.get("subskill", "verb_conjugation")
                topic = params.get("topic", "present_tense")
                difficulty = params.get("difficulty", 2.0)
                task_type = params.get("taskType", "multiple_choice")
                cefr_band = params.get("cefrBand", "A2")
            except (json.JSONDecodeError, AttributeError):
                skill = "grammar"
                subskill = "verb_conjugation"
                topic = "present_tense"
                difficulty = 2.0
                task_type = "multiple_choice"
                cefr_band = "A2"
            
            # Generate realistic diagnostic item
            item_response = {
                "item": {
                    "id": f"stub_item_{hash(input_text) % 10000:04d}",
                    "skill": skill,
                    "subskill": subskill,
                    "topic": topic,
                    "difficulty": difficulty,
                    "taskType": task_type,
                    "cefrBand": cefr_band,
                    "prompt": f"Complete the following {skill} exercise:",
                    "question": "The cat ___ on the mat.",
                    "options": ["sits", "sit", "sitting", "sat"],
                    "correctAnswer": "sits",
                    "explanation": f"For third-person singular subjects in present tense, we add 's' to the verb.",
                    "distractorAnalysis": {
                        "sit": "Base form - incorrect with 'cat'",
                        "sitting": "Present participle - needs 'is'",
                        "sat": "Past tense - incorrect here"
                    }
                }
            }
            out = json.dumps(item_response)
        
        # Lesson generation
        elif "lesson" in instructions_lower and "generate" in instructions_lower:
            lesson_response = {
                "lessonId": f"stub_lesson_{hash(input_text) % 10000:04d}",
                "title": "Grammar Practice",
                "description": "Practice essential grammar concepts",
                "tasks": [
                    {
                        "taskId": "task_001",
                        "type": "explanation",
                        "content": "In this lesson, we'll practice key concepts."
                    },
                    {
                        "taskId": "task_002",
                        "type": "exercise",
                        "question": "Fill in the blank: She ___ to school every day.",
                        "correctAnswer": "goes",
                        "options": ["go", "goes", "going", "went"]
                    }
                ]
            }
            out = json.dumps(lesson_response)
        
        # Grading/scoring
        elif "grade" in instructions_lower or "score" in instructions_lower or "evaluate" in instructions_lower:
            # Extract answer if present
            is_correct = "correct" in input_text.lower() or len(input_text.strip()) > 2
            grade_response = {
                "score": 0.85 if is_correct else 0.3,
                "isCorrect": is_correct,
                "feedback": "Good work!" if is_correct else "Not quite right. Try again.",
                "corrections": [] if is_correct else ["Check the verb form"],
                "explanation": "Your answer demonstrates understanding of the concept." if is_correct else "Review the grammar rules."
            }
            out = json.dumps(grade_response)
        
        # Translation
        elif "translate" in instructions_lower:
            # Simple mock translation (just return input with note)
            translation_response = {
                "translation": input_text,
                "confidence": 0.95,
                "notes": "Mock translation in stub mode"
            }
            out = json.dumps(translation_response)
        
        # Text fixing
        elif "fix" in instructions_lower or "correct" in instructions_lower:
            # Simple cleanup
            out = input_text.strip()
            # Fix common issues
            out = re.sub(r'\s+', ' ', out)  # Multiple spaces
            out = re.sub(r'\s+([.,!?])', r'\1', out)  # Space before punctuation
            if out and out[0].islower():
                out = out[0].upper() + out[1:]  # Capitalize first letter
        
        # Summarization
        elif "summarize" in instructions_lower or "summary" in instructions_lower:
            # Truncate and add summary marker
            max_chars = min(max_output_tokens * 4, 500)  # Rough estimate
            if len(input_text) > max_chars:
                out = input_text[:max_chars].strip() + "…"
            else:
                out = input_text.strip()
        
        # Default: return input with minimal processing
        else:
            out = input_text.strip()
        
        # Calculate output tokens
        tokens_out = len(out.split())
        
        return ActionResult(
            provider="stub",
            model="stub",
            text=out,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
            persona_id_used=persona_id_used
        )


async def execute_action(action: str, input_text: str, options: Dict[str, Any], mode: str, persona_id: Optional[str] = None) -> ActionResult:
    settings = get_settings()

    # Import here to avoid circular dependency
    from app.core import persona_prompts
    
    # Get persona prompt and actual persona ID used
    persona_result = persona_prompts.get_persona_prompt(persona_id)
    persona_id_used = persona_result.persona_id_used
    persona_prompt = persona_result.prompt_text

    instructions, inp = _build_prompt(action, input_text, options, mode, persona_prompt)

    # Choose provider and model
    if mode in ("fast", "hybrid"):
        provider_name = settings.default_provider_fast
        model_openai = settings.openai_model_fast
        model_gemini = settings.gemini_model_fast
    else:
        provider_name = settings.default_provider_batch
        model_openai = settings.openai_model_batch
        model_gemini = settings.gemini_model_batch

    opt_provider = options.get("provider")
    if isinstance(opt_provider, str) and opt_provider.strip().lower() in ("", "auto", "default"):
        opt_provider = None
    provider_name = (opt_provider or provider_name or "stub").lower()

    model_override = options.get("model")
    try:
        max_output_tokens = int(options.get("max_output_tokens") or 800)
    except Exception:
        max_output_tokens = 800

    if provider_name == "openai":
        provider = OpenAIProvider(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        model = str(model_override or model_openai)
        return await provider.run(model=model, instructions=instructions, input_text=inp, max_output_tokens=max_output_tokens, timeout_sec=60, persona_id_used=persona_id_used)
    if provider_name in ("gemini", "google"):
        provider = GeminiProvider(api_key=settings.gemini_api_key, base_url=settings.gemini_base_url)
        model = str(model_override or model_gemini)
        return await provider.run(model=model, instructions=instructions, input_text=inp, max_output_tokens=max_output_tokens, timeout_sec=60, persona_id_used=persona_id_used)

    # fallback
    provider = StubProvider()
    return await provider.run(model="stub", instructions=instructions, input_text=inp, persona_id_used=persona_id_used)


def execute_llm_request(
    system_prompt: str,
    user_prompt: str,
    provider: str = "gemini",
    model: str = "gemini-2.0-flash-exp",
    max_tokens: int = 4000,
    timeout_sec: int = 60,
    return_metadata: bool = False,
    endpoint: str = "/runtime/llm",
    feature: str = "runtime_llm",
    stage: str = "runtime",
    attempt: int = 1,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> str | Dict[str, Any]:
    """
    Synchronous LLM request for lesson generation/grading.
    
    SECURITY: This function is a trust boundary for LLM outputs.
    All responses should be validated using llm_validator module before use.
    
    Args:
        system_prompt: System instructions
        user_prompt: User input
        provider: Provider name (gemini, openai, stub)
        model: Model identifier
        max_tokens: Max output tokens
        timeout_sec: Request timeout in seconds (default 60)
        
    Returns:
        By default: response text from LLM (MUST be validated before use)
        If return_metadata=True: dict with text/usage/cost/pricing/ledger metadata
        
    Raises:
        ProviderError: If request fails or times out
    """
    import httpx
    import logging
    
    logger = logging.getLogger(__name__)
    settings = get_settings()
    provider = str(provider or "gemini").strip().lower()
    
    # Input validation
    if not system_prompt or not user_prompt:
        raise ProviderError("system_prompt and user_prompt are required")
    
    if max_tokens <= 0 or max_tokens > 100000:
        raise ProviderError(f"Invalid max_tokens: {max_tokens}")
    
    if timeout_sec <= 0 or timeout_sec > 300:
        raise ProviderError(f"Invalid timeout_sec: {timeout_sec}")
    
    def _build_runtime_payload(
        *,
        text: str,
        provider_name: str,
        model_name: str,
        raw_usage: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        usage = normalize_usage_breakdown(raw_usage or {}, request_count=1)
        ledger = build_credit_ledger_event(
            provider=provider_name,
            model=model_name,
            endpoint=endpoint,
            feature=feature,
            stage=stage,
            usage=usage,
            attempt=max(1, int(attempt)),
            trace_id=trace_id,
            session_id=session_id,
            job_id=job_id,
        ).to_dict()
        return {
            "text": text,
            "provider": provider_name,
            "model": model_name,
            "usage": usage.to_dict(),
            "cost": {
                "units": float(ledger.get("estimated_cost_usd") or 0.0),
                "currency": "usd_estimate",
                "estimated_cost_usd": float(ledger.get("estimated_cost_usd") or 0.0),
                "credits_charged": int(ledger.get("credits_charged") or 0),
                "pricing_version": str(ledger.get("pricing_version") or ""),
                "provider": provider_name,
                "model": model_name,
            },
            "pricing_version": str(ledger.get("pricing_version") or ""),
            "ledger_event": ledger,
        }

    runtime_response: Dict[str, Any]

    if provider == "gemini":
        api_key = settings.gemini_api_key
        if not api_key:
            raise ProviderError("missing GEMINI_API_KEY")
        
        url = f"{settings.gemini_base_url}/v1beta/models/{model}:generateContent"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": user_prompt}], "role": "user"}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        
        try:
            with httpx.Client(timeout=float(timeout_sec)) as client:
                resp = client.post(f"{url}?key={api_key}", headers=headers, json=payload)
                if resp.status_code >= 400:
                    error_text = resp.text[:500]
                    logger.error(f"Gemini API error: status={resp.status_code}, body={error_text}")
                    raise ProviderError(f"gemini_http_{resp.status_code}: {error_text}")
                
                data = resp.json()
                
                # Extract text and usage with safety checks
                text = ""
                candidates = data.get("candidates")
                if not candidates:
                    logger.warning("Gemini response has no candidates")
                    runtime_response = _build_runtime_payload(
                        text="",
                        provider_name="gemini",
                        model_name=model,
                        raw_usage={},
                    )
                    return runtime_response if return_metadata else runtime_response["text"]
                
                if candidates:
                    content = candidates[0].get("content") or {}
                    parts = content.get("parts") or []
                    for p in parts:
                        if isinstance(p.get("text"), str):
                            text += p.get("text")
                
                result = text.strip()
                
                # Safety check: warn if response is empty
                if not result:
                    logger.warning("Gemini returned empty response")
                
                # Safety check: warn if response is suspiciously short
                if len(result) < 50:
                    logger.warning(f"Gemini returned very short response: {len(result)} chars")
                
                usage_meta = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
                raw_usage = {
                    "prompt_tokens": _safe_int(usage_meta.get("promptTokenCount")),
                    "completion_tokens": _safe_int(usage_meta.get("candidatesTokenCount")),
                    "total_tokens": _safe_int(
                        usage_meta.get("totalTokenCount")
                        or (_safe_int(usage_meta.get("promptTokenCount")) + _safe_int(usage_meta.get("candidatesTokenCount")))
                    ),
                }
                runtime_response = _build_runtime_payload(
                    text=result,
                    provider_name="gemini",
                    model_name=model,
                    raw_usage=raw_usage,
                )
                return runtime_response if return_metadata else runtime_response["text"]
        
        except httpx.TimeoutException as e:
            logger.error(f"Gemini request timeout after {timeout_sec}s")
            raise ProviderError(f"gemini_timeout after {timeout_sec}s: {str(e)}")
        except httpx.HTTPError as e:
            logger.error(f"Gemini HTTP error: {str(e)}")
            raise ProviderError(f"gemini_http_error: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response JSON: {str(e)}")
            raise ProviderError(f"gemini_json_decode_error: {str(e)}")
    
    elif provider == "openai":
        api_key = settings.openai_api_key
        if not api_key:
            raise ProviderError("missing OPENAI_API_KEY")
        
        url = f"{settings.openai_base_url}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
        }
        
        with httpx.Client(timeout=float(timeout_sec)) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                error_text = resp.text[:500]
                logger.error(f"OpenAI API error: status={resp.status_code}, body={error_text}")
                raise ProviderError(f"openai_http_{resp.status_code}: {error_text}")
            
            data = resp.json()
            
            # Extract with safety checks
            choices = data.get("choices")
            if not choices:
                logger.warning("OpenAI response has no choices")
                runtime_response = _build_runtime_payload(
                    text="",
                    provider_name="openai",
                    model_name=model,
                    raw_usage={},
                )
                return runtime_response if return_metadata else runtime_response["text"]
            
            if choices:
                result = choices[0].get("message", {}).get("content", "").strip()
                
                # Safety checks
                if not result:
                    logger.warning("OpenAI returned empty response")
                
                if len(result) < 50:
                    logger.warning(f"OpenAI returned very short response: {len(result)} chars")
                
                usage_meta = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                raw_usage = {
                    "prompt_tokens": _safe_int(usage_meta.get("prompt_tokens")),
                    "completion_tokens": _safe_int(usage_meta.get("completion_tokens")),
                    "total_tokens": _safe_int(
                        usage_meta.get("total_tokens")
                        or (_safe_int(usage_meta.get("prompt_tokens")) + _safe_int(usage_meta.get("completion_tokens")))
                    ),
                }
                runtime_response = _build_runtime_payload(
                    text=result,
                    provider_name="openai",
                    model_name=model,
                    raw_usage=raw_usage,
                )
                return runtime_response if return_metadata else runtime_response["text"]
            
            runtime_response = _build_runtime_payload(
                text="",
                provider_name="openai",
                model_name=model,
                raw_usage={},
            )
            return runtime_response if return_metadata else runtime_response["text"]
    
    else:
        # Stub provider
        stub_text = f"STUB: {user_prompt[:100]}"
        raw_usage = {
            "prompt_tokens": max(1, len(system_prompt.split()) + len(user_prompt.split())),
            "completion_tokens": max(1, len(stub_text.split())),
            "total_tokens": max(1, len(system_prompt.split()) + len(user_prompt.split()) + len(stub_text.split())),
        }
        runtime_response = _build_runtime_payload(
            text=stub_text,
            provider_name="stub",
            model_name="stub",
            raw_usage=raw_usage,
        )
        return runtime_response if return_metadata else runtime_response["text"]
