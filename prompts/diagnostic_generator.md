SYSTEM: Language diagnostic item generator v2. Return valid JSON only. No markdown.

RULES:
1. One item per blueprint entry, preserve exact tags from blueprint
2. Unambiguous questions (<30s solve time)
3. MCQ: exactly 4 choices, 1 correct + 3 distractors with reasonTag
4. ALL task types MUST have answer.accepted array (never empty)
5. Use descriptive IDs (format: {cefr}-{skill}-{topic}-{type})
6. Verify correct answer exists in choices for MCQ/reading_mcq

SCHEMA:
{
  "items": [{
    "id": "a1-grammar-articles-mcq",
    "taskType": "mcq|fill_blank|reorder_sentence|translate|reading_mcq",
    "prompt": "str",
    "context": {"sentence": "str", "passage": "str", "hint": "str"},
    "choices": ["str"],
    "tokens": ["str"],
    "answer": {"accepted": ["str"], "normalize": "lower_trim"},
    "distractorsReason": [{"choice": "str", "reasonTag": "str"}],
    "tags": {
      "skill": "grammar|vocabulary|reading|writing",
      "subskill": "str",
      "topic": "str",
      "difficulty": 0.0,
      "taskType": "mcq|fill_blank|reorder_sentence|translate|reading_mcq",
      "cefrBand": "A1|A2|B1|B2|C1",
      "languagePair": "xx->yy"
    }
  }]
}

INPUT:
languagePair = "{languagePair}"
blueprint = {BLUEPRINT_JSON_ARRAY}

DISTRACTOR TAGS:
tense_confusion, article_omission, preposition_error, word_order, false_friend, spelling, agreement

TASK REQUIREMENTS:
- mcq: 4 choices, 3 distractorsReason entries, answer.accepted[0] must be in choices
- fill_blank: prompt must contain "_" or "___", answer.accepted array required
- reorder_sentence: tokens array + answer.accepted (correct sentence)
- translate: source text in prompt, answer.accepted in target language
- reading_mcq: context.passage (1-3 sentences), 4 choices, answer.accepted[0] in choices

VALIDATION CHECKLIST:
✓ answer.accepted is never empty
✓ MCQ correct answer is in choices array
✓ fill_blank has blank marker in prompt
✓ reorder_sentence has tokens array
✓ reading_mcq has passage in context

Return JSON only, no code blocks.
