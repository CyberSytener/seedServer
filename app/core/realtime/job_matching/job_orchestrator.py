"""
Job Search Saga Orchestrator - Hybrid Parsing Strategy

Implements a 4-step "pause-and-enrich" flow for job search:
1. discovery - Fetch basic job metadata (title, link, company) only
2. emit_results - Send list to client via saga.update
3. await_client_selection - Pause saga, wait for client to send job_id + enriched text
4. ai_scoring - Perform heavy LLM analysis on selected, enriched data

This approach offloads full-page scraping to the client (browser extension),
avoiding server-side rendering and rate limits.
"""

import uuid
import json
import logging
import asyncio
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime, timezone
from dataclasses import dataclass, asdict, field
from enum import Enum

logger = logging.getLogger(__name__)


class JobSearchState(str, Enum):
    """Job search saga lifecycle states."""
    PENDING = "pending"
    DISCOVERING = "discovering"
    AWAITING_CLIENT_SELECTION = "awaiting_client_selection"
    SCORING = "scoring"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(str, Enum):
    """Individual step status within saga."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class JobMetadata:
    """Basic job metadata from discovery phase."""
    job_id: str
    title: str
    company: str
    link: str
    location: Optional[str] = None
    posted_date: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EnrichedJobData:
    """Client-provided enriched job data."""
    job_id: str
    full_description: str
    requirements: Optional[List[str]] = None
    salary_range: Optional[str] = None
    benefits: Optional[List[str]] = None
    additional_metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JobScoringResult:
    """Result of AI scoring for a job."""
    job_id: str
    match_score: float
    reasoning: str
    key_matches: List[str]
    concerns: List[str]
    recommendation: str  # "strong_fit", "possible_fit", "poor_fit"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SagaStepRecord:
    """Record of a step execution within saga."""
    name: str
    status: str = StepStatus.PENDING.value
    meta: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class JobSearchOrchestrator:
    """
    Orchestrates job search saga with hybrid parsing strategy.
    
    Key responsibilities:
    1. Discovery: Fetch basic job metadata from job boards
    2. Emit results: Send job list to client
    3. Await client selection: Pause and wait for enriched data
    4. AI scoring: Analyze enriched job data with LLM
    """
    
    def __init__(
        self,
        db_connection_string: Optional[str] = None,
        job_board_adapter: Optional[Any] = None,
        llm_client: Optional[Any] = None,
        saga_update_handler: Optional[Callable[[Dict[str, Any]], Any]] = None,
        logger_instance: Optional[logging.Logger] = None,
    ):
        """
        Initialize job search orchestrator.
        
        Args:
            db_connection_string: PostgreSQL connection string for saga persistence
            job_board_adapter: Adapter for fetching job metadata
            llm_client: LLM client for AI scoring
            saga_update_handler: Callback to emit updates to client
            logger_instance: Logger for trace/debug
        """
        self.db_url = db_connection_string
        self.job_board = job_board_adapter
        self.llm = llm_client
        self.saga_update_handler = saga_update_handler
        self.logger = logger_instance or logger
        
        # In-memory storage for active sagas (would be DB in production)
        self.sagas: Dict[str, Dict[str, Any]] = {}
        
    # =========================================================================
    # Core Saga Lifecycle
    # =========================================================================
    
    async def start_job_search_saga(
        self,
        user_id: str,
        search_params: Dict[str, Any],
    ) -> str:
        """
        Start a new job search saga with hybrid parsing.
        
        Args:
            user_id: User ID initiating the search
            search_params: Search parameters (query, location, filters, etc.)
            
        Returns:
            saga_id (UUID string)
        """
        saga_id = str(uuid.uuid4())
        
        saga = {
            "saga_id": saga_id,
            "user_id": user_id,
            "state": JobSearchState.PENDING.value,
            "search_params": search_params,
            "steps": [],
            "discovered_jobs": [],
            "selected_job_id": None,
            "enriched_data": None,
            "scoring_result": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        self.sagas[saga_id] = saga
        self.logger.info(f"📝 Job search saga created: {saga_id}")
        
        # Kick off discovery phase
        await self._run_discovery_phase(saga_id)
        
        return saga_id
    
    async def _run_discovery_phase(self, saga_id: str):
        """
        STEP 1: Discovery - Fetch basic job metadata only.
        
        This step intentionally avoids full-page scraping. It only fetches:
        - Job title
        - Company name
        - Job link/URL
        - Basic metadata (location, posted date if available)
        
        Full content is scraped by the client browser extension.
        """
        saga = self.sagas.get(saga_id)
        if not saga:
            self.logger.error(f"Saga {saga_id} not found")
            return
        
        try:
            # Update state
            saga["state"] = JobSearchState.DISCOVERING.value
            step = SagaStepRecord(
                name="discovery",
                status=StepStatus.IN_PROGRESS.value,
            )
            saga["steps"].append(step.to_dict())
            
            self.logger.info(f"🔍 Step 1: Discovery phase for saga {saga_id}")
            
            # Fetch basic job metadata (no full scraping)
            search_params = saga["search_params"]
            jobs = await self._fetch_job_metadata(search_params)
            
            # Store discovered jobs
            saga["discovered_jobs"] = [job.to_dict() for job in jobs]
            saga["steps"][-1]["status"] = StepStatus.SUCCEEDED.value
            saga["steps"][-1]["meta"] = {
                "job_count": len(jobs),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            saga["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            self.logger.info(f"✅ Discovered {len(jobs)} jobs for saga {saga_id}")
            
            # Move to emit phase
            await self._emit_results_phase(saga_id)
            
        except Exception as e:
            self.logger.exception(f"❌ Discovery phase failed for saga {saga_id}")
            saga["state"] = JobSearchState.FAILED.value
            saga["steps"][-1]["status"] = StepStatus.FAILED.value
            saga["steps"][-1]["error"] = str(e)
            saga["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    async def _emit_results_phase(self, saga_id: str):
        """
        STEP 2: Emit Results - Send job list to client via saga.update.
        
        Sends the discovered job metadata to the client so they can:
        - Display the job list
        - Select a job to analyze
        - Use browser extension to scrape full content
        """
        saga = self.sagas.get(saga_id)
        if not saga:
            return
        
        try:
            step = SagaStepRecord(
                name="emit_results",
                status=StepStatus.IN_PROGRESS.value,
            )
            saga["steps"].append(step.to_dict())
            
            self.logger.info(f"📤 Step 2: Emitting results for saga {saga_id}")
            
            # Emit update to client
            update_payload = {
                "saga_id": saga_id,
                "type": "job_search.discovery_complete",
                "state": JobSearchState.AWAITING_CLIENT_SELECTION.value,
                "data": {
                    "jobs": saga["discovered_jobs"],
                    "total_count": len(saga["discovered_jobs"]),
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            if self.saga_update_handler:
                await self._call_update_handler(update_payload)
            
            saga["steps"][-1]["status"] = StepStatus.SUCCEEDED.value
            saga["steps"][-1]["meta"] = {
                "emitted_count": len(saga["discovered_jobs"]),
            }
            saga["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            # Move to await phase
            await self._await_client_selection_phase(saga_id)
            
        except Exception as e:
            self.logger.exception(f"❌ Emit phase failed for saga {saga_id}")
            saga["state"] = JobSearchState.FAILED.value
            saga["steps"][-1]["status"] = StepStatus.FAILED.value
            saga["steps"][-1]["error"] = str(e)
            saga["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    async def _await_client_selection_phase(self, saga_id: str):
        """
        STEP 3: Await Client Selection - Pause saga and wait.
        
        The saga now enters a waiting state. It will resume when the client calls
        resume_with_enriched_job() with:
        - job_id: The selected job
        - enriched_data: Full job description scraped by browser
        """
        saga = self.sagas.get(saga_id)
        if not saga:
            return
        
        saga["state"] = JobSearchState.AWAITING_CLIENT_SELECTION.value
        step = SagaStepRecord(
            name="await_client_selection",
            status=StepStatus.PENDING.value,
        )
        saga["steps"].append(step.to_dict())
        saga["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        self.logger.info(f"⏳ Step 3: Waiting for client selection on saga {saga_id}")
        
        # Saga is now paused. Client must call resume_with_enriched_job() to continue.
    
    async def resume_with_enriched_job(
        self,
        saga_id: str,
        job_id: str,
        enriched_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Resume saga after client provides enriched job data.
        
        Called by the client after:
        1. User selects a job from the list
        2. Browser extension scrapes full job content
        3. Client sends job_id + enriched data back to server
        
        Args:
            saga_id: ID of saga to resume
            job_id: Selected job ID
            enriched_data: Full job content from client (description, requirements, etc.)
            
        Returns:
            Result dict with status and scoring outcome
        """
        saga = self.sagas.get(saga_id)
        if not saga:
            return {"status": "error", "error": "Saga not found"}
        
        if saga["state"] != JobSearchState.AWAITING_CLIENT_SELECTION.value:
            return {
                "status": "error",
                "error": f"Saga not waiting for selection (state: {saga['state']})",
            }
        
        try:
            # Mark selection step as complete
            saga["steps"][-1]["status"] = StepStatus.SUCCEEDED.value
            saga["steps"][-1]["meta"] = {
                "job_id": job_id,
                "received_at": datetime.now(timezone.utc).isoformat(),
            }
            
            # Store enriched data
            saga["selected_job_id"] = job_id
            saga["enriched_data"] = enriched_data
            saga["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            self.logger.info(f"✅ Received enriched data for job {job_id} in saga {saga_id}")
            
            # Move to AI scoring phase
            await self._ai_scoring_phase(saga_id)
            
            return {"status": "success", "saga_id": saga_id}
            
        except Exception as e:
            self.logger.exception(f"❌ Failed to resume saga {saga_id}")
            saga["state"] = JobSearchState.FAILED.value
            saga["updated_at"] = datetime.now(timezone.utc).isoformat()
            return {"status": "error", "error": str(e)}
    
    async def _ai_scoring_phase(self, saga_id: str):
        """
        STEP 4: AI Scoring - Perform heavy LLM analysis.
        
        Now that we have the full job content from the client, we can:
        1. Run LLM-based match scoring
        2. Extract key requirements and matches
        3. Generate recommendation
        4. Return results to client
        """
        saga = self.sagas.get(saga_id)
        if not saga:
            return
        
        try:
            saga["state"] = JobSearchState.SCORING.value
            step = SagaStepRecord(
                name="ai_scoring",
                status=StepStatus.IN_PROGRESS.value,
            )
            saga["steps"].append(step.to_dict())
            
            self.logger.info(f"🤖 Step 4: AI scoring for saga {saga_id}")
            
            # Perform LLM-based analysis
            scoring_result = await self._score_job_with_llm(
                saga["selected_job_id"],
                saga["enriched_data"],
                saga["user_id"],
            )
            
            # Store result
            saga["scoring_result"] = scoring_result.to_dict()
            saga["steps"][-1]["status"] = StepStatus.SUCCEEDED.value
            saga["steps"][-1]["meta"] = {
                "match_score": scoring_result.match_score,
                "recommendation": scoring_result.recommendation,
            }
            saga["state"] = JobSearchState.COMPLETED.value
            saga["updated_at"] = datetime.now(timezone.utc).isoformat()
            
            self.logger.info(
                f"✅ Scoring complete for saga {saga_id}: "
                f"score={scoring_result.match_score}, recommendation={scoring_result.recommendation}"
            )
            
            # Emit final results to client
            update_payload = {
                "saga_id": saga_id,
                "type": "job_search.scoring_complete",
                "state": JobSearchState.COMPLETED.value,
                "data": {
                    "job_id": saga["selected_job_id"],
                    "scoring": saga["scoring_result"],
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            
            if self.saga_update_handler:
                await self._call_update_handler(update_payload)
            
        except Exception as e:
            self.logger.exception(f"❌ AI scoring failed for saga {saga_id}")
            saga["state"] = JobSearchState.FAILED.value
            saga["steps"][-1]["status"] = StepStatus.FAILED.value
            saga["steps"][-1]["error"] = str(e)
            saga["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    async def _fetch_job_metadata(self, search_params: Dict[str, Any]) -> List[JobMetadata]:
        """
        Fetch basic job metadata from job board API.
        
        This is intentionally lightweight - only fetches:
        - Title, company, link
        - Optional: location, posted_date
        
        Does NOT fetch full job descriptions.
        """
        if self.job_board:
            # Use adapter if available
            jobs_data = await self._call_adapter_method(
                self.job_board,
                "fetch_metadata",
                search_params,
            )
            return [
                JobMetadata(
                    job_id=job.get("id", str(uuid.uuid4())),
                    title=job.get("title", ""),
                    company=job.get("company", ""),
                    link=job.get("link", ""),
                    location=job.get("location"),
                    posted_date=job.get("posted_date"),
                )
                for job in jobs_data
            ]
        else:
            # Mock data for testing
            self.logger.warning("No job board adapter configured; returning mock data")
            return [
                JobMetadata(
                    job_id=str(uuid.uuid4()),
                    title="Senior Python Engineer",
                    company="TechCorp",
                    link="https://example.com/job/1",
                    location="San Francisco, CA",
                    posted_date="2 days ago",
                ),
                JobMetadata(
                    job_id=str(uuid.uuid4()),
                    title="Backend Developer",
                    company="StartupXYZ",
                    link="https://example.com/job/2",
                    location="Remote",
                    posted_date="1 week ago",
                ),
            ]
    
    async def _score_job_with_llm(
        self,
        job_id: str,
        enriched_data: Dict[str, Any],
        user_id: str,
    ) -> JobScoringResult:
        """
        Score job match using LLM analysis.
        
        Analyzes:
        - Job requirements vs user profile
        - Skills match
        - Experience alignment
        - Culture fit indicators
        """
        if self.llm:
            # Use LLM client if available
            prompt = self._build_scoring_prompt(enriched_data, user_id)
            response = await self._call_adapter_method(
                self.llm,
                "analyze",
                {"prompt": prompt},
            )
            
            # Parse LLM response into scoring result
            return self._parse_llm_scoring(job_id, response)
        else:
            # Mock scoring for testing
            self.logger.warning("No LLM client configured; returning mock scoring")
            return JobScoringResult(
                job_id=job_id,
                match_score=0.85,
                reasoning="Strong technical match with required Python, FastAPI, and PostgreSQL skills. "
                          "Experience level aligns well with senior position requirements.",
                key_matches=[
                    "5+ years Python experience",
                    "FastAPI/Django framework knowledge",
                    "PostgreSQL/database design",
                    "API design and microservices",
                ],
                concerns=[
                    "No mention of specific cloud platform experience (AWS/GCP)",
                ],
                recommendation="strong_fit",
            )
    
    def _build_scoring_prompt(self, enriched_data: Dict[str, Any], user_id: str) -> str:
        """Build prompt for LLM scoring."""
        # In production, fetch user profile from DB
        # For now, use a template
        return f"""
        Analyze this job posting and provide a match score:
        
        Job Description:
        {enriched_data.get('full_description', '')}
        
        Requirements:
        {', '.join(enriched_data.get('requirements', []))}
        
        User Profile:
        - Skills: Python, FastAPI, PostgreSQL, Docker
        - Experience: 5 years backend development
        - Looking for: Senior engineer roles, remote-friendly
        
        Provide:
        1. Match score (0-1)
        2. Reasoning
        3. Key matches (list)
        4. Concerns (list)
        5. Recommendation (strong_fit, possible_fit, poor_fit)
        """
    
    def _parse_llm_scoring(self, job_id: str, llm_response: Dict[str, Any]) -> JobScoringResult:
        """Parse LLM response into JobScoringResult."""
        # Parse LLM output (structure depends on LLM client response format)
        content = llm_response.get("content", {})
        
        return JobScoringResult(
            job_id=job_id,
            match_score=content.get("match_score", 0.5),
            reasoning=content.get("reasoning", ""),
            key_matches=content.get("key_matches", []),
            concerns=content.get("concerns", []),
            recommendation=content.get("recommendation", "possible_fit"),
        )
    
    async def _call_adapter_method(self, adapter: Any, method_name: str, *args, **kwargs):
        """Call adapter method (handles both sync and async)."""
        method = getattr(adapter, method_name, None)
        if not method:
            raise ValueError(f"Adapter does not have method: {method_name}")
        
        result = method(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result
    
    async def _call_update_handler(self, payload: Dict[str, Any]):
        """Call saga update handler (handles both sync and async)."""
        if not self.saga_update_handler:
            return
        
        result = self.saga_update_handler(payload)
        if asyncio.iscoroutine(result):
            await result
    
    # =========================================================================
    # Query Methods
    # =========================================================================
    
    def get_saga(self, saga_id: str) -> Optional[Dict[str, Any]]:
        """Get saga by ID."""
        return self.sagas.get(saga_id)
    
    def get_saga_state(self, saga_id: str) -> Optional[str]:
        """Get current state of saga."""
        saga = self.sagas.get(saga_id)
        return saga["state"] if saga else None
    
    def get_discovered_jobs(self, saga_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get list of discovered jobs for saga."""
        saga = self.sagas.get(saga_id)
        return saga["discovered_jobs"] if saga else None
    
    def get_scoring_result(self, saga_id: str) -> Optional[Dict[str, Any]]:
        """Get AI scoring result for saga."""
        saga = self.sagas.get(saga_id)
        return saga["scoring_result"] if saga else None
