"""
Learning Path Analytics Models

Pydantic models for tracking user progress and performance:
- Node attempt submission and results
- Task-level analytics
- Performance metrics and adaptive difficulty
"""

import logging
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

logger = logging.getLogger(__name__)


# ==================== Submission Models ====================

class TaskAttemptSubmit(BaseModel):
    """Single task attempt data"""
    task_id: str = Field(..., description="Task ID from generated content")
    task_type: str = Field(..., description="Task type: fill_blank, translate, choice, etc.")
    user_answer: str = Field(..., description="User's answer")
    correct_answer: str = Field(..., description="Expected correct answer")
    is_correct: bool = Field(..., description="Whether answer was correct")
    response_time_ms: Optional[int] = Field(None, description="Time taken to answer (milliseconds)")
    hint_used: bool = Field(default=False, description="Whether user used a hint")
    attempts_count: int = Field(default=1, ge=1, description="Number of attempts for this task")


class NodeAttemptSubmit(BaseModel):
    """Submit complete node attempt results"""
    node_id: str = Field(..., description="Node ID")
    session_id: str = Field(..., description="Client-side session ID for tracking")
    started_at: str = Field(..., description="ISO timestamp when node started")
    completed_at: str = Field(..., description="ISO timestamp when node completed")
    task_attempts: List[TaskAttemptSubmit] = Field(..., min_length=1, description="All task attempts")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    @property
    def duration_seconds(self) -> int:
        """Calculate duration from timestamps"""
        try:
            start = datetime.fromisoformat(self.started_at.replace('Z', '+00:00'))
            end = datetime.fromisoformat(self.completed_at.replace('Z', '+00:00'))
            return int((end - start).total_seconds())
        except Exception:
            logger.debug("Failed to parse duration timestamps", exc_info=True)
            return 0
    
    @property
    def tasks_correct(self) -> int:
        """Count correct tasks"""
        return sum(1 for t in self.task_attempts if t.is_correct)
    
    @property
    def tasks_incorrect(self) -> int:
        """Count incorrect tasks"""
        return sum(1 for t in self.task_attempts if not t.is_correct)
    
    @property
    def score(self) -> float:
        """Calculate score (0.0 to 1.0)"""
        if not self.task_attempts:
            return 0.0
        return self.tasks_correct / len(self.task_attempts)
    
    @property
    def is_success(self) -> bool:
        """Success if score >= 70%"""
        return self.score >= 0.7


class NodeAttemptResponse(BaseModel):
    """Response after submitting node attempt"""
    attempt_id: int
    node_id: str
    score: float
    success: bool
    stars_earned: int
    next_node_unlocked: Optional[str] = None
    feedback: str


# ==================== Analytics Query Models ====================

class TaskTypeStats(BaseModel):
    """Statistics for a specific task type"""
    task_type: str
    total_attempts: int
    correct_attempts: int
    accuracy: float
    avg_response_time_ms: Optional[float]


class NodePerformance(BaseModel):
    """Performance metrics for a node"""
    node_id: str
    node_type: str
    attempts_count: int
    success_rate: float
    avg_score: float
    avg_duration_seconds: float
    avg_stars: float
    task_stats: List[TaskTypeStats]


class UserLearningAnalytics(BaseModel):
    """User's overall learning analytics"""
    user_id: str
    units_started: int
    units_completed: int
    nodes_attempted: int
    nodes_completed: int
    total_tasks_attempted: int
    total_tasks_correct: int
    overall_accuracy: float
    total_time_minutes: int
    avg_session_duration_minutes: float
    strongest_task_types: List[str]
    weakest_task_types: List[str]
    current_streak_days: int
    total_stars_earned: int


class NodeAnalyticsSummary(BaseModel):
    """Detailed analytics for a specific node"""
    node_id: str
    unit_id: str
    node_type: str
    total_attempts: int
    unique_users: int
    avg_score: float
    success_rate: float
    avg_duration_seconds: float
    completion_rate: float  # % of started attempts that finished
    task_type_breakdown: List[TaskTypeStats]
    common_errors: List[Dict[str, Any]]
    difficulty_rating: str  # "easy", "medium", "hard" based on success rate


# ==================== Adaptive Difficulty Models ====================

class DifficultyAdjustment(BaseModel):
    """Suggested difficulty adjustment based on performance"""
    user_id: str
    current_mastery_score: float
    suggested_difficulty_delta: float
    reasoning: str
    based_on_attempts: int


class AdaptiveRecommendation(BaseModel):
    """AI-powered recommendations for next learning steps"""
    user_id: str
    recommended_topics: List[str]
    recommended_grammar: List[str]
    difficulty_level: str
    focus_areas: List[str]
    reasoning: str


# ==================== Leaderboard Models ====================

class LeaderboardEntry(BaseModel):
    """Single entry in leaderboard"""
    rank: int
    user_id: str
    display_name: Optional[str]
    total_stars: int
    nodes_completed: int
    avg_score: float
    total_time_minutes: int


class LeaderboardResponse(BaseModel):
    """Leaderboard data"""
    period: str  # "daily", "weekly", "all_time"
    entries: List[LeaderboardEntry]
    user_rank: Optional[int] = None
    total_users: int


# ==================== Real-time Progress Models ====================

class LiveProgressUpdate(BaseModel):
    """Real-time progress update (for WebSocket/SSE)"""
    session_id: str
    node_id: str
    tasks_completed: int
    tasks_total: int
    current_score: float
    elapsed_seconds: int


# ==================== Historical Trends ====================

class PerformanceTrend(BaseModel):
    """Performance trend over time"""
    user_id: str
    date: str
    nodes_completed: int
    avg_score: float
    total_time_minutes: int
    stars_earned: int


class LearningPathProgress(BaseModel):
    """Overall learning path progress"""
    user_id: str
    unit_id: str
    unit_title: str
    nodes_total: int
    nodes_completed: int
    progress_percentage: float
    current_node_id: Optional[str]
    avg_score: float
    total_stars: int
    estimated_completion_days: Optional[int]


# ==================== Error Analysis ====================

class CommonError(BaseModel):
    """Common error pattern"""
    task_type: str
    error_pattern: str
    frequency: int
    example_user_answer: str
    example_correct_answer: str
    suggested_hint: Optional[str]


class ErrorAnalysisReport(BaseModel):
    """Error analysis for a node"""
    node_id: str
    total_errors: int
    common_errors: List[CommonError]
    most_difficult_tasks: List[str]
    recommended_improvements: List[str]


# ==================== Gamification Models ====================

class Achievement(BaseModel):
    """Achievement/badge earned"""
    id: str
    name: str
    description: str
    icon: str
    earned_at: str
    rarity: str  # "common", "rare", "epic", "legendary"


class UserAchievements(BaseModel):
    """User's achievements"""
    user_id: str
    achievements: List[Achievement]
    total_count: int
    completion_percentage: float


# ==================== Export Models ====================

class AnalyticsExport(BaseModel):
    """Exportable analytics data"""
    user_id: str
    export_date: str
    learning_analytics: UserLearningAnalytics
    node_performances: List[NodePerformance]
    trends: List[PerformanceTrend]
    achievements: List[Achievement]
