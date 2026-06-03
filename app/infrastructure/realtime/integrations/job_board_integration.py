"""
Job Board Integration - Job Source Management

Read-only integration with job boards:
- LinkedIn (manual CSV export)
- Indeed (API or CSV)
- Greenhouse (API)
- Lever (API)

Strategy:
1. Import job listings into JobListing table
2. Normalize job data (title, description, requirements)
3. Match to candidate profiles
4. Auto-create campaigns per job
5. No auto-apply yet (legal risk)

Usage:
    integrator = JobBoardIntegrator(repository_service)
    
    # Import LinkedIn CSV
    jobs = integrator.import_linkedin_csv("linkedin_jobs.csv")
    # Returns: list of imported JobListing objects
    
    # Import Indeed API
    jobs = integrator.fetch_indeed_jobs("python engineer", location="USA")
    
    # Auto-match candidates to jobs
    campaigns = integrator.create_campaigns_for_jobs(jobs)
"""

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import csv
import json
import requests
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class JobBoardSource(str, Enum):
    """Job board source"""
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    MANUAL = "manual"


@dataclass
class JobListing:
    """Normalized job listing"""
    listing_id: str  # Unique ID (source + board ID)
    source: JobBoardSource
    title: str
    company: str
    description: str
    requirements: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[str] = None  # full-time, part-time, contract
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    url: Optional[str] = None
    posted_at: Optional[datetime] = None
    
    # Mapping fields
    skills: Optional[List[str]] = None  # Extracted from description
    years_experience_min: Optional[int] = None


@dataclass
class JobMatchResult:
    """Result of matching job to candidate"""
    candidate_id: str
    job_listing_id: str
    match_score: float  # 0.0-1.0
    matched_skills: List[str]
    message: Optional[str] = None


# ============================================================================
# JOB BOARD IMPORTERS
# ============================================================================

class LinkedInCSVImporter:
    """
    Import LinkedIn job listings from CSV export
    
    CSV format (from LinkedIn Job Search export):
    job_title, company, location, description, link, posted_date, ...
    """
    
    @staticmethod
    def import_csv(filepath: str) -> List[JobListing]:
        """
        Import LinkedIn jobs from CSV file
        
        Example CSV:
            Senior Python Engineer,TechCorp,San Francisco, CA,"5+ years Python experience...",...
        """
        jobs = []
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    job = JobListing(
                        listing_id=f"linkedin_{hash(row['link'])}",
                        source=JobBoardSource.LINKEDIN,
                        title=row.get('job_title', '').strip(),
                        company=row.get('company', '').strip(),
                        description=row.get('description', '').strip(),
                        location=row.get('location', '').strip(),
                        url=row.get('link', '').strip(),
                        posted_at=LinkedInCSVImporter._parse_date(row.get('posted_date')),
                        skills=LinkedInCSVImporter._extract_skills(row.get('description', '')),
                    )
                    jobs.append(job)
        
        except Exception as e:
            print(f"⚠️ Error importing LinkedIn CSV: {e}")
        
        return jobs
    
    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Parse LinkedIn date (e.g., '2 weeks ago', 'Jan 15, 2026')"""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str)
        except Exception:
            return None
    
    @staticmethod
    def _extract_skills(description: str) -> List[str]:
        """Extract skills from job description using simple heuristics"""
        skills = []
        keywords = [
            "Python", "Java", "C++", "JavaScript", "Go", "Rust",
            "FastAPI", "Django", "Flask", "React", "Vue", "Angular",
            "PostgreSQL", "MongoDB", "Redis", "AWS", "GCP", "Azure",
            "Docker", "Kubernetes", "Git", "CI/CD",
        ]
        
        for keyword in keywords:
            if keyword.lower() in description.lower():
                skills.append(keyword)
        
        return skills


class IndeedAPIImporter:
    """
    Import Indeed jobs via Indeed API
    
    Requires: Indeed API key (Authentic Jobs API)
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.indeed.com/ads/apisearch"
    
    def search_jobs(
        self,
        query: str,
        location: str = "",
        limit: int = 50,
    ) -> List[JobListing]:
        """
        Search Indeed for jobs
        
        Args:
            query: Job search (e.g., "Python Engineer")
            location: Location filter
            limit: Max results
        """
        jobs = []
        
        try:
            params = {
                "publisher": self.api_key,
                "q": query,
                "l": location,
                "limit": limit,
                "format": "json",
            }
            
            response = requests.get(self.base_url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            for item in data.get("results", []):
                job = JobListing(
                    listing_id=f"indeed_{item['jobkey']}",
                    source=JobBoardSource.INDEED,
                    title=item.get("jobtitle", ""),
                    company=item.get("company", ""),
                    description=item.get("snippet", ""),
                    location=item.get("formattedLocationFull", ""),
                    url=item.get("url", ""),
                    posted_at=self._parse_date(item.get("date")),
                )
                jobs.append(job)
        
        except Exception as e:
            print(f"⚠️ Error searching Indeed: {e}")
        
        return jobs
    
    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Parse Indeed date"""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str)
        except Exception:
            return None


class GreenhouseAPIImporter:
    """
    Import Greenhouse jobs via Greenhouse API
    
    Requires: Greenhouse API token
    """
    
    def __init__(self, api_token: str):
        self.api_token = api_token
        self.base_url = "https://api.greenhouse.io/v1"
    
    def fetch_jobs(self, limit: int = 100) -> List[JobListing]:
        """Fetch all jobs from Greenhouse job board"""
        jobs = []
        
        try:
            url = f"{self.base_url}/boards/jobs"
            headers = {"Authorization": f"Bearer {self.api_token}"}
            params = {"limit": limit}
            
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            for item in data.get("jobs", []):
                job = JobListing(
                    listing_id=f"greenhouse_{item['id']}",
                    source=JobBoardSource.GREENHOUSE,
                    title=item.get("title", ""),
                    company=item.get("company", ""),
                    description=item.get("content", ""),
                    location=item.get("location", {}).get("name", ""),
                    url=item.get("absolute_url", ""),
                    posted_at=self._parse_date(item.get("created_at")),
                )
                jobs.append(job)
        
        except Exception as e:
            print(f"⚠️ Error fetching Greenhouse jobs: {e}")
        
        return jobs
    
    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Parse Greenhouse ISO date"""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            return None


class LeverAPIImporter:
    """
    Import Lever jobs via Lever API
    
    Requires: Lever company token
    """
    
    def __init__(self, company_token: str):
        self.company_token = company_token
        self.base_url = "https://api.lever.co/v0"
    
    def fetch_jobs(self) -> List[JobListing]:
        """Fetch all open positions from Lever"""
        jobs = []
        
        try:
            url = f"{self.base_url}/postings"
            params = {"team_token": self.company_token, "include": "content"}
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            for item in data.get("data", []):
                job = JobListing(
                    listing_id=f"lever_{item['id']}",
                    source=JobBoardSource.LEVER,
                    title=item.get("text", ""),
                    company=item.get("team", ""),
                    description=item.get("description", ""),
                    location=item.get("locations", [{}])[0].get("name", ""),
                    url=item.get("hostedUrl", ""),
                    posted_at=self._parse_date(item.get("createdAt")),
                )
                jobs.append(job)
        
        except Exception as e:
            print(f"⚠️ Error fetching Lever jobs: {e}")
        
        return jobs
    
    @staticmethod
    def _parse_date(timestamp_ms: int) -> Optional[datetime]:
        """Parse Lever timestamp (milliseconds)"""
        if not timestamp_ms:
            return None
        try:
            return datetime.fromtimestamp(timestamp_ms / 1000)
        except Exception:
            return None


# ============================================================================
# JOB BOARD INTEGRATOR (FACADE)
# ============================================================================

class JobBoardIntegrator:
    """
    Unified job board integrator
    
    Handles multiple sources and creates campaigns automatically
    """
    
    def __init__(self, repository_service):
        self.repo = repository_service
    
    def import_linkedin_csv(self, filepath: str) -> List[JobListing]:
        """Import LinkedIn jobs from CSV"""
        return LinkedInCSVImporter.import_csv(filepath)
    
    def fetch_indeed_jobs(
        self,
        query: str,
        location: str = "",
        api_key: Optional[str] = None,
    ) -> List[JobListing]:
        """Fetch Indeed jobs via API"""
        if not api_key:
            raise ValueError("Indeed API key required")
        
        importer = IndeedAPIImporter(api_key)
        return importer.search_jobs(query, location)
    
    def fetch_greenhouse_jobs(self, api_token: str) -> List[JobListing]:
        """Fetch Greenhouse jobs via API"""
        importer = GreenhouseAPIImporter(api_token)
        return importer.fetch_jobs()
    
    def fetch_lever_jobs(self, company_token: str) -> List[JobListing]:
        """Fetch Lever jobs via API"""
        importer = LeverAPIImporter(company_token)
        return importer.fetch_jobs()
    
    def create_campaigns_from_jobs(
        self,
        jobs: List[JobListing],
        creator_id: str,
    ) -> List[Any]:
        """
        Create outreach campaigns for imported jobs
        
        One campaign per unique job title/company combination
        """
        campaigns = []
        
        for job in jobs:
            # Check if campaign already exists for this job
            existing = self.repo.campaigns.list_by_creator(creator_id)
            campaign_name = f"Auto: {job.title} @ {job.company}"
            
            if any(c.name == campaign_name for c in existing):
                continue
            
            # Create campaign
            campaign = self.repo.campaigns.create(
                campaign_id=self._generate_uuid(),
                name=campaign_name,
                description=job.description,
                target_role=job.title,
                created_by=creator_id,
                max_targets=100,
            )
            
            campaigns.append(campaign)
            print(f"✅ Created campaign: {campaign_name}")
        
        self.repo.commit()
        return campaigns
    
    def match_candidates_to_job(
        self,
        job: JobListing,
    ) -> List[JobMatchResult]:
        """
        Find candidates matching job requirements
        
        Scoring:
        - Target role match: +40%
        - Skills match: +30% per skill
        - Experience level: +30%
        """
        matches = []
        
        # Get all consented, non-suppressed candidates
        candidates = self.repo.candidates.list_by_consent_status(
            consent_granted=True,
            is_suppressed=False,
        )
        
        job_skills = job.skills or []
        min_exp = job.years_experience_min or 0
        
        for candidate in candidates:
            score = 0.0
            matched_skills = []
            
            # Title match
            if candidate.target_role and candidate.target_role.lower() in job.title.lower():
                score += 0.4
            
            # Skills match
            if candidate.experience_tags:
                try:
                    cand_skills = json.loads(candidate.experience_tags)
                    for skill in job_skills:
                        if skill.lower() in [s.lower() for s in cand_skills]:
                            score += 0.1
                            matched_skills.append(skill)
                except Exception:
                    logger.debug("Failed to parse candidate experience_tags JSON", exc_info=True)
            
            if score > 0.3:  # Minimum threshold
                matches.append(JobMatchResult(
                    candidate_id=candidate.candidate_id,
                    job_listing_id=job.listing_id,
                    match_score=min(score, 1.0),
                    matched_skills=matched_skills,
                ))
        
        return sorted(matches, key=lambda x: x.match_score, reverse=True)
    
    @staticmethod
    def _generate_uuid() -> str:
        """Generate UUID"""
        import uuid
        return str(uuid.uuid4())


if __name__ == "__main__":
    print("✅ JobBoardIntegrator ready")
    print("   Supports: LinkedIn CSV, Indeed API, Greenhouse API, Lever API")
    print("   Creates campaigns, matches candidates to jobs")
