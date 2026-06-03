"""
Dynamic Test API Router
Provides FastAPI endpoints for running custom tests with user-specified parameters.

Endpoints:
- POST /v1/tests/dynamic - Run dynamic tests with custom config
- GET /v1/tests/dynamic/{session_id} - Get test results
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import asyncio
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/tests", tags=["Dynamic Testing"])


# Request/Response Models
class DynamicTestRequest(BaseModel):
    """Request for dynamic test generation"""
    num_tests: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Number of tests to run (1-50)"
    )
    languages: List[str] = Field(
        default=["es", "fr", "de"],
        description="Language codes (ISO 639-1): es, fr, de, it, pt, ja, ko, zh, ru, ar"
    )
    topics: Optional[List[str]] = Field(
        default=None,
        description="Custom topics (if None, uses predefined list)"
    )
    cefr_levels: List[str] = Field(
        default=["A1", "A2", "B1", "B2", "C1"],
        description="CEFR levels to test"
    )
    focus_areas: List[str] = Field(
        default=["conversation", "grammar"],
        description="Focus areas: conversation, grammar, vocabulary"
    )
    test_modes: Optional[List[str]] = Field(
        default=None,
        description="Test modes: learning_path, ad_hoc_lesson (if None, uses both)"
    )


class DynamicTestSessionResponse(BaseModel):
    """Response for test session creation"""
    session_id: str
    status: str  # "running", "completed", "failed"
    created_at: datetime
    config: Dict[str, Any]


class TestResultItem(BaseModel):
    """Single test result"""
    test_id: str
    language_code: str
    language_name: str
    topic: str
    cefr_level: str
    test_mode: str
    focus: str
    duration_s: float
    success: bool
    score: int
    error_message: str = ""


class DynamicTestResultsResponse(BaseModel):
    """Complete test results"""
    session_id: str
    timestamp: datetime
    total_tests: int
    passed: int
    failed: int
    pass_rate_percent: float
    total_duration_seconds: float
    average_duration_seconds: float
    average_quality_score: float
    total_api_calls: int
    by_language: Dict[str, Dict[str, int]]
    by_topic: Dict[str, Dict[str, int]]
    results: List[TestResultItem]


# In-memory session storage (in production, use database/redis)
_test_sessions: Dict[str, Dict[str, Any]] = {}


@router.post("/dynamic", response_model=DynamicTestSessionResponse)
async def run_dynamic_tests(
    request: DynamicTestRequest,
    background_tasks: BackgroundTasks
) -> DynamicTestSessionResponse:
    """
    Create and run a dynamic test session with custom parameters.
    
    Returns immediately with session_id. Tests run in background.
    Use GET /v1/tests/dynamic/{session_id} to poll for results.
    
    Example:
    ```json
    {
      "num_tests": 5,
      "languages": ["es", "fr", "ja"],
      "topics": ["Cooking", "Travel", "Business"],
      "cefr_levels": ["A1", "B1", "C1"],
      "focus_areas": ["conversation", "grammar"]
    }
    ```
    """
    
    from dynamic_test_module import DynamicTestRunner, DynamicTestConfig
    
    try:
        # Create config
        config = DynamicTestConfig(
            num_tests=request.num_tests,
            languages=request.languages,
            topics=request.topics,
            cefr_levels=request.cefr_levels,
            test_modes=request.test_modes,
            focus_areas=request.focus_areas
        )
        
        # Create runner
        runner = DynamicTestRunner(config)
        session_id = runner.session_id
        
        # Store session metadata
        _test_sessions[session_id] = {
            "status": "running",
            "created_at": datetime.now(timezone.utc),
            "config": {
                "num_tests": request.num_tests,
                "languages": request.languages,
                "topics": request.topics or [],
                "cefr_levels": request.cefr_levels,
                "focus_areas": request.focus_areas
            },
            "results": None,
            "runner": runner
        }
        
        # Schedule background task
        background_tasks.add_task(_run_tests_background, session_id, runner)
        
        return DynamicTestSessionResponse(
            session_id=session_id,
            status="running",
            created_at=datetime.now(timezone.utc),
            config=_test_sessions[session_id]["config"]
        )
    
    except Exception as e:
        logger.error(f"Failed to start dynamic test: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/dynamic/{session_id}", response_model=DynamicTestResultsResponse)
async def get_dynamic_test_results(session_id: str) -> DynamicTestResultsResponse:
    """
    Get results for a dynamic test session.
    
    Returns:
    - 404 if session not found
    - Results with status="running" if still executing
    - Complete results when done
    """
    
    if session_id not in _test_sessions:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    
    session = _test_sessions[session_id]
    
    if session["results"] is None:
        raise HTTPException(status_code=202, detail="Test still running. Check back later.")
    
    results = session["results"]
    
    # Convert to response format
    return DynamicTestResultsResponse(
        session_id=session_id,
        timestamp=datetime.fromisoformat(results["timestamp"]),
        total_tests=results["total_tests"],
        passed=results["passed"],
        failed=results["failed"],
        pass_rate_percent=results["pass_rate_percent"],
        total_duration_seconds=results["total_duration_seconds"],
        average_duration_seconds=results["average_duration_seconds"],
        average_quality_score=results["average_quality_score"],
        total_api_calls=results["total_api_calls"],
        by_language=results["by_language"],
        by_topic=results["by_topic"],
        results=[
            TestResultItem(**r) for r in results["results"]
        ]
    )


@router.get("/dynamic")
async def list_test_sessions() -> Dict[str, Any]:
    """
    List all test sessions (running and completed).
    
    Returns metadata about each session.
    """
    
    sessions_info = {}
    for sid, session in _test_sessions.items():
        sessions_info[sid] = {
            "status": session["status"],
            "created_at": session["created_at"].isoformat(),
            "num_tests": session["config"]["num_tests"],
            "languages": session["config"]["languages"],
            "has_results": session["results"] is not None
        }
    
    return {
        "total_sessions": len(_test_sessions),
        "sessions": sessions_info
    }


async def _run_tests_background(session_id: str, runner) -> None:
    """Background task to run tests"""
    
    try:
        logger.info(f"Starting background test run: {session_id}")
        
        # Run tests (non-verbose since it's background)
        results = await runner.run_dynamic_tests(verbose=False)
        
        # Store results
        _test_sessions[session_id]["results"] = results
        _test_sessions[session_id]["status"] = "completed"
        
        logger.info(f"Test run completed: {session_id}")
    
    except Exception as e:
        logger.error(f"Test run failed: {session_id} - {e}")
        _test_sessions[session_id]["status"] = "failed"
        _test_sessions[session_id]["error"] = str(e)
