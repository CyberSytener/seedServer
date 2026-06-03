"""
DTO transformation layer for Client Contract V1 alignment.

This module provides transformations between internal models and client-facing DTOs
without modifying core business logic.
"""

from app.models.api import (
    DiagnosticItem,
    DiagnosticItemClientV1,
    DiagnosticItemContentV1,
    DiagnosticItemMetadataV1,
)


def transform_diagnostic_item_to_v1(item: DiagnosticItem) -> DiagnosticItemClientV1:
    """
    Transform internal DiagnosticItem to Client V1 format.
    
    Moves root-level fields (choices, tokens, context.*) into content object.
    Moves tags into metadata object.
    Renames 'id' to 'itemId'.
    
    Task-specific mappings:
    - translate: prompt becomes sourceText
    - mcq/reading_mcq: choices array
    - reorder_sentence: tokens array
    - fill_blank: sentence with blank (from prompt or context.sentence)
    """
    # Determine sourceText based on task type
    # For translate tasks, the prompt IS the source text to translate
    source_text = None
    if item.task_type == "translate":
        source_text = item.prompt
    elif item.context:
        # Check if context has sourceText/source_text field (extra="allow")
        source_text = getattr(item.context, "sourceText", None) or getattr(item.context, "source_text", None)
    
    # Determine sentence with blank for fill_blank tasks
    # LLM may put blank sentence in prompt OR context.sentence
    sentence_with_blank = None
    if item.task_type == "fill_blank":
        # Check prompt first (if it contains blank marker)
        if item.prompt and ("_____" in item.prompt or "__" in item.prompt):
            sentence_with_blank = item.prompt
        # Otherwise check context.sentence
        elif item.context and item.context.sentence:
            sentence_with_blank = item.context.sentence
    elif item.context:
        # For non-fill_blank tasks, use context.sentence if available
        sentence_with_blank = item.context.sentence
    
    # Build content object from dispersed fields
    content = DiagnosticItemContentV1(
        choices=item.choices,
        tokens=item.tokens,
        sentence=sentence_with_blank,
        sourceText=source_text,
        readingPassage=item.context.passage if item.context else None,
        hint=item.context.hint if item.context else None,
    )
    
    # Build metadata object from tags
    metadata = DiagnosticItemMetadataV1(
        skill=item.tags.skill,
        subskill=item.tags.subskill,
        difficulty=item.tags.difficulty,
        topic=item.tags.topic,
        cefrBand=item.tags.cefr_band,
    )
    
    # Return transformed item
    return DiagnosticItemClientV1(
        itemId=item.id,
        taskType=item.task_type,
        prompt=item.prompt,
        content=content,
        metadata=metadata,
    )


