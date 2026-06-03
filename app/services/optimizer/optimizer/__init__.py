"""
Optimizer System - Multi-version optimization framework

Поддерживает оптимизацию различных компонентов:
- Промпты (ContentCreator, Planner, Validator)
- Валидационные правила
- Параметры пайплайна

Версионирование позволяет запускать разные стратегии оптимизации
без уничтожения старого кода.

Quick Start:
    # V1: Optimize prompt only
    from app.services.optimizer.optimizer import optimize_prompt, OptimizationTarget
    result = await optimize_prompt(
        target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
        max_iterations=5
    )
    
    # V2: Optimize validation only
    from app.services.optimizer.optimizer import optimize_validation
    result = await optimize_validation(max_iterations=5)
    
    # V2: Optimize both
    from app.services.optimizer.optimizer import optimize_both
    result = await optimize_both(max_iterations=10)
    
    # Full control
    from app.services.optimizer.optimizer import OptimizerManager, OptimizerVersion
    manager = OptimizerManager()
    result = await manager.run_optimization(
        version=OptimizerVersion.V2_PROMPT_VALIDATION,
        target=OptimizationTarget.PROMPT_CONTENT_CREATOR
    )
"""

from .base import (
    BaseOptimizer,
    OptimizationTarget,
    OptimizationResult,
    OptimizerVersion,
    OptimizerTestCase,
    TestResult,
    OptimizationIteration,
    OptimizationConfig,
    LLMProvider,
    # Language schemas
    LANGUAGE_SCHEMAS,
    LATIN_ALPHABET_LANGUAGES,
    get_language_schema,
    validate_language_fields,
)

# Backward compatibility alias
TestCase = OptimizerTestCase
from .manager import (
    OptimizerManager,
    optimize_prompt,
    optimize_validation,
    optimize_both,
)
from .optimizer_v1 import OptimizerV1
from .optimizer_v2 import OptimizerV2
from .testing import (
    TestCaseLoader,
    TestResultAnalyzer,
    ValidationTestBuilder,
    OptimizationReportGenerator,
)

from .pedagogical import (
    SynonymExpander,
    LLMSynonymExpander,
    expand_lesson_vocabulary_sync,
)

__all__ = [
    # Core classes
    "BaseOptimizer",
    "OptimizationTarget",
    "OptimizationResult",
    "OptimizerVersion",
    "OptimizerTestCase",
    "TestCase",  # Backward compatibility
    "TestResult",
    "OptimizationIteration",
    "OptimizationConfig",
    "LLMProvider",
    
    # Language schemas (Linguistic Integrity)
    "LANGUAGE_SCHEMAS",
    "LATIN_ALPHABET_LANGUAGES",
    "get_language_schema",
    "validate_language_fields",
    
    # Manager
    "OptimizerManager",
    
    # Convenience functions
    "optimize_prompt",
    "optimize_validation",
    "optimize_both",
    
    # Optimizer implementations
    "OptimizerV1",
    "OptimizerV2",
    
    # Testing utilities
    "TestCaseLoader",
    "TestResultAnalyzer",
    "ValidationTestBuilder",
    "OptimizationReportGenerator",
    
    # Pedagogical utilities
    "SynonymExpander",
    "LLMSynonymExpander",
    "expand_lesson_vocabulary_sync",
]

