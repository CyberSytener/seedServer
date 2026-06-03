"""
API endpoints for prompt testing and management.

Allows starting test sessions, viewing results, and managing test prompts.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.auth import require_auth_context
from app.dependencies import get_db
from app.infrastructure.db.sqlite import DB
from app.services.prompt_testing import (
    PromptType,
    get_prompt_test_manager,
    PromptTestManager,
)


class PromptTestSessionRequest(BaseModel):
    """Request to start a new prompt testing session."""
    session_name: str = Field(..., description="Name for the test session")
    description: Optional[str] = Field(None, description="Optional description of the test")


class PromptTestSessionResponse(BaseModel):
    """Response from starting a prompt testing session."""
    session_id: str = Field(..., description="Unique session identifier")
    status: str = Field(..., description="Session status")
    message: str = Field(..., description="Status message")


class PromptTestSummaryResponse(BaseModel):
    """Summary of prompt testing results."""
    session: Optional[str]
    total_tests: int
    success_rate: float
    by_type: Dict[str, Dict[str, Any]]


class PromptListResponse(BaseModel):
    """List of available prompt files."""
    baseline_prompts: List[str]
    test_prompts: List[str]
    prompt_types: List[str]


class PromptContentRequest(BaseModel):
    """Request to get or update prompt content."""
    prompt_type: str = Field(..., description="Type of prompt")
    is_test_version: bool = Field(False, description="Whether this is a test version")


class PromptContentResponse(BaseModel):
    """Response with prompt content."""
    prompt_type: str
    version: str  # "baseline" or "test"
    content: str
    file_path: str


# Create router
router = APIRouter(prefix="/api/prompt-testing", tags=["Prompt Testing"])


def _require_ctx(request: Request, db: DB = Depends(get_db)):
    return require_auth_context(request, db)


@router.post("/session/start", response_model=PromptTestSessionResponse)
async def start_test_session(req: PromptTestSessionRequest, request: Request):
    """Start a new prompt testing session."""
    ctx = _require_ctx(request)
    
    try:
        test_manager = get_prompt_test_manager()
        
        if not test_manager.is_test_mode_active():
            raise HTTPException(
                status_code=400,
                detail="Prompt testing is not enabled. Set SEED_PROMPT_TEST_MODE=true"
            )
        
        session_id = test_manager.start_test_session(req.session_name)
        
        logging.info(f"Started prompt test session: {session_id} by user {ctx.user_id}")
        
        return PromptTestSessionResponse(
            session_id=session_id,
            status="active",
            message=f"Test session '{session_id}' started successfully"
        )
        
    except Exception as e:
        logging.error(f"Failed to start test session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/summary", response_model=PromptTestSummaryResponse)
async def get_session_summary(request: Request):
    """Get summary of current test session results."""
    ctx = _require_ctx(request)
    
    try:
        test_manager = get_prompt_test_manager()
        summary = test_manager.get_session_summary()
        
        return PromptTestSummaryResponse(**summary)
        
    except Exception as e:
        logging.error(f"Failed to get session summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompts", response_model=PromptListResponse)
async def list_prompts(request: Request):
    """List all available prompt files."""
    ctx = _require_ctx(request)
    
    try:
        test_manager = get_prompt_test_manager()
        
        # List baseline prompts (from main prompts directory)
        prompts_dir = Path(test_manager.base_dir)
        baseline_prompts = [f.stem for f in prompts_dir.glob("*.md")]
        
        # List test prompts
        test_prompts = test_manager.list_available_test_prompts()
        
        # Get available prompt types
        prompt_types = [pt.value for pt in PromptType]
        
        return PromptListResponse(
            baseline_prompts=baseline_prompts,
            test_prompts=test_prompts,
            prompt_types=prompt_types
        )
        
    except Exception as e:
        logging.error(f"Failed to list prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prompts/content", response_model=PromptContentResponse)
async def get_prompt_content(req: PromptContentRequest, request: Request):
    """Get content of a specific prompt."""
    ctx = _require_ctx(request)
    
    try:
        # Validate prompt type
        try:
            prompt_type = PromptType(req.prompt_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid prompt type. Available types: {[pt.value for pt in PromptType]}"
            )
        
        test_manager = get_prompt_test_manager()
        
        try:
            content = test_manager.get_prompt_content(prompt_type, req.is_test_version)
            version = "test" if req.is_test_version else "baseline"
            
            # Determine file path
            if req.is_test_version:
                file_path = str(test_manager.test_dir / f"{prompt_type.value}.md")
            else:
                file_path = str(test_manager.base_dir / f"{prompt_type.value}.md")
            
            return PromptContentResponse(
                prompt_type=req.prompt_type,
                version=version,
                content=content,
                file_path=file_path
            )
            
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to get prompt content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_test_status(request: Request):
    """Get current prompt testing status."""
    ctx = _require_ctx(request)
    
    try:
        test_manager = get_prompt_test_manager()
        
        return {
            "test_mode_active": test_manager.is_test_mode_active(),
            "current_session": test_manager._current_test_session,
            "available_test_prompts": test_manager.list_available_test_prompts(),
            "results_directory": str(test_manager.results_dir)
        }
        
    except Exception as e:
        logging.error(f"Failed to get test status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/results/{session_id}")
async def get_session_results(session_id: str, request: Request):
    """Get detailed results for a specific test session."""
    ctx = _require_ctx(request)
    
    try:
        test_manager = get_prompt_test_manager()
        session_dir = test_manager.results_dir / session_id
        
        if not session_dir.exists():
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        # Load all result files
        results = []
        for result_file in session_dir.glob("*.json"):
            try:
                result_data = json.loads(result_file.read_text())
                results.append(result_data)
            except Exception as e:
                logging.warning(f"Failed to load result file {result_file}: {e}")
        
        # Sort by timestamp
        results.sort(key=lambda x: x.get("timestamp", ""))
        
        return {
            "session_id": session_id,
            "total_results": len(results),
            "results": results
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to get session results: {e}")
        raise HTTPException(status_code=500, detail=str(e))
