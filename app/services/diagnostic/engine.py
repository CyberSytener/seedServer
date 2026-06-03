"""
Diagnostic item generation engine for language learning assessments.

Generates diagnostic test items using LLM with strict JSON validation.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.models.api import (
    DiagnosticGenerateRequest,
    DiagnosticResponse,
    DiagnosticSet,
    DiagnosticItem,
    DiagnosticTaskType,
)
from app.core.llm.router import execute_llm_request
from app.core.util import job_id
from app.core.llm.validator import validate_llm_json, get_validator
from app.infrastructure.monitoring.monitoring.metrics import BillingMetrics
from app.services.llm.contracts import build_credit_ledger_event, normalize_usage_breakdown, summarize_ledger_events


FALLBACK_DIAGNOSTIC_PROMPT = """Generate diagnostic language-learning items from the provided blueprint.
Return valid JSON only and preserve requested task types, tags, and answer schema."""

FALLBACK_DIAGNOSTIC_COMPACT_PROMPT = """Generate compact diagnostic items while preserving schema requirements.
Return compact output that can be deterministically parsed into the diagnostic JSON schema."""


def _resolve_prompts_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent / "prompts",
        Path(__file__).resolve().parents[3] / "prompts",
    ]
    required_files = ("diagnostic_generator.md", "diagnostic_generator_compact.md")
    for candidate in candidates:
        if candidate.exists() and all((candidate / file_name).exists() for file_name in required_files):
            return candidate
    fallback = candidates[0]
    logging.warning(
        "Diagnostic prompt directory could not be fully validated; using fallback path %s",
        fallback,
    )
    return fallback


def _read_prompt_file(prompt_path: Path, fallback_text: str, prompt_name: str) -> str:
    try:
        content = prompt_path.read_text(encoding="utf-8").strip()
        if content:
            return content
        raise ValueError("prompt file is empty")
    except Exception as exc:
        logging.warning(
            "Prompt %s unavailable at %s (%s). Using built-in fallback prompt.",
            prompt_name,
            prompt_path,
            exc,
        )
        return fallback_text


# Load diagnostic prompt
PROMPTS_DIR = _resolve_prompts_dir()
DIAGNOSTIC_PROMPT_FILE = PROMPTS_DIR / "diagnostic_generator.md"
DIAGNOSTIC_PROMPT_COMPACT_FILE = PROMPTS_DIR / "diagnostic_generator_compact.md"
DIAGNOSTIC_PROMPT_TEST_FILE = PROMPTS_DIR / "test" / "diagnostic_generator.md"


def validate_diagnostic_set(data: dict, blueprint_count: int) -> tuple[bool, list[str]]:
    """
    Validate diagnostic set structure.
    
    Returns:
        (is_valid, list_of_error_messages)
    """
    errors = []
    
    # Validate top-level structure
    if "items" not in data:
        errors.append("Missing 'items' array")
        return False, errors
    
    items = data.get("items", [])
    if not isinstance(items, list):
        errors.append("'items' must be an array")
        return False, errors
    
    if len(items) != blueprint_count:
        errors.append(f"Expected {blueprint_count} items, got {len(items)}")
    
    # Validate each item
    for idx, item in enumerate(items):
        item_errors = validate_diagnostic_item(item, idx)
        errors.extend(item_errors)
    
    return len(errors) == 0, errors


def validate_diagnostic_item(item: dict, index: int) -> list[str]:
    """Validate a single diagnostic item."""
    errors = []
    prefix = f"Item[{index}]"
    
    # Required fields (using camelCase for API compatibility)
    required_fields = ["id", "taskType", "prompt", "answer", "tags"]
    for field in required_fields:
        if field not in item:
            errors.append(f"{prefix}: missing required field '{field}'")
    
    item_type = item.get("taskType")
    
    # Type-specific validation
    if item_type == "mcq" or item_type == "reading_mcq":
        choices = item.get("choices")
        if not choices or not isinstance(choices, list) or len(choices) != 4:
            errors.append(f"{prefix}: {item_type} must have exactly 4 choices")
        
        # Validate distractorsReason
        distractors = item.get("distractorsReason")
        if distractors and isinstance(distractors, list):
            if len(distractors) != 3:
                errors.append(f"{prefix}: distractorsReason must have exactly 3 entries (for wrong choices)")
    
    elif item_type == "reorder_sentence":
        tokens = item.get("tokens")
        if not tokens or not isinstance(tokens, list) or len(tokens) == 0:
            errors.append(f"{prefix}: reorder_sentence must have non-empty 'tokens' array")
    
    elif item_type == "fill_blank":
        # fill_blank can have context.sentence with blank, or prompt with blank
        context = item.get("context") or {}  # Handle None explicitly
        sentence = context.get("sentence", "") if isinstance(context, dict) else ""
        prompt = item.get("prompt") or ""
        # Check if blank marker exists in either place
        has_blank = "_____" in sentence or "__" in sentence or "_____" in prompt or "__" in prompt
        if not has_blank:
            errors.append(f"{prefix}: fill_blank must have blank marker (_____ or __) in prompt or context.sentence")
    
    elif item_type == "translate":
        # translate can have context.sentence or just rely on prompt
        # For V0, we're permissive - validation will be tightened later
        pass
    
    # Validate answer structure
    answer = item.get("answer")
    if answer:
        if not isinstance(answer, dict):
            errors.append(f"{prefix}: 'answer' must be an object")
        elif "accepted" not in answer:
            errors.append(f"{prefix}: answer.accepted is required")
        elif not isinstance(answer.get("accepted"), list) or len(answer.get("accepted", [])) == 0:
            errors.append(f"{prefix}: answer.accepted must be a non-empty array")
    
    # Validate tags
    tags = item.get("tags")
    if tags:
        required_tag_fields = ["skill", "subskill", "topic", "difficulty", "taskType", "cefrBand", "languagePair"]
        for field in required_tag_fields:
            if field not in tags:
                errors.append(f"{prefix}: tags.{field} is required")
        
        # Validate difficulty range
        difficulty = tags.get("difficulty")
        if difficulty is not None:
            try:
                diff_val = float(difficulty)
                if diff_val < 0.0 or diff_val > 5.0:
                    errors.append(f"{prefix}: tags.difficulty must be 0.0-5.0, got {diff_val}")
            except (ValueError, TypeError):
                errors.append(f"{prefix}: tags.difficulty must be a number")
    
    return errors


def generate_diagnostic_items(
    request: DiagnosticGenerateRequest,
    user_id: str,
    persona_id_override: Optional[str] = None,
    optimize_mode: bool = False,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> DiagnosticResponse:
    """
    Generate diagnostic test items based on blueprint.
    
    Args:
        request: Generation parameters including blueprint
        user_id: User making the request
        persona_id_override: Optional persona override
        optimize_mode: If True, use compact prompt format
        
    Returns:
        DiagnosticResponse with generated items
        
    Raises:
        ValueError: If generation or validation fails
    """
    # Check if test mode is enabled (overrides optimize_mode)
    from app.settings import get_settings
    settings = get_settings()
    
    # Performance tracking is optional for generation flow.
    # Keep this resilient so prompt fallback paths never fail due monitoring setup.
    perf_context = None
    
    # Debug logging for specialized blueprint analysis
    logging.info(f"🔥 DIAGNOSTIC GENERATION START - blueprint items: {len(request.blueprint)}")
    for i, item in enumerate(request.blueprint):
        logging.info(f"   Item {i+1}: domain={getattr(item, 'domain', None)}, dialect={getattr(item, 'dialect', None)}")
    use_test_prompt = settings.prompt_test_mode
    
    # Determine if specialized prompt is needed
    specialized_domain = None
    has_dialect_focus = False
    
    # Analyze blueprint for specialized requirements
    for item in request.blueprint:
        logging.info(f"🔍 Blueprint item analysis - domain: {getattr(item, 'domain', None)}, dialect: {getattr(item, 'dialect', None)}")
        if hasattr(item, 'domain') and item.domain:
            specialized_domain = item.domain
            logging.info(f"✅ Found specialized domain: {specialized_domain}")
            break
        if hasattr(item, 'dialect') and item.dialect:
            has_dialect_focus = True
            logging.info(f"✅ Found dialect focus: {item.dialect}")
            break

    baseline_prompt = _read_prompt_file(
        DIAGNOSTIC_PROMPT_FILE,
        FALLBACK_DIAGNOSTIC_PROMPT,
        "diagnostic_generator",
    )
    compact_prompt = _read_prompt_file(
        DIAGNOSTIC_PROMPT_COMPACT_FILE,
        FALLBACK_DIAGNOSTIC_COMPACT_PROMPT,
        "diagnostic_generator_compact",
    )
    
    # Load prompt template based on specialization and mode
    if specialized_domain:
        specialized_prompt_file = PROMPTS_DIR / "specialized" / f"{specialized_domain}_english.md"
        if specialized_prompt_file.exists():
            prompt_template = _read_prompt_file(
                specialized_prompt_file,
                baseline_prompt,
                f"specialized_{specialized_domain}",
            )
            logging.info(f"🎯 Using SPECIALIZED prompt for {specialized_domain}: {specialized_prompt_file}")
        else:
            logging.warning(f"Specialized prompt not found for domain '{specialized_domain}', falling back to default")
            prompt_template = baseline_prompt
    elif has_dialect_focus:
        dialect_prompt_file = PROMPTS_DIR / "specialized" / "dialect_differences.md"
        if dialect_prompt_file.exists():
            prompt_template = _read_prompt_file(
                dialect_prompt_file,
                baseline_prompt,
                "specialized_dialect_differences",
            )
            logging.info("🌍 Using DIALECT DIFFERENCES prompt")
        else:
            logging.warning("Dialect differences prompt not found, falling back to baseline prompt")
            prompt_template = baseline_prompt
    elif use_test_prompt and DIAGNOSTIC_PROMPT_TEST_FILE.exists():
        # Test mode: use test version
        prompt_template = _read_prompt_file(
            DIAGNOSTIC_PROMPT_TEST_FILE,
            baseline_prompt,
            "diagnostic_generator_test",
        )
        logging.info("🧪 Using TEST prompt: prompts/test/diagnostic_generator.md")
    elif optimize_mode:
        # Optimize mode: use compact version
        if not DIAGNOSTIC_PROMPT_COMPACT_FILE.exists():
            logging.warning(
                "Compact diagnostic prompt file not found at %s, using fallback compact prompt",
                DIAGNOSTIC_PROMPT_COMPACT_FILE,
            )
        prompt_template = compact_prompt
        logging.info("Using COMPACT prompt: prompts/diagnostic_generator_compact.md")
    else:
        # Normal mode: use baseline
        prompt_template = baseline_prompt
        logging.info("Using BASELINE prompt: prompts/diagnostic_generator.md")
    
    # Format blueprint as JSON
    blueprint_json = json.dumps(
        [bp.model_dump(by_alias=True) for bp in request.blueprint],
        indent=2
    )
    
    # Build language pair
    language_pair = f"{request.native_lang}->{request.target_lang}"
    
    # Replace placeholders
    user_prompt = prompt_template.replace("{native}", request.native_lang)
    user_prompt = user_prompt.replace("{target}", request.target_lang)
    user_prompt = user_prompt.replace("{BLUEPRINT_JSON_ARRAY}", blueprint_json)
    user_prompt = user_prompt.replace("{languagePair}", language_pair)
    
    # Determine persona
    final_persona_id = persona_id_override or request.persona_id
    
    logging.info(
        f"Generating diagnostic items: {len(request.blueprint)} items, "
        f"{request.native_lang}->{request.target_lang}, persona={final_persona_id}"
    )
    
    # Execute LLM request with retries
    max_attempts = 3
    last_error = None
    ledger_events: list[dict] = []
    
    # Initialize performance tracking (best effort, currently disabled for resilience)
    perf_context = None
    
    # Load persona prompt if specified
    try:
        from app.core import persona_prompts

        persona_result = persona_prompts.get_persona_prompt(final_persona_id)
        persona_used = persona_result.persona_id_used
        fallback_reason = persona_result.fallback_reason
        persona_prompt = persona_result.prompt_text
    except Exception as exc:
        logging.warning(
            "Persona prompt module unavailable (%s). Using default diagnostic persona prompt.",
            exc,
        )
        persona_used = final_persona_id or "default"
        fallback_reason = "persona_module_unavailable"
        persona_prompt = "You are an encouraging language assessment coach."
    
    # Build system prompt
    system_prompt = f"""{persona_prompt}

---
{prompt_template}

Remember: Output ONLY valid JSON array with the diagnostic items. No markdown, no extra text."""
    
    for attempt in range(max_attempts):
        try:
            # Call synchronous LLM request with aggressive timeout
            # For 25 items, Gemini usually responds in 20-40s
            # Timeout at 45s to prevent indefinite hangs
            stage_name = "candidate" if attempt == 0 else f"retry_{attempt + 1}"
            runtime_llm = execute_llm_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                provider="gemini",
                model="gemini-2.0-flash-exp",
                max_tokens=24000,
                timeout_sec=45,  # Aggressive timeout
                return_metadata=True,
                endpoint="/v1/diagnostics/generate",
                feature="diagnostic_generation",
                stage=stage_name,
                attempt=attempt + 1,
                trace_id=trace_id,
                session_id=session_id,
                job_id=job_id,
            )

            result_text = str((runtime_llm or {}).get("text") or "") if isinstance(runtime_llm, dict) else str(runtime_llm or "")
            ledger_event = (runtime_llm or {}).get("ledger_event") if isinstance(runtime_llm, dict) else None
            if not isinstance(ledger_event, dict):
                # Backward-compatible fallback (should not trigger in normal runtime paths).
                estimated_input_tokens = max(1, len(system_prompt + user_prompt) // 4)
                estimated_output_tokens = max(1, len(result_text) // 4)
                total_tokens = estimated_input_tokens + estimated_output_tokens
                fallback_usage = normalize_usage_breakdown(
                    {
                        "prompt_tokens": estimated_input_tokens,
                        "completion_tokens": estimated_output_tokens,
                        "total_tokens": total_tokens,
                    },
                    request_count=1,
                )
                ledger_event = build_credit_ledger_event(
                    provider="gemini",
                    model="gemini-2.0-flash-exp",
                    endpoint="/v1/diagnostics/generate",
                    feature="diagnostic_generation",
                    stage=stage_name,
                    usage=fallback_usage,
                    attempt=attempt + 1,
                    trace_id=trace_id,
                    session_id=session_id,
                    job_id=job_id,
                ).to_dict()
            ledger_events.append(ledger_event)
            BillingMetrics.record_credit_ledger_event(ledger_event)
            
            # Parse response based on format
            result_text = result_text.strip()
            
            if optimize_mode:
                # Parse compact format with version support
                from app.settings import get_settings
                settings = get_settings()
                parser_version = settings.parser_version
                
                if parser_version == 'v2':
                    # Use optimized parser v2
                    import sys
                    from pathlib import Path
                    parsers_path = Path(__file__).parent.parent / "parsers"
                    sys.path.insert(0, str(parsers_path))
                    
                    from compact_parser_v2 import parse_compact_diagnostic
                    logging.info("[PARSER] Using optimized parser v2")
                else:
                    # Use baseline parser
                    from app.core.compact_parser import parse_compact_diagnostic
                    logging.info("[PARSER] Using baseline parser")
                
                items = parse_compact_diagnostic(result_text, {
                    'native_lang': request.native_lang,
                    'target_lang': request.target_lang
                })
                
                # Build diagnostic set structure
                diagnostic_set = DiagnosticSet(items=[DiagnosticItem(**item) for item in items])
                logging.info(f"Parsed compact diagnostic format: {len(items)} items")
            else:
                # Parse JSON format (original) with robust validation
                validator = get_validator()
                sanitized, warnings = validator.sanitize_json_response(result_text)
                
                if warnings:
                    logging.info(f"Diagnostic sanitization warnings: {', '.join(warnings)}")
                
                # Parse JSON with error handling
                try:
                    data = json.loads(sanitized)
                except json.JSONDecodeError as e:
                    error_msg = f"JSON parse error at position {e.pos}: {e.msg}"
                    logging.warning(
                        f"Diagnostic JSON parsing failed (attempt {attempt + 1}/{max_attempts}): {error_msg}"
                    )
                    last_error = error_msg
                    continue
                
                # Normalize data: fix null context fields
                if "items" in data and isinstance(data["items"], list):
                    for item in data["items"]:
                        if isinstance(item, dict) and item.get("context") is None:
                            item["context"] = {}
                
                # Validate structure
                is_valid, errors = validate_diagnostic_set(data, len(request.blueprint))
                
                if not is_valid:
                    error_msg = "; ".join(errors[:5])  # Show first 5 errors
                    logging.warning(
                        f"Diagnostic validation failed (attempt {attempt + 1}/{max_attempts}): {error_msg}"
                    )
                    last_error = f"Validation errors: {error_msg}"
                    continue
                
                # Parse into Pydantic models with error handling
                try:
                    diagnostic_set = DiagnosticSet(**data)
                except Exception as e:
                    error_msg = f"Pydantic validation failed: {str(e)}"
                    logging.warning(
                        f"Diagnostic schema validation failed (attempt {attempt + 1}/{max_attempts}): {error_msg}"
                    )
                    last_error = error_msg
                    continue
            
            logging.info(f"Successfully generated {len(diagnostic_set.items)} diagnostic items")
            
            # Record successful generation with token count
            if perf_context:
                try:
                    # Estimate token count (rough approximation: 1 token ≈ 4 characters)
                    estimated_tokens = len(result_text) // 4
                    perf_context.mark_success(token_count=estimated_tokens)
                except Exception as e:
                    logging.warning(f"Failed to record performance metrics: {e}")
            
            cost_summary = summarize_ledger_events(ledger_events)

            return DiagnosticResponse(
                diagnosticSet=diagnostic_set,
                personaIdUsed=persona_used,
                fallbackReason=fallback_reason,
                totalCostUsd=cost_summary["total_cost_usd"],
                totalCreditsCharged=cost_summary["total_credits_charged"],
                costBreakdown=cost_summary["cost_breakdown"],
                costTotalsBySession=cost_summary["totals_by_session"],
                costTotalsByJob=cost_summary["totals_by_job"],
            )
            
        except json.JSONDecodeError as e:
            last_error = f"Invalid JSON: {str(e)}"
            logging.warning(
                f"JSON parse error (attempt {attempt + 1}/{max_attempts}): {last_error}",
                extra={"attempt": attempt + 1, "max_attempts": max_attempts, "error_type": "json_decode"}
            )
            continue
            
        except Exception as e:
            import traceback
            last_error = f"Generation error: {str(e)}"
            error_type = type(e).__name__
            
            # Log with full context
            logging.error(
                f"[DIAGNOSTIC] Generation failed (attempt {attempt + 1}/{max_attempts}): {error_type}: {last_error}",
                extra={
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "error_type": error_type,
                    "language_pair": f"{request.native_lang}->{request.target_lang}",
                    "item_count": len(request.blueprint),
                    "traceback": traceback.format_exc()
                }
            )
            
            # Re-raise on last attempt
            if attempt == max_attempts - 1:
                # Record failure in performance tracking
                if perf_context:
                    try:
                        perf_context.mark_failed("generation_failed")
                    except Exception as perf_err:
                        logging.warning(f"Failed to record performance failure: {perf_err}")
                raise ValueError(f"Failed to generate diagnostic items after {max_attempts} attempts: {last_error}") from e
            continue
    
    # All attempts failed - record failure
    if perf_context:
        try:
            perf_context.mark_failed("all_attempts_failed")
        except Exception as perf_err:
            logging.warning(f"Failed to record performance failure: {perf_err}")
    
    # All attempts failed
    raise ValueError(f"Failed to generate valid diagnostic items after {max_attempts} attempts: {last_error}")



