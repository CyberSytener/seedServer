Generate diagnostic items in compact YAML-like format to save tokens.

**FORMAT: One item per block, separated by ---**
Return items in this exact format:

Item 1: mcq
Prompt: I _____ coffee every morning.
Choices: drink, drinks, drinking, drunk
Answer: drink
Explanation: Present simple for habits
Skill: grammar
Subskill: verb_conjugation
Topic: present_tense
Difficulty: 1.5
CEFR: A1
Type: mcq
---
Item 2: translate
Prompt: Translate: 'Good morning'
Answer: Buenos días
Variants: Buen día
Explanation: Standard morning greeting
Skill: vocabulary
Subskill: greetings
Topic: daily_interactions
Difficulty: 1.0
CEFR: A1
Type: translate
---
Item 3: fill_blank
Prompt: Elle _____ (she is) française.
Answer: est
Explanation: Use être for nationality
Skill: grammar
Subskill: verb_conjugation
Topic: nationality
Difficulty: 2.0
CEFR: A2
Type: fill_blank
---
Item 4: reorder_sentence
Prompt: Rearrange: gato / el / negro / es
Tokens: gato, el, negro, es
Answer: El gato es negro
Explanation: Article + noun + verb + adjective
Skill: grammar
Subskill: word_order
Topic: sentence_structure
Difficulty: 2.5
CEFR: A2
Type: reorder_sentence
---

**RULES:**
- Each item separated by ---
- Use exact field names as shown
- For MCQ: 4 comma-separated choices, specify correct answer text
- For translate: Answer + optional Variants separated by |
- For fill_blank: _____ in prompt, single word Answer
- For reorder_sentence: Comma-separated Tokens + correct Answer sentence
- Keep explanations brief (under 10 words)
- Difficulty: 0.5-4.0 scale
- CEFR: A1, A2, B1, B2, C1
- Types: mcq, translate, fill_blank, reorder_sentence, reading_mcq