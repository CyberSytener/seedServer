from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Action(str, Enum):
    fix = "fix"
    translate = "translate"
    summarize = "summarize"
    ask = "ask"


class Mode(str, Enum):
    fast = "fast"
    hybrid = "hybrid"
    batch = "batch"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class ActionRequest(BaseModel):
    model_config = {"populate_by_name": True}
    
    action: Action
    text: str = Field(min_length=1)
    options: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = Field(default=None, max_length=256)
    persona_id: Optional[str] = Field(default=None, max_length=64, alias="personaId")


class ActionResponse(BaseModel):
    model_config = {"populate_by_name": True}
    
    job_id: str
    mode: Mode
    status: JobStatus = JobStatus.queued
    eta_hint: Optional[str] = None
    result_text: Optional[str] = None
    error_message: Optional[str] = None
    persona_id_used: Optional[str] = Field(default=None, alias="personaIdUsed")
    fallback_reason: Optional[str] = Field(default=None, alias="fallbackReason")


class CreateUserRequest(BaseModel):
    user_id: Optional[str] = None
    email: Optional[str] = None
    is_admin: bool = False
    meta: Dict[str, Any] = Field(default_factory=dict)


class CreateUserResponse(BaseModel):
    user_id: str
    api_key: str


class MeResponse(BaseModel):
    user_id: str
    is_admin: bool = False
    email: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    credits_balance: int = Field(default=0, alias="creditsBalance")
    credits_daily_limit: int = Field(default=0, alias="creditsDailyLimit")


class ModelPricingHint(BaseModel):
    model_config = {"populate_by_name": True}

    input_per_1k_tokens_usd: float = Field(alias="inputPer1kTokensUsd")
    output_per_1k_tokens_usd: float = Field(alias="outputPer1kTokensUsd")
    credit_multiplier: float = Field(alias="creditMultiplier")


class ModelCatalogItem(BaseModel):
    model_config = {"populate_by_name": True}

    provider: str
    id: str
    label: str
    tier: str
    capabilities: list[str] = Field(default_factory=list)
    available: bool = True
    pricing: ModelPricingHint


class ModelsResponse(BaseModel):
    model_config = {"populate_by_name": True}

    models: list[ModelCatalogItem] = Field(default_factory=list)
    default_fast_model: str = Field(alias="defaultFastModel")
    default_batch_model: str = Field(alias="defaultBatchModel")


class JobResponse(BaseModel):
    model_config = {"populate_by_name": True}
    
    id: str
    user_id: str
    action: Action
    mode: Mode
    status: JobStatus
    queue_name: str
    priority: int
    not_before: Optional[str] = None
    provider: str
    model: str
    persona_id_used: Optional[str] = Field(default=None, alias="personaIdUsed")
    fallback_reason: Optional[str] = Field(default=None, alias="fallbackReason")
    result_text: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class PersonaInfo(BaseModel):
    """Metadata for a single persona (used in GET /v1/personas response)."""
    model_config = {"populate_by_name": True}
    
    id: str
    name: str
    description: str
    tags: list[str]
    prompt_source: str = Field(alias="promptSource")
    prompt_updated_at: Optional[str] = Field(default=None, alias="promptUpdatedAt")
    is_default: bool = Field(alias="isDefault")


class PersonasResponse(BaseModel):
    """Response for GET /v1/personas endpoint."""
    model_config = {"populate_by_name": True}
    
    personas: list[PersonaInfo]
    default_persona_id: str = Field(alias="defaultPersonaId")


# ============================================================================
# Lesson Engine Models
# ============================================================================

class LessonMode(str, Enum):
    """Learning mode for lesson generation."""
    vocabulary = "vocabulary"
    grammar = "grammar"
    mixed = "mixed"


class TaskType(str, Enum):
    """Supported task types for lessons."""
    mcq = "mcq"  # Multiple choice question
    translate = "translate"  # Translation task
    fill_blank = "fill_blank"  # Fill in the blank
    word_order = "word_order"  # Arrange words in correct order


class TaskContent(BaseModel):
    """Content structure for a lesson task."""
    model_config = {"populate_by_name": True, "extra": "allow"}
    
    question: Optional[str] = None  # General question field
    options: Optional[list[str]] = None  # For MCQ
    words: Optional[list[str]] = None  # For word_order
    sentence: Optional[str] = None  # For fill_blank (with _____)
    source_text: Optional[str] = Field(default=None, alias="sourceText")  # For translate (primary)
    target_lang: Optional[str] = Field(default=None, alias="targetLang")  # For translate


class TaskGrading(BaseModel):
    """Grading rules for a task."""
    model_config = {"populate_by_name": True}
    
    correct_answer: str = Field(alias="correctAnswer")
    correct_choice_index: int | None = Field(default=None, alias="correctChoiceIndex")  # For MCQ: index of correct choice
    accepted_variants: list[str] = Field(default_factory=list, alias="acceptedVariants")
    partial_credit_keywords: list[str] = Field(default_factory=list, alias="partialCreditKeywords")
    tip: str  # Hint to show on wrong answer


class Task(BaseModel):
    """A single lesson task."""
    model_config = {"populate_by_name": True}
    
    id: str
    type: TaskType
    prompt: str
    skill: str  # e.g., "present tense", "colors", "greetings"
    difficulty: int = Field(ge=1, le=5)  # 1=easy, 5=hard
    content: TaskContent
    grading: TaskGrading


class Lesson(BaseModel):
    """Complete lesson structure."""
    model_config = {"populate_by_name": True}
    
    lesson_id: str = Field(alias="lessonId")
    mode: LessonMode
    target_lang: str = Field(alias="targetLang")
    native_lang: str = Field(alias="nativeLang")
    level: str  # e.g., "A1", "A2", "B1"
    topic: Optional[str] = None
    title: str
    tasks: list[Task]


class LessonGenerateRequest(BaseModel):
    """Request to generate a new lesson."""
    model_config = {"populate_by_name": True}
    
    mode: LessonMode
    target_lang: str = Field(alias="targetLang", min_length=2, max_length=50)
    native_lang: str = Field(alias="nativeLang", min_length=2, max_length=50)
    level: str = Field(min_length=2, max_length=50)  # A1, A2, B1, B2, C1, C2, beginner, intermediate, advanced, etc.
    topic: Optional[str] = Field(default=None, max_length=100)
    lesson_length: int = Field(alias="lessonLength", ge=3, le=15)  # 3-15 tasks
    persona_id: Optional[str] = Field(default=None, max_length=64, alias="personaId")
    node_id: Optional[str] = Field(default=None, alias="nodeId")
    unit_id: Optional[str] = Field(default=None, alias="unitId")


class LessonResponse(BaseModel):
    """Response containing generated lesson."""
    model_config = {"populate_by_name": True}
    
    lesson: Lesson
    persona_id_used: Optional[str] = Field(default=None, alias="personaIdUsed")
    fallback_reason: Optional[str] = Field(default=None, alias="fallbackReason")
    node_id: Optional[str] = Field(default=None, alias="nodeId")
    unit_id: Optional[str] = Field(default=None, alias="unitId")
    xp_reward: int = Field(default=15, alias="xpReward")
    total_cost_usd: float = Field(default=0.0, alias="totalCostUsd")
    total_credits_charged: int = Field(default=0, alias="totalCreditsCharged")
    cost_breakdown: list[Dict[str, Any]] = Field(default_factory=list, alias="costBreakdown")
    cost_totals_by_session: Dict[str, Dict[str, Any]] = Field(default_factory=dict, alias="costTotalsBySession")
    cost_totals_by_job: Dict[str, Dict[str, Any]] = Field(default_factory=dict, alias="costTotalsByJob")


class GradeResult(BaseModel):
    """Result of grading a single task submission."""
    model_config = {"populate_by_name": True}
    
    task_id: str = Field(alias="taskId")
    correct: bool
    score: float = Field(ge=0.0, le=1.0)  # 0.0 to 1.0
    feedback: str
    correct_answer: Optional[str] = Field(default=None, alias="correctAnswer")  # Show if wrong


class LessonSummary(BaseModel):
    """Summary after completing all tasks in a lesson."""
    model_config = {"populate_by_name": True}
    
    lesson_id: str = Field(alias="lessonId")
    total_tasks: int = Field(alias="totalTasks")
    correct_count: int = Field(alias="correctCount")
    score_percentage: float = Field(alias="scorePercentage", ge=0.0, le=100.0)
    completed: bool
    encouragement: str  # Personalized message


class LessonSubmitRequest(BaseModel):
    """Request to submit an answer for a task."""
    model_config = {"populate_by_name": True}
    
    lesson_id: str = Field(alias="lessonId", min_length=1, max_length=100)
    task_id: str = Field(alias="taskId", min_length=1, max_length=100)
    user_answer: str = Field(alias="userAnswer", max_length=1000)
    persona_id: Optional[str] = Field(default=None, max_length=64, alias="personaId")


class GradeResponse(BaseModel):
    """Response after grading a submission."""
    model_config = {"populate_by_name": True}
    
    grade: Optional[GradeResult] = None  # Individual task grade
    summary: Optional[LessonSummary] = None  # Lesson summary if last task
    persona_id_used: Optional[str] = Field(default=None, alias="personaIdUsed")
    fallback_reason: Optional[str] = Field(default=None, alias="fallbackReason")


class LessonListItem(BaseModel):
    """Minimal lesson metadata for list view."""
    model_config = {"populate_by_name": True}
    
    lesson_id: str = Field(alias="lessonId")
    title: str
    native_lang: str = Field(alias="nativeLang")
    target_lang: str = Field(alias="targetLang")
    level: str
    mode: str
    created_at: str = Field(alias="createdAt")
    persona_id_used: Optional[str] = Field(default=None, alias="personaIdUsed")
    tasks_count: int = Field(alias="tasksCount")
    completed_count: int = Field(alias="completedCount")


class LessonListResponse(BaseModel):
    """Response for GET /v1/lessons."""
    model_config = {"populate_by_name": True}
    
    lessons: list[LessonListItem]
    total: int


class LessonAttemptInfo(BaseModel):
    """Attempt information for a task."""
    model_config = {"populate_by_name": True}
    
    task_id: str = Field(alias="taskId")
    user_answer: str = Field(alias="userAnswer")
    correct: bool
    score: int
    created_at: str = Field(alias="createdAt")


class LessonGetResponse(BaseModel):
    """Response for GET /v1/lessons/{lessonId}."""
    model_config = {"populate_by_name": True}
    
    lesson: Lesson
    attempts: list[LessonAttemptInfo]
    total_attempts: int = Field(alias="totalAttempts")
    completed_count: int = Field(alias="completedCount")
    total_score: int = Field(alias="totalScore")
    persona_id_used: Optional[str] = Field(default=None, alias="personaIdUsed")


class LessonDeleteResponse(BaseModel):
    """Response for DELETE /v1/lessons/{lessonId}."""
    model_config = {"populate_by_name": True}
    
    deleted: bool
    lesson_id: str = Field(alias="lessonId")


# ============================================================================
# Diagnostic Items Models
# ============================================================================

class DiagnosticTaskType(str, Enum):
    """Task types for diagnostic items."""
    mcq = "mcq"
    fill_blank = "fill_blank"
    reorder_sentence = "reorder_sentence"
    translate = "translate"
    reading_mcq = "reading_mcq"


class DiagnosticContext(BaseModel):
    """Context information for a diagnostic item."""
    model_config = {"extra": "allow"}
    
    sentence: Optional[str] = None
    passage: Optional[str] = None
    hint: Optional[str] = None


class DiagnosticAnswer(BaseModel):
    """Answer structure for diagnostic items."""
    model_config = {"extra": "allow"}
    
    accepted: list[str]  # List of accepted answers
    normalize: Optional[str] = "lower_trim"  # Normalization strategy


class DistractorReason(BaseModel):
    """Reason for a distractor choice."""
    model_config = {"populate_by_name": True}
    
    choice: str
    reason_tag: str = Field(alias="reasonTag")


class DiagnosticTags(BaseModel):
    """Tags for diagnostic item metadata."""
    model_config = {"populate_by_name": True}
    
    skill: str  # grammar|vocabulary|reading|writing
    subskill: str
    topic: str
    difficulty: float = Field(ge=0.0, le=5.0)
    task_type: str = Field(alias="taskType")
    cefr_band: str = Field(alias="cefrBand")  # A1|A2|B1|B2|C1
    language_pair: str = Field(alias="languagePair")  # e.g., "en->es"


class DiagnosticItem(BaseModel):
    """A single diagnostic test item."""
    model_config = {
        "populate_by_name": True,
        "extra": "allow",
        "use_enum_values": True,
        "ser_json_bytes": "utf8",
        "ser_json_inf_nan": "constants"
    }

    @model_validator(mode='before')
    def _accept_legacy_type_alias(cls, values):
        """Support legacy key 'type' used in older tests / inputs by mapping it to 'taskType'."""
        if isinstance(values, dict) and 'type' in values and 'taskType' not in values:
            values['taskType'] = values.pop('type')
        return values
    
    id: str
    task_type: DiagnosticTaskType = Field(alias="taskType")
    prompt: str
    context: DiagnosticContext = Field(default_factory=DiagnosticContext)
    choices: Optional[list[str]] = None  # For MCQ (exactly 4)
    tokens: Optional[list[str]] = None  # For reorder_sentence
    answer: DiagnosticAnswer
    distractors_reason: Optional[list[DistractorReason]] = Field(default=None, alias="distractorsReason")
    tags: DiagnosticTags


class DiagnosticBlueprint(BaseModel):
    """Blueprint entry for generating diagnostic items."""
    skill: str
    subskill: str
    topic: str
    difficulty: float
    task_type: str = Field(alias="taskType")
    cefr_band: str = Field(alias="cefrBand")
    
    # Specialized test support
    domain: Optional[str] = Field(default=None, description="Specialized domain (business, medical, academic, technical, etc)")
    dialect: Optional[str] = Field(default=None, description="Language dialect/variant (british, american, canadian, etc)")
    context: Optional[str] = Field(default=None, description="Specific context within domain (interview, presentation, email, etc)")


class DiagnosticGenerateRequest(BaseModel):
    """Request to generate diagnostic items."""
    model_config = {"populate_by_name": True}
    
    native_lang: str = Field(alias="nativeLang", min_length=2, max_length=50)
    target_lang: str = Field(alias="targetLang", min_length=2, max_length=50)
    blueprint: list[DiagnosticBlueprint]  # Array of item specifications
    persona_id: Optional[str] = Field(default=None, max_length=64, alias="personaId")


class DiagnosticSet(BaseModel):
    """Container for generated diagnostic items."""
    model_config = {"populate_by_name": True}
    
    items: list[DiagnosticItem]


class DiagnosticResponse(BaseModel):
    """Response containing generated diagnostic items."""
    model_config = {"populate_by_name": True}
    
    diagnostic_set: DiagnosticSet = Field(alias="diagnosticSet")
    persona_id_used: Optional[str] = Field(default=None, alias="personaIdUsed")
    fallback_reason: Optional[str] = Field(default=None, alias="fallbackReason")
    total_cost_usd: float = Field(default=0.0, alias="totalCostUsd")
    total_credits_charged: int = Field(default=0, alias="totalCreditsCharged")
    cost_breakdown: list[Dict[str, Any]] = Field(default_factory=list, alias="costBreakdown")
    cost_totals_by_session: Dict[str, Dict[str, Any]] = Field(default_factory=dict, alias="costTotalsBySession")
    cost_totals_by_job: Dict[str, Dict[str, Any]] = Field(default_factory=dict, alias="costTotalsByJob")


# ============================================================================
# Diagnostic Core Models
# ============================================================================

class PortfolioEvidence(BaseModel):
    """Evidence extracted from a portfolio for a single skill."""
    model_config = {"populate_by_name": True}

    skill: str
    evidence: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: Optional[str] = None


class PortfolioAnalysis(BaseModel):
    """Portfolio analysis output."""
    model_config = {"populate_by_name": True}

    skills: list[PortfolioEvidence] = Field(default_factory=list)
    summary: str
    domains: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list, alias="redFlags")


# ============================================================================
# Diagnostic Session Models (V0 - Placement Test)
# ============================================================================

class DiagnosticSessionStatus(str, Enum):
    """Status of diagnostic session."""
    running = "running"
    finished = "finished"
    abandoned = "abandoned"


class DiagnosticStartRequest(BaseModel):
    """Request to start a diagnostic placement test session."""
    model_config = {"populate_by_name": True}
    
    native_language: str = Field(alias="nativeLanguage", min_length=2, max_length=50)
    target_language: str = Field(alias="targetLanguage", min_length=2, max_length=50)
    start_level_guess: Optional[str] = Field(default="A2", alias="startLevelGuess")  # A1, A2, B1, B2, C1
    use_adaptive: Optional[bool] = Field(default=False, alias="useAdaptive")  # Enable personalized item selection


class DiagnosticStartResponse(BaseModel):
    """Response after starting diagnostic session."""
    model_config = {"populate_by_name": True}
    
    session_id: str = Field(alias="sessionId")
    total_items: int = Field(alias="totalItems")
    next_item: DiagnosticItem = Field(alias="nextItem")


class DiagnosticAttemptRequest(BaseModel):
    """Request to submit an answer for a diagnostic item."""
    model_config = {"populate_by_name": True}
    
    session_id: str = Field(alias="sessionId", min_length=1, max_length=100)
    item_id: str = Field(alias="itemId", min_length=1, max_length=100)
    user_answer_raw: str = Field(alias="userAnswerRaw", max_length=2000)
    response_time_ms: Optional[int] = Field(default=None, alias="responseTimeMs", ge=0)


class DiagnosticAttemptResponse(BaseModel):
    """Response after submitting an answer."""
    model_config = {"populate_by_name": True}
    
    ok: bool
    is_correct: bool = Field(alias="isCorrect")
    correct_answer: str = Field(alias="correctAnswer")


class DiagnosticNextRequest(BaseModel):
    """Request to get next item in session."""
    model_config = {"populate_by_name": True}
    
    session_id: str = Field(alias="sessionId", min_length=1, max_length=100)


class DiagnosticNextResponse(BaseModel):
    """Response with next item or completion status."""
    model_config = {"populate_by_name": True}
    
    complete: bool
    item: Optional[DiagnosticItem] = None
    index: Optional[int] = None
    total_items: Optional[int] = Field(default=None, alias="totalItems")


class DiagnosticFinishRequest(BaseModel):
    """Request to finish diagnostic session and get results."""
    model_config = {"populate_by_name": True}
    
    session_id: str = Field(alias="sessionId", min_length=1, max_length=100)


class WeakSubskill(BaseModel):
    """Weak subskill recommendation."""
    model_config = {"populate_by_name": True}
    
    subskill: str
    skill: str
    accuracy: float
    suggested_focus: str = Field(alias="suggestedFocus")


class DiagnosticFinishResponse(BaseModel):
    """Final results after completing diagnostic session."""
    model_config = {"populate_by_name": True}
    
    estimated_cefr: str = Field(alias="estimatedCefr")  # A1, A2, B1, B2, C1
    skill_scores: Dict[str, int] = Field(alias="skillScores")  # skill -> 0-100
    weak_subskills: list[WeakSubskill] = Field(alias="weakSubskills")
    attempts_count: int = Field(alias="attemptsCount")  # Backward compat
    items_count: int = Field(alias="itemsCount")  # Backward compat
    # Desktop-friendly fields for Score/Accuracy computation
    total_correct: int = Field(alias="totalCorrect")
    total_attempts: int = Field(alias="totalAttempts")
    accuracy: float  # 0.0-1.0


# ============================================================================
# Career Upskilling Contracts
# ============================================================================

class UserBaseData(BaseModel):
    """Key user data from CV + profile."""
    model_config = {"populate_by_name": True}

    skills: list[str]
    experience_years: int = Field(ge=0, le=60)
    target_roles: list[str]
    languages: list[str]


class MarketGapData(BaseModel):
    """Aggregated market skill gap from job search monitoring."""
    model_config = {"populate_by_name": True}

    missing_skills: list[str]
    critical_weakness: Optional[str] = None
    priority_level: int = Field(ge=1, le=5, description="1=low, 5=critical")


class PlacementResults(BaseModel):
    """Placement test outcomes (language or professional)."""
    model_config = {"populate_by_name": True}

    topic_id: str
    raw_score: int = Field(ge=0, le=100)
    verified_skills: list[str]
    failed_questions: list[str]


class LearningPlanContract(BaseModel):
    """Learning plan produced by 4-step AI pipeline."""
    model_config = {"populate_by_name": True}

    curriculum_id: str
    modules: list[Dict[str, Any]]
    success_threshold: int = Field(default=85, ge=0, le=100)


class CareerUpskillingRequest(BaseModel):
    """Request to generate an upskilling plan from key user data."""
    model_config = {"populate_by_name": True}

    user_base_data: UserBaseData
    market_gap_data: MarketGapData
    placement_results: Optional[PlacementResults] = None
    target_role: Optional[str] = None
    duration_weeks: int = Field(default=8, ge=2, le=52)
    success_threshold: int = Field(default=85, ge=0, le=100)


class CareerUpskillingResponse(BaseModel):
    """Response with generated learning plan and summary of gaps."""
    model_config = {"populate_by_name": True}

    learning_plan: LearningPlanContract
    missing_skills: list[str]
    critical_weakness: Optional[str]
    priority_level: int


# ============================================================================
# Job Search & Vacancy Models
# ============================================================================

class JobSearchRequest(BaseModel):
    """Request to search for job vacancies."""
    model_config = {"populate_by_name": True}
    
    job_title: str = Field(..., min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    limit: int = Field(default=10, ge=1, le=50)


class VacancySkill(BaseModel):
    """Skill mentioned in vacancy."""
    skill: str
    frequency: int


class JobVacancyResponse(BaseModel):
    """Single job vacancy data."""
    model_config = {"populate_by_name": True}
    
    title: str
    company: str
    location: str
    description: str
    required_skills: list[str]
    salary_range: Optional[str] = None
    url: Optional[str] = None
    experience_years: Optional[int] = None


class JobSearchResponse(BaseModel):
    """Response from job search."""
    model_config = {"populate_by_name": True}
    
    query: str
    location: str
    total_found: int
    vacancies: list[JobVacancyResponse]
    source: str


class MarketAnalysisRequest(BaseModel):
    """Request to analyze job market for a role."""
    model_config = {"populate_by_name": True}
    
    job_title: str = Field(..., min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    limit: int = Field(default=20, ge=5, le=100)


class MarketAnalysisResponse(BaseModel):
    """Market analysis results for a job role."""
    model_config = {"populate_by_name": True}
    
    job_title: str
    location: str
    total_vacancies: int
    analyzed_count: int
    top_skills: list[VacancySkill]
    avg_experience_years: Optional[float] = None
    sources: list[str]


# ============================================================================
# Career Learning Models
# ============================================================================

class CareerAnalysisResponse(BaseModel):
    """Stored career analysis (editable by user)."""
    model_config = {"populate_by_name": True}

    analysis_id: str
    user_base_data: UserBaseData
    market_gap_data: MarketGapData
    placement_results: Optional[PlacementResults] = None
    target_role: Optional[str] = None
    duration_weeks: int
    success_threshold: int
    created_at: str
    updated_at: str


class CareerAnalysisPatchRequest(BaseModel):
    """User edits to an existing career analysis."""
    model_config = {"populate_by_name": True}

    user_base_data: Optional[UserBaseData] = None
    market_gap_data: Optional[MarketGapData] = None
    placement_results: Optional[PlacementResults] = None
    target_role: Optional[str] = None
    duration_weeks: Optional[int] = Field(default=None, ge=2, le=52)
    success_threshold: Optional[int] = Field(default=None, ge=0, le=100)


class CareerModule(BaseModel):
    """Single learning module in a career track."""
    model_config = {"populate_by_name": True}

    module_id: str
    title: str
    objectives: list[str]
    recommended_activities: list[str]
    status: str = Field(default="planned")


class CareerLearningTrack(BaseModel):
    """Career learning track derived from analysis."""
    model_config = {"populate_by_name": True}

    track_id: str
    analysis_id: str
    target_role: Optional[str]
    modules: list[CareerModule]
    progress_percent: float
    created_at: str
    updated_at: str


class CareerLesson(BaseModel):
    """Background lesson generated for a module."""
    model_config = {"populate_by_name": True}

    lesson_id: str
    track_id: str
    module_id: str
    title: str
    content: dict
    status: str
    created_at: str
    updated_at: str


class CareerLessonCreateRequest(BaseModel):
    """Create a new background lesson for a module or topic."""
    model_config = {"populate_by_name": True}

    module_id: str
    title: str
    content: dict


class CareerLessonListResponse(BaseModel):
    """List background lessons for a user."""
    model_config = {"populate_by_name": True}

    lessons: list[CareerLesson]
    total: int


# ============================================================================
# Learning Profile Models
# ============================================================================

class SkillScore(BaseModel):
    """Skill score with metadata."""
    model_config = {"populate_by_name": True}
    
    skill: str
    score: int  # 0-100
    item_count: Optional[int] = Field(default=None, alias="itemCount")


class DiagnosticHistoryEntry(BaseModel):
    """Historical diagnostic session result."""
    model_config = {"populate_by_name": True}
    
    session_id: str = Field(alias="sessionId")
    completed_at: str = Field(alias="completedAt")  # ISO datetime
    estimated_cefr: str = Field(alias="estimatedCefr")
    total_correct: int = Field(alias="totalCorrect")
    total_attempts: int = Field(alias="totalAttempts")
    accuracy: float


class LearningPreferences(BaseModel):
    """User learning preferences."""
    model_config = {"populate_by_name": True}
    
    topic: Optional[str] = None
    persona_id: Optional[str] = Field(default=None, alias="personaId")
    lesson_length: Optional[int] = Field(default=5, alias="lessonLength")


class LearningHistory(BaseModel):
    """Historical learning data."""
    model_config = {"populate_by_name": True}
    
    diagnostics: list[DiagnosticHistoryEntry] = Field(default_factory=list)


class LearningProfile(BaseModel):
    """User learning profile - AI-readable context."""
    model_config = {"populate_by_name": True}
    
    version: int = 1
    target_language: str = Field(alias="targetLanguage")
    native_language: str = Field(alias="nativeLanguage")
    estimated_cefr: str = Field(alias="estimatedCefr")
    skill_scores: list[SkillScore] = Field(default_factory=list, alias="skillScores")
    weak_subskills: list[WeakSubskill] = Field(default_factory=list, alias="weakSubskills")
    preferences: LearningPreferences = Field(default_factory=LearningPreferences)
    history: Optional[LearningHistory] = None
    updated_at: str = Field(alias="updatedAt")  # ISO datetime


class UpsertLearningProfileRequest(BaseModel):
    """Request to upsert learning profile."""
    model_config = {"populate_by_name": True}
    
    profile: LearningProfile


class UpsertLearningProfileResponse(BaseModel):
    """Response after upserting learning profile."""
    model_config = {"populate_by_name": True}
    
    ok: bool
    updated_at: str = Field(alias="updatedAt")


class PatchLearningProfileRequest(BaseModel):
    """Request to patch learning profile fields."""
    model_config = {"populate_by_name": True}
    
    target_language: Optional[str] = Field(default=None, alias="targetLanguage")
    native_language: Optional[str] = Field(default=None, alias="nativeLanguage")
    preferences: Optional[LearningPreferences] = None


class GetLearningProfileResponse(BaseModel):
    """Response with user learning profile."""
    model_config = {"populate_by_name": True}
    
    profile: LearningProfile


# ============================================================================
# Learning Plan Models
# ============================================================================

class LessonSpec(BaseModel):
    """Recommended lesson specification."""
    model_config = {"populate_by_name": True}
    
    order: int
    mode: str  # "translate", "fill_blank", "mcq", "mixed"
    topic: str
    lesson_length: int = Field(alias="lessonLength")
    rationale: str
    tags: list[str] = Field(default_factory=list)


class LearningPlan(BaseModel):
    """Structured learning plan."""
    model_config = {"populate_by_name": True}
    
    level: str  # CEFR level
    focus_areas: list[str] = Field(alias="focusAreas")
    recommended_lessons: list[LessonSpec] = Field(alias="recommendedLessons")


class FirstLessonRequest(BaseModel):
    """Ready-to-use request payload for /v1/lessons/generate."""
    model_config = {"populate_by_name": True}
    
    mode: str
    target_language: str = Field(alias="targetLanguage")
    native_language: str = Field(alias="nativeLanguage")
    level: str
    topic: str
    lesson_length: int = Field(alias="lessonLength")
    persona_id: Optional[str] = Field(default=None, alias="personaId")


class GenerateLearningPlanRequest(BaseModel):
    """Request to generate learning plan."""
    model_config = {"populate_by_name": True}
    
    target_language: str = Field(alias="targetLanguage")
    native_language: str = Field(alias="nativeLanguage")
    topic: Optional[str] = None
    session_id: Optional[str] = Field(default=None, alias="sessionId")
    estimated_cefr: Optional[str] = Field(default=None, alias="estimatedCefr")
    weak_subskills: Optional[list[WeakSubskill]] = Field(default=None, alias="weakSubskills")
    lesson_length: int = Field(default=5, alias="lessonLength")
    persona_id: Optional[str] = Field(default=None, alias="personaId")


class GenerateLearningPlanResponse(BaseModel):
    """Response with generated learning plan."""
    model_config = {"populate_by_name": True}
    
    plan_id: str = Field(alias="planId")
    profile: LearningProfile
    plan: LearningPlan
    first_lesson_request: FirstLessonRequest = Field(alias="firstLessonRequest")


# ============================================================================
# Client Contract V1 - DTO Layer for Desktop Alignment
# ============================================================================

class DiagnosticItemContentV1(BaseModel):
    """Client V1: content object containing task-type-specific fields."""
    model_config = {"populate_by_name": True}
    
    choices: Optional[list[str]] = None  # For MCQ tasks
    tokens: Optional[list[str]] = None  # For reorder_sentence tasks
    sentence: Optional[str] = None  # From context
    source_text: Optional[str] = Field(default=None, alias="sourceText")  # From context (translate)
    reading_passage: Optional[str] = Field(default=None, alias="readingPassage")  # From context.passage
    hint: Optional[str] = None  # From context.hint


class DiagnosticItemMetadataV1(BaseModel):
    """Client V1: metadata object from tags."""
    model_config = {"populate_by_name": True}
    
    skill: str
    subskill: str
    difficulty: float
    topic: str
    cefr_band: str = Field(alias="cefrBand")


class DiagnosticItemClientV1(BaseModel):
    """Client V1: transformed diagnostic item for desktop."""
    model_config = {"populate_by_name": True}
    
    item_id: str = Field(alias="itemId")  # Renamed from 'id'
    task_type: str = Field(alias="taskType")
    prompt: str
    content: DiagnosticItemContentV1
    metadata: DiagnosticItemMetadataV1


class DiagnosticStartResponseV1(BaseModel):
    """Client V1: start response with transformed item."""
    model_config = {"populate_by_name": True}
    
    session_id: str = Field(alias="sessionId")
    total_items: int = Field(alias="totalItems")
    next_item: DiagnosticItemClientV1 = Field(alias="nextItem")


class DiagnosticAttemptResponseV1(BaseModel):
    """Client V1: attempt response with 'correct' instead of 'isCorrect'."""
    model_config = {"populate_by_name": True}
    
    ok: bool
    correct: bool  # Changed from isCorrect
    correct_answer: str = Field(alias="correctAnswer")
    feedback: Optional[str] = None  # Optional feedback
    attempt_id: Optional[str] = Field(default=None, alias="attemptId")  # Optional attempt tracking


class DiagnosticNextResponseV1(BaseModel):
    """Client V1: next response with transformed item."""
    model_config = {"populate_by_name": True}
    
    complete: bool
    item: Optional[DiagnosticItemClientV1] = None
    index: Optional[int] = None
    total_items: Optional[int] = Field(default=None, alias="totalItems")


# ============================================================================
# Bug Reports / Feedback Models
# ============================================================================

class BugReportKind(str, Enum):
    """Kind of bug report."""
    grading_mismatch = "grading_mismatch"
    ui_bug = "ui_bug"
    content_bug = "content_bug"
    other = "other"


class BugReportSeverity(str, Enum):
    """Severity level of bug report."""
    minor = "minor"
    major = "major"


class BugReportRequest(BaseModel):
    """Request to submit a bug report."""
    model_config = {"populate_by_name": True}
    
    kind: BugReportKind
    severity: BugReportSeverity
    user_message: Optional[str] = Field(default=None, max_length=5000, alias="userMessage")
    context: Dict[str, Any] = Field(default_factory=dict)  # feature, sessionId, itemId, taskType, etc.
    client: Dict[str, Any] = Field(default_factory=dict)  # app, appVersion, platform, userAgent, etc.
    debug: Optional[Dict[str, Any]] = Field(default=None)  # includeDetails, captureAt, etc.


class BugReportResponse(BaseModel):
    """Response after submitting a bug report."""
    model_config = {"populate_by_name": True}
    
    ok: bool
    report_id: str = Field(alias="reportId")
    received_at: str = Field(alias="receivedAt")  # ISO datetime


# ============================================================================
# Learning Path Models
# ============================================================================

class NodeStatus(str, Enum):
    """Status of a learning path node."""
    locked = "locked"
    available = "available"
    in_progress = "in_progress"
    completed = "completed"


class NodeType(str, Enum):
    """Type of learning path node."""
    lesson = "lesson"
    practice = "practice"
    story = "story"
    review = "review"


class PathNode(BaseModel):
    """A single node in a learning unit."""
    model_config = {"populate_by_name": True}
    
    node_id: str = Field(alias="nodeId")
    type: NodeType
    title: str
    status: NodeStatus
    xp: int = 15


class PathUnit(BaseModel):
    """A learning unit containing multiple nodes."""
    model_config = {"populate_by_name": True}
    
    unit_id: str = Field(alias="unitId")
    title: str
    progress: int = 0  # 0-100
    nodes: list[PathNode] = Field(default_factory=list)


class UserPath(BaseModel):
    """Complete user learning path state."""
    model_config = {"populate_by_name": True}
    
    native_lang: str = Field(alias="nativeLang")
    target_lang: str = Field(alias="targetLang")
    total_xp: int = Field(default=0, alias="totalXp")
    streak: int = 0
    cefr_level: str = Field(default="A1", alias="cefrLevel")
    units: list[PathUnit] = Field(default_factory=list)


class GetLearningPathResponse(BaseModel):
    """Response for GET /v1/user/learning-path"""
    model_config = {"populate_by_name": True}
    
    path: UserPath


class StartNodeRequest(BaseModel):
    """Request to start a node."""
    model_config = {"populate_by_name": True}
    
    node_id: str = Field(alias="nodeId")


class StartNodeResponse(BaseModel):
    """Response after starting a node."""
    model_config = {"populate_by_name": True}
    
    node_id: str = Field(alias="nodeId")
    status: NodeStatus


class CompleteNodeRequest(BaseModel):
    """Request to complete a node."""
    model_config = {"populate_by_name": True}
    
    node_id: str = Field(alias="nodeId")
    unit_id: str = Field(alias="unitId")
    score: int = Field(ge=0, le=100)


class CompleteNodeResponse(BaseModel):
    """Response after completing a node."""
    model_config = {"populate_by_name": True}
    
    node_id: str = Field(alias="nodeId")
    status: NodeStatus
    xp_awarded: int = Field(alias="xpAwarded")
    total_xp: int = Field(alias="totalXp")
    next_node_id: Optional[str] = Field(default=None, alias="nextNodeId")
    unlocked_nodes: list[str] = Field(default_factory=list, alias="unlockedNodes")
    unlocked_units: list[str] = Field(default_factory=list, alias="unlockedUnits")
