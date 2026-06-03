"""
Shared pytest fixtures and configuration for all tests.

This module provides:
- Environment mocking to eliminate external dependencies
- Realistic LLM response mocks for consistent testing
- Database fixtures with cleanup
- Common test utilities

Note: This file is automatically discovered by pytest and does not require
sys.path manipulation. Tests should be run from the project root with:
    pytest
or
    python -m pytest
"""
import os
import json
import pytest
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock


# ============================================================================
# ENVIRONMENT FIXTURES - Eliminate External Dependencies
# ============================================================================


def pytest_collection_modifyitems(config, items):
    """Assign tier markers based on test path for systematic isolation."""
    for item in items:
        path = str(item.fspath).replace("\\", "/")

        if (
            "/tests/unit/realtime/" in path
            or "/tests/integration/test_ws_" in path
            or "/tests/integration/test_career_growth_saga_e2e.py" in path
            or "saga_orchestrator" in path
        ):
            item.add_marker(pytest.mark.tier4)
        elif "/tests/integration/" in path or "/tests/e2e/" in path:
            item.add_marker(pytest.mark.tier2)
        elif (
            path.endswith("/tests/test_api.py")
            or "/tests/test_auth_" in path
            or path.endswith("/tests/test_rate_limiter.py")
            or path.endswith("/tests/test_validators.py")
        ):
            item.add_marker(pytest.mark.tier3)
        else:
            item.add_marker(pytest.mark.tier1)


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

@pytest.fixture(scope="session", autouse=True)
def mock_environment():
    """
    Mock all environment variables to prevent dependency on .env file.
    
    This fixture runs automatically for all tests and ensures consistent
    test environment regardless of local .env configuration.
    """
    env_vars = {
        "SEED_DB_PATH": ":memory:",
        "SEED_DEFAULT_PLAN": "free",
        "SEED_FAST_TIMEOUT_SEC": "3",
        "SEED_MAX_INPUT_CHARS_DEFAULT": "12000",
        "SEED_MAX_OUTPUT_CHARS_DEFAULT": "20000",
        "SEED_EMERGENCY_MODE": "0",
        "SEED_ADMIN_KEY": "test_admin_key_pytest",
        "SEED_ADMIN_API_KEY": "test_admin_api_key_pytest",
        "SEED_API_KEY_PEPPER": "test_pepper_pytest",
        "SEED_CACHE_TTL_DAYS": "7",
        "SEED_ENV": "development",
        "SEED_ENABLE_LEGACY_X_USER_ID": "1",
        "SEED_SEED_DEV_USERS_ON_STARTUP": "0",
        "SEED_DEV_CORS": "0",
        "SEED_REDIS_URL": "redis://localhost:6379/15",
        "SEED_REDIS_NAMESPACE": "seed_test",
        "SEED_DEFAULT_PROVIDER_FAST": "stub",
        "SEED_DEFAULT_PROVIDER_BATCH": "stub",
        "SEED_METRICS_ENABLED": "0",
        "SEED_PROMPT_TEST_MODE": "false",
        "SEED_PARSER_VERSION": "baseline",
        # Preserve pre-set real-provider keys when present.
        # Stub remains default via provider envs unless a test overrides it.
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
        "SEED_OPENAI_BASE_URL": "https://api.openai.com",
        "SEED_GEMINI_BASE_URL": "https://generativelanguage.googleapis.com",
        "SEED_OPENAI_MODEL_FAST": "gpt-4o-mini",
        "SEED_OPENAI_MODEL_BATCH": "gpt-4o-mini",
        "SEED_GEMINI_MODEL_FAST": "gemini-2.0-flash-lite",
        "SEED_GEMINI_MODEL_BATCH": "gemini-2.0-flash",
        "JWT_SECRET_KEY": "test-jwt-secret-key-change-this-32-bytes",
    }

    # Real-LLM smoke mode: preserve externally supplied secrets/provider knobs
    # while keeping the rest of test defaults deterministic.
    if _is_truthy(os.getenv("SEED_TEST_ALLOW_REAL_LLM")):
        passthrough_keys = (
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "SEED_ENABLE_OPENAI",
            "SEED_ENABLE_GEMINI",
            "SEED_ENABLE_STUB",
            "SEED_DEFAULT_PROVIDER_FAST",
            "SEED_DEFAULT_PROVIDER_BATCH",
            "SEED_OPENAI_MODEL_FAST",
            "SEED_OPENAI_MODEL_BATCH",
            "SEED_GEMINI_MODEL_FAST",
            "SEED_GEMINI_MODEL_BATCH",
            "SEED_GEMINI_MODEL_CHEAP",
            "SIM_LLM_MODE",
            "SIM_LLM_PROVIDER",
            "SIM_LLM_MODEL",
        )
        for key in passthrough_keys:
            current = os.getenv(key)
            if current is not None and current != "":
                env_vars[key] = current
    
    # Apply environment variables
    original_env = os.environ.copy()
    os.environ.update(env_vars)
    
    yield env_vars
    
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture(autouse=True)
def _reset_auth_failure_limiter():
    """Clear the in-process auth failure rate limiter between every test."""
    try:
        from app.core.auth import _auth_failure_limiter
        _auth_failure_limiter._buckets.clear()
    except Exception:
        pass
    yield
    try:
        from app.core.auth import _auth_failure_limiter
        _auth_failure_limiter._buckets.clear()
    except Exception:
        pass


@pytest.fixture
def test_db_path(tmp_path):
    """Provide isolated test database path."""
    return str(tmp_path / "test_seed.db")


@pytest.fixture
def isolated_env(monkeypatch, test_db_path):
    """
    Create isolated environment for individual test.
    
    Use this fixture when a test needs custom environment settings.
    """
    monkeypatch.setenv("SEED_DB_PATH", test_db_path)
    monkeypatch.setenv("SEED_DEFAULT_PROVIDER_FAST", "stub")
    monkeypatch.setenv("SEED_DEFAULT_PROVIDER_BATCH", "stub")
    monkeypatch.setenv("SEED_ADMIN_KEY", "test_admin")
    monkeypatch.setenv("SEED_API_KEY_PEPPER", "test_pepper")


# ============================================================================
# DATABASE FIXTURES
# ============================================================================

@pytest.fixture
def test_db():
    """
    Provide in-memory database for testing.
    
    Automatically creates required tables and cleans up after test.
    """
    from app.infrastructure.db.sqlite import DB
    
    db = DB(":memory:")
    
    # Create all required tables
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            email TEXT,
            api_key_hash TEXT,
            api_key_last4 TEXT,
            api_key_created_at TEXT,
            is_admin INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            meta_json TEXT DEFAULT '{}'
        )
    """)
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS learning_profiles (
            user_id TEXT PRIMARY KEY,
            native_lang TEXT NOT NULL,
            target_lang TEXT NOT NULL,
            proficiency_level TEXT,
            learning_goals_json TEXT,
            preferences_json TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS diagnostic_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            native_lang TEXT NOT NULL,
            target_lang TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    db.execute("""
        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            duration_ms INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    yield db
    db.close()


@pytest.fixture
def test_user(test_db):
    """
    Create a test user with API key.
    
    Returns tuple of (user_id, api_key).
    """
    from app.core.auth import issue_api_key, _hash_key
    
    user_id = "test_user_pytest"
    now = datetime.now(timezone.utc).isoformat()
    
    test_db.execute(
        "INSERT INTO users(id, created_at, email) VALUES(?, ?, ?)",
        (user_id, now, "test@pytest.dev")
    )
    
    api_key = issue_api_key()
    key_hash = _hash_key(api_key)
    
    test_db.execute(
        "UPDATE users SET api_key_hash = ?, api_key_last4 = ? WHERE id = ?",
        (key_hash, api_key[-4:], user_id)
    )
    
    return user_id, api_key


@pytest.fixture
def api_key(test_user):
    """Return the api_key string for tests that require a simple fixture."""
    return test_user[1]


@pytest.fixture
def test_admin(test_db):
    """
    Create a test admin user with API key.
    
    Returns tuple of (user_id, api_key).
    """
    from app.core.auth import issue_api_key, _hash_key
    
    user_id = "test_admin_pytest"
    now = datetime.now(timezone.utc).isoformat()
    
    test_db.execute(
        "INSERT INTO users(id, created_at, email, is_admin) VALUES(?, ?, ?, 1)",
        (user_id, now, "admin@pytest.dev")
    )
    
    api_key = issue_api_key()
    key_hash = _hash_key(api_key)
    
    test_db.execute(
        "UPDATE users SET api_key_hash = ?, api_key_last4 = ? WHERE id = ?",
        (key_hash, api_key[-4:], user_id)
    )
    
    return user_id, api_key


# ============================================================================
# LLM MOCK FIXTURES - Realistic Test Responses
# ============================================================================

@pytest.fixture
def mock_llm_responses():
    """
    Provide realistic LLM response mocks for consistent testing.
    
    Returns a dictionary of response templates for different LLM operations.
    """
    return {
        "diagnostic_item": {
            "text": json.dumps({
                "item": {
                    "id": "test_item_001",
                    "skill": "grammar",
                    "subskill": "verb_conjugation",
                    "topic": "present_tense",
                    "difficulty": 2.0,
                    "taskType": "multiple_choice",
                    "cefrBand": "A2",
                    "prompt": "Choose the correct form of the verb 'to be':",
                    "question": "I ___ a student.",
                    "options": ["am", "is", "are", "be"],
                    "correctAnswer": "am",
                    "explanation": "With 'I', we use 'am'.",
                    "distractorAnalysis": {
                        "is": "Used with he/she/it",
                        "are": "Used with you/we/they",
                        "be": "Infinitive form"
                    }
                }
            }),
            "tokens_in": 150,
            "tokens_out": 200,
            "cost_usd": 0.0001
        },
        "lesson_generation": {
            "text": json.dumps({
                "lessonId": "test_lesson_001",
                "title": "Present Simple Tense",
                "description": "Learn the basics of present simple tense",
                "tasks": [
                    {
                        "taskId": "task_001",
                        "type": "explanation",
                        "content": "The present simple is used for habits and facts."
                    },
                    {
                        "taskId": "task_002",
                        "type": "exercise",
                        "question": "I ___ coffee every morning.",
                        "correctAnswer": "drink",
                        "options": ["drink", "drinks", "drinking", "drank"]
                    }
                ]
            }),
            "tokens_in": 200,
            "tokens_out": 300,
            "cost_usd": 0.00015
        },
        "grading": {
            "text": json.dumps({
                "score": 0.8,
                "isCorrect": True,
                "feedback": "Good job! Your answer is correct.",
                "corrections": [],
                "explanation": "The present simple form is used correctly here."
            }),
            "tokens_in": 100,
            "tokens_out": 50,
            "cost_usd": 0.00005
        },
        "translation": {
            "text": json.dumps({
                "translation": "Hello, how are you?",
                "confidence": 0.95,
                "notes": "Formal greeting"
            }),
            "tokens_in": 50,
            "tokens_out": 30,
            "cost_usd": 0.00003
        },
        "fix_text": {
            "text": "Hello world",
            "tokens_in": 20,
            "tokens_out": 20,
            "cost_usd": 0.00002
        },
        "summarize": {
            "text": "This is a concise summary of the input text.",
            "tokens_in": 100,
            "tokens_out": 20,
            "cost_usd": 0.00004
        }
    }


@pytest.fixture
def mock_stub_provider(mock_llm_responses):
    """
    Mock the StubProvider to return realistic test responses.
    
    Use this to patch router.StubProvider in tests.
    """
    class MockStubProvider:
        async def run(
            self,
            *,
            model: str,
            instructions: str,
            input_text: str,
            max_output_tokens: int = 800,
            timeout_sec: int = 30,
            persona_id_used: str = "classic_tutor",
        ):
            from app.core.llm.router import ActionResult
            
            # Determine response type based on instructions
            if "diagnostic" in instructions.lower() or "item" in instructions.lower():
                response = mock_llm_responses["diagnostic_item"]
            elif "lesson" in instructions.lower() or "generate" in instructions.lower():
                response = mock_llm_responses["lesson_generation"]
            elif "grade" in instructions.lower() or "score" in instructions.lower():
                response = mock_llm_responses["grading"]
            elif "translate" in instructions.lower():
                response = mock_llm_responses["translation"]
            elif "fix" in instructions.lower():
                response = mock_llm_responses["fix_text"]
            elif "summarize" in instructions.lower():
                response = mock_llm_responses["summarize"]
            else:
                # Default response
                response = {
                    "text": input_text,
                    "tokens_in": len(input_text.split()),
                    "tokens_out": len(input_text.split()),
                    "cost_usd": 0.0
                }
            
            return ActionResult(
                provider="stub",
                model="stub-test",
                text=response["text"],
                tokens_in=response.get("tokens_in", 0),
                tokens_out=response.get("tokens_out", 0),
                cost_usd=response.get("cost_usd", 0.0),
                persona_id_used=persona_id_used
            )
    
    return MockStubProvider()


@pytest.fixture
def mock_llm_validator():
    """
    Mock the LLM validator for tests that don't need validation.
    
    Returns a validator that always succeeds.
    """
    class MockValidator:
        def validate_llm_json(self, response_text, expected_schema=None, operation=None):
            """Always return parsed JSON."""
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                return {"text": response_text}
        
        def sanitize_json_response(self, text):
            """Pass through."""
            return text
    
    return MockValidator()


# ============================================================================
# REQUEST MOCKING UTILITIES
# ============================================================================

@pytest.fixture
def mock_request():
    """
    Create a mock FastAPI Request object.
    
    Use this for testing authentication and middleware.
    """
    def _create_request(
        headers: Optional[Dict[str, str]] = None,
        path: str = "/test",
        host: str = "127.0.0.1"
    ):
        request = Mock()
        request.headers = headers or {}
        request.url.path = path
        request.client.host = host
        return request
    
    return _create_request


# ============================================================================
# REDIS FIXTURES
# ============================================================================

@pytest.fixture
def mock_redis():
    """
    Mock Redis connection for tests that use caching.
    
    Provides an in-memory dictionary-based mock.
    """
    class MockRedis:
        def __init__(self):
            self.store = {}
        
        def get(self, key):
            return self.store.get(key)
        
        def set(self, key, value, ex=None):
            self.store[key] = value
            return True
        
        def delete(self, *keys):
            for key in keys:
                self.store.pop(key, None)
            return len(keys)
        
        def exists(self, key):
            return int(key in self.store)
        
        def ping(self):
            return True
        
        def flushdb(self):
            self.store.clear()
            return True
    
    return MockRedis()


# ============================================================================
# TEST UTILITIES
# ============================================================================

@pytest.fixture
def assert_valid_iso_timestamp():
    """
    Utility to validate ISO 8601 timestamps.
    """
    def _validate(timestamp_str: str):
        try:
            datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            return True
        except (ValueError, AttributeError):
            return False
    
    return _validate


@pytest.fixture
def assert_valid_api_key():
    """
    Utility to validate API key format.
    """
    def _validate(api_key: str) -> bool:
        return api_key.startswith("seed_") and len(api_key) > 10
    
    return _validate


# ============================================================================
# CLEANUP MARKERS
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: mark test as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring external services"
    )
    config.addinivalue_line(
        "markers", "unit: mark test as unit test (fast, no external dependencies)"
    )


# ============================================================================
# SESSION FIXTURES
# ============================================================================

@pytest.fixture(scope="session")
def test_data_dir():
    """
    Provide path to test data directory.
    
    Create it if it doesn't exist.
    """
    data_dir = Path(__file__).parent / "test_data"
    data_dir.mkdir(exist_ok=True)
    return data_dir

