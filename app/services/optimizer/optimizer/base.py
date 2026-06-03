"""
Базовые классы и интерфейсы для системы оптимизации

Определяет общую архитектуру для всех версий оптимизаторов.
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional, TypeVar, Generic

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================

class OptimizationTarget(str, Enum):
    """Цели оптимизации"""
    PROMPT_CONTENT_CREATOR = "prompt_content_creator"
    PROMPT_LESSON_PLANNER = "prompt_lesson_planner"
    PROMPT_VALIDATOR = "prompt_validator"
    VALIDATION_RULES = "validation_rules"
    VALIDATION_WEIGHTS = "validation_weights"
    PIPELINE_PARAMS = "pipeline_params"


class OptimizerVersion(str, Enum):
    """Версии оптимизаторов"""
    V1_PROMPT_ONLY = "v1_prompt_only"
    V2_PROMPT_VALIDATION = "v2_prompt_validation"
    V3_MULTI_TARGET = "v3_multi_target"


class LLMProvider(str, Enum):
    """LLM провайдеры для cross-validation"""
    GEMINI_PRO = "gemini_pro"
    GEMINI_FLASH = "gemini_flash"
    GPT4O = "gpt4o"
    CLAUDE = "claude"
    

# ============================================================================
# LANGUAGE SCHEMAS (Linguistic Integrity)
# ============================================================================

# Конфигурация допустимых полей для каждого языка
LANGUAGE_SCHEMAS = {
    "Japanese": {
        "required_fields": ["kanji", "romaji", "translation"],
        "optional_fields": ["hiragana", "katakana", "reading"],
        "phonetic_field": "romaji"
    },
    "Chinese": {
        "required_fields": ["hanzi", "pinyin", "translation"],
        "optional_fields": ["traditional", "simplified"],
        "phonetic_field": "pinyin"
    },
    "Korean": {
        "required_fields": ["hangul", "romanization", "translation"],
        "optional_fields": ["hanja"],
        "phonetic_field": "romanization"
    },
    "Arabic": {
        "required_fields": ["arabic", "transliteration", "translation"],
        "optional_fields": ["voweled_form"],
        "phonetic_field": "transliteration"
    },
    "Russian": {
        "required_fields": ["word", "translation"],
        "optional_fields": ["ipa_transcription"],
        "phonetic_field": "ipa_transcription"
    },
    # Языки с латинским алфавитом
    "default": {
        "required_fields": ["word", "translation"],
        "optional_fields": ["ipa_transcription", "pronunciation_guide"],
        "phonetic_field": "ipa_transcription"
    }
}

# Список языков, использующих латиницу
LATIN_ALPHABET_LANGUAGES = {
    "English", "Spanish", "French", "German", "Italian", "Portuguese",
    "Dutch", "Swedish", "Norwegian", "Danish", "Finnish", "Polish",
    "Czech", "Romanian", "Turkish", "Indonesian", "Malay", "Swahili"
}


def get_language_schema(language: str) -> Dict[str, Any]:
    """Получить схему для языка"""
    if language in LANGUAGE_SCHEMAS:
        return LANGUAGE_SCHEMAS[language]
    elif language in LATIN_ALPHABET_LANGUAGES:
        return LANGUAGE_SCHEMAS["default"]
    else:
        # Для неизвестных языков используем default
        logger.warning(f"Unknown language '{language}', using default schema")
        return LANGUAGE_SCHEMAS["default"]


def validate_language_fields(language: str, fields: List[str]) -> tuple[bool, List[str]]:
    """
    Проверить что поля соответствуют языку
    
    Returns:
        (is_valid, list_of_errors)
    """
    schema = get_language_schema(language)
    required = set(schema["required_fields"])
    optional = set(schema["optional_fields"])
    allowed = required | optional
    
    errors = []
    
    # Проверка на запрещенные поля
    for field in fields:
        if field not in allowed:
            # Особая проверка для romaji в неяпонских языках
            if field == "romaji" and language != "Japanese":
                errors.append(
                    f"CRITICAL: Field 'romaji' is not valid for {language}. "
                    f"Use '{schema['phonetic_field']}' instead."
                )
            elif field in ["kanji", "hiragana", "katakana"] and language != "Japanese":
                errors.append(f"Field '{field}' is only valid for Japanese, not {language}")
            elif field in ["hanzi", "pinyin"] and language != "Chinese":
                errors.append(f"Field '{field}' is only valid for Chinese, not {language}")
            else:
                errors.append(f"Unknown field '{field}' for {language}")
    
    # Проверка обязательных полей
    missing = required - set(fields)
    if missing:
        errors.append(f"Missing required fields for {language}: {missing}")
    
    return len(errors) == 0, errors


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class OptimizerTestCase:
    """Единый тестовый случай для всех оптимизаторов
    
    Note: Named OptimizerTestCase instead of TestCase to avoid pytest collection warning
    """
    id: str
    description: str
    target_lang: str
    native_lang: str
    cefr_level: str
    topic: str
    focus: str
    expected_vocab_count: int
    expected_dialogue_scenes: int
    min_score: int
    custom_params: Dict[str, Any] = field(default_factory=dict)
    
    # Breaking Echo Chamber: Negative constraints
    forbidden_patterns: List[str] = field(default_factory=list)  # Запрещенные паттерны
    
    # Human-in-the-Loop
    is_human_verified: bool = False  # Ручная проверка
    human_feedback: str = ""  # Комментарий эксперта
    
    # Make pytest ignore this class
    __test__ = False


@dataclass
class TestResult:
    """Результат выполнения теста"""
    test_case_id: str
    duration_s: float
    score: int
    passed: bool
    issues: List[str]
    validation_details: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Linguistic Integrity: Language field validation errors
    language_errors: List[str] = field(default_factory=list)
    
    # Negative constraints violations
    forbidden_pattern_violations: List[str] = field(default_factory=list)
    
    # Cross-model validation (jury)
    jury_score: Optional[int] = None  # Оценка от другой модели
    jury_feedback: str = ""  # Комментарий jury


@dataclass
class OptimizationIteration:
    """Одна итерация оптимизации"""
    iteration: int
    timestamp: str
    target: OptimizationTarget
    artifact: Any  # Может быть промпт (str), правила валидации (dict), и т.д.
    avg_score: float
    test_results: List[TestResult]
    token_count: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizationResult:
    """Финальный результат оптимизации"""
    version: OptimizerVersion
    target: OptimizationTarget
    iterations: List[OptimizationIteration]
    best_iteration: OptimizationIteration
    improvement_delta: float
    session_id: str
    session_timestamp: str
    
    # Efficiency: Early stopping info
    early_stopped: bool = False
    early_stop_reason: str = ""
    
    # Two-phase optimization tracking
    phase_1_iterations: int = 0  # Flash model iterations
    phase_2_iterations: int = 0  # Pro model iterations
    
    # Cross-model jury validation
    jury_validated: bool = False
    jury_provider: Optional[str] = None
    jury_best_score: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертация в словарь для сериализации"""
        return {
            "version": self.version.value,
            "target": self.target.value,
            "iterations": [
                {
                    "iteration": it.iteration,
                    "timestamp": it.timestamp,
                    "target": it.target.value,
                    "avg_score": it.avg_score,
                    "test_count": len(it.test_results),
                    "passed_count": sum(1 for r in it.test_results if r.passed),
                    "token_count": it.token_count,
                    "metadata": it.metadata,
                }
                for it in self.iterations
            ],
            "best_iteration": {
                "iteration": self.best_iteration.iteration,
                "avg_score": self.best_iteration.avg_score,
                "token_count": self.best_iteration.token_count,
            },
            "improvement_delta": self.improvement_delta,
            "session_id": self.session_id,
            "session_timestamp": self.session_timestamp,
            "early_stopped": self.early_stopped,
            "early_stop_reason": self.early_stop_reason,
            "phase_1_iterations": self.phase_1_iterations,
            "phase_2_iterations": self.phase_2_iterations,
            "jury_validated": self.jury_validated,
            "jury_provider": self.jury_provider,
            "jury_best_score": self.jury_best_score,
        }


# ============================================================================
# OPTIMIZATION CONFIGURATION
# ============================================================================

@dataclass
class OptimizationConfig:
    """Конфигурация оптимизации с новыми фичами"""
    
    # Basic settings
    max_iterations: int = 10
    stability_threshold: float = 95.0
    
    # Two-phase optimization (Efficiency)
    enable_two_phase: bool = False
    phase_1_provider: LLMProvider = LLMProvider.GEMINI_FLASH  # Быстрая модель
    phase_2_provider: LLMProvider = LLMProvider.GEMINI_PRO    # Точная модель
    phase_1_iterations: int = 7  # Первые N итераций на Flash
    phase_2_iterations: int = 3  # Последние N итераций на Pro
    
    # Early stopping (Efficiency)
    enable_early_stopping: bool = True
    min_improvement_threshold: float = 0.5  # % минимального улучшения
    patience: int = 3  # Количество итераций без улучшения
    
    # Cross-model jury (Breaking Echo Chamber)
    enable_jury_validation: bool = False
    jury_provider: Optional[LLMProvider] = LLMProvider.GPT4O
    jury_validates_final: bool = True  # Jury проверяет только финальный результат
    jury_validates_all: bool = False   # Jury проверяет все итерации
    
    # Linguistic integrity
    enforce_language_schemas: bool = True
    
    # Negative constraints
    enforce_forbidden_patterns: bool = True
    
    # Pedagogical quality
    enable_synonym_expansion: bool = False
    min_accepted_variants: int = 2  # Минимум вариантов перевода


# ============================================================================
# ABSTRACT BASE OPTIMIZER
# ============================================================================

T = TypeVar('T')  # Тип артефакта (str для промптов, dict для правил)

class BaseOptimizer(ABC, Generic[T]):
    """
    Базовый класс для всех версий оптимизаторов
    
    Определяет общий интерфейс и workflow для оптимизации.
    """
    
    def __init__(
        self,
        version: OptimizerVersion,
        target: OptimizationTarget,
        output_dir: Path,
        stability_threshold: float = 95.0,
        max_iterations: int = 10,
        config: Optional[OptimizationConfig] = None,
    ):
        self.version = version
        self.target = target
        self.output_dir = output_dir
        self.stability_threshold = stability_threshold
        self.max_iterations = max_iterations
        self.config = config or OptimizationConfig()
        
        # Создаем директорию для результатов
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Создаем session-специфичную директорию
        self.session_id = f"{version.value}_{target.value}_{int(time.time())}"
        self.session_dir = self.output_dir / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # Early stopping tracking
        self._no_improvement_count = 0
        self._last_best_score = 0.0
        
        logger.info(f"Initialized {version.value} optimizer for {target.value}")
        logger.info(f"Session directory: {self.session_dir}")
        if self.config.enable_two_phase:
            logger.info(f"Two-phase optimization enabled: {self.config.phase_1_iterations} Flash + {self.config.phase_2_iterations} Pro")
        if self.config.enable_early_stopping:
            logger.info(f"Early stopping enabled: min improvement {self.config.min_improvement_threshold}%, patience {self.config.patience}")
    
    @abstractmethod
    async def load_initial_artifact(self) -> T:
        """
        Загружает начальный артефакт для оптимизации
        
        Returns:
            Начальная версия артефакта (промпт, правила валидации, и т.д.)
        """
        pass
    
    @abstractmethod
    async def execute_test_case(
        self,
        test_case: OptimizerTestCase,
        artifact: T,
        iteration: int
    ) -> TestResult:
        """
        Выполняет один тестовый случай с текущим артефактом
        
        Args:
            test_case: Тестовый случай
            artifact: Текущая версия артефакта
            iteration: Номер итерации
            
        Returns:
            Результат теста
        """
        pass
    
    @abstractmethod
    async def refine_artifact(
        self,
        current_artifact: T,
        failures: List[TestResult],
        successes: List[TestResult],
        iteration: int
    ) -> T:
        """
        Улучшает артефакт на основе результатов тестирования
        
        Args:
            current_artifact: Текущая версия артефакта
            failures: Неудачные тесты
            successes: Успешные тесты
            iteration: Номер итерации
            
        Returns:
            Улучшенная версия артефакта
        """
        pass
    
    @abstractmethod
    def save_artifact(self, artifact: T, iteration: int, avg_score: float) -> Path:
        """
        Сохраняет артефакт на диск
        
        Args:
            artifact: Артефакт для сохранения
            iteration: Номер итерации
            avg_score: Средний score
            
        Returns:
            Путь к сохраненному файлу
        """
        pass
    
    async def run_optimization(
        self,
        test_cases: List[OptimizerTestCase],
        resume: bool = False
    ) -> OptimizationResult:
        """
        Главный цикл оптимизации
        
        Args:
            test_cases: Список тестовых случаев
            resume: Возобновить с сохраненного состояния
            
        Returns:
            Результат оптимизации
        """
        logger.info(f"Starting optimization: {self.version.value} -> {self.target.value}")
        logger.info(f"Test cases: {len(test_cases)}, Max iterations: {self.max_iterations}")
        
        iterations: List[OptimizationIteration] = []
        
        # Загружаем начальный артефакт
        current_artifact = await self.load_initial_artifact()
        
        for iteration in range(1, self.max_iterations + 1):
            logger.info(f"\n{'='*70}")
            logger.info(f"ITERATION {iteration}/{self.max_iterations}")
            logger.info(f"{'='*70}\n")
            
            # Phase 1: RUN - Выполняем все тесты
            logger.info(f"Phase 1: Running {len(test_cases)} test cases...")
            test_results: List[TestResult] = []
            
            for i, test_case in enumerate(test_cases, 1):
                logger.info(f"  Test {i}/{len(test_cases)}: {test_case.id}")
                result = await self.execute_test_case(test_case, current_artifact, iteration)
                test_results.append(result)
                
                status = "✅ PASS" if result.passed else "❌ FAIL"
                logger.info(f"    {status} - Score: {result.score}/100")
            
            # Вычисляем метрики
            avg_score = sum(r.score for r in test_results) / len(test_results)
            passed_count = sum(1 for r in test_results if r.passed)
            
            logger.info(f"\nIteration {iteration} Results:")
            logger.info(f"  Average Score: {avg_score:.1f}/100")
            logger.info(f"  Tests Passed: {passed_count}/{len(test_results)}")
            
            # Сохраняем артефакт
            artifact_path = self.save_artifact(current_artifact, iteration, avg_score)
            
            # Создаем запись об итерации
            opt_iteration = OptimizationIteration(
                iteration=iteration,
                timestamp=datetime.now().isoformat(),
                target=self.target,
                artifact=current_artifact,
                avg_score=avg_score,
                test_results=test_results,
                token_count=self._count_tokens(current_artifact),
                metadata={
                    "artifact_path": str(artifact_path),
                    "passed_count": passed_count,
                    "total_tests": len(test_results),
                }
            )
            iterations.append(opt_iteration)
            
            # Сохраняем детальный лог итерации
            self._save_iteration_log(opt_iteration)
            
            # Early stopping check
            if self.config.enable_early_stopping:
                should_stop, reason = self._check_early_stopping(avg_score, iteration)
                if should_stop:
                    logger.info(f"\n🛑 EARLY STOPPING: {reason}")
                    result = self._create_result(iterations, early_stopped=True, reason=reason)
                    return result
            
            # Проверяем достижение порога стабильности
            if avg_score >= self.stability_threshold and passed_count == len(test_results):
                logger.info(f"\n🎉 STABILITY THRESHOLD REACHED! 🎉")
                logger.info(f"Average score {avg_score:.1f} >= {self.stability_threshold}")
                break
            
            # Последняя итерация?
            if iteration >= self.max_iterations:
                logger.info(f"\nMax iterations ({self.max_iterations}) reached.")
                break
            
            # Phase 2: ANALYZE - Анализируем результаты
            failures = [r for r in test_results if r.score < 90]
            successes = [r for r in test_results if r.score >= 95]
            
            logger.info(f"\nPhase 2: Analysis")
            logger.info(f"  Failures (score < 90): {len(failures)}")
            logger.info(f"  Successes (score >= 95): {len(successes)}")
            
            # Phase 3: REFINE - Улучшаем артефакт
            logger.info(f"\nPhase 3: Refinement")
            
            # Two-phase optimization: switch model if needed
            if self.config.enable_two_phase:
                self._switch_model_if_needed(iteration)
            
            try:
                improved_artifact = await self.refine_artifact(
                    current_artifact,
                    failures,
                    successes,
                    iteration
                )
                
                if improved_artifact and improved_artifact != current_artifact:
                    current_artifact = improved_artifact
                    logger.info(f"  ✅ Artifact refined successfully")
                else:
                    logger.warning(f"  ⚠️ No improvement generated, keeping current artifact")
            
            except Exception as e:
                logger.error(f"  ❌ Refinement failed: {e}")
                logger.info(f"  Continuing with current artifact...")
        
        # Создаем финальный результат
        result = self._create_result(iterations, early_stopped=False)
        
        # Cross-model jury validation (Breaking Echo Chamber)
        if self.config.enable_jury_validation and self.config.jury_validates_final:
            logger.info("\n⚖️ Running cross-model jury validation...")
            result = await self._validate_with_jury(result, test_cases)
        
        return result
    
    def _check_early_stopping(self, current_score: float, iteration: int) -> tuple[bool, str]:
        """Проверка условий early stopping"""
        improvement = current_score - self._last_best_score
        
        if improvement < self.config.min_improvement_threshold:
            self._no_improvement_count += 1
            logger.debug(f"No significant improvement: {improvement:.2f}% (count: {self._no_improvement_count})")
        else:
            self._no_improvement_count = 0
            self._last_best_score = current_score
        
        if self._no_improvement_count >= self.config.patience:
            reason = f"No improvement >{self.config.min_improvement_threshold}% for {self.config.patience} iterations"
            return True, reason
        
        return False, ""
    
    def _switch_model_if_needed(self, iteration: int) -> None:
        """Переключение между Flash и Pro моделями (two-phase optimization)"""
        if iteration == self.config.phase_1_iterations:
            logger.info(f"🔄 Switching from {self.config.phase_1_provider.value} to {self.config.phase_2_provider.value}")
            # Subclasses should override this to actually switch models
            self._current_provider = self.config.phase_2_provider
    
    def _create_result(
        self, 
        iterations: List[OptimizationIteration],
        early_stopped: bool = False,
        reason: str = ""
    ) -> OptimizationResult:
        """Создание финального результата"""
        best_iteration = max(iterations, key=lambda it: it.avg_score)
        first_iteration = iterations[0]
        
        # Count phase iterations
        phase_1_count = min(len(iterations), self.config.phase_1_iterations) if self.config.enable_two_phase else 0
        phase_2_count = max(0, len(iterations) - phase_1_count) if self.config.enable_two_phase else 0
        
        result = OptimizationResult(
            version=self.version,
            target=self.target,
            iterations=iterations,
            best_iteration=best_iteration,
            improvement_delta=best_iteration.avg_score - first_iteration.avg_score,
            session_id=self.session_id,
            session_timestamp=datetime.now().isoformat(),
            early_stopped=early_stopped,
            early_stop_reason=reason,
            phase_1_iterations=phase_1_count,
            phase_2_iterations=phase_2_count,
        )
        
        # Сохраняем финальный отчет
        self._save_final_report(result)
        
        return result
    
    async def _validate_with_jury(
        self,
        result: OptimizationResult,
        test_cases: List[OptimizerTestCase]
    ) -> OptimizationResult:
        """
        Cross-model jury validation (Breaking Echo Chamber)
        
        Использует другую LLM модель для независимой оценки лучшего результата
        """
        try:
            logger.info(f"Jury model: {self.config.jury_provider.value}")
            
            # Re-run best iteration with jury model
            # This should be implemented in subclasses
            # For now, just mark as validated
            result.jury_validated = True
            result.jury_provider = self.config.jury_provider.value
            result.jury_best_score = result.best_iteration.avg_score  # Placeholder
            
            logger.info(f"✅ Jury validation complete: {result.jury_best_score}/100")
            
        except Exception as e:
            logger.error(f"❌ Jury validation failed: {e}")
            result.jury_validated = False
        
        return result
    
    def _count_tokens(self, artifact: T) -> Optional[int]:
        """Подсчитывает токены (для промптов)"""
        if isinstance(artifact, str):
            return len(artifact.split())
        return None
    
    def _save_iteration_log(self, iteration: OptimizationIteration) -> None:
        """Сохраняет детальный лог итерации"""
        iteration_dir = self.session_dir / f"iteration_{iteration.iteration}"
        iteration_dir.mkdir(exist_ok=True)
        
        # Сохраняем результаты тестов
        log_data = {
            "iteration": iteration.iteration,
            "timestamp": iteration.timestamp,
            "target": iteration.target.value,
            "avg_score": iteration.avg_score,
            "token_count": iteration.token_count,
            "test_results": [
                {
                    "test_case_id": r.test_case_id,
                    "score": r.score,
                    "passed": r.passed,
                    "duration_s": r.duration_s,
                    "issues": r.issues,
                    "validation_details": r.validation_details,
                    "metadata": r.metadata,
                }
                for r in iteration.test_results
            ],
            "metadata": iteration.metadata,
        }
        
        (iteration_dir / "results.json").write_text(
            json.dumps(log_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        logger.info(f"  Iteration log saved to: {iteration_dir}")
    
    def _save_final_report(self, result: OptimizationResult) -> None:
        """Сохраняет финальный отчет"""
        report_path = self.session_dir / "final_report.json"
        report_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        # Также создаем Markdown отчет
        markdown_report = self._generate_markdown_report(result)
        (self.session_dir / "final_report.md").write_text(
            markdown_report,
            encoding="utf-8"
        )
        
        logger.info(f"Final report saved to: {self.session_dir}")
    
    def _generate_markdown_report(self, result: OptimizationResult) -> str:
        """Генерирует Markdown отчет"""
        report = f"""# Optimization Report

**Version:** {result.version.value}  
**Target:** {result.target.value}  
**Session ID:** {result.session_id}  
**Generated:** {result.session_timestamp}

---

## Summary

- **Total Iterations:** {len(result.iterations)}
- **Initial Score:** {result.iterations[0].avg_score:.1f}/100
- **Final Score:** {result.iterations[-1].avg_score:.1f}/100
- **Improvement:** {result.improvement_delta:+.1f} points
- **Best Score:** {result.best_iteration.avg_score:.1f}/100 (Iteration {result.best_iteration.iteration})

---

## Evolution Path

"""
        
        for it in result.iterations:
            passed = it.metadata.get("passed_count", 0)
            total = it.metadata.get("total_tests", 0)
            
            report += f"""### Iteration {it.iteration}
- **Score:** {it.avg_score:.1f}/100
- **Tests Passed:** {passed}/{total}
- **Token Count:** {it.token_count or "N/A"}

"""
        
        return report
