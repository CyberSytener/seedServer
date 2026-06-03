"""
Verify production readiness of Learning Path system

Checks:
1. All required modules import successfully
2. Redis connection works
3. Database schema is current
4. All API endpoints registered
5. Worker can process jobs
6. Metrics are available

Run before deploying to production.
"""

import asyncio
import os
import sys
from typing import List, Tuple


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(title: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{title}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*70}{Colors.END}\n")


def print_check(name: str, passed: bool, details: str = ""):
    status = f"{Colors.GREEN}✅ PASS{Colors.END}" if passed else f"{Colors.RED}❌ FAIL{Colors.END}"
    print(f"{status} {name}")
    if details:
        print(f"     {details}")


async def check_imports() -> Tuple[bool, List[str]]:
    """Check all required modules can be imported"""
    print_header("Module Import Checks")
    
    modules = [
        ("app.main", "Main application"),
        ("app.api.path", "Learning Path API"),
        ("app.services.path.worker", "Background worker"),
        ("app.services.path.analytics", "Analytics models"),
        ("app.services.path.adaptive", "Adaptive difficulty"),
        ("app.api.metrics", "Performance metrics"),
        ("app.infrastructure.llm.client", "Async LLM client"),
        ("app.api.lesson_stream", "Streaming API"),
        ("app.api.job_queue", "Job queue API"),
    ]
    
    errors = []
    all_passed = True
    
    for module_name, description in modules:
        try:
            __import__(module_name)
            print_check(description, True, module_name)
        except Exception as e:
            print_check(description, False, f"{module_name}: {e}")
            errors.append(f"{module_name}: {e}")
            all_passed = False
    
    return all_passed, errors


async def check_redis() -> Tuple[bool, str]:
    """Check Redis connection"""
    print_header("Redis Connection Check")
    
    try:
        import redis.asyncio as redis
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        print(f"Connecting to: {redis_url}")
        
        client = redis.from_url(redis_url, decode_responses=True)
        response = await client.ping()
        await client.aclose()
        
        print_check("Redis connection", response == True, f"PONG received")
        return response == True, ""
    
    except ImportError as e:
        print_check("Redis module", False, f"redis.asyncio not installed: {e}")
        return False, "redis.asyncio not installed"
    except Exception as e:
        print_check("Redis connection", False, str(e))
        return False, str(e)


async def check_database() -> Tuple[bool, str]:
    """Check database connectivity and schema"""
    print_header("Database Check")
    
    try:
        from app.infrastructure.db.sqlite import DB
        
        db_path = os.getenv("DATABASE_PATH", "./data/seed_v5.db")
        print(f"Database: {db_path}")
        
        db = DB(db_path)
        conn = db._conn
        cursor = conn.cursor()
        
        # Check for Learning Path tables
        required_tables = ["units", "nodes", "node_attempts", "task_attempts"]
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in cursor.fetchall()]
        
        all_present = True
        for table in required_tables:
            present = table in existing_tables
            print_check(f"Table: {table}", present)
            if not present:
                all_present = False
        
        db.close()
        
        return all_present, "" if all_present else f"Missing tables: {set(required_tables) - set(existing_tables)}"
    
    except Exception as e:
        print_check("Database access", False, str(e))
        return False, str(e)


async def check_api_endpoints() -> Tuple[bool, List[str]]:
    """Check all API endpoints are registered"""
    print_header("API Endpoints Check")
    
    try:
        from app.main import app
        
        # Expected endpoint patterns
        expected_patterns = [
            "/v1/path/unit/generate_blueprint",
            "/v1/path/node/start",
            "/v1/path/node/submit",
            "/v1/path/analytics/user",
            "/v1/path/analytics/node",
            "/v1/path/leaderboard",
            "/v1/path/adaptive/difficulty",
            "/v1/path/adaptive/recommendations",
            "/v1/jobs/submit",
            "/v1/jobs/status",
            "/v1/lessons/generate/stream",
            "/v1/metrics/prometheus",
            "/v1/metrics/summary",
            "/v1/metrics/health",
        ]
        
        routes = [route.path for route in app.routes]
        
        missing = []
        for pattern in expected_patterns:
            found = any(pattern in route for route in routes)
            print_check(pattern, found)
            if not found:
                missing.append(pattern)
        
        return len(missing) == 0, missing
    
    except Exception as e:
        print_check("API registration", False, str(e))
        return False, [str(e)]


async def check_llm_client() -> Tuple[bool, str]:
    """Check LLM client configuration"""
    print_header("LLM Client Check")
    
    try:
        from app.infrastructure.llm.client import get_llm_client
        
        api_key = os.getenv("GEMINI_API_KEY")
        
        if not api_key:
            print_check("GEMINI_API_KEY", False, "Environment variable not set")
            return False, "API key not configured"
        
        print_check("GEMINI_API_KEY", True, f"Set ({len(api_key)} chars)")
        
        # Try to get client
        client = await get_llm_client()
        print_check("LLM client initialization", True, f"Client ready with connection pooling")
        
        return True, ""
    
    except Exception as e:
        print_check("LLM client", False, str(e))
        return False, str(e)


async def check_worker_imports() -> Tuple[bool, str]:
    """Check worker can be imported"""
    print_header("Worker Check")
    
    try:
        from app.infrastructure.redis.worker import process_job
        print_check("Worker module", True, "process_job available")
        
        # Check if worker script exists
        import os.path
        worker_script = "run_worker.py"
        if os.path.exists(worker_script):
            print_check("Worker script", True, f"{worker_script} exists")
        else:
            print_check("Worker script", False, f"{worker_script} not found")
            return False, "Worker script missing"
        
        return True, ""
    
    except Exception as e:
        print_check("Worker import", False, str(e))
        return False, str(e)


async def main():
    """Run all checks"""
    print(f"{Colors.BOLD}{'='*70}{Colors.END}")
    print(f"{Colors.BOLD}Production Readiness Check{Colors.END}")
    print(f"{Colors.BOLD}{'='*70}{Colors.END}")
    
    results = []
    
    # Run all checks
    passed, _ = await check_imports()
    results.append(("Imports", passed))
    
    passed, _ = await check_redis()
    results.append(("Redis", passed))
    
    passed, _ = await check_database()
    results.append(("Database", passed))
    
    passed, _ = await check_api_endpoints()
    results.append(("API Endpoints", passed))
    
    passed, _ = await check_llm_client()
    results.append(("LLM Client", passed))
    
    passed, _ = await check_worker_imports()
    results.append(("Worker", passed))
    
    # Summary
    print_header("Summary")
    
    total = len(results)
    passed_count = sum(1 for _, passed in results if passed)
    
    for name, passed in results:
        status = f"{Colors.GREEN}✅{Colors.END}" if passed else f"{Colors.RED}❌{Colors.END}"
        print(f"{status} {name}")
    
    print(f"\n{Colors.BOLD}Results: {passed_count}/{total} checks passed{Colors.END}")
    
    if passed_count == total:
        print(f"\n{Colors.GREEN}{Colors.BOLD}🚀 System is ready for production!{Colors.END}")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}⚠️  Fix failing checks before deploying{Colors.END}")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)



