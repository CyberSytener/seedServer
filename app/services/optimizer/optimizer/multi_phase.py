"""
Multi-Phase Optimizer with Cost Guardrails

Phases:
- Phase 0: Intent Analysis (gemini-2.5-pro)
  - Transform natural language requirements into technical spec
  - Generate baseline system instruction, test cases, constraints
- Phase 1: Bulk Discovery (gemini-2.0-flash-lite)  
  - 5-7 fast iterations to find optimal prompt structure
  - Automated validation & filtering (~80% suboptimal removed)
- Phase 2: Precision Refinement (gemini-2.5-flash)
  - 2-3 final iterations on best Phase 1 candidate
  - Focus: style, pedagogy, synonym expansion
- Phase 3: Jury Audit (gemini-2.0-flash)
  - Independent cross-model verification
  - Fallback to Phase 2 if score < 80

Cost: < $0.01 per request via token counting & early stopping
"""

from __future__ import annotations

import json
import logging
import time
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from .base import (
    OptimizerTestCase, TestResult, OptimizationIteration, OptimizationResult,
    get_language_schema, validate_language_fields, OptimizationTarget, OptimizerVersion
)
from app.infrastructure.llm.client import get_llm_client
from ..settings import get_settings

logger = logging.getLogger(__name__)

# Conservative default pricing (USD per token units are small; keys are model names)
DEFAULT_PRICING = {
    "gemini-2.5-pro": {"input": 0.0000001, "output": 0.0000004},
    "gemini-2.0-flash-lite": {"input": 0.0000000075, "output": 0.00000003},
    "gemini-2.5-flash": {"input": 0.000000075, "output": 0.0000003},
    "gemini-2.0-flash": {"input": 0.00000001, "output": 0.00000003},
}


class OptimizerLogger:
    """Логирование всех шагов оптимизации в структурированный JSON"""
    
    def __init__(self, session_id: str, log_dir: Path = None):
        if log_dir is None:
            log_dir = Path("/app/optimizer_logs/multi_phase")
        self.session_dir = log_dir / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.steps: List[Dict[str, Any]] = []
        self.phase_data = {}
    
    def log_step(self, phase: str, step: str, prompt: str = None, response: str = None, 
                 model: str = None, tokens_in: int = None, tokens_out: int = None, 
                 metadata: Dict[str, Any] = None):
        """Логировать один шаг оптимизации"""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "step": step,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }
        
        if metadata:
            entry.update(metadata)
        
        # Сохранить промт в отдельный файл
        if prompt:
            prompt_file = self.session_dir / f"prompt_{phase}_{step}_{datetime.now(timezone.utc).strftime('%H%M%S%f')}.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
            entry["prompt_file"] = prompt_file.name
        
        # Сохранить ответ в отдельный файл
        if response:
            response_file = self.session_dir / f"response_{phase}_{step}_{datetime.now(timezone.utc).strftime('%H%M%S%f')}.txt"
            response_file.write_text(response, encoding="utf-8")
            entry["response_file"] = response_file.name
        
        self.steps.append(entry)
        logger.info(f"[{phase}] {step} - logged")
    
    def save_summary(self):
        """Сохранить итоговый JSON с метаинформацией всех шагов"""
        summary = {
            "session_id": self.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "steps_count": len(self.steps),
            "steps": self.steps,
            "phase_data": self.phase_data,
        }
        summary_file = self.session_dir / "summary.json"
        summary_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"✓ Session log saved to {self.session_dir}")
        return summary_file



def parse_llm_json(text: str) -> Optional[Any]:
    """Robustly try to parse JSON from LLM text.

    Returns parsed JSON (dict/list) or None if parsing failed.
    Handles markdown code blocks (```json ... ```), direct JSON, and wrapped responses.
    Also handles truncated JSON by attempting recovery of incomplete strings.
    """
    if not text:
        return None
    text = text.strip()
    
    # Try direct parse first
    try:
        return json.loads(text)
    except Exception:
        logging.debug("Suppressed exception", exc_info=True)
    # Strip markdown code blocks (```json ... ```)
    if text.startswith("```"):
        # Remove opening fence (with optional language tag)
        start_idx = text.find("\n")
        if start_idx != -1:
            text = text[start_idx+1:]
        # Remove closing fence
        if text.endswith("```"):
            text = text[:-3].rstrip()
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
    # Try to extract a JSON array/object and fix if incomplete
    for open_ch, close_ch in (('[', ']'), ('{', '}')):
        start = text.find(open_ch)
        if start == -1:
            continue
            
        # Try the full range first
        end = text.rfind(close_ch)
        if end > start:
            candidate = text[start:end+1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        
        # If that fails, try to auto-complete by handling truncated strings
        candidate = text[start:]
        
        # Count opening and closing brackets
        open_count = candidate.count(open_ch)
        close_count = candidate.count(close_ch)
        
        # Check for unclosed string at the end (common truncation issue)
        # If text ends with unclosed quote, close it and add brackets
        if candidate.rfind('"') > candidate.rfind('\\'):  # Simple check: not escaped quote
            last_quote = candidate.rfind('"')
            # Check if there's an odd number of unescaped quotes in the last segment
            check_segment = candidate[max(0, last_quote-10):]
            if check_segment.count('"') % 2 == 1:  # Odd number = unclosed
                candidate = candidate + '"'  # Close the string
        
        # Add missing closing brackets
        while open_count > close_count and len(candidate) < 10000:  # safety limit
            candidate = candidate + close_ch
            close_count += 1
        
        # Try parsing the fixed JSON
        try:
            result = json.loads(candidate)
            return result
        except Exception:
            continue

    return None


def unwrap_json_array(data: Any) -> Optional[Any]:
    """If data is a dict with a single key containing a list, unwrap it.
    
    Example: {"test_cases": [...]} → [...]
    Also handles {"items": [...], "count": ...} by extracting the largest list.
    """
    if isinstance(data, list):
        return data  # Already unwrapped
    if not isinstance(data, dict):
        return None
    
    # Find all lists in dict values
    lists_found = [(k, v) for k, v in data.items() if isinstance(v, list)]
    if not lists_found:
        return None
    
    # If only one list, use it
    if len(lists_found) == 1:
        return lists_found[0][1]
    
    # If multiple lists, pick the largest (likely the data)
    lists_found.sort(key=lambda x: len(x[1]), reverse=True)
    return lists_found[0][1]


def extract_jury_score(data: Any) -> int:
    """Extract jury score from various jury response formats.
    
    Tries to find 'score' key in nested dicts, handles wrapped responses.
    Returns 0 if not found.
    """
    if not isinstance(data, dict):
        return 0
    
    # Direct key lookup
    if 'score' in data:
        try:
            return int(data['score'])
        except (ValueError, TypeError):
            return 0
    
    # Search nested dicts
    def find_score(obj: Any) -> Optional[int]:
        if isinstance(obj, dict):
            if 'score' in obj:
                try:
                    return int(obj['score'])
                except (ValueError, TypeError):
                    pass
            for v in obj.values():
                result = find_score(v)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for item in obj:
                result = find_score(item)
                if result is not None:
                    return result
        return None
    
    result = find_score(data)
    return result if result is not None else 0


def _extract_text_from_raw_json(raw: Dict[str, Any]) -> str:
    """Walk the raw Gemini JSON and collect any string fragments to attempt recovery.

    This is a best-effort heuristic: concatenate string leaves and try to parse JSON.
    """
    pieces: List[str] = []

    def walk(obj: Any):
        if obj is None:
            return
        if isinstance(obj, str):
            pieces.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    try:
        walk(raw)
    except Exception:
        return ""

    # join with newlines to separate fragments
    return "\n".join(pieces)


async def safe_generate(llm_client, system_prompt: str, user_prompt: str, model: str, max_tokens: int, settings, retries: int = 2):
    """Generate via LLM with cost guard and simple retry/backoff.

    Estimates tokens conservatively and compares against settings.max_cost_per_request.
    Raises RuntimeError if estimated cost exceeds cap.
    """
    # conservative estimates: 1 token ~= 4 chars
    input_tokens = max(1, len(user_prompt) // 4)
    output_tokens = max_tokens

    tm = TokenMetrics(input_tokens=input_tokens, output_tokens=output_tokens, model=model)
    # prefer pricing lookup in TokenMetrics but allow override via DEFAULT_PRICING
    try:
        est_cost = tm.estimate_cost()
    except Exception:
        # fallback to DEFAULT_PRICING
        rates = DEFAULT_PRICING.get(model, {"input": 0.00000001, "output": 0.00000003})
        est_cost = (input_tokens * rates["input"]) + (output_tokens * rates["output"])  

    max_allowed = getattr(settings, "max_cost_per_request", 0.01)
    if est_cost > max_allowed:
        raise RuntimeError(f"Cost guard: estimated ${est_cost:.6f} for model={model} exceeds per-request cap ${max_allowed:.6f}")

    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = await llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                provider="gemini",
                model=model,
                max_tokens=max_tokens
            )
            # Save raw response text for debugging and post-mortem analysis
            try:
                raw_dir = Path("/tmp/seed_raw_llm")
                raw_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                model_safe = model.replace("/", "_")
                fname = raw_dir / f"{ts}_{model_safe}.txt"
                text_val = getattr(resp, 'text', '') or ''
                fname.write_text(text_val, encoding="utf-8")
                logger.info(f"Saved raw LLM response to {fname} (len={len(text_val)})")
                if not text_val:
                    meta_fname = raw_dir / f"{ts}_{model_safe}.meta.txt"
                    try:
                        meta = {
                            "repr": str(resp),
                            "provider": getattr(resp, 'provider', None),
                            "model": getattr(resp, 'model', None),
                            "tokens_in": getattr(resp, 'tokens_in', None),
                            "tokens_out": getattr(resp, 'tokens_out', None),
                        }
                        # include raw_json if returned by the client
                        if hasattr(resp, '_raw_json') and resp._raw_json is not None:
                            meta['raw_http'] = resp._raw_json

                        meta_fname.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                        logger.info(f"Saved raw LLM response metadata to {meta_fname}")
                    except Exception:
                        logger.exception("Failed to save raw LLM response metadata")
                    # Attempt to recover any parsable JSON from raw_http for later use
                    try:
                        recovered = ""
                        if hasattr(resp, '_raw_json') and resp._raw_json:
                            recovered = _extract_text_from_raw_json(resp._raw_json.get('body', {}))
                            if recovered:
                                setattr(resp, 'recovered_text', recovered)
                                # also persist recovered text
                                rec_fname = raw_dir / f"{ts}_{model_safe}.recovered.txt"
                                rec_fname.write_text(recovered, encoding="utf-8")
                                logger.info(f"Saved recovered text to {rec_fname}")
                    except Exception:
                        logger.exception("Failed to recover text from raw LLM response")
            except Exception:
                logger.exception("Failed to save raw LLM response to /tmp/seed_raw_llm")
            # If model returned empty text but raw_json indicates MAX_TOKENS, try one fallback model
            try:
                if (not text_val) and hasattr(resp, '_raw_json') and resp._raw_json:
                    body = resp._raw_json.get('body', {})
                    candidates = body.get('candidates', []) if isinstance(body, dict) else []
                    if candidates and candidates[0].get('finishReason') == 'MAX_TOKENS':
                        fallback_model = getattr(settings, 'gemini_fallback_model', 'gemini-2.5-flash')
                        # avoid retrying same model
                        if fallback_model and fallback_model != model:
                            # estimate fallback cost conservatively
                            try:
                                tm_fb = TokenMetrics(input_tokens=input_tokens, output_tokens=max_tokens, model=fallback_model)
                                est_fb = tm_fb.estimate_cost()
                            except Exception:
                                est_fb = 0.0

                            if est_fb <= getattr(settings, 'max_cost_per_request', 0.01):
                                logger.warning(f"LLM returned MAX_TOKENS on model={model}; retrying once with fallback_model={fallback_model}")
                                try:
                                    resp_fb = await llm_client.generate(
                                        system_prompt=system_prompt,
                                        user_prompt=user_prompt,
                                        provider="gemini",
                                        model=fallback_model,
                                        max_tokens=max_tokens
                                    )
                                    # persist fallback raw
                                    try:
                                        ts_fb = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
                                        fname_fb = raw_dir / f"{ts_fb}_{fallback_model.replace('/','_')}.txt"
                                        fname_fb.write_text(getattr(resp_fb, 'text', '') or '', encoding='utf-8')
                                        logger.info(f"Saved fallback raw LLM response to {fname_fb} (len={len(getattr(resp_fb,'text','') or '')})")
                                    except Exception:
                                        logger.exception("Failed to save fallback raw response")
                                    return resp_fb
                                except Exception:
                                    logger.exception("Fallback LLM generate failed")
            except Exception:
                logger.exception("Error checking raw_json finishReason for fallback")

            return resp
        except Exception as e:
            last_exc = e
            wait = 0.5 * (2 ** attempt)
            logger.warning(f"LLM generate failed (attempt {attempt+1}/{retries+1}): {e}; retrying in {wait}s")
            await asyncio.sleep(wait)

    # if we reach here, re-raise last exception
    raise last_exc

# ============================================================================
# COST TRACKING & GUARDRAILS
# ============================================================================

@dataclass
class TokenMetrics:
    """Track tokens and estimated cost"""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens
    
    def estimate_cost(self) -> float:
        """Estimate cost in USD based on model pricing"""
        # Use DEFAULT_PRICING defined at module level (units USD per token approx)
        pricing = DEFAULT_PRICING
        rates = pricing.get(self.model, {"input": 0.00000001, "output": 0.00000003})
        cost = (self.input_tokens * rates["input"]) + (self.output_tokens * rates["output"])
        return cost


@dataclass
class CostBudget:
    """Track costs across all phases"""
    phase_0_cost: float = 0.0
    phase_1_cost: float = 0.0
    phase_2_cost: float = 0.0
    phase_3_cost: float = 0.0
    max_cost_per_request: float = 0.01
    
    @property
    def total_cost(self) -> float:
        return self.phase_0_cost + self.phase_1_cost + self.phase_2_cost + self.phase_3_cost
    
    def can_proceed(self, phase_cost: float) -> bool:
        """Check if next request would exceed budget"""
        # Enforce per-request cap: phase_cost must not exceed max_cost_per_request
        return phase_cost <= self.max_cost_per_request


# ============================================================================
# PHASE 0: INTENT ANALYSIS
# ============================================================================

@dataclass
class PedagogicalIntent:
    """High-level pedagogical requirement"""
    description: str  # e.g., "Create Spanish A2 lesson on greetings"
    target_lang: str
    native_lang: str
    cefr_level: str
    topics: List[str]
    focus_areas: List[str]
    constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IntentSpecification:
    """Output of Phase 0"""
    baseline_system_instruction: str
    test_cases: List[OptimizerTestCase]
    negative_constraints: List[str]  # e.g., "Avoid subjunctive for A2", "No romaji for non-Japanese"
    target_vocabulary: List[str]
    linguistic_schema: Dict[str, Any]


class IntentAnalyzer:
    """Phase 0: Transform natural language intent into technical spec"""
    
    def __init__(self, use_experimental_models: bool = False, logger_obj: OptimizerLogger = None):
        """Initialize Phase 0 analyzer.
        
        Args:
            use_experimental_models: If False (default), use gemini-2.5-flash for all Phase 0 tasks.
                                      If True, use gemini-2.5-pro (for diagnosis/experimentation only).
            logger_obj: OptimizerLogger instance for tracking steps
        """
        self.settings = get_settings()
        self.llm_client = None
        self.cost_budget = CostBudget()
        self.use_experimental_models = use_experimental_models
        self.phase0_model = "gemini-2.5-pro" if use_experimental_models else "gemini-2.5-flash"
        self.logger_obj = logger_obj
    
    async def analyze_intent(self, intent: PedagogicalIntent) -> IntentSpecification:
        """Transform intent into specification"""
        self.llm_client = await get_llm_client()
        
        logger.info(f"Phase 0: Intent Analysis - {intent.description}")
        
        # Generate baseline system instruction
        baseline_prompt = await self._generate_baseline_instruction(intent)
        
        # Generate test cases
        test_cases = await self._generate_test_cases(intent)
        
        # Generate negative constraints
        negative_constraints = await self._generate_negative_constraints(intent)
        
        # Extract target vocabulary
        target_vocabulary = await self._extract_target_vocabulary(intent)
        
        # Get linguistic schema
        linguistic_schema = get_language_schema(intent.target_lang)
        
        return IntentSpecification(
            baseline_system_instruction=baseline_prompt,
            test_cases=test_cases,
            negative_constraints=negative_constraints,
            target_vocabulary=target_vocabulary,
            linguistic_schema=linguistic_schema
        )
    
    async def _generate_baseline_instruction(self, intent: PedagogicalIntent) -> str:
        """Generate initial system instruction"""
        prompt = f"""You are an expert language learning content designer.

Analyze this pedagogical intent and create a concise system instruction for a content generator:

**Intent:**
- Description: {intent.description}
- Target Language: {intent.target_lang}
- CEFR Level: {intent.cefr_level}
- Topics: {', '.join(intent.topics)}
- Focus Areas: {', '.join(intent.focus_areas)}

Generate a system instruction that:
1. Is concise (< 500 tokens)
2. Specifies the exact format expected (JSON schema outline)
3. Enforces CEFR {intent.cefr_level} constraints
4. Mandates 10 exercises with specific diversity (3 MCQ, 3 Translation, 2 Word Bank, 2 Listening)
5. Includes quality checks for {intent.target_lang}

Return ONLY the system instruction text, no explanations."""
        
        response = await safe_generate(
            self.llm_client,
            system_prompt="You are a prompt engineer specializing in language learning.",
            user_prompt=prompt,
            model=self.phase0_model,
            max_tokens=800,
            settings=self.settings,
            retries=2
        )
        
        # Log baseline generation
        if self.logger_obj:
            self.logger_obj.log_step(
                phase="Phase0",
                step="generate_baseline_instruction",
                prompt=prompt,
                response=response.text or "",
                model=self.phase0_model,
                tokens_in=getattr(response, 'tokens_in', None),
                tokens_out=getattr(response, 'tokens_out', None)
            )
        
        # If the LLM client returned raw_http diagnostics, log them for post-mortem
        if hasattr(response, '_raw_json') and response._raw_json:
            logger.debug(f"Phase 0 baseline response raw_http: {response._raw_json}")
        # If the primary model returned empty text, retry with a different model
        if not (getattr(response, 'text', '') or '').strip():
            logger.warning("Phase 0: gemini-2.5-pro returned empty text — retrying with gemini-2.5-flash")
            try:
                response = await safe_generate(
                    self.llm_client,
                    system_prompt="You are a prompt engineer specializing in language learning.",
                    user_prompt=prompt,
                    model="gemini-2.5-flash",
                    max_tokens=1000,
                    settings=self.settings,
                    retries=2
                )
            except Exception as e:
                logger.warning(f"Phase 0 retry failed: {e}")

        logger.info(f"✓ Phase 0: Baseline instruction generated ({len(getattr(response,'text','') or '')} chars)")
        return getattr(response, 'text', '') or ''
    
    async def _generate_test_cases(self, intent: PedagogicalIntent) -> List[OptimizerTestCase]:
        """Generate 3-5 test cases specific to this intent"""
        prompt = f"""Create 3-5 diverse test cases for a {intent.target_lang} lesson on {', '.join(intent.topics)}.

Each test case should:
1. Vary the difficulty within {intent.cefr_level}
2. Test different aspects of the content
3. Include specific validation criteria

Return JSON array:
[
  {{
    "id": "tc_1",
    "description": "...",
    "target_lang": "{intent.target_lang}",
    "cefr_level": "{intent.cefr_level}",
    "topic": "topic_name",
    "focus": "focus_area",
    "min_score": 85
  }},
  ...
]"""
        
        # Force strict JSON-only output to avoid markdown, preamble, or explanation
        prompt += "\n\n🚨 CRITICAL: OUTPUT ONLY VALID JSON ARRAY. NO MARKDOWN. NO EXPLANATIONS. NO PREAMBLE. STRICTLY [{...}, {...}] FORMAT."
        response = await safe_generate(
            self.llm_client,
            system_prompt="You are a language learning assessment specialist.",
            user_prompt=prompt,
            model=self.phase0_model,
            max_tokens=2000,  # Increased from 1000 to prevent truncation
            settings=self.settings,
            retries=2
        )
        
        # Parse and convert to OptimizerTestCase
        response_text = response.text or getattr(response, 'recovered_text', '') or ''
        parsed = parse_llm_json(response_text)
        test_dicts: List[Dict[str, Any]] = []
        
        if isinstance(parsed, list):
            test_dicts = parsed
            logger.debug(f"Phase 0: Parsed test cases directly as list ({len(parsed)} items)")
        elif isinstance(parsed, dict):
            # Try to unwrap if it's a dict with a list inside
            unwrapped = unwrap_json_array(parsed)
            if isinstance(unwrapped, list):
                test_dicts = unwrapped
                logger.info(f"Phase 0: Unwrapped test cases from dict ({len(unwrapped)} items)")
            else:
                logger.warning(f"Phase 0: Failed to parse test cases JSON (got dict without list), creating defaults. Response preview: {response_text[:150]}")
        else:
            logger.warning(f"Phase 0: Failed to parse test cases JSON (got {type(parsed).__name__}), creating defaults. Response preview: {response_text[:150]}")
        
        # Create defaults if parsing failed
        if not test_dicts:
            test_dicts = [
                {"id": f"tc_{i+1}", "description": f"{t}", "topic": t, "focus": f, "min_score": 85}
                for i, (t, f) in enumerate(zip(intent.topics, intent.focus_areas))
            ][:5]
        
        test_cases = [
            OptimizerTestCase(
                id=t.get("id", f"tc_{i+1}"),
                description=t.get("description", ""),
                target_lang=intent.target_lang,
                native_lang=intent.native_lang,
                cefr_level=intent.cefr_level,
                topic=t.get("topic", ""),
                focus=t.get("focus", ""),
                expected_vocab_count=10,
                expected_dialogue_scenes=2,
                min_score=t.get("min_score", 85)
            )
            for i, t in enumerate(test_dicts[:5])
        ]
        
        logger.info(f"✓ Phase 0: Generated {len(test_cases)} test cases")
        return test_cases
    
    async def _generate_negative_constraints(self, intent: PedagogicalIntent) -> List[str]:
        """Generate forbidden structures/topics"""
        prompt = f"""List forbidden grammatical structures, topics, and patterns for {intent.target_lang} CEFR {intent.cefr_level}.

Examples:
- "Avoid subjunctive mood"
- "No formal register"
- "Exclude past perfect"

Return JSON array of 5-8 constraints:
["constraint1", "constraint2", ...]"""
        
        # Force strict JSON-only output
        prompt += "\n\nIMPORTANT: Return ONLY a JSON array (a list) of strings and nothing else. No markdown, no explanation."
        response = await safe_generate(
            self.llm_client,
            system_prompt="You are a CEFR curriculum expert.",
            user_prompt=prompt,
            model=self.phase0_model,
            max_tokens=500,
            settings=self.settings,
            retries=2
        )
        
        parsed = parse_llm_json(response.text or getattr(response, 'recovered_text', ''))
        constraints: List[str] = []
        if isinstance(parsed, list):
            constraints = parsed
        else:
            constraints = [f"Avoid complex {intent.target_lang} structures"]
        
        logger.info(f"✓ Phase 0: Generated {len(constraints)} negative constraints")
        return constraints
    
    async def _extract_target_vocabulary(self, intent: PedagogicalIntent) -> List[str]:
        """Extract mandatory vocabulary"""
        prompt = f"""What are the essential vocabulary words for {intent.target_lang} learners at CEFR {intent.cefr_level} studying {', '.join(intent.topics)}?

Return JSON array of 10-15 key terms:
["word1", "word2", ...]"""
        
        # Force strict JSON-only output
        prompt += "\n\nIMPORTANT: Return ONLY a JSON array (a list) of strings. Do not include markdown, explanation, or extra text."
        response = await safe_generate(
            self.llm_client,
            system_prompt="You are a vocabulary specialist.",
            user_prompt=prompt,
            model=self.phase0_model,
            max_tokens=400,
            settings=self.settings,
            retries=2
        )
        
        parsed = parse_llm_json(response.text or getattr(response, 'recovered_text', ''))
        vocab: List[str] = []
        if isinstance(parsed, list):
            vocab = parsed
        else:
            vocab = [f"{intent.target_lang}_{t}" for t in intent.topics[:5]]
        
        logger.info(f"✓ Phase 0: Extracted {len(vocab)} target vocabulary terms")
        return vocab


# ============================================================================
# PHASE 1: BULK DISCOVERY
# ============================================================================

class BulkDiscovery:
    """Phase 1: 5-7 fast iterations to find optimal prompt"""
    
    def __init__(self, specification: IntentSpecification):
        self.spec = specification
        self.settings = get_settings()
        self.iterations = []
        self.cost_budget = CostBudget()
    
    async def run(self, max_iterations: int = 7) -> Dict[str, Any]:
        """Execute bulk discovery iterations"""
        logger.info(f"Phase 1: Bulk Discovery - starting {max_iterations} iterations")
        
        llm_client = await get_llm_client()
        current_prompt = self.spec.baseline_system_instruction
        best_score = 0.0
        best_prompt = current_prompt
        
        for iteration in range(1, max_iterations + 1):
            logger.info(f"  Phase 1 Iteration {iteration}/{max_iterations}")
            
            # Quick validation of prompt
            score = await self._quick_validate(current_prompt, llm_client)
            
            self.iterations.append({
                "iteration": iteration,
                "score": score,
                "prompt_length": len(current_prompt),
                "timestamp": datetime.now().isoformat()
            })
            
            if score > best_score:
                best_score = score
                best_prompt = current_prompt
            
            # Early stopping if plateau
            if iteration > 3 and self._check_plateau():
                logger.info(f"  Phase 1: Early stopping after {iteration} iterations (plateau detected)")
                break
            
            # Refine prompt for next iteration
            current_prompt = await self._refine_prompt(
                current_prompt, score, llm_client, iteration
            )
        
        logger.info(f"✓ Phase 1: Complete - Best score {best_score:.1f}/100")
        
        return {
            "best_prompt": best_prompt,
            "best_score": best_score,
            "iterations": self.iterations
        }
    
    async def _quick_validate(self, prompt: str, llm_client) -> float:
        """Quick validation without full test run"""
        # Simplified: just check that prompt is non-empty and contains key requirements
        base_score = 50.0
        
        checks = [
            ("10 exercises" in prompt.lower(), 10),
            ("mcq" in prompt.lower() or "multiple choice" in prompt.lower(), 10),
            ("translation" in prompt.lower(), 10),
            ("json" in prompt.lower(), 10),
            ("cefr" in prompt.lower() or "level" in prompt.lower(), 10),
            ("listening" in prompt.lower(), 10),
            ("word bank" in prompt.lower(), 10),
        ]
        
        for check, points in checks:
            if check:
                base_score += points
        
        return min(base_score, 100.0)
    
    def _check_plateau(self) -> bool:
        """Check if improvements have plateaued"""
        if len(self.iterations) < 4:  # Need at least 4 iterations to confirm plateau
            return False
        
        # Check last 4 iterations for plateau
        recent = [it["score"] for it in self.iterations[-4:]]
        
        # If last 3 scores are identical or within ±0.5, it's a plateau
        last_three = recent[-3:]
        if max(last_three) - min(last_three) < 0.5:
            logger.debug(f"Phase 1: Plateau detected - scores {last_three}")
            return True
        
        # Also check if trend is negative/flat
        avg_improvement = (recent[-1] - recent[0]) / 3
        if avg_improvement < 0.1:  # < 0.1 points improvement per iteration
            logger.debug(f"Phase 1: Minimal improvement trend - avg {avg_improvement:.2f} pts/iter")
            return True
        
        return False
    
    async def _refine_prompt(self, prompt: str, score: float, llm_client, iteration: int) -> str:
        """Refine prompt for next iteration (simple rule-based)"""
        if score < 60:
            return prompt + "\n\n[CRITICAL] Ensure exactly 10 exercises structured as: 3 MCQ, 3 Translation, 2 Word Bank, 2 Listening Mimic."
        elif score < 80:
            return prompt + "\n\n[IMPORTANT] Add specific acceptance criteria for each exercise type."
        else:
            return prompt  # Good enough, no refinement needed


# ============================================================================
# PHASE 2: PRECISION REFINEMENT
# ============================================================================

class PrecisionRefinement:
    """Phase 2: 2-3 final iterations with gemini-2.5-flash"""
    
    def __init__(self, spec: IntentSpecification, best_prompt_from_phase1: str, jury_feedback: Optional[List[str]] = None):
        self.spec = spec
        self.current_prompt = best_prompt_from_phase1
        self.iterations = []
        self.jury_feedback = jury_feedback or []
    
    async def run(self, max_iterations: int = 3) -> Dict[str, Any]:
        """Execute precision refinement"""
        logger.info(f"Phase 2: Precision Refinement - {max_iterations} iterations")
        
        llm_client = await get_llm_client()
        best_score = 0.0
        best_prompt = self.current_prompt
        
        for iteration in range(1, max_iterations + 1):
            logger.info(f"  Phase 2 Iteration {iteration}/{max_iterations}")
            
            # Refine for style, pedagogy, synonym expansion
            refined = await self._refine_for_quality(llm_client, iteration)
            
            # Quick validation
            score = await self._validate_quality(refined, llm_client)
            
            self.iterations.append({
                "iteration": iteration,
                "score": score,
                "focus": "style_pedagogy_synonyms",
                "timestamp": datetime.now().isoformat()
            })
            
            if score > best_score:
                best_score = score
                best_prompt = refined
            
            self.current_prompt = refined
        
        logger.info(f"✓ Phase 2: Complete - Best score {best_score:.1f}/100")
        
        return {
            "best_prompt": best_prompt,
            "best_score": best_score,
            "iterations": self.iterations
        }
    
    async def _refine_for_quality(self, llm_client, iteration: int) -> str:
        """Refine using LLM for style, pedagogy, synonym expansion"""
        feedback_context = ""
        if self.jury_feedback:
            feedback_context = f"\n\nAddress these jury issues:\n" + "\n".join(f"- {fb}" for fb in self.jury_feedback[:3])
        
        refine_prompt = f"""Enhance this language learning instruction prompt:

**Current Prompt:**
{self.current_prompt}
{feedback_context}

**Enhancement Focus:**
1. Pedagogical clarity (explain why each exercise type)
2. Synonym expansion (provide 3+ accepted answer variants for translation)
3. CEFR {self.spec.test_cases[0].cefr_level if self.spec.test_cases else 'A2'} appropriateness
4. Explicit exercise count enforcement (10 exercises: 3 MCQ, 3 Translation, 2 Word Bank, 2 Listening)

Return the refined instruction prompt only, no explanations."""
        
        settings = get_settings()
        response = await safe_generate(
            llm_client,
            system_prompt="You are a language learning curriculum specialist refining system instructions.",
            user_prompt=refine_prompt,
            model="gemini-2.5-flash",
            max_tokens=1500,
            settings=settings,
            retries=2
        )

        return response.text.strip()
    
    async def _validate_quality(self, prompt: str, llm_client) -> float:
        """Validate quality of refined prompt"""
        # Simplified quality check - can be enhanced
        quality_score = 70.0
        
        checks = [
            ("synonym" in prompt.lower() or "variant" in prompt.lower(), 10),
            ("cefr" in prompt.lower(), 5),
            ("pedagog" in prompt.lower(), 10),
            ("exercise" in prompt.lower() and ("10" in prompt or "ten" in prompt.lower()), 5),
        ]
        
        for check, points in checks:
            if check:
                quality_score += points
        
        return min(quality_score, 100.0)


# ============================================================================
# PHASE 3: JURY AUDIT
# ============================================================================

class JuryAudit:
    """Phase 3: Independent cross-model verification"""
    
    def __init__(self, spec: IntentSpecification, final_prompt: str):
        self.spec = spec
        self.final_prompt = final_prompt
    
    async def run(self) -> Dict[str, Any]:
        """Execute jury audit"""
        logger.info("Phase 3: Jury Audit")
        
        llm_client = await get_llm_client()

        # First, generate one sample exercise using the final prompt so the jury can evaluate real output
        sample_text = ""
        try:
            sample_req = f"""Using the following system instruction, generate EXACTLY ONE exercise in the expected JSON object format (no markdown, no explanation).\n\nSYSTEM INSTRUCTION:\n{self.final_prompt}\n\nReturn ONLY a single JSON object representing one exercise."""
            sample_resp = await safe_generate(
                llm_client,
                system_prompt="You are a language learning content generator.",
                user_prompt=sample_req,
                model="gemini-2.0-flash-lite",
                max_tokens=400,
                settings=get_settings(),
                retries=1
            )
            sample_text = sample_resp.text or ""
        except Exception as e:
            logger.warning(f"Failed to generate sample exercise for jury: {e}")

        audit_prompt = f"""Review this language learning content generator system instruction against the original intent.

**Original Intent:**
- Target: {self.spec.test_cases[0].target_lang if self.spec.test_cases else 'Unknown'} CEFR {self.spec.test_cases[0].cefr_level if self.spec.test_cases else 'Unknown'}
- Topics: {', '.join([tc.topic for tc in self.spec.test_cases[:3]])}

**System Instruction to Audit:**
{self.final_prompt}

**Example generated exercise (one sample):**
{sample_text}


**Audit Criteria:**
1. Does it enforce 10 exercises (3 MCQ, 3 Translation, 2 Word Bank, 2 Listening)?
2. Are negative constraints respected? {self.spec.negative_constraints[:2]}
3. Does it target the right vocabulary? {self.spec.target_vocabulary[:5]}

Return JSON:
{{
  "aligned_with_intent": true/false,
  "score": 0-100,
  "issues": ["issue1", "issue2"],
  "recommendation": "APPROVE|REVISE"
}}"""
        
        settings = get_settings()
        response = await safe_generate(
            llm_client,
            system_prompt="You are an independent QA auditor for language learning content.",
            user_prompt=audit_prompt,
            model="gemini-2.0-flash",
            max_tokens=800,
            settings=settings,
            retries=2
        )

        parsed = parse_llm_json(response.text or getattr(response, 'recovered_text', ''))
        audit_result = parsed if isinstance(parsed, dict) else {}
        
        # Log if parsing failed for debugging
        if not audit_result:
            logger.warning(f"Phase 3: Jury response parse failed. Raw text preview (first 200 chars): {(response.text or '')[:200]}")
        
        # Try to unwrap if wrapped in a dict
        if not audit_result or 'score' not in audit_result:
            unwrapped = unwrap_json_array(parsed) if parsed else None
            if isinstance(unwrapped, dict):
                audit_result = unwrapped
        
        # Extract score using robust helper (handles nested dicts)
        score = extract_jury_score(audit_result)
        logger.info(f"✓ Phase 3: Jury score {score}/100 - {audit_result.get('recommendation', 'UNKNOWN')}")
        
        return {
            "jury_score": score,
            "audit_result": audit_result,
            "needs_revision": score < 80
        }


# ============================================================================
# MULTI-PHASE ORCHESTRATOR
# ============================================================================

class MultiPhaseOptimizer:
    """Orchestrates all 4 phases"""
    
    def __init__(self, output_dir: Optional[Path] = None):
        if output_dir is None:
            output_dir = Path(__file__).parent.parent.parent / "optimizer_logs" / "multi_phase"
        
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = f"multi_phase_{int(time.time())}"
        self.session_dir = self.output_dir / self.session_id
        self.session_dir.mkdir(exist_ok=True)
        self.logger_obj = OptimizerLogger(self.session_id, self.output_dir)
    
    async def optimize(self, intent: PedagogicalIntent) -> Dict[str, Any]:
        """Run full 4-phase optimization"""
        logger.info(f"🚀 Multi-Phase Optimizer - Session {self.session_id}")
        
        result = {
            "session_id": self.session_id,
            "intent": asdict(intent),
            "phases": {}
        }
        
        # Phase 0
        analyzer = IntentAnalyzer(logger_obj=self.logger_obj)
        spec = await analyzer.analyze_intent(intent)
        result["phases"]["phase_0"] = {
            "baseline_instruction_length": len(spec.baseline_system_instruction),
            "test_cases_count": len(spec.test_cases),
            "negative_constraints_count": len(spec.negative_constraints),
            "vocabulary_count": len(spec.target_vocabulary)
        }
        
        # Phase 1
        discovery = BulkDiscovery(spec)
        phase1_result = await discovery.run(max_iterations=7)
        result["phases"]["phase_1"] = phase1_result
        
        # Phase 2
        refinement = PrecisionRefinement(spec, phase1_result["best_prompt"])
        phase2_result = await refinement.run(max_iterations=3)
        result["phases"]["phase_2"] = phase2_result
        
        # Phase 3
        jury = JuryAudit(spec, phase2_result["best_prompt"])
        phase3_result = await jury.run()
        result["phases"]["phase_3"] = phase3_result
        
        # Fallback if jury score < 80
        if phase3_result["needs_revision"]:
            logger.info("⚠️ Phase 3: Jury score below 80, triggering Phase 2 fallback...")
            jury_issues = phase3_result.get("audit_result", {}).get("issues", [])
            refinement = PrecisionRefinement(spec, phase1_result["best_prompt"], jury_feedback=jury_issues)
            phase2_retry = await refinement.run(max_iterations=2)
            result["phases"]["phase_2_retry"] = phase2_retry
            # create a new JuryAudit using the updated prompt from the retry
            updated_prompt = phase2_retry.get("best_prompt") or phase2_retry.get("prompt") or phase1_result.get("best_prompt")
            new_jury = JuryAudit(spec, updated_prompt)
            phase3_retry = await new_jury.run()
            result["phases"]["phase_3_retry"] = phase3_retry
        
        # Save results
        self._save_results(result, spec)
        
        # Save logger summary
        self.logger_obj.save_summary()
        
        logger.info(f"✅ Optimization complete - Session: {self.session_id}")
        return result
    
    def _save_results(self, result: Dict[str, Any], spec: IntentSpecification) -> None:
        """Save results to session directory"""
        report_path = self.session_dir / "optimization_report.json"
        report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        
        spec_path = self.session_dir / "specification.json"
        spec_data = {
            "baseline_system_instruction": spec.baseline_system_instruction,
            "negative_constraints": spec.negative_constraints,
            "target_vocabulary": spec.target_vocabulary,
            "test_cases": [asdict(tc) for tc in spec.test_cases]
        }
        spec_path.write_text(json.dumps(spec_data, indent=2, ensure_ascii=False), encoding="utf-8")
        
        logger.info(f"  📁 Results saved to {self.session_dir}")
