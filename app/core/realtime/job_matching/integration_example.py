"""
Job Search Saga Integration Example

Shows how to wire the JobSearchOrchestrator with the existing saga infrastructure.
"""

import asyncio
from typing import Dict, Any
from app.core.realtime.job_matching.job_orchestrator import (
    JobSearchOrchestrator,
    JobSearchState,
)
from app.core.realtime.job_matching.job_search_actions import (
    InitiateJobSearchInput,
    SelectJobInput,
    SubmitEnrichedJobInput,
)


# ============================================================================
# EXAMPLE 1: Start a Job Search Saga
# ============================================================================

async def example_start_job_search():
    """Example: Initiate a new job search with hybrid parsing."""
    
    # Initialize orchestrator
    orchestrator = JobSearchOrchestrator(
        db_connection_string=None,  # Optional: provide PostgreSQL connection
        job_board_adapter=None,     # Optional: provide job board API client
        llm_client=None,            # Optional: provide LLM client
        saga_update_handler=None,   # Optional: provide WebSocket update handler
    )
    
    # Prepare search parameters
    search_input = InitiateJobSearchInput(
        query="Senior Python Engineer",
        location="San Francisco, CA",
        employment_types=["full_time"],
        remote_policy="hybrid",
        min_salary=120000,
        max_salary=180000,
        sources=["linkedin", "indeed"],
        max_results=20,
        user_id="user_123",
        user_skills=["Python", "FastAPI", "PostgreSQL", "Docker"],
        user_experience_years=5,
    )
    
    # Start saga
    saga_id = await orchestrator.start_job_search_saga(
        user_id=search_input.user_id,
        search_params=search_input.dict(),
    )
    
    print(f"✅ Job search saga started: {saga_id}")
    
    # The orchestrator will:
    # 1. Fetch basic job metadata (title, company, link)
    # 2. Send job list to client via saga_update_handler
    # 3. Pause and wait for client to select a job
    
    return saga_id


# ============================================================================
# EXAMPLE 2: Client Workflow (Simulated)
# ============================================================================

async def example_client_workflow(saga_id: str):
    """
    Example: Client-side workflow after receiving job list.
    
    In production, this would happen in the browser:
    1. User views job list
    2. User clicks on a job
    3. Browser extension scrapes full content
    4. Client sends enriched data back to server
    """
    
    # Step 1: User selects a job (from the list sent by server)
    selected_job_id = "job_001"
    print(f"👤 User selected job: {selected_job_id}")
    
    # Step 2: Browser extension scrapes full content
    print("🌐 Browser extension scraping full job content...")
    
    # Simulated scraped content
    enriched_data = {
        "full_description": """
        We are seeking a Senior Python Engineer to join our backend team.
        
        About the Role:
        You'll be responsible for designing and implementing scalable backend services,
        optimizing database performance, and mentoring junior engineers.
        
        Requirements:
        - 5+ years of Python development experience
        - Strong knowledge of FastAPI or Django
        - Expertise in PostgreSQL and database design
        - Experience with API design and microservices architecture
        - Familiarity with Docker and containerization
        
        Nice to Have:
        - AWS or GCP cloud experience
        - Redis caching
        - Event-driven architectures
        
        Benefits:
        - Competitive salary ($150k-$180k) + equity
        - Health, dental, vision insurance
        - 401k with company match
        - Flexible remote work policy (hybrid)
        - $2,000 annual learning budget
        """,
        "requirements": [
            "5+ years Python experience",
            "Strong knowledge of FastAPI or Django",
            "PostgreSQL/database design expertise",
            "API design and microservices",
            "Docker experience",
        ],
        "responsibilities": [
            "Design and implement backend services",
            "Optimize database queries and performance",
            "Mentor junior engineers",
            "Participate in code reviews",
            "Collaborate with frontend team",
        ],
        "benefits": [
            "Health insurance",
            "401k matching",
            "Remote work flexibility",
            "$2,000 learning budget",
            "Equity/stock options",
        ],
        "salary_details": "$150,000 - $180,000 base + equity",
        "employment_type": "full_time",
        "remote_policy": "hybrid",
        "tech_stack": ["Python", "FastAPI", "PostgreSQL", "Docker", "AWS", "Redis"],
    }
    
    print("✅ Content scraped successfully")
    
    return selected_job_id, enriched_data


# ============================================================================
# EXAMPLE 3: Resume Saga with Enriched Data
# ============================================================================

async def example_resume_saga_with_enriched_data(
    orchestrator: JobSearchOrchestrator,
    saga_id: str,
    job_id: str,
    enriched_data: Dict[str, Any],
):
    """Example: Resume saga after client provides enriched job data."""
    
    # Client sends enriched data back to server
    result = await orchestrator.resume_with_enriched_job(
        saga_id=saga_id,
        job_id=job_id,
        enriched_data=enriched_data,
    )
    
    if result["status"] == "success":
        print(f"✅ Saga resumed successfully")
        
        # The orchestrator will now:
        # 1. Perform LLM-based analysis on the enriched data
        # 2. Generate match score and recommendations
        # 3. Send final results to client via saga_update_handler
        
        # Wait a moment for async scoring to complete
        await asyncio.sleep(0.5)
        
        # Retrieve scoring results
        scoring_result = orchestrator.get_scoring_result(saga_id)
        if scoring_result:
            print(f"\n🤖 AI Scoring Results:")
            print(f"   Match Score: {scoring_result['match_score']:.2f}")
            print(f"   Recommendation: {scoring_result['recommendation']}")
            print(f"   Key Matches: {', '.join(scoring_result['key_matches'][:3])}")
            print(f"   Concerns: {', '.join(scoring_result['concerns']) if scoring_result['concerns'] else 'None'}")
        
        return scoring_result
    else:
        print(f"❌ Failed to resume saga: {result.get('error')}")
        return None


# ============================================================================
# EXAMPLE 4: Full End-to-End Workflow
# ============================================================================

async def example_full_workflow():
    """Complete end-to-end example of hybrid parsing job search."""
    
    print("=" * 70)
    print("Job Search Saga - Hybrid Parsing Strategy")
    print("=" * 70)
    
    # Step 1: Initialize orchestrator
    print("\n[STEP 1: INITIALIZATION]")
    orchestrator = JobSearchOrchestrator()
    
    # Step 2: Start job search saga (discovery phase)
    print("\n[STEP 2: DISCOVERY PHASE]")
    saga_id = await example_start_job_search()
    
    # Check discovered jobs
    discovered_jobs = orchestrator.get_discovered_jobs(saga_id)
    if discovered_jobs:
        print(f"\n📋 Discovered {len(discovered_jobs)} jobs:")
        for job in discovered_jobs[:3]:  # Show first 3
            print(f"   - {job['title']} at {job['company']}")
            print(f"     Link: {job['link']}")
    
    # Step 3: Verify saga is waiting for client selection
    print("\n[STEP 3: AWAITING CLIENT SELECTION]")
    state = orchestrator.get_saga_state(saga_id)
    print(f"Saga State: {state}")
    assert state == JobSearchState.AWAITING_CLIENT_SELECTION.value
    
    # Step 4: Simulate client workflow (scraping)
    print("\n[STEP 4: CLIENT SCRAPING]")
    job_id, enriched_data = await example_client_workflow(saga_id)
    
    # Step 5: Resume saga with enriched data (AI scoring)
    print("\n[STEP 5: AI SCORING PHASE]")
    scoring_result = await example_resume_saga_with_enriched_data(
        orchestrator,
        saga_id,
        job_id,
        enriched_data,
    )
    
    # Step 6: Verify saga completed
    print("\n[STEP 6: COMPLETION]")
    final_state = orchestrator.get_saga_state(saga_id)
    print(f"Final Saga State: {final_state}")
    
    print("\n" + "=" * 70)
    print("✅ Hybrid parsing workflow completed successfully!")
    print("=" * 70)
    
    return saga_id, scoring_result


# ============================================================================
# EXAMPLE 5: Integration with WebSocket Updates
# ============================================================================

async def example_with_websocket_updates():
    """Example: Job search saga with real-time WebSocket updates."""
    
    # Mock WebSocket update handler
    async def websocket_update_handler(payload: Dict[str, Any]):
        """Send updates to client via WebSocket."""
        update_type = payload.get("type")
        saga_id = payload.get("saga_id")
        
        if update_type == "job_search.discovery_complete":
            jobs = payload["data"]["jobs"]
            print(f"📤 Sending {len(jobs)} jobs to client via WebSocket")
            # In production: await websocket.send_json(payload)
        
        elif update_type == "job_search.scoring_complete":
            scoring = payload["data"]["scoring"]
            print(f"📤 Sending scoring results to client via WebSocket")
            print(f"   Match Score: {scoring['match_score']}")
            # In production: await websocket.send_json(payload)
    
    # Initialize orchestrator with update handler
    orchestrator = JobSearchOrchestrator(
        saga_update_handler=websocket_update_handler,
    )
    
    # Run workflow
    search_input = InitiateJobSearchInput(
        query="Backend Engineer",
        location="Remote",
        user_id="user_456",
        user_skills=["Python", "Django", "PostgreSQL"],
    )
    
    saga_id = await orchestrator.start_job_search_saga(
        user_id=search_input.user_id,
        search_params=search_input.dict(),
    )
    
    print(f"\n✅ Saga {saga_id} started with WebSocket updates")
    
    return saga_id


# ============================================================================
# EXAMPLE 6: Integration with Action Router
# ============================================================================

async def example_action_router_integration():
    """
    Example: How to integrate JobSearchOrchestrator with ActionRouter.
    
    Add this to your ActionRouter or main.py:
    """
    
    # Pseudo-code for action router integration
    print("""
    # In app/main.py or app/realtime/action_router.py:
    
    from app.core.realtime.job_matching.job_orchestrator import JobSearchOrchestrator
    from app.core.realtime.job_matching.job_search_actions import (
        InitiateJobSearchInput,
        SubmitEnrichedJobInput,
    )
    
    # Initialize orchestrator (do this once at startup)
    job_search_orchestrator = JobSearchOrchestrator(
        db_connection_string=settings.DATABASE_URL,
        job_board_adapter=job_board_client,
        llm_client=llm_service,
        saga_update_handler=send_websocket_update,
    )
    
    # Add action handlers
    @router.post("/actions/job_search/initiate")
    async def initiate_job_search(input: InitiateJobSearchInput):
        saga_id = await job_search_orchestrator.start_job_search_saga(
            user_id=input.user_id,
            search_params=input.dict(),
        )
        return {"saga_id": saga_id, "status": "discovering"}
    
    @router.post("/actions/job_search/submit_enriched")
    async def submit_enriched_job(input: SubmitEnrichedJobInput):
        result = await job_search_orchestrator.resume_with_enriched_job(
            saga_id=input.saga_id,
            job_id=input.job_id,
            enriched_data={
                "full_description": input.full_description,
                "requirements": input.requirements,
                "responsibilities": input.responsibilities,
                "benefits": input.benefits,
                "tech_stack": input.tech_stack,
                # ... other fields
            },
        )
        return result
    
    @router.get("/sagas/job_search/{saga_id}")
    async def get_saga_status(saga_id: str):
        saga = job_search_orchestrator.get_saga(saga_id)
        if not saga:
            raise HTTPException(status_code=404, detail="Saga not found")
        
        return {
            "saga_id": saga["saga_id"],
            "state": saga["state"],
            "discovered_jobs": saga["discovered_jobs"],
            "scoring_result": saga["scoring_result"],
        }
    """)


# ============================================================================
# RUN EXAMPLES
# ============================================================================

if __name__ == "__main__":
    # Run full workflow example
    asyncio.run(example_full_workflow())
    
    # Uncomment to run WebSocket example:
    # asyncio.run(example_with_websocket_updates())
    
    # Uncomment to see action router integration:
    # asyncio.run(example_action_router_integration())

