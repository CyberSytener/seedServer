"""
Optimizer Manager - Central orchestration for all optimizer versions

Provides:
- Version selection and instantiation
- Unified interface for running optimizations
- Cross-version comparison
- Session management
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Type

from .base import (
    BaseOptimizer,
    OptimizationTarget,
    OptimizerVersion,
    OptimizationResult,
    OptimizerTestCase,
)
from .optimizer_v1 import OptimizerV1
from .optimizer_v2 import OptimizerV2
from .testing import TestCaseLoader, TestResultAnalyzer, OptimizationReportGenerator

logger = logging.getLogger(__name__)


# ============================================================================
# OPTIMIZER MANAGER
# ============================================================================

class OptimizerManager:
    """
    Central manager for all optimizer versions
    
    Usage:
        manager = OptimizerManager()
        
        # Run V1 (prompt only)
        result_v1 = await manager.run_optimization(
            version=OptimizerVersion.V1_PROMPT_ONLY,
            target=OptimizationTarget.PROMPT_CONTENT_CREATOR
        )
        
        # Run V2 (prompt + validation)
        result_v2 = await manager.run_optimization(
            version=OptimizerVersion.V2_PROMPT_VALIDATION,
            target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
            optimize_validation=True
        )
    """
    
    def __init__(self, base_output_dir: Optional[Path] = None):
        """
        Initialize optimizer manager
        
        Args:
            base_output_dir: Base directory for all optimizer outputs
        """
        if base_output_dir is None:
            base_output_dir = Path(__file__).parent.parent.parent / "optimizer_logs"
        
        self.base_output_dir = base_output_dir
        self.base_output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"OptimizerManager initialized, output dir: {base_output_dir}")
    
    def get_optimizer(
        self,
        version: OptimizerVersion,
        target: OptimizationTarget,
        **kwargs
    ) -> BaseOptimizer:
        """
        Get optimizer instance for specified version
        
        Args:
            version: Optimizer version to use
            target: Optimization target
            **kwargs: Version-specific parameters
            
        Returns:
            Configured optimizer instance
        """
        output_dir = self.base_output_dir / version.value
        
        if version == OptimizerVersion.V1_PROMPT_ONLY:
            return OptimizerV1(
                target=target,
                output_dir=output_dir,
                stability_threshold=kwargs.get("stability_threshold", 95.0),
                max_iterations=kwargs.get("max_iterations", 10),
                token_limit=kwargs.get("token_limit", 1500),
            )
        
        elif version == OptimizerVersion.V2_PROMPT_VALIDATION:
            return OptimizerV2(
                target=target,
                output_dir=output_dir,
                stability_threshold=kwargs.get("stability_threshold", 95.0),
                max_iterations=kwargs.get("max_iterations", 10),
                optimize_prompt=kwargs.get("optimize_prompt", True),
                optimize_validation=kwargs.get("optimize_validation", True),
            )
        
        elif version == OptimizerVersion.V3_MULTI_TARGET:
            raise NotImplementedError("V3 optimizer not yet implemented")
        
        else:
            raise ValueError(f"Unknown optimizer version: {version}")
    
    async def run_optimization(
        self,
        version: OptimizerVersion,
        target: OptimizationTarget,
        test_cases: Optional[List[OptimizerTestCase]] = None,
        test_cases_file: Optional[Path] = None,
        **kwargs
    ) -> OptimizationResult:
        """
        Run optimization with specified version
        
        Args:
            version: Optimizer version to use
            target: What to optimize
            test_cases: Test cases to use (optional)
            test_cases_file: Path to test cases JSON file (optional)
            **kwargs: Version-specific parameters
            
        Returns:
            Optimization result
        """
        logger.info(f"Starting optimization: {version.value} -> {target.value}")
        
        # Load test cases
        if test_cases is None:
            if test_cases_file and test_cases_file.exists():
                test_cases = TestCaseLoader.load_from_file(test_cases_file)
            else:
                logger.info("No test cases provided, using standard suite")
                test_cases = TestCaseLoader.create_standard_suite()
        
        # Get optimizer instance
        optimizer = self.get_optimizer(version, target, **kwargs)
        
        # Run optimization
        result = await optimizer.run_optimization(
            test_cases=test_cases,
            resume=kwargs.get("resume", False)
        )
        
        # Generate HTML report
        OptimizationReportGenerator.generate_html_report(
            session_dir=optimizer.session_dir,
            optimization_result=result
        )
        
        logger.info(f"Optimization complete: {result.session_id}")
        logger.info(f"Final score: {result.best_iteration.avg_score:.1f}/100")
        logger.info(f"Improvement: {result.improvement_delta:+.1f} points")
        logger.info(f"Session dir: {optimizer.session_dir}")
        
        return result
    
    async def compare_versions(
        self,
        versions: List[OptimizerVersion],
        target: OptimizationTarget,
        test_cases: List[OptimizerTestCase],
        **kwargs
    ) -> Dict[str, OptimizationResult]:
        """
        Compare multiple optimizer versions on same test cases
        
        Args:
            versions: List of versions to compare
            target: Optimization target
            test_cases: Test cases to use
            **kwargs: Shared parameters
            
        Returns:
            Dictionary mapping version to result
        """
        logger.info(f"Running version comparison: {[v.value for v in versions]}")
        
        results = {}
        
        for version in versions:
            logger.info(f"\n{'='*70}")
            logger.info(f"Running {version.value}")
            logger.info(f"{'='*70}\n")
            
            result = await self.run_optimization(
                version=version,
                target=target,
                test_cases=test_cases,
                **kwargs
            )
            
            results[version.value] = result
        
        # Generate comparison report
        self._generate_comparison_report(results)
        
        return results
    
    def _generate_comparison_report(
        self,
        results: Dict[str, OptimizationResult]
    ) -> Path:
        """Generate comparison report for multiple versions"""
        comparison_dir = self.base_output_dir / "comparisons"
        comparison_dir.mkdir(exist_ok=True)
        
        timestamp = int(time.time())
        report_path = comparison_dir / f"comparison_{timestamp}.md"
        
        report = f"""# Optimizer Version Comparison

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**Versions Compared:** {len(results)}

---

## Summary

"""
        
        # Create summary table
        report += "| Version | Final Score | Improvement | Iterations |\n"
        report += "|---------|-------------|-------------|------------|\n"
        
        for version_str, result in results.items():
            report += (
                f"| {version_str} | "
                f"{result.best_iteration.avg_score:.1f}/100 | "
                f"{result.improvement_delta:+.1f} | "
                f"{len(result.iterations)} |\n"
            )
        
        report += "\n---\n\n"
        
        # Detailed results for each version
        for version_str, result in results.items():
            report += f"""## {version_str}

- **Session ID:** {result.session_id}
- **Target:** {result.target.value}
- **Initial Score:** {result.iterations[0].avg_score:.1f}/100
- **Final Score:** {result.iterations[-1].avg_score:.1f}/100
- **Best Score:** {result.best_iteration.avg_score:.1f}/100
- **Total Improvement:** {result.improvement_delta:+.1f} points

"""
        
        report_path.write_text(report, encoding="utf-8")
        logger.info(f"Comparison report saved: {report_path}")
        
        return report_path
    
    def list_sessions(self, version: Optional[OptimizerVersion] = None) -> List[Path]:
        """
        List all optimization sessions
        
        Args:
            version: Filter by version (optional)
            
        Returns:
            List of session directories
        """
        if version:
            version_dir = self.base_output_dir / version.value
            if not version_dir.exists():
                return []
            
            sessions = [
                d for d in version_dir.iterdir()
                if d.is_dir() and d.name.startswith(version.value)
            ]
        else:
            sessions = []
            for version_dir in self.base_output_dir.iterdir():
                if version_dir.is_dir():
                    sessions.extend([
                        d for d in version_dir.iterdir()
                        if d.is_dir()
                    ])
        
        # Sort by timestamp (newest first)
        sessions.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        
        return sessions
    
    def get_session_summary(self, session_dir: Path) -> Dict[str, Any]:
        """
        Get summary of an optimization session
        
        Args:
            session_dir: Path to session directory
            
        Returns:
            Session summary dict
        """
        report_file = session_dir / "final_report.json"
        
        if not report_file.exists():
            return {"error": "No final report found"}
        
        import json
        return json.loads(report_file.read_text(encoding="utf-8"))


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

async def optimize_prompt(
    target: OptimizationTarget = OptimizationTarget.PROMPT_CONTENT_CREATOR,
    max_iterations: int = 5,
    test_cases_file: Optional[Path] = None
) -> OptimizationResult:
    """
    Quick function to optimize a prompt (uses V1)
    
    Args:
        target: Which prompt to optimize
        max_iterations: Maximum iterations
        test_cases_file: Optional test cases file
        
    Returns:
        Optimization result
    """
    manager = OptimizerManager()
    return await manager.run_optimization(
        version=OptimizerVersion.V1_PROMPT_ONLY,
        target=target,
        max_iterations=max_iterations,
        test_cases_file=test_cases_file
    )


async def optimize_validation(
    max_iterations: int = 5,
    test_cases_file: Optional[Path] = None
) -> OptimizationResult:
    """
    Quick function to optimize validation rules (uses V2)
    
    Args:
        max_iterations: Maximum iterations
        test_cases_file: Optional test cases file
        
    Returns:
        Optimization result
    """
    manager = OptimizerManager()
    return await manager.run_optimization(
        version=OptimizerVersion.V2_PROMPT_VALIDATION,
        target=OptimizationTarget.VALIDATION_RULES,
        max_iterations=max_iterations,
        test_cases_file=test_cases_file,
        optimize_prompt=False,
        optimize_validation=True
    )


async def optimize_both(
    max_iterations: int = 5,
    test_cases_file: Optional[Path] = None
) -> OptimizationResult:
    """
    Quick function to optimize both prompt and validation (uses V2)
    
    Args:
        max_iterations: Maximum iterations
        test_cases_file: Optional test cases file
        
    Returns:
        Optimization result
    """
    manager = OptimizerManager()
    return await manager.run_optimization(
        version=OptimizerVersion.V2_PROMPT_VALIDATION,
        target=OptimizationTarget.PROMPT_CONTENT_CREATOR,
        max_iterations=max_iterations,
        test_cases_file=test_cases_file,
        optimize_prompt=True,
        optimize_validation=True
    )


# Import for type hints
import time
from datetime import datetime
from typing import Dict, Any

