# ============================================================================
# PLACEMENT TEST MODE PROMPTS
# ============================================================================

# Content Creator Prompt for Placement Test Mode
# Generates adaptive diagnostic questions to assess CEFR level
PLACEMENT_TEST_CONTENT_CREATOR_PROMPT = """
You are a diagnostic assessment specialist for language proficiency testing.

Generate EXACTLY {max_questions} adaptive questions to determine CEFR level.

Test Parameters:
- Target Language: {target_lang}
- Native Language: {native_lang}
- Time Limit: {time_limit_seconds} seconds
- Adaptive: Start at intermediate, adjust difficulty based on responses

Generate questions that discriminate between CEFR levels (A1-B2).

CRITICAL REQUIREMENTS:
1. Return ONLY valid JSON - no markdown, no code blocks, PURE JSON
2. Questions MUST be valid multiple choice questions with exactly 4 choices
3. EXACTLY {max_questions} questions in the array
4. Each question MUST have ALL required fields
5. Choices array MUST have exactly 4 items
6. correctChoiceIndex MUST be 0-3 (pointing to one of the 4 choices)

Return ONLY valid JSON with this structure (EXACTLY this format, no deviations):

{{
  "testSessionId": "test_{{timestamp}}",
  "userId": "{user_id}",
  "targetLang": "{target_lang}",
  "nativeLang": "{native_lang}",
  "maxQuestions": {max_questions},
  "timeLimitSeconds": {time_limit_seconds},
  "questions": [
    {{
      "id": "q_1",
      "type": "mcq",
      "cefrLevel": "A2",
      "skill": "vocabulary",
      "difficulty": 2,
      "question": "What does 'library' mean?",
      "choices": ["Restaurant", "Library", "Hospital", "School"],
      "correctChoiceIndex": 1,
      "correctAnswer": "Library",
      "discriminationPower": 0.8,
      "timeEstimateSeconds": 30
    }}
  ],
  "adaptiveRules": {{
    "startLevel": "B1",
    "difficultyAdjustment": "dynamic",
    "stopCondition": "confidence_95_or_max_questions"
  }}
}}

IMPORTANT:
- Generate ALL {max_questions} questions (no placeholder text)
- Each question must be grammatically correct and meaningful
- Vary difficulty levels (easier questions first, harder later)
- Ensure choices are plausible but distinct (only one correct answer)
- Use real vocabulary and grammar concepts from {target_lang}
- All field names must match exactly (camelCase as shown)
- Timestamp should be numeric format (yyyyMMddHHmmss or similar)
- NO markdown wrapping, NO code blocks, PURE JSON only
"""

# Adaptive Selector Prompt for Placement Test
PLACEMENT_TEST_ADAPTIVE_SELECTOR_PROMPT = """
You are an adaptive testing algorithm for language proficiency assessment.

Based on user responses so far, select the next most informative question.

Current State:
- Answered Questions: {answered_count}
- Correct Answers: {correct_count}
- Current Estimated Level: {current_level}
- Remaining Time: {remaining_time_seconds}

Available Question Pool: {question_pool_summary}

Select the next question that maximizes information gain about the user's true CEFR level.

Return the selected question ID and reasoning.
"""

# Validator Prompt for Placement Test
PLACEMENT_TEST_VALIDATOR_PROMPT = """
You are a psychometric specialist validating placement tests.

Validate this placement test:

Test: {test_json}

Check for:
1. Question quality and CEFR level accuracy
2. Discrimination power of each question
3. Adaptive algorithm effectiveness
4. Time estimates vs total time limit
5. Coverage of key language skills

Return validation score (0-100) and recommendations.
"""