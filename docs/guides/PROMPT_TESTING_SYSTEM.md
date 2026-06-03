# Prompt Testing System Documentation

## Overview

The Prompt Testing System provides an isolated A/B testing framework for experimenting with different AI prompting strategies without disrupting the production system. It allows comparing baseline prompts with experimental test prompts while collecting detailed metrics.

## Features

- **A/B Testing**: Automatically splits users between baseline and test prompts
- **Isolated Testing**: Test prompts stored separately from production prompts
- **Comprehensive Logging**: Tracks execution time, success rate, and response quality
- **Session Management**: Organize tests into named sessions for analysis
- **API Management**: RESTful endpoints for managing tests and viewing results
- **Consistent Assignment**: Users get the same prompt version consistently during a session

## Architecture

```
prompts/
├── lesson_generator.md          # Baseline prompts
├── diagnostic_generator.md      
├── lesson_grader.md
├── lesson_generator_compact.md
└── test/                        # Test prompts directory
    ├── lesson_generator.md      # Test version of lesson generator
    ├── lesson_generator_compact.md
    └── diagnostic_generator.md  # Test version of diagnostic generator
```

## Configuration

### Environment Variables

```bash
# Enable prompt testing system
SEED_PROMPT_TEST_MODE=true

# Also requires optimization flag for compact prompts
SEED_OPTIMIZE_MODE=true
```

### Docker Compose

```yaml
environment:
  - SEED_PROMPT_TEST_MODE=true
  - SEED_OPTIMIZE_MODE=true
```

### Startup Validation

При запуске сервера система автоматически проверяет:

- **Наличие базовых промптов**: Все файлы в `prompts/` директории должны существовать и быть читаемыми
- **Валидность контента**: Промпты не должны быть пустыми
- **Тестовые промпты**: Логирует наличие/отсутствие тестовых версий

Если базовые промпты отсутствуют или повреждены, сервер не запустится с подробными ошибками в логах.

## Usage

### 1. Starting a Test Session

```python
from app.prompt_testing import get_prompt_test_manager

test_manager = get_prompt_test_manager()
session_id = test_manager.start_test_session("my_experiment")
```

### 2. Creating Test Prompts

Create test versions in `prompts/test/` directory:

```bash
# Copy baseline prompt to test directory
cp prompts/lesson_generator.md prompts/test/lesson_generator.md

# Edit the test version with your improvements
nano prompts/test/lesson_generator.md
```

### 3. Running Tests

The system automatically handles A/B testing when generating lessons:

```python
# Users are automatically assigned to baseline or test prompts
lesson = generate_lesson(
    req=lesson_request,
    persona_prompt=persona_prompt,
    user_id="user_123"  # Critical for consistent assignment
)
```

### 4. Viewing Results

```python
# Get session summary
summary = test_manager.get_session_summary()
print(f"Success rate: {summary['success_rate']}")
print(f"Tests by type: {summary['by_type']}")
```

## API Endpoints

### Start Test Session

```http
POST /api/prompt-testing/session/start
{
  "session_name": "experiment_1",
  "description": "Testing improved context awareness"
}
```

### Get Session Summary

```http
GET /api/prompt-testing/session/summary
```

Response:
```json
{
  "session": "experiment_1_1703123456",
  "total_tests": 24,
  "success_rate": 0.958,
  "by_type": {
    "lesson_generator:baseline": {
      "count": 12,
      "success_count": 11,
      "avg_time_ms": 3200
    },
    "lesson_generator:test": {
      "count": 12, 
      "success_count": 12,
      "avg_time_ms": 2800
    }
  }
}
```

### List Available Prompts

```http
GET /api/prompt-testing/prompts
```

### Get Prompt Content

```http
POST /api/prompt-testing/prompts/content
{
  "prompt_type": "lesson_generator",
  "is_test_version": true
}
```

### Get Test Status

```http
GET /api/prompt-testing/status
```

### Get Session Results

```http
GET /api/prompt-testing/results/{session_id}
```

## Test Script Usage

Run the included test script to verify the system:

```bash
cd seed_server
python test_prompt_system.py
```

Expected output:
```
🧪 Testing Prompt A/B Testing System
==================================================
📊 Started test session: cli_test_1703123456
🔧 Test mode active: True
📝 Available test prompts: ['lesson_generator', 'lesson_generator_compact']

🔬 Running Lesson Generation Tests
----------------------------------------
✅ Success: Basic Spanish Greetings
   Tasks: 4 (vocabulary, fill_blank, translate, multiple_choice)

📈 Test Session Summary
Session: cli_test_1703123456
Total tests: 2
Success rate: 100.0%
```

## Prompt Development Guidelines

### Test Prompt Improvements

When creating test prompts, focus on:

1. **Clarity**: Clearer, more specific instructions
2. **Context**: Better situational context and examples
3. **Structure**: Improved format and organization
4. **Efficiency**: Reduced token usage while maintaining quality

### Example: Lesson Generator Test Improvements

Original baseline prompt:
```markdown
Create a lesson with exactly 4 tasks for language learning.
```

Improved test prompt:
```markdown
Create a **concise and focused** lesson with exactly 4 tasks.

## Enhanced Guidelines:
1. **Brevity First**: Each task should take 2-3 minutes maximum
2. **Progressive Complexity**: Gradual difficulty increase
3. **Real-world Context**: Situational scenarios from user interests
```

### A/B Testing Best Practices

1. **Single Variable Testing**: Change one aspect at a time
2. **Adequate Sample Size**: Run enough tests for statistical significance
3. **Consistent Conditions**: Keep other variables constant
4. **Document Changes**: Clear description of what's being tested

## Data Collection and Analysis

### Logged Metrics

For each prompt test, the system logs:

- **Performance**: Execution time, success rate, error tracking
- **Token Usage**: Estimated input tokens (prompt + user message), output tokens (AI response), total tokens
- **Request Context**: User ID, language, level, topic for analysis
- **Response Summary**: Task count, types, and structure for lesson generation
- **Error Details**: Failure reasons for debugging

### Sample Results Output
```json
{
  "session": "experiment_1_1703123456",
  "total_tests": 24,
  "success_rate": 0.958,
  "avg_execution_time_ms": 2850,
  "total_tokens_used": 45600,
  "avg_input_tokens": 1200,
  "avg_output_tokens": 800,
  "by_type": {
    "lesson_generator:baseline": {
      "count": 12,
      "success_count": 11,
      "avg_time_ms": 3200,
      "avg_tokens": 1950
    },
    "lesson_generator:test": {
      "count": 12,
      "success_count": 12,
      "avg_time_ms": 2800,
      "avg_tokens": 1800
    }
  }
}
```

## Integration with Existing System

### Lesson Generation

The prompt testing system integrates seamlessly with existing lesson generation:

```python
# In lesson_engine.py
def generate_lesson(..., user_id: str = "anonymous"):
    # Get prompt through testing system
    prompt_content, prompt_version = get_prompt_for_test(prompt_type, user_id)
    
    # Generate lesson with selected prompt
    lesson = generate_with_prompt(prompt_content, ...)
    
    # Log results for analysis
    test_manager.log_test_result(...)
```

### Backward Compatibility

- System works with existing prompts if no test versions exist
- Falls back to baseline prompts if test loading fails
- Can be disabled by setting `SEED_PROMPT_TEST_MODE=false`

## Troubleshooting

### Common Issues

**Test mode not activating:**
- Check `SEED_PROMPT_TEST_MODE=true` in environment
- Verify docker-compose configuration
- Check server logs for initialization errors

**Test prompts not found:**
- Ensure test prompts exist in `prompts/test/` directory
- Check file naming matches prompt type exactly
- Verify file permissions and encoding (UTF-8)

**Inconsistent user assignment:**
- Make sure `user_id` is passed consistently
- Check that test session is active
- Verify A/B split logic with different user IDs

**Results not saving:**
- Check write permissions on results directory
- Verify disk space availability
- Monitor logs for JSON serialization errors

### Debug Commands

```bash
# Check test mode status
curl http://localhost:8000/api/prompt-testing/status

# List available test prompts
curl http://localhost:8000/api/prompt-testing/prompts

# View current session summary
curl http://localhost:8000/api/prompt-testing/session/summary
```

## Future Enhancements

Planned improvements:

1. **Quality Scoring**: Automated assessment of prompt output quality
2. **Multi-variate Testing**: Test multiple prompt aspects simultaneously
3. **Statistical Analysis**: Built-in significance testing
4. **Prompt Versioning**: Track prompt changes over time
5. **Performance Dashboards**: Real-time monitoring and visualization
6. **Auto-deployment**: Promote successful test prompts to baseline

## Security Considerations

- Test results may contain sensitive user data - ensure appropriate access controls
- Test prompts should not expose internal system information
- Session data should be regularly cleaned up to prevent storage bloat
- API endpoints require authentication via existing auth system