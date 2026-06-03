"""
Adaptive Difficulty System for Learning Path

Analyzes user performance and adjusts difficulty dynamically:
- Calculates mastery score based on recent attempts
- Suggests difficulty adjustments for next nodes
- Provides personalized recommendations
"""

import logging
from typing import List, Dict, Optional, Tuple

from app.infrastructure.db.sqlite import DB
from app.models.path import SeedConstants
from app.services.path.analytics import DifficultyAdjustment, AdaptiveRecommendation


logger = logging.getLogger(__name__)


def calculate_mastery_score(db: DB, user_id: str, lookback_attempts: int = 10) -> float:
    """
    Calculate user's current mastery score based on recent performance.
    
    Returns float between 0.0 and 1.0
    """
    recent_attempts = db.fetchall(
        """
        SELECT score, success
        FROM node_attempts
        WHERE user_id = ?
        ORDER BY completed_at DESC
        LIMIT ?
        """,
        (user_id, lookback_attempts)
    )
    
    if not recent_attempts:
        return 0.5  # Default for new users
    
    # Weighted average (recent attempts weighted more)
    total_weight = 0
    weighted_sum = 0
    
    for i, attempt in enumerate(recent_attempts):
        weight = 1.0 / (i + 1)  # Exponential decay
        weighted_sum += attempt["score"] * weight
        total_weight += weight
    
    mastery = weighted_sum / total_weight if total_weight > 0 else 0.5
    
    # Clamp between 0.3 and 1.0 (don't go too low)
    return max(0.3, min(1.0, mastery))


def suggest_difficulty_adjustment(
    db: DB,
    user_id: str,
    current_level: str
) -> DifficultyAdjustment:
    """
    Suggest difficulty adjustment based on recent performance.
    
    Returns:
    - Current mastery score
    - Suggested difficulty_delta for next nodes
    - Reasoning for the adjustment
    """
    mastery = calculate_mastery_score(db, user_id)
    
    # Get recent attempts for analysis
    recent = db.fetchall(
        """
        SELECT score, success, duration_seconds
        FROM node_attempts
        WHERE user_id = ?
        ORDER BY completed_at DESC
        LIMIT 5
        """,
        (user_id,)
    )
    
    attempts_count = len(recent)
    
    if attempts_count < 3:
        # Not enough data, use conservative adjustment
        return DifficultyAdjustment(
            user_id=user_id,
            current_mastery_score=mastery,
            suggested_difficulty_delta=0.0,
            reasoning="Not enough data yet. Starting with baseline difficulty.",
            based_on_attempts=attempts_count
        )
    
    # Analyze trends
    success_rate = sum(1 for a in recent if a["success"]) / len(recent)
    avg_score = sum(a["score"] for a in recent) / len(recent)
    
    # Determine adjustment
    if success_rate >= 0.9 and avg_score >= 0.85:
        # Performing very well - increase difficulty
        delta = 0.1
        reasoning = f"Excellent performance ({avg_score*100:.0f}% avg). Ready for more challenge!"
    
    elif success_rate >= 0.7 and avg_score >= 0.75:
        # Performing well - slight increase
        delta = 0.05
        reasoning = f"Good performance ({avg_score*100:.0f}% avg). Gradual difficulty increase recommended."
    
    elif success_rate >= 0.5:
        # Moderate performance - maintain
        delta = 0.0
        reasoning = f"Steady progress ({avg_score*100:.0f}% avg). Current difficulty is appropriate."
    
    elif success_rate >= 0.3:
        # Struggling - reduce difficulty
        delta = -0.05
        reasoning = f"Some difficulty ({avg_score*100:.0f}% avg). Easier content recommended."
    
    else:
        # Struggling significantly - reduce more
        delta = -0.1
        reasoning = f"Challenging material ({avg_score*100:.0f}% avg). Let's review fundamentals."
    
    # Clamp delta within valid range
    delta = max(-0.2, min(0.2, delta))
    
    logger.info(f"Adaptive difficulty: user={user_id}, mastery={mastery:.2f}, delta={delta:+.2f}")
    
    return DifficultyAdjustment(
        user_id=user_id,
        current_mastery_score=mastery,
        suggested_difficulty_delta=delta,
        reasoning=reasoning,
        based_on_attempts=attempts_count
    )


def identify_weak_areas(db: DB, user_id: str) -> List[str]:
    """
    Identify task types where user struggles.
    
    Returns list of task types with < 60% accuracy
    """
    weak_types = db.fetchall(
        """
        SELECT
            ta.task_type,
            COUNT(*) as attempts,
            SUM(CASE WHEN ta.is_correct = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as accuracy
        FROM task_attempts ta
        JOIN node_attempts na ON ta.node_attempt_id = na.id
        WHERE na.user_id = ?
        GROUP BY ta.task_type
        HAVING COUNT(*) >= 5 AND accuracy < 0.6
        ORDER BY accuracy ASC
        """,
        (user_id,)
    )
    
    return [row["task_type"] for row in weak_types]


def identify_strong_areas(db: DB, user_id: str) -> List[str]:
    """
    Identify task types where user excels.
    
    Returns list of task types with > 85% accuracy
    """
    strong_types = db.fetchall(
        """
        SELECT
            ta.task_type,
            COUNT(*) as attempts,
            SUM(CASE WHEN ta.is_correct = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as accuracy
        FROM task_attempts ta
        JOIN node_attempts na ON ta.node_attempt_id = na.id
        WHERE na.user_id = ?
        GROUP BY ta.task_type
        HAVING COUNT(*) >= 5 AND accuracy > 0.85
        ORDER BY accuracy DESC
        """,
        (user_id,)
    )
    
    return [row["task_type"] for row in strong_types]


def recommend_next_topics(
    db: DB,
    user_id: str,
    current_level: str
) -> AdaptiveRecommendation:
    """
    Provide personalized recommendations for next learning steps.
    
    Analyzes:
    - Completed topics
    - Weak areas needing reinforcement
    - Strong areas ready for advancement
    """
    mastery = calculate_mastery_score(db, user_id)
    weak_areas = identify_weak_areas(db, user_id)
    strong_areas = identify_strong_areas(db, user_id)
    
    # Get completed topics from nodes
    completed_topics = db.fetchall(
        """
        SELECT DISTINCT json_extract(n.preset_json, '$.topic') as topic
        FROM nodes n
        JOIN node_attempts na ON n.id = na.node_id
        WHERE na.user_id = ? AND na.success = 1
        """,
        (user_id,)
    )
    completed_topic_names = [row["topic"] for row in completed_topics if row["topic"]]
    
    # Get available topics for level
    available_topics = SeedConstants.get_topics_for_level(current_level)
    available_grammar = SeedConstants.get_grammar_for_level(current_level)
    
    # Filter out completed topics
    remaining_topics = [t for t in available_topics if t not in completed_topic_names]
    
    # Recommendations
    recommended_topics = []
    recommended_grammar = []
    focus_areas = []
    
    # If struggling, reinforce fundamentals
    if mastery < 0.6:
        # Recommend easier topics or review
        if completed_topic_names:
            recommended_topics = completed_topic_names[:2]  # Review
            focus_areas.append("Review previous topics to build confidence")
        else:
            recommended_topics = available_topics[:2]  # Start with easiest
        
        recommended_grammar = available_grammar[:2]
        focus_areas.append(f"Focus on weak areas: {', '.join(weak_areas[:3])}")
        difficulty_level = "Beginner-friendly"
        reasoning = "Current performance suggests reviewing fundamentals. Building strong foundation is key."
    
    # If doing well, advance
    elif mastery >= 0.8:
        # Recommend new topics
        recommended_topics = remaining_topics[:3] if remaining_topics else available_topics[:3]
        recommended_grammar = available_grammar[-3:] if len(available_grammar) > 3 else available_grammar
        focus_areas.append(f"Leverage strengths: {', '.join(strong_areas[:3])}")
        difficulty_level = "Challenging"
        reasoning = "Strong performance! Ready for advanced material and new topics."
    
    # Balanced approach
    else:
        # Mix review and new topics
        recommended_topics = (
            completed_topic_names[:1] +  # 1 review
            remaining_topics[:2]  # 2 new
        )[:3]
        
        recommended_grammar = available_grammar[len(available_grammar)//2:][:3]
        
        if weak_areas:
            focus_areas.append(f"Improve: {', '.join(weak_areas[:2])}")
        if strong_areas:
            focus_areas.append(f"Maintain: {', '.join(strong_areas[:2])}")
        
        difficulty_level = "Moderate"
        reasoning = "Steady progress. Balancing review with new material for optimal learning."
    
    return AdaptiveRecommendation(
        user_id=user_id,
        recommended_topics=recommended_topics,
        recommended_grammar=recommended_grammar,
        difficulty_level=difficulty_level,
        focus_areas=focus_areas,
        reasoning=reasoning
    )


def should_regenerate_node(db: DB, node_id: str, threshold_failure_rate: float = 0.5) -> Tuple[bool, str]:
    """
    Determine if a node should be regenerated due to poor performance.
    
    Returns:
    - bool: Should regenerate
    - str: Reason
    """
    stats = db.fetchone(
        """
        SELECT
            COUNT(*) as attempts,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as success_rate,
            AVG(score) as avg_score
        FROM node_attempts
        WHERE node_id = ?
        """,
        (node_id,)
    )
    
    if not stats or stats["attempts"] < 10:
        return False, "Not enough data"
    
    success_rate = stats["success_rate"] or 0.0
    avg_score = stats["avg_score"] or 0.0
    
    if success_rate < threshold_failure_rate and avg_score < 0.5:
        return True, f"Low success rate ({success_rate*100:.0f}%) and average score ({avg_score*100:.0f}%). Content may be too difficult or unclear."
    
    return False, "Performance is acceptable"


def adjust_preset_for_user(
    preset_json: Dict,
    user_mastery: float,
    weak_areas: List[str]
) -> Dict:
    """
    Adjust node preset based on user's performance.
    
    Returns modified preset with appropriate difficulty and focus.
    """
    import copy
    adjusted = copy.deepcopy(preset_json)
    
    # Adjust difficulty delta
    if user_mastery < 0.5:
        # Make easier
        adjusted["difficulty_delta"] = max(-0.2, adjusted.get("difficulty_delta", 0.0) - 0.1)
        adjusted["vocabulary_level"] = "basic"
    elif user_mastery > 0.8:
        # Make harder
        adjusted["difficulty_delta"] = min(0.2, adjusted.get("difficulty_delta", 0.0) + 0.1)
        adjusted["vocabulary_level"] = "advanced"
    
    # Add context for weak areas
    if weak_areas:
        adjusted["context"] = f"Focus on {weak_areas[0]} practice"
    
    return adjusted




