"""
Diagnostic Session Engine for Placement Testing (V0).

Handles session lifecycle, item generation, answer evaluation, and scoring.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.infrastructure.db.sqlite import DB
from app.services.diagnostic.engine import generate_diagnostic_items
from app.models.api import (
    DiagnosticBlueprint,
    DiagnosticGenerateRequest,
    DiagnosticItem,
    DiagnosticStartRequest,
    DiagnosticAttemptRequest,
    WeakSubskill,
)


# Load taxonomy (lazy, cached to avoid hard failure at import)
TAXONOMY_FILE = Path(__file__).parent.parent / "data" / "cefr_taxonomy.json"
_TAXONOMY_CACHE: dict | None = None

def get_taxonomy() -> dict:
    """
    Load taxonomy lazily and cache the result.
    
    Raises:
        RuntimeError: If taxonomy file cannot be loaded or is empty/invalid
    """
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is not None:
        return _TAXONOMY_CACHE
    
    try:
        _TAXONOMY_CACHE = json.loads(TAXONOMY_FILE.read_text(encoding="utf-8"))
        
        # Validate basic structure
        if not _TAXONOMY_CACHE.get("levels"):
            raise ValueError("Taxonomy file is missing 'levels' section")
        
        logging.info("Successfully loaded taxonomy with %d CEFR levels", 
                    len(_TAXONOMY_CACHE.get("levels", {})))
        return _TAXONOMY_CACHE
        
    except FileNotFoundError:
        logging.error("Taxonomy file not found: %s", TAXONOMY_FILE)
        raise RuntimeError(f"Taxonomy file not found: {TAXONOMY_FILE}")
    except json.JSONDecodeError as e:
        logging.error("Invalid JSON in taxonomy file: %s", e)
        raise RuntimeError(f"Invalid taxonomy file format: {e}")
    except Exception as e:
        logging.exception("Failed to load taxonomy file %s: %s", TAXONOMY_FILE, e)
        raise RuntimeError(f"Failed to load taxonomy: {e}")


def _now_iso() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _generate_session_id() -> str:
    """Generate unique session ID."""
    import uuid
    return f"diag_{uuid.uuid4().hex[:16]}"


def _hash_item(item_json: str) -> str:
    """Create deterministic hash of item for deduplication."""
    return hashlib.sha256(item_json.encode()).hexdigest()[:16]


def get_user_learning_profile(db: DB, user_id: str) -> dict:
    """
    Get user's learning profile based on historical diagnostic sessions.
    
    Returns:
        Dictionary with:
        - estimated_level: Latest CEFR estimate
        - weak_areas: List of (skill, subskill, accuracy) tuples
        - avg_accuracy: Overall accuracy across all attempts
        - session_count: Number of completed sessions
        - last_session_date: ISO timestamp of last session
    """
    # Get latest finished session
    cursor = db._conn.execute(
        """
        SELECT id, start_level_guess, finished_at
        FROM diagnostic_sessions 
        WHERE user_id = ? AND status = 'finished'
        ORDER BY finished_at DESC
        LIMIT 1
        """,
        (user_id,)
    )
    latest_session = cursor.fetchone()
    
    if not latest_session:
        return {
            "estimated_level": "A2",
            "weak_areas": [],
            "avg_accuracy": 0.0,
            "session_count": 0,
            "last_session_date": None
        }
    
    session_id = latest_session[0]
    
    # Calculate results for latest session
    results = calculate_results(db, session_id)
    
    # Get weak areas from all historical attempts
    cursor = db._conn.execute(
        """
        SELECT ds.id, da.tags_snapshot_json, da.is_correct
        FROM diagnostic_sessions ds
        JOIN diagnostic_attempts da ON ds.id = da.session_id
        WHERE ds.user_id = ? AND ds.status = 'finished'
        """,
        (user_id,)
    )
    
    # Aggregate weak areas across all sessions
    skill_stats = {}
    total_attempts = 0
    total_correct = 0
    
    for _, tags_json, is_correct in cursor.fetchall():
        tags = json.loads(tags_json)
        skill = tags.get("skill", "unknown")
        subskill = tags.get("subskill", "unknown")
        key = f"{skill}:{subskill}"
        
        if key not in skill_stats:
            skill_stats[key] = {"correct": 0, "total": 0, "skill": skill, "subskill": subskill}
        
        skill_stats[key]["total"] += 1
        if is_correct:
            skill_stats[key]["correct"] += 1
        
        total_attempts += 1
        if is_correct:
            total_correct += 1
    
    # Find weak areas (accuracy < 0.6)
    weak_areas = []
    for key, stats in skill_stats.items():
        if stats["total"] >= 2:  # Require at least 2 attempts
            accuracy = stats["correct"] / stats["total"]
            if accuracy < 0.6:
                weak_areas.append((stats["skill"], stats["subskill"], accuracy))
    
    # Sort by accuracy (weakest first)
    weak_areas.sort(key=lambda x: x[2])
    
    # Count sessions
    cursor = db._conn.execute(
        "SELECT COUNT(*) FROM diagnostic_sessions WHERE user_id = ? AND status = 'finished'",
        (user_id,)
    )
    session_count = cursor.fetchone()[0]
    
    avg_accuracy = total_correct / total_attempts if total_attempts > 0 else 0.0
    
    return {
        "estimated_level": results.get("estimated_cefr", "A2"),
        "weak_areas": weak_areas[:5],  # Top 5 weakest areas
        "avg_accuracy": avg_accuracy,
        "session_count": session_count,
        "last_session_date": latest_session[2]
    }


def load_blueprint_v0(
    start_level: str = "A2",
    seed: Optional[int] = None,
    shuffle: bool = True
) -> list[DiagnosticBlueprint]:
    """
    Load and adapt the standard 25-item blueprint from taxonomy.

    Behavior:
    - Filters items by difficulty appropriate to `start_level`.
    - Uses a local RNG seeded by `seed` for deterministic shuffling (does not affect global random).
    - If there are fewer than 25 items after filtering, relaxes the threshold progressively as a fallback
      (but with a maximum allowed difficulty cap to prevent inappropriate items).
    - Skips invalid blueprint entries that fail Pydantic parsing.

    Args:
        start_level: Starting CEFR level (A1, A2, B1, B2, C1)
        seed: Random seed for shuffling (if provided, enables deterministic shuffle)
        shuffle: Whether to shuffle the filtered items (default: True)

    Returns:
        List of up to 25 DiagnosticBlueprint objects

    Raises:
        ValueError: If no valid blueprint items are available after filtering
    """
    taxonomy = get_taxonomy()
    blueprint_data = taxonomy.get("standard_blueprint_25", [])

    if not blueprint_data:
        raise ValueError("Taxonomy contains no blueprint items")

    # Map levels to numeric difficulty thresholds (assumes difficulty numeric scale ~1-5)
    level_thresholds = {
        "A1": 2.0,
        "A2": 3.0,
        "B1": 4.0,
        "B2": 5.0,
        "C1": float("inf")
    }

    # Safe getter for difficulty
    def _get_difficulty(item: dict) -> float:
        try:
            return float(item.get("difficulty", 3.0))
        except (ValueError, TypeError):
            logging.warning("Invalid difficulty value in blueprint item, using default 3.0")
            return 3.0

    # Determine base threshold
    threshold = level_thresholds.get(start_level, level_thresholds["A2"])

    # Filter by threshold
    filtered_data = [item for item in blueprint_data if _get_difficulty(item) <= threshold]

    # Fallback: progressively relax threshold if too few items (with upper bound)
    TARGET_COUNT = 25
    MAX_RELAX_STEPS = 3  # Maximum number of relaxation steps
    RELAX_INCREMENT = 0.5  # Increment per step
    
    if len(filtered_data) < TARGET_COUNT:
        original_count = len(filtered_data)
        relaxed_threshold = threshold
        
        for step in range(MAX_RELAX_STEPS):
            relaxed_threshold += RELAX_INCREMENT
            
            # Don't go beyond reasonable bounds
            if relaxed_threshold > 5.5:
                break
            
            # Re-filter with relaxed threshold
            filtered_data = [item for item in blueprint_data if _get_difficulty(item) <= relaxed_threshold]
            
            if len(filtered_data) >= TARGET_COUNT:
                logging.info(
                    "Relaxed difficulty threshold from %.1f to %.1f for level %s (step %d): %d -> %d items",
                    threshold, relaxed_threshold, start_level, step + 1, original_count, len(filtered_data)
                )
                break
        
        if len(filtered_data) < TARGET_COUNT:
            logging.warning(
                "After relaxation, only %d items available for level %s (target: %d)",
                len(filtered_data), start_level, TARGET_COUNT
            )

    # Shuffle deterministically using local RNG if requested
    if shuffle and seed is not None:
        rng = random.Random(seed)
        rng.shuffle(filtered_data)
    elif shuffle:
        # Shuffle with system random (non-deterministic)
        random.shuffle(filtered_data)

    # Finally select up to TARGET_COUNT items
    selected_data = filtered_data[:TARGET_COUNT]

    # Convert to Pydantic models, skipping invalid entries
    blueprints: list[DiagnosticBlueprint] = []
    skipped = 0
    for item in selected_data:
        try:
            blueprints.append(DiagnosticBlueprint(**item))
        except Exception as e:
            skipped += 1
            logging.warning("Skipping invalid blueprint item during conversion: %s", e)

    if skipped:
        logging.info("Skipped %d invalid blueprint items", skipped)

    # Critical check: ensure we have at least some valid items
    if not blueprints:
        raise ValueError(
            f"No valid blueprint items available for level {start_level} after filtering and validation"
        )

    logging.debug(
        "Loaded blueprint: %d valid items for level %s (threshold=%.1f, seed=%s, shuffle=%s)",
        len(blueprints), start_level, threshold, str(seed), shuffle
    )
    
    return blueprints


def load_blueprint_adaptive(
    db: DB,
    user_id: str,
    start_level: Optional[str] = None,
    seed: Optional[int] = None,
    shuffle: bool = True,
    focus_weak_areas: bool = True
) -> list[DiagnosticBlueprint]:
    """
    Load adaptive blueprint based on user's learning profile.
    
    Uses user's historical data to:
    - Determine appropriate difficulty level
    - Emphasize weak areas (skills/subskills with low accuracy)
    - Adjust task distribution based on progress
    
    Args:
        db: Database instance
        user_id: User ID for profile lookup
        start_level: Override level (if None, uses profile)
        seed: Random seed for deterministic shuffle
        shuffle: Whether to shuffle items
        focus_weak_areas: If True, increase representation of weak areas
        
    Returns:
        List of DiagnosticBlueprint objects adapted to user
    """
    # Get user profile
    profile = get_user_learning_profile(db, user_id)
    
    # Determine effective level
    effective_level = start_level or profile["estimated_level"]
    
    # Load base blueprint
    taxonomy = get_taxonomy()
    blueprint_data = taxonomy.get("standard_blueprint_25", [])
    
    if not blueprint_data:
        raise ValueError("Taxonomy contains no blueprint items")
    
    # If user has weak areas and focus is enabled, boost those areas
    if focus_weak_areas and profile["weak_areas"]:
        weak_skills = {area[0] for area in profile["weak_areas"]}
        weak_subskills = {area[1] for area in profile["weak_areas"]}
        
        # Categorize items
        weak_area_items = []
        regular_items = []
        
        for item in blueprint_data:
            item_skill = item.get("skill", "")
            item_subskill = item.get("subskill", "")
            
            if item_skill in weak_skills or item_subskill in weak_subskills:
                weak_area_items.append(item)
            else:
                regular_items.append(item)
        
        # Use standard load for level filtering
        base_blueprints = load_blueprint_v0(effective_level, seed=None, shuffle=False)
        base_difficulty_threshold = max(bp.difficulty for bp in base_blueprints) if base_blueprints else 3.0
        
        # Filter weak area items by appropriate difficulty
        def _get_difficulty(item: dict) -> float:
            try:
                return float(item.get("difficulty", 3.0))
            except (ValueError, TypeError):
                return 3.0
        
        filtered_weak = [item for item in weak_area_items if _get_difficulty(item) <= base_difficulty_threshold + 0.5]
        filtered_regular = [item for item in regular_items if _get_difficulty(item) <= base_difficulty_threshold]
        
        # Compose: 60% weak areas, 40% regular (if enough weak items available)
        TARGET_COUNT = 25
        target_weak_count = min(15, len(filtered_weak))
        target_regular_count = TARGET_COUNT - target_weak_count
        
        # Select items
        selected_weak = filtered_weak[:target_weak_count]
        selected_regular = filtered_regular[:target_regular_count]
        
        # If not enough weak items, fill with regular
        if len(selected_weak) < target_weak_count:
            deficit = target_weak_count - len(selected_weak)
            selected_regular = filtered_regular[:target_regular_count + deficit]
        
        combined = selected_weak + selected_regular
        
        # Shuffle if requested
        if shuffle and seed is not None:
            rng = random.Random(seed)
            rng.shuffle(combined)
        elif shuffle:
            random.shuffle(combined)
        
        # Convert to Pydantic models
        blueprints: list[DiagnosticBlueprint] = []
        for item in combined[:TARGET_COUNT]:
            try:
                blueprints.append(DiagnosticBlueprint(**item))
            except Exception as e:
                logging.warning("Skipping invalid adaptive blueprint item: %s", e)
        
        if not blueprints:
            logging.warning("Adaptive blueprint generation failed, falling back to standard")
            return load_blueprint_v0(effective_level, seed, shuffle)
        
        logging.info(
            "Loaded adaptive blueprint for user %s: %d items (level=%s, weak_areas=%d)",
            user_id, len(blueprints), effective_level, len(selected_weak)
        )
        
        return blueprints
    
    # No weak areas or focus disabled - use standard blueprint
    return load_blueprint_v0(effective_level, seed, shuffle)


def analyze_user_progression(db: DB, user_id: str, window_sessions: int = 5) -> dict:
    """
    Analyze user's learning progression over recent sessions.
    
    Args:
        db: Database instance
        user_id: User ID
        window_sessions: Number of recent sessions to analyze
        
    Returns:
        Dictionary with:
        - trend: 'improving', 'stable', or 'declining'
        - level_progression: List of (session_date, estimated_level) tuples
        - accuracy_progression: List of (session_date, accuracy) tuples
        - velocity: Rate of improvement (CEFR levels per session)
    """
    cursor = db._conn.execute(
        """
        SELECT id, finished_at
        FROM diagnostic_sessions
        WHERE user_id = ? AND status = 'finished'
        ORDER BY finished_at DESC
        LIMIT ?
        """,
        (user_id, window_sessions)
    )
    
    sessions = cursor.fetchall()
    
    if len(sessions) < 2:
        return {
            "trend": "insufficient_data",
            "level_progression": [],
            "accuracy_progression": [],
            "velocity": 0.0
        }
    
    # Collect metrics for each session
    level_map = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5}
    level_progression = []
    accuracy_progression = []
    
    for session_id, finished_at in reversed(sessions):  # Oldest to newest
        results = calculate_results(db, session_id)
        level = results.get("estimated_cefr", "A2")
        accuracy = results.get("accuracy", 0.0)
        
        level_progression.append((finished_at, level))
        accuracy_progression.append((finished_at, accuracy))
    
    # Calculate trend
    level_values = [level_map.get(lvl, 2) for _, lvl in level_progression]
    
    if len(level_values) >= 2:
        # Simple linear trend
        first_level = level_values[0]
        last_level = level_values[-1]
        
        if last_level > first_level:
            trend = "improving"
        elif last_level < first_level:
            trend = "declining"
        else:
            # Check accuracy trend if level is stable
            accuracy_values = [acc for _, acc in accuracy_progression]
            if accuracy_values[-1] > accuracy_values[0] + 0.1:
                trend = "improving"
            elif accuracy_values[-1] < accuracy_values[0] - 0.1:
                trend = "declining"
            else:
                trend = "stable"
        
        velocity = (last_level - first_level) / len(level_values)
    else:
        trend = "stable"
        velocity = 0.0
    
    return {
        "trend": trend,
        "level_progression": level_progression,
        "accuracy_progression": accuracy_progression,
        "velocity": velocity
    }


def create_diagnostic_session(
    db: DB,
    user_id: str,
    request: DiagnosticStartRequest,
    persona_id: Optional[str] = None,
    use_adaptive: bool = False,
    optimize_mode: bool = False
) -> tuple[str, list[DiagnosticItem]]:
    """
    Create a new diagnostic session with generated items.
    
    Args:
        db: Database instance
        user_id: User ID
        request: Start request with language params
        persona_id: Optional persona for generation
        use_adaptive: If True, use user profile to adapt blueprint (default: False for V0)
        
    Returns:
        (session_id, list of generated items)
    """
    session_id = _generate_session_id()
    seed = random.randint(1, 1000000)
    
    # Load blueprint (adaptive or standard)
    if use_adaptive:
        try:
            blueprint = load_blueprint_adaptive(
                db=db,
                user_id=user_id,
                start_level=request.start_level_guess,
                seed=seed,
                shuffle=True,
                focus_weak_areas=True
            )
            logging.info("Using adaptive blueprint for user %s", user_id)
        except Exception as e:
            logging.warning("Adaptive blueprint failed, falling back to standard: %s", e)
            blueprint = load_blueprint_v0(request.start_level_guess, seed)
    else:
        blueprint = load_blueprint_v0(request.start_level_guess, seed)
    
    # Create session record
    db.execute(
        """
        INSERT INTO diagnostic_sessions 
        (id, user_id, native_lang, target_lang, start_level_guess, status, seed, created_at)
        VALUES (?, ?, ?, ?, ?, 'running', ?, ?)
        """,
        (
            session_id,
            user_id,
            request.native_language,
            request.target_language,
            request.start_level_guess or "A2",
            seed,
            _now_iso()
        )
    )
    
    logging.info(
        "Created diagnostic session %s for user %s: %s->%s, seed=%d",
        session_id, user_id, request.native_language, request.target_language, seed
    )
    
    # Generate items using existing diagnostic engine
    # Note: This is now synchronous
    gen_request = DiagnosticGenerateRequest(
        nativeLang=request.native_language,
        targetLang=request.target_language,
        blueprint=blueprint,
        personaId=persona_id
    )
    
    # Call synchronous generation function
    response = generate_diagnostic_items(
        gen_request,
        user_id,
        persona_id,
        optimize_mode,
        trace_id=None,
        session_id=session_id,
        job_id=None,
    )
    
    items = response.diagnostic_set.items
    
    # Store items in database
    for idx, item in enumerate(items):
        item_json = item.model_dump_json(by_alias=True)
        tags_json = item.tags.model_dump_json(by_alias=True)
        item_hash = _hash_item(item_json)
        
        db.execute(
            """
            INSERT INTO diagnostic_session_items 
            (session_id, item_id, item_json, order_index, tags_json, item_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, item.id, item_json, idx, tags_json, item_hash)
        )
    
    logging.debug("Stored %d items for session %s", len(items), session_id)
    
    return session_id, items


def get_session_info(db: DB, session_id: str, user_id: str) -> Optional[dict]:
    """Get session information."""
    cursor = db._conn.execute(
        "SELECT * FROM diagnostic_sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id)
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def get_session_item(db: DB, session_id: str, item_id: str) -> Optional[DiagnosticItem]:
    """Load a specific item from session."""
    cursor = db._conn.execute(
        """
        SELECT item_json FROM diagnostic_session_items 
        WHERE session_id = ? AND item_id = ?
        """,
        (session_id, item_id)
    )
    row = cursor.fetchone()
    if not row:
        return None
    
    item_data = json.loads(row[0])
    return DiagnosticItem(**item_data)


def get_next_unanswered_item(db: DB, session_id: str) -> Optional[tuple[DiagnosticItem, int, int]]:
    """
    Get next unanswered item in session.
    
    Returns:
        (item, current_index, total_items) or None if all answered
    """
    # Get all items ordered
    cursor = db._conn.execute(
        """
        SELECT item_id, item_json, order_index 
        FROM diagnostic_session_items 
        WHERE session_id = ? 
        ORDER BY order_index
        """,
        (session_id,)
    )
    all_items = cursor.fetchall()
    
    if not all_items:
        return None
    
    total_items = len(all_items)
    
    # Get answered item IDs
    cursor = db._conn.execute(
        """
        SELECT DISTINCT item_id FROM diagnostic_attempts 
        WHERE session_id = ?
        """,
        (session_id,)
    )
    answered_ids = {row[0] for row in cursor.fetchall()}
    
    # Find first unanswered
    for item_id, item_json, order_index in all_items:
        if item_id not in answered_ids:
            item_data = json.loads(item_json)
            item = DiagnosticItem(**item_data)
            return item, order_index, total_items
    
    return None


def normalize_answer(text: str, method: str = "lower_trim") -> str:
    """Normalize answer for comparison."""
    if method == "lower_trim":
        return text.lower().strip()
    elif method == "exact":
        return text
    elif method == "ignore_punctuation":
        import string
        return text.lower().translate(str.maketrans('', '', string.punctuation)).strip()
    return text.lower().strip()


def normalize_answer_reorder_sentence(text: str) -> str:
    """
    Normalize answer for reorder_sentence task type.
    
    Handles common punctuation/case differences between user tokens and expected answers.
    Normalization steps:
    - Unicode NFKC normalization
    - Strip leading/trailing whitespace
    - Collapse multiple spaces to single space
    - Casefold (locale-aware lowercase)
    - Remove trailing sentence punctuation: . ! ? …
    """
    import re
    import unicodedata
    
    # Unicode normalize
    normalized = unicodedata.normalize("NFKC", text)
    
    # Strip and collapse whitespace
    normalized = normalized.strip()
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Casefold (better than lower for international text)
    normalized = normalized.casefold()
    
    # Remove trailing sentence punctuation
    normalized = re.sub(r'[.!?…]+$', '', normalized)
    
    # Final strip after punctuation removal
    normalized = normalized.strip()
    
    return normalized


def evaluate_answer(item: DiagnosticItem, user_answer: str) -> tuple[bool, str]:
    """
    Evaluate user answer against item's correct answers.
    
    For reorder_sentence tasks, applies robust normalization to handle
    punctuation/case differences between user tokens and expected answers.
    
    Returns:
        (is_correct, correct_answer_display)
    """
    item_type = item.task_type
    accepted_answers = item.answer.accepted
    normalize_method = item.answer.normalize or "lower_trim"
    
    # Special handling for reorder_sentence
    if item_type == "reorder_sentence":
        user_normalized = normalize_answer_reorder_sentence(user_answer)
        
        # Check against all accepted variants
        for accepted in accepted_answers:
            accepted_normalized = normalize_answer_reorder_sentence(accepted)
            if user_normalized == accepted_normalized:
                return True, accepted_answers[0]
        
        # Not correct
        return False, accepted_answers[0]
    
    # Standard normalization for other task types
    user_normalized = normalize_answer(user_answer, normalize_method)
    
    # Check against all accepted variants
    for accepted in accepted_answers:
        accepted_normalized = normalize_answer(accepted, normalize_method)
        if user_normalized == accepted_normalized:
            return True, accepted_answers[0]
    
    # Not correct
    return False, accepted_answers[0]


def store_attempt(
    db: DB,
    session_id: str,
    item_id: str,
    user_answer: str,
    is_correct: bool,
    response_time_ms: Optional[int],
    tags_json: str
) -> None:
    """Store user attempt in database."""
    score = 1.0 if is_correct else 0.0
    
    db.execute(
        """
        INSERT INTO diagnostic_attempts 
        (session_id, item_id, answer_raw, is_correct, score, response_time_ms, tags_snapshot_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, item_id, user_answer, int(is_correct), score, response_time_ms, tags_json, _now_iso())
    )
    
    logging.debug(
        "Stored attempt for session %s, item %s: correct=%s, time=%sms",
        session_id, item_id, is_correct, response_time_ms
    )


def calculate_results(db: DB, session_id: str) -> dict:
    """
    Calculate diagnostic results from all attempts.
    
    Returns:
        Dictionary with estimated_cefr, skill_scores, weak_subskills, etc.
    """
    # Load all attempts with tags
    cursor = db._conn.execute(
        """
        SELECT is_correct, score, tags_snapshot_json 
        FROM diagnostic_attempts 
        WHERE session_id = ?
        """,
        (session_id,)
    )
    attempts = cursor.fetchall()
    
    if not attempts:
        # No attempts yet
        return {
            "estimated_cefr": "A1",
            "skill_scores": {},
            "weak_subskills": [],
            "attempts_count": 0,
            "items_count": 0
        }
    
    attempts_count = len(attempts)
    
    # Parse attempts and group by skill/subskill
    skill_correct = {}
    skill_total = {}
    subskill_correct = {}
    subskill_total = {}
    subskill_skill_map = {}
    total_difficulty = 0.0
    
    for is_correct, score, tags_json in attempts:
        tags = json.loads(tags_json)
        skill = tags.get("skill", "unknown")
        subskill = tags.get("subskill", "unknown")
        difficulty = tags.get("difficulty", 2.0)
        
        # Track skill accuracy
        skill_correct[skill] = skill_correct.get(skill, 0) + (1 if is_correct else 0)
        skill_total[skill] = skill_total.get(skill, 0) + 1
        
        # Track subskill accuracy
        subskill_key = f"{skill}:{subskill}"
        subskill_correct[subskill_key] = subskill_correct.get(subskill_key, 0) + (1 if is_correct else 0)
        subskill_total[subskill_key] = subskill_total.get(subskill_key, 0) + 1
        subskill_skill_map[subskill_key] = (skill, subskill)
        
        total_difficulty += difficulty
    
    # Calculate overall accuracy
    total_correct = sum(1 for is_correct, _, _ in attempts if is_correct)
    overall_accuracy = total_correct / attempts_count if attempts_count > 0 else 0
    avg_difficulty = total_difficulty / attempts_count if attempts_count > 0 else 2.0
    
    # Estimate CEFR based on accuracy and difficulty
    estimated_cefr = estimate_cefr_level(overall_accuracy, avg_difficulty)
    
    # Calculate skill scores (0-100)
    skill_scores = {}
    for skill, total in skill_total.items():
        correct = skill_correct.get(skill, 0)
        accuracy = correct / total if total > 0 else 0
        skill_scores[skill] = int(accuracy * 100)
    
    # Find weak subskills (accuracy < 0.6, with at least 2 items)
    weak_subskills_list = []
    for subskill_key, total in subskill_total.items():
        if total >= 2:  # Require at least 2 items
            correct = subskill_correct.get(subskill_key, 0)
            accuracy = correct / total
            if accuracy < 0.6:
                skill, subskill = subskill_skill_map[subskill_key]
                weak_subskills_list.append({
                    "subskill": subskill,
                    "skill": skill,
                    "accuracy": accuracy,
                    "items_count": total
                })
    
    # Sort by accuracy (weakest first) and take top 3
    weak_subskills_list.sort(key=lambda x: x["accuracy"])
    top_weak = weak_subskills_list[:3]
    
    # If fewer than 3, pad with any subskills that have data
    if len(top_weak) < 3:
        for subskill_key, total in subskill_total.items():
            if len(top_weak) >= 3:
                break
            correct = subskill_correct.get(subskill_key, 0)
            accuracy = correct / total
            skill, subskill = subskill_skill_map[subskill_key]
            
            # Check if already in list
            if not any(w["subskill"] == subskill for w in top_weak):
                top_weak.append({
                    "subskill": subskill,
                    "skill": skill,
                    "accuracy": accuracy,
                    "items_count": total
                })
    
    # Format weak subskills with suggestions
    weak_subskills = [
        WeakSubskill(
            subskill=w["subskill"],
            skill=w["skill"],
            accuracy=w["accuracy"],
            suggestedFocus=generate_focus_suggestion(w["skill"], w["subskill"], w["accuracy"])
        )
        for w in top_weak
    ]
    
    # Get total items count
    cursor = db._conn.execute(
        "SELECT COUNT(*) FROM diagnostic_session_items WHERE session_id = ?",
        (session_id,)
    )
    items_count = cursor.fetchone()[0]
    
    # Compute desktop-friendly fields
    total_correct = sum(1 for is_correct, _, _ in attempts if is_correct)
    total_attempts = attempts_count
    accuracy_value = total_correct / total_attempts if total_attempts > 0 else 0.0
    
    return {
        "estimated_cefr": estimated_cefr,
        "skill_scores": skill_scores,
        "weak_subskills": weak_subskills,
        "attempts_count": attempts_count,
        "items_count": items_count,
        "total_correct": total_correct,
        "total_attempts": total_attempts,
        "accuracy": accuracy_value
    }


def estimate_cefr_level(accuracy: float, avg_difficulty: float) -> str:
    """
    Estimate CEFR level based on accuracy and average item difficulty.
    
    Simple V0 heuristic:
    - Consider both accuracy and the difficulty of items answered
    - Higher accuracy on harder items = higher level
    """
    # Adjust accuracy by difficulty factor
    # If avg_difficulty is high (4-5), boost the level estimate
    # If avg_difficulty is low (1-2), reduce the level estimate
    difficulty_factor = avg_difficulty / 3.5  # Normalize to avoid over-boosting by difficulty
    adjusted_score = accuracy * difficulty_factor
    
    # Map to CEFR
    if adjusted_score < 0.30:
        return "A1"
    elif adjusted_score < 0.50:
        return "A2"
    elif adjusted_score < 0.70:
        return "B1"
    elif adjusted_score < 0.85:
        return "B2"
    else:
        return "C1"


def generate_focus_suggestion(skill: str, subskill: str, accuracy: float) -> str:
    """Generate a focus suggestion based on weak area."""
    if accuracy < 0.3:
        intensity = "fundamental practice"
    elif accuracy < 0.5:
        intensity = "focused review"
    else:
        intensity = "light reinforcement"
    
    return f"Needs {intensity} in {subskill.replace('_', ' ')}"


def _serialize_weak_subskills_for_json(weak_subskills: list) -> list[dict]:
    serialized: list[dict] = []
    for weak_subskill in weak_subskills:
        if isinstance(weak_subskill, WeakSubskill):
            serialized.append(weak_subskill.model_dump(by_alias=True))
        elif hasattr(weak_subskill, "model_dump"):
            serialized.append(weak_subskill.model_dump(by_alias=True))
        elif isinstance(weak_subskill, dict):
            serialized.append(dict(weak_subskill))
        else:
            serialized.append({"value": str(weak_subskill)})
    return serialized


def finish_session(db: DB, session_id: str) -> dict:
    """
    Mark session as finished and calculate final results.
    
    Returns:
        Results dictionary
    """
    results = calculate_results(db, session_id)
    
    # Update session status
    db.execute(
        "UPDATE diagnostic_sessions SET status = 'finished', finished_at = ? WHERE id = ?",
        (_now_iso(), session_id)
    )
    
    logging.info(
        "Finished diagnostic session %s: CEFR=%s, accuracy=%d/%d",
        session_id, results['estimated_cefr'], 
        results['attempts_count'], results['items_count']
    )

    try:
        cursor = db._conn.execute(
            "SELECT user_id FROM diagnostic_sessions WHERE id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        if row:
            from app.services.diagnostic.core import update_skill_matrix_from_diagnostic

            matrix_safe_results = dict(results)
            matrix_safe_results["weak_subskills"] = _serialize_weak_subskills_for_json(
                results.get("weak_subskills", [])
            )

            update_skill_matrix_from_diagnostic(
                db,
                user_id=row[0],
                diagnostic_results=matrix_safe_results,
            )
    except Exception as exc:
        logging.warning("Failed to update skill matrix for session %s: %s", session_id, exc)
    
    return results


def get_personalized_recommendations(db: DB, user_id: str) -> dict:
    """
    Generate personalized learning recommendations based on user profile and progression.
    
    Args:
        db: Database instance
        user_id: User ID
        
    Returns:
        Dictionary with:
        - recommended_level: Suggested starting level for next session
        - focus_areas: List of (skill, subskill, reason) tuples
        - study_plan: Suggested approach ("review_basics", "advance", "maintain")
        - estimated_time_to_next_level: Estimated sessions needed
    """
    profile = get_user_learning_profile(db, user_id)
    progression = analyze_user_progression(db, user_id)
    
    current_level = profile["estimated_level"]
    trend = progression["trend"]
    velocity = progression["velocity"]
    
    # Determine recommended level
    level_map = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5}
    reverse_map = {v: k for k, v in level_map.items()}
    
    current_level_num = level_map.get(current_level, 2)
    
    if trend == "improving" and profile["avg_accuracy"] > 0.75:
        # User is ready to advance
        recommended_level_num = min(current_level_num + 1, 5)
        study_plan = "advance"
    elif trend == "declining" or profile["avg_accuracy"] < 0.5:
        # User needs to review
        recommended_level_num = max(current_level_num - 1, 1)
        study_plan = "review_basics"
    else:
        # Maintain current level
        recommended_level_num = current_level_num
        study_plan = "maintain"
    
    recommended_level = reverse_map.get(recommended_level_num, "A2")
    
    # Generate focus areas with reasons
    focus_areas = []
    for skill, subskill, accuracy in profile["weak_areas"][:3]:
        if accuracy < 0.3:
            reason = f"Critical weakness ({int(accuracy*100)}% accuracy) - requires fundamental practice"
        elif accuracy < 0.5:
            reason = f"Below target ({int(accuracy*100)}% accuracy) - needs focused review"
        else:
            reason = f"Room for improvement ({int(accuracy*100)}% accuracy) - light reinforcement"
        
        focus_areas.append((skill, subskill, reason))
    
    # Estimate time to next level (based on velocity)
    if velocity > 0 and trend == "improving":
        estimated_sessions = int(1.0 / velocity) if velocity > 0 else 10
    else:
        estimated_sessions = None  # Not progressing
    
    return {
        "recommended_level": recommended_level,
        "focus_areas": focus_areas,
        "study_plan": study_plan,
        "estimated_time_to_next_level": estimated_sessions,
        "current_accuracy": profile["avg_accuracy"],
        "trend": trend
    }




