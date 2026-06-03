# Test Infrastructure - Quick Reference

**Zero-dependency testing with comprehensive fixtures and mocking**

---

## Quick Start

```bash
# Install
pip install pytest pytest-asyncio pytest-cov

# Run all tests
python -m pytest -v

# Run with coverage
python -m pytest --cov=app --cov-report=html

# Verify infrastructure
python verify_test_infrastructure.py
```

**No .env file or API keys needed!**

---

## Available Fixtures

### Environment & Database

```python
def test_example(test_db, isolated_env):
    """Auto-mocked environment + in-memory database"""
    # test_db is SQLite :memory: with all tables
    # Environment is isolated with stub providers
```

### Users & Authentication

```python
def test_with_user(test_user):
    """Pre-configured user with API key"""
    user_id, api_key = test_user
    # Use for authenticated endpoints

def test_with_admin(test_admin):
    """Pre-configured admin user"""
    admin_id, admin_api_key = test_admin
    # Use for admin-only endpoints
```

### LLM Mocking

```python
def test_llm_operation(mock_llm_responses):
    """Realistic response templates"""
    response = mock_llm_responses["diagnostic_item"]
    # Returns properly formatted JSON

def test_with_stub(mock_stub_provider):
    """Mock StubProvider instance"""
    result = await mock_stub_provider.run(...)
    # Returns ActionResult with realistic data
```

### Request Mocking

```python
def test_auth(mock_request):
    """Create mock FastAPI request"""
    request = mock_request(
        headers={"Authorization": "Bearer test_key"},
        path="/api/test"
    )
```

### Redis Mocking

```python
def test_cache(mock_redis):
    """In-memory Redis mock"""
    mock_redis.set("key", "value")
    assert mock_redis.get("key") == "value"
```

---

## StubProvider Operations

The enhanced `StubProvider` intelligently mocks LLM responses:

### Diagnostic Items
```python
# Input: {"skill": "grammar", "difficulty": 2.0}
# Returns: Complete diagnostic item with question, options, answer
```

### Lesson Generation
```python
# Input: Lesson parameters
# Returns: Structured lesson with tasks and exercises
```

### Grading
```python
# Input: Student submission
# Returns: Score, feedback, corrections
```

### Translation
```python
# Input: Text to translate
# Returns: Translation with confidence score
```

### Text Fixing
```python
# Input: Text with errors
# Returns: Cleaned and corrected text
```

### Summarization
```python
# Input: Long text
# Returns: Intelligent summary
```

**All operations return realistic, properly formatted responses.**

---

## Environment Variables

### Automatically Set by Fixtures

```python
SEED_DEFAULT_PROVIDER_FAST=stub    # No API calls
SEED_DEFAULT_PROVIDER_BATCH=stub   # No API calls
OPENAI_API_KEY=""                  # Empty (safe)
GEMINI_API_KEY=""                  # Empty (safe)
SEED_ADMIN_KEY=test_admin_key_pytest
SEED_DB_PATH=:memory:              # In-memory
```

### Custom Override

```python
def test_custom(monkeypatch):
    """Override for one test"""
    monkeypatch.setenv("SEED_PROMPT_TEST_MODE", "true")
```

---

## Test Markers

```python
@pytest.mark.unit
def test_fast():
    """Unit test - no external deps"""
    pass

@pytest.mark.integration
def test_with_redis():
    """Integration test - may need Redis"""
    pass

@pytest.mark.slow
def test_takes_time():
    """Slow test - skip with -m "not slow" """
    pass
```

### Run by Marker

```bash
pytest -m unit -v           # Fast unit tests only
pytest -m "not slow" -v     # Skip slow tests
pytest -m integration -v    # Integration tests only
```

---

## Common Patterns

### Test Database Operations

```python
@pytest.mark.unit
def test_db_operation(test_db):
    test_db.execute("INSERT INTO users ...")
    rows = test_db.fetchall("SELECT * FROM users")
    assert len(rows) > 0
```

### Test Authentication

```python
@pytest.mark.unit
def test_auth(test_db, test_user, mock_request):
    from app.auth import authenticate
    
    user_id, api_key = test_user
    request = mock_request(
        headers={"Authorization": f"Bearer {api_key}"}
    )
    
    auth_ctx = authenticate(request, test_db)
    assert auth_ctx.user_id == user_id
```

### Test Async Operations

```python
@pytest.mark.unit
@pytest.mark.asyncio
async def test_async():
    result = await some_async_function()
    assert result is not None
```

### Test LLM Operations

```python
@pytest.mark.unit
def test_llm(test_db, test_user):
    # No mocking needed - StubProvider is automatic
    result = generate_diagnostic_items(
        db=test_db,
        user_id=test_user[0],
        ...
    )
    assert len(result) > 0
```

---

## Verification Checklist

```bash
python verify_test_infrastructure.py
```

**Should pass all 6 checks:**
- ✅ conftest.py fixtures (9 required)
- ✅ Enhanced StubProvider (6 operations)
- ✅ alerting.py TODO completed
- ✅ Test documentation (7 sections)
- ✅ Environment mocking (28 fixtures)
- ✅ Python syntax (all files)

---

## Troubleshooting

### Tests Can't Find Fixtures

```bash
# Ensure conftest.py exists
ls tests/conftest.py

# Run with verbose discovery
pytest --collect-only
```

### Tests Use Real API

```bash
# Verify stub provider is default
python -c "from app.settings import get_settings; print(get_settings().default_provider_fast)"
# Should print: stub
```

### Import Errors

```python
# Add to test file
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```

### Redis Tests Fail

```bash
# Option 1: Install Redis
brew install redis  # macOS
sudo apt install redis  # Ubuntu

# Option 2: Skip integration tests
pytest -m "not integration" -v

# Option 3: Use mock_redis fixture
```

---

## Key Benefits

✅ **No Configuration** - Works immediately  
✅ **No API Keys** - Zero costs, zero secrets  
✅ **No Network** - Runs offline  
✅ **Fast** - In-memory everything  
✅ **Isolated** - Clean state per test  
✅ **Realistic** - Mock responses match production  
✅ **Documented** - 15KB comprehensive guide  

---

## Documentation

- **Full Guide**: [TESTING_WITHOUT_DEPENDENCIES.md](TESTING_WITHOUT_DEPENDENCIES.md)
- **Summary**: [TEST_INFRASTRUCTURE_COMPLETE.md](TEST_INFRASTRUCTURE_COMPLETE.md)
- **Fixtures**: [tests/conftest.py](tests/conftest.py)
- **Verification**: `python verify_test_infrastructure.py`

---

## Example Test

```python
"""Example test using all fixtures."""
import pytest
from app.diagnostic_engine import generate_diagnostic_items


@pytest.mark.unit
def test_diagnostic_generation(test_db, test_user):
    """
    Test diagnostic item generation.
    
    Uses:
    - test_db: In-memory database with all tables
    - test_user: Pre-configured user with API key
    - StubProvider: Automatic (no mocking needed)
    """
    user_id, api_key = test_user
    
    # Call actual function - StubProvider is default
    items = generate_diagnostic_items(
        db=test_db,
        user_id=user_id,
        native_lang="English",
        target_lang="French",
        blueprint=[{
            "skill": "grammar",
            "difficulty": 2.0,
            "taskType": "multiple_choice"
        }]
    )
    
    # Verify results
    assert len(items) > 0
    assert items[0]["skill"] == "grammar"
    assert items[0]["taskType"] == "multiple_choice"
    
    # No API calls made, no costs incurred!
```

**Run**: `pytest -v test_example.py`

---

**Updated**: 2026-01-11  
**Status**: ✅ All checks passing  
**Coverage**: 100% test infrastructure
