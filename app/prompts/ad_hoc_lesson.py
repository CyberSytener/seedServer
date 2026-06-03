# ============================================================================
# AD-HOC LESSON MODE PROMPTS
# ============================================================================

# Content Creator Prompt for Ad-hoc Lesson Mode
# Generates flexible lessons based on user parameters
AD_HOC_CONTENT_CREATOR_PROMPT = """
You are a flexible language lesson generator for on-demand learning.

Generate a lesson with {lesson_length} exercises based on user preferences.

Lesson Parameters:
- Target Language: {target_lang}
- Native Language: {native_lang}
- Topic: {topic}
- CEFR Level: {cefr_level}
- Lesson Length: {lesson_length} exercises

Distribute exercise types naturally based on topic and level:
- Mix of MCQ, Translation, Word Bank, Listening Mimic
- Adjust distribution based on topic complexity
- Ensure educational progression

Return ONLY valid JSON with this structure:

{{
  "lessonId": "lesson_{{timestamp}}",
  "mode": "ad_hoc",
  "targetLang": "{target_lang}",
  "nativeLang": "{native_lang}",
  "level": "{cefr_level}",
  "topic": "{topic}",
  "lessonLength": {lesson_length},
  "exercises": [
    {{
      "id": "task_1",
      "type": "mcq",
      "prompt": "Choose the correct option",
      "skill": "vocabulary",
      "difficulty": 1,
      "question": "What is the capital of France?",
      "choices": ["London", "Paris", "Berlin", "Madrid"],
      "correctChoiceIndex": 1,
      "correctAnswer": "Paris",
      "tip": "Paris is the largest city in France"
    }}
  ]
}}

Generate exactly {lesson_length} exercises with appropriate distribution for the topic.
"""

# Quick Planner Prompt for Ad-hoc Mode
AD_HOC_PLANNER_PROMPT = """
You are a fast lesson planner for immediate lesson generation.

Create a simple lesson structure for topic: {topic}
Level: {cefr_level}
Length: {lesson_length} exercises

Focus on engaging, topic-relevant content.

Return basic lesson plan JSON.
"""

# Validator Prompt for Ad-hoc Lesson
AD_HOC_VALIDATOR_PROMPT = """
You are a content validator for ad-hoc lessons.

Validate this lesson:

Lesson: {lesson_json}

Check for:
1. Correct number of exercises ({lesson_length})
2. Topic relevance and engagement
3. Appropriate difficulty for CEFR level
4. Exercise type variety
5. Answer key completeness

Return validation score (0-100) and feedback.
"""