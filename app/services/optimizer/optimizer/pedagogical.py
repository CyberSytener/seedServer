"""
Педагогические утилиты для улучшения качества контента

Includes:
- Synonym expansion для translations
- Variant generation для acceptedAnswers
"""
import logging
from typing import Dict, List, Any, Optional
import asyncio

logger = logging.getLogger(__name__)


class SynonymExpander:
    """Расширяет варианты переводов и ответов для лучшего пользовательского опыта"""
    
    @staticmethod
    def expand_translation_variants(
        word: str,
        primary_translation: str,
        context: str = "",
        min_variants: int = 2
    ) -> List[str]:
        """
        Генерирует дополнительные варианты перевода
        
        Args:
            word: Исходное слово
            primary_translation: Основной перевод
            context: Контекст использования
            min_variants: Минимальное количество вариантов
            
        Returns:
            Список вариантов перевода (включая основной)
        """
        variants = [primary_translation]
        
        # Rule-based expansion (базовые правила)
        
        # Артикли для английского (исходного слова)
        if word.startswith("the "):
            variant = word[4:]  # "the house" -> "house"
            variants.append(variant)
        elif word.startswith("a "):
            variant = word[2:]  # "a car" -> "car"
            variants.append(variant)
        elif word.startswith("an "):
            variant = word[3:]  # "an apple" -> "apple"
            variants.append(variant)
        
        # Добавить с артиклем если его нет
        if not word.startswith(("the ", "a ", "an ")):
            # Определяем какой артикль использовать
            if word[0].lower() in 'aeiou':
                variants.append(f"an {word}")
            else:
                variants.append(f"a {word}")
            variants.append(f"the {word}")
        
        # Капитализация
        if primary_translation != primary_translation.capitalize():
            variants.append(primary_translation.capitalize())
        if primary_translation != primary_translation.lower():
            variants.append(primary_translation.lower())
        
        # Убираем дубликаты и основной перевод
        unique_variants = []
        seen = {primary_translation}
        for v in variants[1:]:  # Пропускаем первый (primary)
            if v not in seen and v != primary_translation:
                unique_variants.append(v)
                seen.add(v)
        
        logger.debug(f"Expanded '{word}' ({primary_translation}) to {len(unique_variants)} variants")
        return unique_variants
    
    @staticmethod
    def expand_vocabulary_entry(
        vocab_entry: Dict[str, Any],
        min_variants: int = 2
    ) -> Dict[str, Any]:
        """
        Расширяет vocabulary entry с дополнительными вариантами
        
        Args:
            vocab_entry: Словарная статья
            min_variants: Минимум вариантов
            
        Returns:
            Обновленная словарная статья
        """
        if "translation" not in vocab_entry:
            return vocab_entry
        
        # Получаем текущие варианты
        current_variants = vocab_entry.get("acceptedVariants", [])
        primary_translation = vocab_entry["translation"]
        
        # Если уже достаточно вариантов, возвращаем как есть
        if len(current_variants) >= min_variants:
            return vocab_entry
        
        # Генерируем дополнительные варианты
        word = vocab_entry.get("word", "") or vocab_entry.get("kanji", "")
        context = vocab_entry.get("example_sentence", "")
        
        expanded_variants = SynonymExpander.expand_translation_variants(
            word=word,
            primary_translation=primary_translation,
            context=context,
            min_variants=min_variants
        )
        
        # Объединяем с существующими
        all_variants = list(set(current_variants + expanded_variants))
        
        # Убираем основной перевод из вариантов (он уже в translation)
        all_variants = [v for v in all_variants if v != primary_translation]
        
        vocab_entry["acceptedVariants"] = all_variants
        
        return vocab_entry
    
    @staticmethod
    async def expand_lesson_vocabulary(
        lesson: Dict[str, Any],
        min_variants: int = 2
    ) -> Dict[str, Any]:
        """
        Расширяет все vocabulary entries в уроке
        
        Args:
            lesson: Урок с vocabulary
            min_variants: Минимум вариантов на слово
            
        Returns:
            Обновленный урок
        """
        if "vocabulary" not in lesson:
            return lesson
        
        logger.info(f"Expanding vocabulary variants (min: {min_variants})")
        
        expanded_vocab = []
        for vocab in lesson["vocabulary"]:
            expanded = SynonymExpander.expand_vocabulary_entry(vocab, min_variants)
            expanded_vocab.append(expanded)
        
        lesson["vocabulary"] = expanded_vocab
        
        # Статистика
        total_entries = len(expanded_vocab)
        entries_with_variants = sum(
            1 for v in expanded_vocab 
            if len(v.get("acceptedVariants", [])) >= min_variants
        )
        
        logger.info(
            f"✅ Vocabulary expansion complete: "
            f"{entries_with_variants}/{total_entries} entries have {min_variants}+ variants"
        )
        
        return lesson


class LLMSynonymExpander(SynonymExpander):
    """
    Расширенная версия с использованием LLM для генерации синонимов
    
    TODO: Implement LLM-based synonym generation
    """
    
    def __init__(self, llm_provider: str = "gemini"):
        self.llm_provider = llm_provider
        logger.info(f"LLM Synonym Expander initialized with {llm_provider}")
    
    async def generate_synonyms_llm(
        self,
        word: str,
        translation: str,
        context: str,
        count: int = 3
    ) -> List[str]:
        """
        Генерирует синонимы используя LLM
        
        Args:
            word: Исходное слово
            translation: Перевод
            context: Контекст
            count: Количество синонимов
            
        Returns:
            Список синонимов
        """
        # TODO: Implement actual LLM call
        # For now, fall back to rule-based
        return self.expand_translation_variants(word, translation, context, count)


# Convenience functions - NOTE: This is now async, rename if needed
async def expand_lesson_vocabulary_sync(
    lesson: Dict[str, Any],
    min_variants: int = 2
) -> Dict[str, Any]:
    """Async function for expand_lesson_vocabulary (renamed to avoid nested event loop)"""
    return await SynonymExpander.expand_lesson_vocabulary(lesson, min_variants)
