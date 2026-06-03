"""
Job Search Action Contracts

Defines Pydantic v2 contracts for job search saga actions:
1. initiate_job_search - Start job discovery
2. select_job - Client selects a job for analysis
3. submit_enriched_job - Client submits scraped job content

All actions support the hybrid parsing strategy where the client
scrapes full content and the server handles AI analysis.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field, HttpUrl, validator
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class JobSourceType(str, Enum):
    """Source of job posting"""
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GLASSDOOR = "glassdoor"
    COMPANY_WEBSITE = "company_website"
    JOB_BOARD = "job_board"
    OTHER = "other"


class EmploymentType(str, Enum):
    """Employment type for job"""
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"


class RemotePolicy(str, Enum):
    """Remote work policy"""
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    FLEXIBLE = "flexible"


class MatchRecommendation(str, Enum):
    """AI match recommendation"""
    STRONG_FIT = "strong_fit"
    POSSIBLE_FIT = "possible_fit"
    POOR_FIT = "poor_fit"


# ============================================================================
# ACTION 1: INITIATE JOB SEARCH
# ============================================================================

class InitiateJobSearchInput(BaseModel):
    """Input for initiate_job_search action (discovery phase)"""
    
    # Search parameters
    query: str = Field(..., min_length=1, max_length=500, description="Job search query (e.g., 'Python Engineer')")
    location: Optional[str] = Field(None, max_length=200, description="Location (e.g., 'San Francisco, CA' or 'Remote')")
    
    # Filters
    employment_types: Optional[List[EmploymentType]] = Field(None, max_items=5)
    remote_policy: Optional[RemotePolicy] = None
    min_salary: Optional[int] = Field(None, ge=0)
    max_salary: Optional[int] = Field(None, ge=0)
    
    # Search scope
    sources: Optional[List[JobSourceType]] = Field(None, max_items=10, description="Job boards to search")
    max_results: int = Field(20, ge=1, le=100, description="Maximum number of jobs to discover")
    
    # User context (for personalized results)
    user_id: str = Field(..., min_length=1)
    user_skills: Optional[List[str]] = Field(None, max_items=50)
    user_experience_years: Optional[int] = Field(None, ge=0, le=50)
    
    model_config = {"json_schema_extra": {
        "example": {
            "query": "Senior Python Engineer",
            "location": "San Francisco, CA",
            "employment_types": ["full_time"],
            "remote_policy": "hybrid",
            "min_salary": 120000,
            "max_salary": 180000,
            "sources": ["linkedin", "indeed"],
            "max_results": 20,
            "user_id": "user_123",
            "user_skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
            "user_experience_years": 5
        }
    }}


class JobMetadataOutput(BaseModel):
    """Basic job metadata from discovery phase (no full content)"""
    job_id: str
    title: str
    company: str
    link: HttpUrl
    location: Optional[str] = None
    posted_date: Optional[str] = None
    source: Optional[JobSourceType] = None
    employment_type: Optional[EmploymentType] = None
    salary_range: Optional[str] = None  # Brief string like "$120k-$180k"


class InitiateJobSearchOutput(BaseModel):
    """Output from initiate_job_search action"""
    saga_id: str
    jobs: List[JobMetadataOutput]
    total_count: int
    search_params: Dict[str, Any]
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    model_config = {"json_schema_extra": {
        "example": {
            "saga_id": "saga_abc123",
            "jobs": [
                {
                    "job_id": "job_001",
                    "title": "Senior Python Engineer",
                    "company": "TechCorp",
                    "link": "https://example.com/job/1",
                    "location": "San Francisco, CA",
                    "posted_date": "2 days ago",
                    "source": "linkedin",
                    "employment_type": "full_time",
                    "salary_range": "$150k-$180k"
                }
            ],
            "total_count": 1,
            "search_params": {"query": "Senior Python Engineer"},
            "timestamp": "2026-02-01T10:00:00Z"
        }
    }}


# ============================================================================
# ACTION 2: SELECT JOB (CLIENT-SIDE)
# ============================================================================

class SelectJobInput(BaseModel):
    """Input for select_job action (client selects a job to analyze)"""
    saga_id: str = Field(..., min_length=1)
    job_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    
    model_config = {"json_schema_extra": {
        "example": {
            "saga_id": "saga_abc123",
            "job_id": "job_001",
            "user_id": "user_123"
        }
    }}


class SelectJobOutput(BaseModel):
    """Output from select_job action"""
    saga_id: str
    job_id: str
    status: str = "awaiting_enrichment"
    message: str = "Job selected. Please scrape and submit full content."


# ============================================================================
# ACTION 3: SUBMIT ENRICHED JOB (CLIENT PROVIDES SCRAPED CONTENT)
# ============================================================================

class SubmitEnrichedJobInput(BaseModel):
    """Input for submit_enriched_job action (client sends scraped content)"""
    
    # Saga context
    saga_id: str = Field(..., min_length=1)
    job_id: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    
    # Full job content (scraped by client)
    full_description: str = Field(..., min_length=10, max_length=50000, description="Full job description text")
    
    # Structured data (if client can extract it)
    requirements: Optional[List[str]] = Field(None, max_items=100, description="Job requirements/qualifications")
    responsibilities: Optional[List[str]] = Field(None, max_items=100, description="Job responsibilities")
    benefits: Optional[List[str]] = Field(None, max_items=50, description="Benefits/perks")
    salary_details: Optional[str] = Field(None, max_length=500, description="Detailed salary info")
    
    # Additional metadata
    employment_type: Optional[EmploymentType] = None
    remote_policy: Optional[RemotePolicy] = None
    team_size: Optional[str] = Field(None, max_length=100)
    tech_stack: Optional[List[str]] = Field(None, max_items=50)
    
    # Enrichment metadata
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scraper_version: Optional[str] = Field(None, max_length=50)
    raw_html_available: bool = Field(False, description="Whether client has raw HTML cached")
    
    model_config = {"json_schema_extra": {
        "example": {
            "saga_id": "saga_abc123",
            "job_id": "job_001",
            "user_id": "user_123",
            "full_description": "We are seeking a Senior Python Engineer to join our backend team...",
            "requirements": [
                "5+ years Python experience",
                "Strong knowledge of FastAPI or Django",
                "PostgreSQL/database design",
                "API design and microservices"
            ],
            "responsibilities": [
                "Design and implement backend services",
                "Optimize database queries",
                "Mentor junior engineers"
            ],
            "benefits": [
                "Health insurance",
                "401k matching",
                "Remote work flexibility",
                "Learning budget"
            ],
            "salary_details": "$150,000 - $180,000 base + equity",
            "employment_type": "full_time",
            "remote_policy": "hybrid",
            "tech_stack": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS"],
            "scraped_at": "2026-02-01T10:05:00Z",
            "scraper_version": "1.0.0"
        }
    }}


class JobScoringOutput(BaseModel):
    """AI scoring result for a job"""
    job_id: str
    match_score: float = Field(..., ge=0.0, le=1.0, description="Match score from 0 to 1")
    reasoning: str = Field(..., min_length=1, max_length=5000)
    key_matches: List[str] = Field(..., max_items=50)
    concerns: List[str] = Field(..., max_items=50)
    recommendation: MatchRecommendation
    
    # Detailed breakdowns
    skills_match_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    experience_match_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    culture_match_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    
    scored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SubmitEnrichedJobOutput(BaseModel):
    """Output from submit_enriched_job action"""
    saga_id: str
    job_id: str
    scoring: JobScoringOutput
    status: str = "completed"
    
    model_config = {"json_schema_extra": {
        "example": {
            "saga_id": "saga_abc123",
            "job_id": "job_001",
            "scoring": {
                "job_id": "job_001",
                "match_score": 0.85,
                "reasoning": "Strong technical match with required skills...",
                "key_matches": [
                    "5+ years Python experience",
                    "FastAPI knowledge",
                    "PostgreSQL expertise"
                ],
                "concerns": [
                    "No AWS experience mentioned"
                ],
                "recommendation": "strong_fit",
                "skills_match_score": 0.9,
                "experience_match_score": 0.8,
                "culture_match_score": 0.85,
                "scored_at": "2026-02-01T10:10:00Z"
            },
            "status": "completed"
        }
    }}


# ============================================================================
# HELPER MODELS
# ============================================================================

class JobSearchSagaStatus(BaseModel):
    """Status query for job search saga"""
    saga_id: str
    state: str  # JobSearchState enum value
    discovered_jobs_count: int
    selected_job_id: Optional[str] = None
    has_scoring_result: bool
    created_at: datetime
    updated_at: datetime
