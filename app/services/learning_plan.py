"""
Learning plan generation logic.

Generates structured learning plans based on diagnostic results,
user preferences, and CEFR level.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.infrastructure.db.sqlite import DB
from app.models.api import (
    LearningPlan,
    LessonSpec,
    FirstLessonRequest,
    WeakSubskill,
    SkillScore,
    LearningProfile,
    LearningPreferences,
    LearningHistory,
    DiagnosticHistoryEntry,
)
from app.core.util import job_id
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_diagnostic_results(
    db: DB,
    user_id: str,
    session_id: Optional[str],
    estimated_cefr: Optional[str],
    weak_subskills: Optional[list[WeakSubskill]],
) -> tuple[str, list[WeakSubskill], dict]:
    """
    Resolve effective diagnostic results.
    
    Priority:
    1. If session_id provided, use that session's results
    2. Else if estimated_cefr + weak_subskills provided, use those
    3. Else use latest finished session for user
    4. Else return defaults
    
    Returns:
        (estimated_cefr, weak_subskills, skill_scores_dict)
    """
    if session_id:
        # Load results from specific session
        from app.services.diagnostic import session as diagnostic_session
        results = diagnostic_session.calculate_results(db, session_id)
        return (
            results["estimated_cefr"],
            results["weak_subskills"],
            results["skill_scores"]
        )
    
    if estimated_cefr and weak_subskills:
        # Use provided values
        return estimated_cefr, weak_subskills, {}
    
    # Try to find latest finished session for user
    row = db.fetchone(
        """
        SELECT id FROM diagnostic_sessions
        WHERE user_id = ? AND status = 'finished'
        ORDER BY finished_at DESC
        LIMIT 1
        """,
        (user_id,)
    )
    
    if row:
        from app.services.diagnostic import session as diagnostic_session
        results = diagnostic_session.calculate_results(db, row["id"])
        return (
            results["estimated_cefr"],
            results["weak_subskills"],
            results["skill_scores"]
        )
    
    # No diagnostic data available, return defaults
    logging.warning(f"No diagnostic data found for user {user_id}, using defaults")
    return "A2", [], {}


def generate_focus_areas(
    weak_subskills: list[WeakSubskill],
    skill_scores: dict[str, int]
) -> list[str]:
    """
    Generate top 3 focus areas from weak subskills and skill scores.
    
    Priority:
    1. Top 3 weakest subskills (by accuracy)
    2. If < 3, add skills with lowest scores
    """
    focus = []
    
    # Add weak subskills
    for weak in weak_subskills[:3]:
        focus.append(f"{weak.skill}: {weak.subskill}")
    
    # If we need more, add lowest scoring skills
    if len(focus) < 3 and skill_scores:
        sorted_skills = sorted(skill_scores.items(), key=lambda x: x[1])
        for skill, score in sorted_skills:
            if len(focus) >= 3:
                break
            skill_focus = f"{skill} (score: {score})"
            if skill_focus not in focus:
                focus.append(skill_focus)
    
    # Ensure we have at least some default
    if len(focus) == 0:
        focus = ["grammar: fundamentals", "vocabulary: basics", "reading: comprehension"]
    
    return focus[:3]


def generate_lesson_specs(
    level: str,
    focus_areas: list[str],
    topic: Optional[str],
    lesson_length: int,
    weak_subskills: list[WeakSubskill]
) -> list[LessonSpec]:
    """
    Generate 5-10 recommended lesson specs.
    
    V0 implementation: Deterministic rule-based generation.
    Future: Could use LLM to generate personalized recommendations.
    """
    specs = []
    
    # Extract primary weak skill if available
    primary_skill = weak_subskills[0].skill if weak_subskills else "grammar"
    secondary_skill = weak_subskills[1].skill if len(weak_subskills) > 1 else "vocabulary"
    
    # Default topic if not provided
    effective_topic = topic or "everyday_conversations"
    
    # Lesson 1: Diagnostic weak area (translate)
    specs.append(LessonSpec(
        order=1,
        mode="translate",
        topic=effective_topic,
        lessonLength=lesson_length,
        rationale=f"Focus on {primary_skill} weakness identified in diagnostic",
        tags=[primary_skill, level.lower(), "foundational"]
    ))
    
    # Lesson 2: Fill blank for second weak area
    specs.append(LessonSpec(
        order=2,
        mode="fill_blank",
        topic=effective_topic,
        lessonLength=lesson_length,
        rationale=f"Reinforce {secondary_skill} with contextual practice",
        tags=[secondary_skill, level.lower(), "contextual"]
    ))
    
    # Lesson 3: MCQ for comprehension
    specs.append(LessonSpec(
        order=3,
        mode="mcq",
        topic=effective_topic,
        lessonLength=lesson_length,
        rationale="Build comprehension and decision-making skills",
        tags=["reading", level.lower(), "comprehension"]
    ))
    
    # Lesson 4: Mixed mode for variety
    specs.append(LessonSpec(
        order=4,
        mode="mixed",
        topic=effective_topic,
        lessonLength=lesson_length,
        rationale="Practice multiple skills with varied exercises",
        tags=[primary_skill, secondary_skill, level.lower(), "mixed"]
    ))
    
    # Lesson 5: Translate with new topic
    specs.append(LessonSpec(
        order=5,
        mode="translate",
        topic="daily_routines" if effective_topic != "daily_routines" else "hobbies",
        lessonLength=lesson_length,
        rationale="Expand vocabulary with new context",
        tags=["vocabulary", level.lower(), "expansion"]
    ))
    
    # Additional lessons if plan is longer
    if len(specs) < 7:
        # Lesson 6: Review weak area
        specs.append(LessonSpec(
            order=6,
            mode="fill_blank",
            topic=effective_topic,
            lessonLength=lesson_length,
            rationale=f"Review and reinforce {primary_skill}",
            tags=[primary_skill, level.lower(), "review"]
        ))
    
    if len(specs) < 8:
        # Lesson 7: Advanced mixed
        specs.append(LessonSpec(
            order=7,
            mode="mixed",
            topic="culture_and_society",
            lessonLength=lesson_length,
            rationale="Challenge with more complex content",
            tags=["reading", "vocabulary", level.lower(), "advanced"]
        ))
    
    return specs[:7]  # Return 5-7 lessons


def build_first_lesson_request(
    target_language: str,
    native_language: str,
    level: str,
    topic: str,
    lesson_length: int,
    persona_id: Optional[str],
    first_spec: LessonSpec
) -> FirstLessonRequest:
    """Build ready-to-use request for /v1/lessons/generate."""
    return FirstLessonRequest(
        mode=first_spec.mode,
        targetLanguage=target_language,
        nativeLanguage=native_language,
        level=level,
        topic=first_spec.topic,
        lessonLength=lesson_length,
        personaId=persona_id
    )


def create_or_update_profile(
    db: DB,
    user_id: str,
    target_language: str,
    native_language: str,
    estimated_cefr: str,
    skill_scores: dict[str, int],
    weak_subskills: list[WeakSubskill],
    preferences: LearningPreferences,
    session_id: Optional[str] = None
) -> LearningProfile:
    """
    Create or update learning profile for user.
    
    If profile exists, updates it with new diagnostic data.
    Otherwise, creates new profile.
    """
    now = _now_iso()
    
    # Load existing profile if any
    row = db.fetchone(
        "SELECT profile_json FROM learning_profiles WHERE user_id = ?",
        (user_id,)
    )
    
    # Convert skill_scores dict to list of SkillScore objects
    skill_scores_list = [
        SkillScore(skill=skill, score=score)
        for skill, score in skill_scores.items()
    ]
    
    if row:
        # Update existing profile
        import json
        profile_data = json.loads(row["profile_json"])
        profile = LearningProfile.model_validate(profile_data)
        
        # Update with new data
        profile.target_language = target_language
        profile.native_language = native_language
        profile.estimated_cefr = estimated_cefr
        profile.skill_scores = skill_scores_list
        profile.weak_subskills = weak_subskills
        profile.preferences = preferences
        profile.updated_at = now
        
        # Add to history if session_id provided
        if session_id:
            # Get session details
            session_row = db.fetchone(
                "SELECT finished_at FROM diagnostic_sessions WHERE id = ?",
                (session_id,)
            )
            
            # Get attempts count for this session
            from app.services.diagnostic import session as diagnostic_session
            results = diagnostic_session.calculate_results(db, session_id)
            
            if not profile.history:
                profile.history = LearningHistory(diagnostics=[])
            
            # Add entry
            entry = DiagnosticHistoryEntry(
                sessionId=session_id,
                completedAt=session_row["finished_at"] if session_row else now,
                estimatedCefr=estimated_cefr,
                totalCorrect=results["total_correct"],
                totalAttempts=results["total_attempts"],
                accuracy=results["accuracy"]
            )
            profile.history.diagnostics.append(entry)
    else:
        # Create new profile
        history = None
        if session_id:
            session_row = db.fetchone(
                "SELECT finished_at FROM diagnostic_sessions WHERE id = ?",
                (session_id,)
            )
            from app.services.diagnostic import session as diagnostic_session
            results = diagnostic_session.calculate_results(db, session_id)
            
            entry = DiagnosticHistoryEntry(
                sessionId=session_id,
                completedAt=session_row["finished_at"] if session_row else now,
                estimatedCefr=estimated_cefr,
                totalCorrect=results["total_correct"],
                totalAttempts=results["total_attempts"],
                accuracy=results["accuracy"]
            )
            history = LearningHistory(diagnostics=[entry])
        
        profile = LearningProfile(
            version=1,
            targetLanguage=target_language,
            nativeLanguage=native_language,
            estimatedCefr=estimated_cefr,
            skillScores=skill_scores_list,
            weakSubskills=weak_subskills,
            preferences=preferences,
            history=history,
            updatedAt=now
        )
    
    # Save to database
    import json
    profile_json = profile.model_dump_json(by_alias=True)
    db.execute(
        """
        INSERT INTO learning_profiles (user_id, profile_json, version, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            profile_json = excluded.profile_json,
            version = excluded.version,
            updated_at = excluded.updated_at
        """,
        (user_id, profile_json, profile.version, now)
    )
    
    logging.info(
        f"Created/updated learning profile for user {user_id}",
        extra={"user_id": user_id, "cefr": estimated_cefr}
    )
    
    return profile


def generate_learning_plan(
    db: DB,
    user_id: str,
    target_language: str,
    native_language: str,
    topic: Optional[str],
    session_id: Optional[str],
    estimated_cefr: Optional[str],
    weak_subskills: Optional[list[WeakSubskill]],
    lesson_length: int,
    persona_id: Optional[str]
) -> tuple[str, LearningProfile, LearningPlan, FirstLessonRequest]:
    """
    Generate complete learning plan.
    
    Returns:
        (plan_id, profile, plan, first_lesson_request)
    """
    # Resolve diagnostic results
    effective_cefr, effective_weak_subskills, skill_scores = resolve_diagnostic_results(
        db, user_id, session_id, estimated_cefr, weak_subskills
    )
    
    # Generate focus areas
    focus_areas = generate_focus_areas(effective_weak_subskills, skill_scores)
    
    # Generate lesson specs
    lesson_specs = generate_lesson_specs(
        level=effective_cefr,
        focus_areas=focus_areas,
        topic=topic,
        lesson_length=lesson_length,
        weak_subskills=effective_weak_subskills
    )
    
    # Build plan
    plan = LearningPlan(
        level=effective_cefr,
        focusAreas=focus_areas,
        recommendedLessons=lesson_specs
    )
    
    # Build first lesson request
    first_lesson_req = build_first_lesson_request(
        target_language=target_language,
        native_language=native_language,
        level=effective_cefr,
        topic=lesson_specs[0].topic,
        lesson_length=lesson_length,
        persona_id=persona_id,
        first_spec=lesson_specs[0]
    )
    
    # Create/update profile
    preferences = LearningPreferences(
        topic=topic,
        personaId=persona_id,
        lessonLength=lesson_length
    )
    
    profile = create_or_update_profile(
        db=db,
        user_id=user_id,
        target_language=target_language,
        native_language=native_language,
        estimated_cefr=effective_cefr,
        skill_scores=skill_scores,
        weak_subskills=effective_weak_subskills,
        preferences=preferences,
        session_id=session_id
    )
    
    # Generate plan ID
    plan_id = job_id("plan")
    
    logging.info(
        f"Generated learning plan {plan_id} for user {user_id}",
        extra={
            "user_id": user_id,
            "plan_id": plan_id,
            "cefr": effective_cefr,
            "lesson_count": len(lesson_specs)
        }
    )
    
    return plan_id, profile, plan, first_lesson_req



