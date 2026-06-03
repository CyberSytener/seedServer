#!/usr/bin/env python3
"""
Consolidated Diagnostics Script for Seed Server v5

Combines all check_*.py functions into unified subcommand system:
  python diagnostics.py [COMMAND] [OPTIONS]

Commands:
  all              Run all diagnostics (default)
  imports          Check module imports
  production       Check production readiness
  schema           Verify database schema
  analytics        Check analytics system
  bug-reports      Check bug reports table
  profiles         Check learning profiles
  diagnostic       Check diagnostic data
  learning-paths   Check learning paths
  desktop          Check desktop compatibility
  database         Check database health

Examples:
  python diagnostics.py all                 # Full health check
  python diagnostics.py production          # Production readiness
  python diagnostics.py imports --verbose   # Import check with details
"""

import asyncio
import json
import os
import sys
import sqlite3
import time
from pathlib import Path
from typing import List, Tuple, Dict, Any
from datetime import datetime
import argparse
import traceback

# Add parent directory to path so we can import app module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Colors:
    """ANSI color codes"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def print_header(title: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.CYAN}{title.center(60)}{Colors.ENDC}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.ENDC}\n")


def print_check(name: str, passed: bool, details: str = ""):
    status = f"{Colors.GREEN}✅{Colors.ENDC}" if passed else f"{Colors.RED}❌{Colors.ENDC}"
    details_str = f" {Colors.YELLOW}({details}){Colors.ENDC}" if details else ""
    print(f"{status} {name}{details_str}")


def print_section(title: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}» {title}{Colors.ENDC}")


# =====================================================================
# IMPORTS CHECK
# =====================================================================

async def check_imports(verbose: bool = False) -> Tuple[bool, List[str]]:
    """Check all required modules can be imported"""
    print_header("Module Import Checks")
    
    modules = [
        # Core
        ("app.main", "Main application"),
        ("app.models", "Data models"),
        ("app.infrastructure.db.sqlite", "Database layer"),
        ("app.settings", "Configuration"),
        
        # Learning
        ("app.services.diagnostic.session", "Diagnostic engine"),
        ("app.services.diagnostic.engine", "Item generation"),
        ("app.services.learning_plan", "Learning profiles"),
        ("app.api.path", "Learning paths API"),
        ("app.services.path.worker", "Path background worker"),
        ("app.services.path.analytics", "Path analytics"),
        ("app.services.path.adaptive", "Adaptive difficulty"),
        
        # Content
        ("app.infrastructure.llm.client", "Async LLM client"),
        ("app.services.lesson.engine", "Lesson generator"),
        ("app.api.lesson_stream", "Streaming API"),
        ("app.core.personas", "Persona system"),
        ("app.services.prompt_testing", "Prompt testing"),
        
        # Infrastructure
        ("app.infrastructure.redis.queue", "Redis queue"),
        ("app.infrastructure.scheduler", "Job scheduler"),
        ("app.infrastructure.redis.worker", "Redis worker"),
        ("app.infrastructure.metrics", "Prometheus metrics"),
        ("app.infrastructure.monitoring.alerting", "Alert system"),
        ("app.infrastructure.monitoring.slo_monitor", "SLO monitoring"),
        
        # Security
        ("app.core.auth", "Authentication"),
        ("app.key_management", "API key management"),
        ("app.core.rate_limit", "Rate limiting"),
        ("app.core.feature_flags", "Feature flags"),
        
        # Utils
        ("app.core.util", "Utilities"),
        ("app.core.compat", "Backward compatibility"),
        ("app.api.sse", "Server-sent events"),
    ]
    
    errors = []
    all_passed = True
    
    for module_name, description in modules:
        try:
            __import__(module_name)
            print_check(description, True, module_name if verbose else "")
        except Exception as e:
            print_check(description, False, str(e)[:80])
            errors.append(f"{module_name}: {e}")
            all_passed = False
    
    return all_passed, errors


# =====================================================================
# DATABASE CHECK
# =====================================================================

def check_database_schema() -> Tuple[bool, str]:
    """Verify database schema and tables"""
    print_section("Database Schema")
    
    try:
        db_path = os.environ.get("SEED_DB_PATH", "./seed.db")
        
        if not os.path.exists(db_path):
            print_check("Database file exists", False, "No seed.db found")
            return False, "Database not initialized"
        
        print_check("Database file exists", True, f"{db_path}")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        
        tables = [row[0] for row in cursor.fetchall()]
        
        required_tables = [
            'users', 'plans', 'diagnostic_sessions',
            'diagnostic_session_items', 'diagnostic_attempts',
            'learning_profiles', 'units', 'nodes',
            'node_attempts', 'bug_reports', 'lessons'
        ]
        
        missing = [t for t in required_tables if t not in tables]
        
        if missing:
            print_check(
                f"Required tables ({len(required_tables)})",
                False,
                f"Missing: {', '.join(missing)}"
            )
            return False, f"Missing tables: {missing}"
        else:
            print_check(f"Required tables ({len(required_tables)})", True)
        
        print(f"  {Colors.YELLOW}Found {len(tables)} total tables{Colors.ENDC}")
        
        # Check schema version
        try:
            cursor.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]
            print_check(f"Journal mode", True, mode)
        except:
            pass
        
        conn.close()
        return True, "Database schema valid"
        
    except Exception as e:
        print_check("Database check", False, str(e))
        return False, str(e)


def check_database_health() -> Tuple[bool, str]:
    """Check database connectivity and integrity"""
    print_section("Database Health")
    
    try:
        db_path = os.environ.get("SEED_DB_PATH", "./seed.db")
        
        start = time.time()
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Test query
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        elapsed = time.time() - start
        
        print_check("Database connection", True, f"{elapsed*1000:.2f}ms")
        print_check(f"User records", True, f"{user_count} users")
        
        # Check write access
        try:
            cursor.execute("INSERT INTO system_state(key, value_json) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET updated_at=datetime('now')", 
                          ('_health_check', '{}'))
            conn.commit()
            print_check("Write access", True)
        except Exception as e:
            print_check("Write access", False, str(e)[:50])
        
        conn.close()
        return True, "Database healthy"
        
    except Exception as e:
        print_check("Database health check", False, str(e))
        return False, str(e)


# =====================================================================
# REDIS CHECK
# =====================================================================

async def check_redis() -> Tuple[bool, str]:
    """Check Redis connection"""
    print_section("Redis Connection")
    
    try:
        import redis
        
        redis_url = os.environ.get("SEED_REDIS_URL", "redis://localhost:6379/0")
        
        try:
            r = redis.Redis.from_url(redis_url, decode_responses=True)
            
            start = time.time()
            r.ping()
            elapsed = time.time() - start
            
            print_check("Redis connection", True, f"{elapsed*1000:.2f}ms")
            
            # Get info
            info = r.info()
            print_check("Redis version", True, info.get("redis_version", "unknown"))
            
            # Check queues
            namespace = os.environ.get("SEED_REDIS_NAMESPACE", "seed")
            queues = [f"{namespace}:q_fast", f"{namespace}:q_batch", f"{namespace}:q_low"]
            queue_sizes = {}
            
            for q in queues:
                size = r.llen(q)
                queue_sizes[q] = size
            
            print(f"  {Colors.YELLOW}Job queues:{Colors.ENDC}")
            for q, size in queue_sizes.items():
                status = Colors.GREEN if size < 1000 else Colors.YELLOW if size < 5000 else Colors.RED
                print(f"    {status}{q}: {size} jobs{Colors.ENDC}")
            
            return True, "Redis connected"
            
        except Exception as e:
            print_check("Redis connection", False, str(e)[:100])
            return False, f"Redis connection failed: {e}"
            
    except ImportError:
        print_check("Redis module", False, "redis package not installed")
        return False, "redis module not available"


# =====================================================================
# API ENDPOINTS CHECK
# =====================================================================

async def check_api_endpoints() -> Tuple[bool, List[str]]:
    """Check all API endpoints are registered"""
    print_section("API Endpoints")
    
    try:
        from app.main import create_app
        
        app = create_app()
        
        # Get all routes
        routes = []
        for route in app.routes:
            if hasattr(route, 'path'):
                routes.append({
                    'path': route.path,
                    'methods': list(getattr(route, 'methods', ['GET'])),
                })
        
        # Group by category
        categories = {
            'diagnostic': [r for r in routes if '/diagnostic/' in r['path']],
            'learning_path': [r for r in routes if '/path/' in r['path']],
            'profiles': [r for r in routes if '/profiles/' in r['path']],
            'lessons': [r for r in routes if '/lessons/' in r['path']],
            'admin': [r for r in routes if '/admin/' in r['path']],
            'jobs': [r for r in routes if '/jobs/' in r['path']],
        }
        
        total = len(routes)
        print_check(f"Total endpoints", True, f"{total} routes")
        
        for cat, endpoints in categories.items():
            count = len(endpoints)
            if count > 0:
                print_check(f"  {cat}", True, f"{count} endpoints")
        
        return True, []
        
    except Exception as e:
        print_check("API endpoints check", False, str(e)[:100])
        return False, [str(e)]


# =====================================================================
# FEATURES CHECK
# =====================================================================

def check_analytics_system() -> Tuple[bool, str]:
    """Check learning path analytics"""
    print_section("Learning Path Analytics")
    
    try:
        from app.services.path.analytics import UserLearningAnalytics, NodeAttemptSubmit
        from app.services.path.adaptive import calculate_mastery_score
        
        print_check("Analytics models", True, "imported")
        print_check("Mastery calculation", True, "available")
        
        return True, "Analytics system operational"
        
    except Exception as e:
        print_check("Analytics system", False, str(e))
        return False, str(e)


def check_bug_reports() -> Tuple[bool, str]:
    """Check bug reports system"""
    print_section("Bug Reports System")
    
    try:
        db_path = os.environ.get("SEED_DB_PATH", "./seed.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='bug_reports'
        """)
        
        has_table = cursor.fetchone() is not None
        
        if has_table:
            cursor.execute("SELECT COUNT(*) FROM bug_reports")
            count = cursor.fetchone()[0]
            print_check("Bug reports table", True, f"{count} reports")
        else:
            print_check("Bug reports table", False, "Table not found")
        
        conn.close()
        
        return has_table, "Bug reports operational" if has_table else "Table missing"
        
    except Exception as e:
        print_check("Bug reports check", False, str(e))
        return False, str(e)


def check_diagnostic_data() -> Tuple[bool, str]:
    """Check diagnostic system data"""
    print_section("Diagnostic System")
    
    try:
        # Check taxonomy
        taxonomy_path = Path("data/cefr_taxonomy.json")
        
        if not taxonomy_path.exists():
            print_check("Taxonomy file", False, "Not found")
            return False, "Taxonomy missing"
        
        with open(taxonomy_path, 'r', encoding='utf-8') as f:
            taxonomy = json.load(f)
        
        levels_count = len(taxonomy.get('levels', {}))
        print_check("Taxonomy file", True, f"{levels_count} CEFR levels")
        
        # Check database
        db_path = os.environ.get("SEED_DB_PATH", "./seed.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM diagnostic_sessions")
        sessions = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM diagnostic_attempts")
        attempts = cursor.fetchone()[0]
        
        print_check(f"Diagnostic sessions", True, f"{sessions} sessions")
        print_check(f"Diagnostic attempts", True, f"{attempts} attempts")
        
        conn.close()
        
        return True, "Diagnostic system operational"
        
    except Exception as e:
        print_check("Diagnostic check", False, str(e))
        return False, str(e)


def check_learning_paths() -> Tuple[bool, str]:
    """Check learning paths functionality"""
    print_section("Learning Paths")
    
    try:
        from app.api.path import router
        
        print_check("Path API router", True, f"prefix: {router.prefix}")
        
        db_path = os.environ.get("SEED_DB_PATH", "./seed.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM units")
        units = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM nodes")
        nodes = cursor.fetchone()[0]
        
        print_check(f"Learning units", True, f"{units} units")
        print_check(f"Learning nodes", True, f"{nodes} nodes")
        
        conn.close()
        
        return True, "Learning paths operational"
        
    except Exception as e:
        print_check("Learning paths check", False, str(e))
        return False, str(e)


async def check_llm_client() -> Tuple[bool, str]:
    """Check LLM client configuration"""
    print_section("LLM Client")
    
    try:
        from app.infrastructure.llm.client import get_llm_client
        
        # Check if keys are configured
        openai_key = os.environ.get("OPENAI_API_KEY")
        gemini_key = os.environ.get("GEMINI_API_KEY")
        
        if not openai_key and not gemini_key:
            print_check("LLM API keys", False, "No keys configured")
            return False, "Missing LLM API keys"
        
        provider = os.environ.get("SEED_PROVIDER", "gemini")
        print_check("LLM Provider", True, provider)
        
        if openai_key:
            print_check("  OpenAI key", True, openai_key[:20] + "...")
        
        if gemini_key:
            print_check("  Gemini key", True, gemini_key[:20] + "...")
        
        return True, "LLM client configured"
        
    except Exception as e:
        print_check("LLM client check", False, str(e))
        return False, str(e)


# =====================================================================
# COMPREHENSIVE CHECKS
# =====================================================================

async def run_production_ready_check() -> Tuple[bool, Dict[str, Any]]:
    """Full production readiness check"""
    print_header("PRODUCTION READINESS CHECK")
    
    results = {}
    
    # Run all checks
    print_section("Core Systems")
    results['imports'], import_errors = await check_imports()
    results['redis'], redis_msg = await check_redis()
    results['database_schema'], db_schema_msg = check_database_schema()
    results['database_health'], db_health_msg = check_database_health()
    results['api_endpoints'], api_errors = await check_api_endpoints()
    results['llm_client'], llm_msg = await check_llm_client()
    
    print_section("Features")
    results['analytics'], analytics_msg = check_analytics_system()
    results['bug_reports'], bug_msg = check_bug_reports()
    results['diagnostic'], diag_msg = check_diagnostic_data()
    results['learning_paths'], path_msg = check_learning_paths()
    
    # Summary
    print_header("SUMMARY")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print(f"{Colors.BOLD}Status: ", end="")
    if passed == total:
        print(f"{Colors.GREEN}✅ ALL CHECKS PASSED{Colors.ENDC}\n")
        status = True
    elif passed >= total * 0.8:
        print(f"{Colors.YELLOW}⚠️  MOSTLY READY ({passed}/{total} checks){Colors.ENDC}\n")
        status = True
    else:
        print(f"{Colors.RED}❌ FAILURES DETECTED ({passed}/{total} checks){Colors.ENDC}\n")
        status = False
    
    return status, results


# =====================================================================
# MAIN
# =====================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Seed Server v5 - Unified Diagnostics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        'command',
        nargs='?',
        default='all',
        choices=['all', 'imports', 'production', 'schema', 'analytics',
                'bug-reports', 'profiles', 'diagnostic', 'learning-paths',
                'desktop', 'database', 'redis'],
        help='Diagnostic command to run'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )
    
    args = parser.parse_args()
    
    try:
        if args.command in ['all', 'production']:
            await run_production_ready_check()
        elif args.command == 'imports':
            await check_imports(verbose=args.verbose)
        elif args.command == 'schema':
            check_database_schema()
        elif args.command == 'database':
            check_database_schema()
            check_database_health()
        elif args.command == 'redis':
            await check_redis()
        elif args.command == 'analytics':
            check_analytics_system()
        elif args.command == 'bug-reports':
            check_bug_reports()
        elif args.command == 'diagnostic':
            check_diagnostic_data()
        elif args.command == 'learning-paths':
            check_learning_paths()
        elif args.command == 'profiles':
            check_learning_paths()
        elif args.command == 'desktop':
            print("Desktop compatibility check coming soon...")
        
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted by user{Colors.ENDC}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{Colors.RED}Error: {e}{Colors.ENDC}")
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())



