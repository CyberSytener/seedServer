"""
Test Infrastructure for Optimizer System

Предоставляет:
- Загрузку и управление тестовыми случаями
- Утилиты для создания тестовых наборов
- Генерацию тестовых отчетов
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from .base import OptimizerTestCase, TestResult

logger = logging.getLogger(__name__)


# ============================================================================
# TEST CASE LOADER
# ============================================================================

class TestCaseLoader:
    """Manages loading and creation of test cases"""
    
    @staticmethod
    def load_from_file(filepath: Path) -> List[OptimizerTestCase]:
        """Load test cases from JSON file"""
        if not filepath.exists():
            raise FileNotFoundError(f"Test cases file not found: {filepath}")
        
        data = json.loads(filepath.read_text(encoding="utf-8"))
        test_cases = []
        
        for tc_data in data.get("test_cases", []):
            test_cases.append(OptimizerTestCase(**tc_data))
        
        logger.info(f"Loaded {len(test_cases)} test cases from {filepath}")
        return test_cases
    
    @staticmethod
    def create_standard_suite() -> List[OptimizerTestCase]:
        """Create a standard test suite for optimization"""
        return [
            # Basic cases - different languages
            OptimizerTestCase(
                id="basic_spanish_a2",
                description="Basic Spanish A2 lesson",
                target_lang="Spanish",
                native_lang="English",
                cefr_level="A2",
                topic="Daily Activities",
                focus="grammar",
                expected_vocab_count=10,
                expected_dialogue_scenes=2,
                min_score=90
            ),
            OptimizerTestCase(
                id="basic_french_b1",
                description="Basic French B1 lesson",
                target_lang="French",
                native_lang="English",
                cefr_level="B1",
                topic="Travel",
                focus="vocabulary",
                expected_vocab_count=10,
                expected_dialogue_scenes=3,
                min_score=90
            ),
            OptimizerTestCase(
                id="basic_japanese_a1",
                description="Basic Japanese A1 lesson",
                target_lang="Japanese",
                native_lang="English",
                cefr_level="A1",
                topic="Greetings",
                focus="pronunciation",
                expected_vocab_count=8,
                expected_dialogue_scenes=2,
                min_score=90
            ),
            
            # Edge cases
            OptimizerTestCase(
                id="edge_complex_german_c1",
                description="Complex German C1 lesson",
                target_lang="German",
                native_lang="English",
                cefr_level="C1",
                topic="Business Communication",
                focus="grammar",
                expected_vocab_count=15,
                expected_dialogue_scenes=4,
                min_score=85
            ),
            OptimizerTestCase(
                id="edge_minimal_italian_a1",
                description="Minimal Italian A1 lesson",
                target_lang="Italian",
                native_lang="English",
                cefr_level="A1",
                topic="Numbers",
                focus="vocabulary",
                expected_vocab_count=8,
                expected_dialogue_scenes=2,
                min_score=85
            ),
            
            # Stress test cases
            OptimizerTestCase(
                id="stress_multi_focus_spanish_b2",
                description="Multi-focus Spanish B2 lesson",
                target_lang="Spanish",
                native_lang="English",
                cefr_level="B2",
                topic="Culture and Traditions",
                focus="grammar+vocabulary+pronunciation",
                expected_vocab_count=12,
                expected_dialogue_scenes=3,
                min_score=80
            ),
        ]
    
    @staticmethod
    def save_test_suite(test_cases: List[OptimizerTestCase], filepath: Path) -> None:
        """Save test cases to JSON file"""
        data = {
            "test_cases": [
                {
                    "id": tc.id,
                    "description": tc.description,
                    "target_lang": tc.target_lang,
                    "native_lang": tc.native_lang,
                    "cefr_level": tc.cefr_level,
                    "topic": tc.topic,
                    "focus": tc.focus,
                    "expected_vocab_count": tc.expected_vocab_count,
                    "expected_dialogue_scenes": tc.expected_dialogue_scenes,
                    "min_score": tc.min_score,
                    "custom_params": tc.custom_params,
                }
                for tc in test_cases
            ]
        }
        
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Saved {len(test_cases)} test cases to {filepath}")


# ============================================================================
# TEST RESULT ANALYZER
# ============================================================================

class TestResultAnalyzer:
    """Analyzes test results and provides insights"""
    
    @staticmethod
    def analyze_results(results: List[TestResult]) -> Dict[str, Any]:
        """Analyze a set of test results"""
        if not results:
            return {"error": "No results to analyze"}
        
        # Basic stats
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        
        avg_score = sum(r.score for r in results) / total
        avg_duration = sum(r.duration_s for r in results) / total
        
        # Issue frequency
        issue_counts = {}
        for result in results:
            for issue in result.issues:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
        
        # Score distribution
        score_ranges = {
            "0-49": 0,
            "50-69": 0,
            "70-84": 0,
            "85-94": 0,
            "95-100": 0,
        }
        
        for result in results:
            score = result.score
            if score < 50:
                score_ranges["0-49"] += 1
            elif score < 70:
                score_ranges["50-69"] += 1
            elif score < 85:
                score_ranges["70-84"] += 1
            elif score < 95:
                score_ranges["85-94"] += 1
            else:
                score_ranges["95-100"] += 1
        
        return {
            "summary": {
                "total_tests": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": (passed / total) * 100,
                "avg_score": avg_score,
                "avg_duration_s": avg_duration,
            },
            "score_distribution": score_ranges,
            "common_issues": sorted(
                issue_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10],
            "recommendations": TestResultAnalyzer._generate_recommendations(
                results,
                issue_counts
            )
        }
    
    @staticmethod
    def _generate_recommendations(
        results: List[TestResult],
        issue_counts: Dict[str, int]
    ) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []
        
        # Check for common issues
        if any("exercise" in issue.lower() for issue in issue_counts.keys()):
            recommendations.append(
                "High frequency of exercise-related issues. "
                "Consider refining exercise generation instructions."
            )
        
        if any("vocabulary" in issue.lower() for issue in issue_counts.keys()):
            recommendations.append(
                "Vocabulary issues detected. "
                "Review vocabulary count constraints and generation quality."
            )
        
        if any("json" in issue.lower() for issue in issue_counts.keys()):
            recommendations.append(
                "JSON structure issues found. "
                "Strengthen JSON formatting instructions in prompt."
            )
        
        # Check for performance issues
        avg_duration = sum(r.duration_s for r in results) / len(results)
        if avg_duration > 30:
            recommendations.append(
                f"Average test duration is high ({avg_duration:.1f}s). "
                "Consider optimizing pipeline or using faster models."
            )
        
        # Check for low pass rate
        pass_rate = sum(1 for r in results if r.passed) / len(results)
        if pass_rate < 0.7:
            recommendations.append(
                f"Low pass rate ({pass_rate*100:.1f}%). "
                "Major prompt or validation refinement needed."
            )
        
        if not recommendations:
            recommendations.append("Results look good! Continue monitoring.")
        
        return recommendations
    
    @staticmethod
    def generate_comparison_report(
        before_results: List[TestResult],
        after_results: List[TestResult]
    ) -> Dict[str, Any]:
        """Compare two sets of results (e.g., before/after optimization)"""
        before_analysis = TestResultAnalyzer.analyze_results(before_results)
        after_analysis = TestResultAnalyzer.analyze_results(after_results)
        
        before_avg = before_analysis["summary"]["avg_score"]
        after_avg = after_analysis["summary"]["avg_score"]
        
        improvement = after_avg - before_avg
        improvement_pct = (improvement / before_avg) * 100 if before_avg > 0 else 0
        
        return {
            "before": before_analysis,
            "after": after_analysis,
            "improvement": {
                "score_delta": improvement,
                "score_delta_pct": improvement_pct,
                "pass_rate_delta": (
                    after_analysis["summary"]["pass_rate"] -
                    before_analysis["summary"]["pass_rate"]
                ),
                "duration_delta_s": (
                    after_analysis["summary"]["avg_duration_s"] -
                    before_analysis["summary"]["avg_duration_s"]
                ),
            },
            "verdict": (
                "IMPROVED" if improvement > 5 else
                "STABLE" if improvement >= -2 else
                "DEGRADED"
            )
        }


# ============================================================================
# VALIDATION TEST BUILDER
# ============================================================================

class ValidationTestBuilder:
    """Builds specialized test cases for validation optimization"""
    
    @staticmethod
    def create_validation_stress_tests() -> List[OptimizerTestCase]:
        """Create test cases specifically for stressing validation"""
        return [
            # Test exercise count validation
            OptimizerTestCase(
                id="val_exercise_count_exact",
                description="Test exact exercise count requirement",
                target_lang="Spanish",
                native_lang="English",
                cefr_level="A2",
                topic="Colors",
                focus="vocabulary",
                expected_vocab_count=10,
                expected_dialogue_scenes=2,
                min_score=95,
                custom_params={"stress_exercise_count": True}
            ),
            
            # Test exercise diversity
            OptimizerTestCase(
                id="val_exercise_diversity",
                description="Test exercise type diversity",
                target_lang="French",
                native_lang="English",
                cefr_level="B1",
                topic="Food",
                focus="vocabulary",
                expected_vocab_count=10,
                expected_dialogue_scenes=2,
                min_score=95,
                custom_params={"stress_exercise_diversity": True}
            ),
            
            # Test vocabulary boundaries
            OptimizerTestCase(
                id="val_vocab_min_boundary",
                description="Test minimum vocabulary count",
                target_lang="German",
                native_lang="English",
                cefr_level="A1",
                topic="Basic Words",
                focus="vocabulary",
                expected_vocab_count=8,
                expected_dialogue_scenes=2,
                min_score=90,
                custom_params={"stress_vocab_min": True}
            ),
            
            OptimizerTestCase(
                id="val_vocab_max_boundary",
                description="Test maximum vocabulary count",
                target_lang="Italian",
                native_lang="English",
                cefr_level="B2",
                topic="Advanced Topics",
                focus="vocabulary",
                expected_vocab_count=15,
                expected_dialogue_scenes=3,
                min_score=90,
                custom_params={"stress_vocab_max": True}
            ),
            
            # Test CEFR appropriateness
            OptimizerTestCase(
                id="val_cefr_a1_simple",
                description="Test CEFR A1 simplicity",
                target_lang="Spanish",
                native_lang="English",
                cefr_level="A1",
                topic="Simple Greetings",
                focus="pronunciation",
                expected_vocab_count=8,
                expected_dialogue_scenes=2,
                min_score=95,
                custom_params={"stress_cefr_appropriateness": True}
            ),
            
            OptimizerTestCase(
                id="val_cefr_c1_complex",
                description="Test CEFR C1 complexity",
                target_lang="French",
                native_lang="English",
                cefr_level="C1",
                topic="Abstract Concepts",
                focus="grammar",
                expected_vocab_count=15,
                expected_dialogue_scenes=4,
                min_score=85,
                custom_params={"stress_cefr_appropriateness": True}
            ),
        ]


# ============================================================================
# REPORT GENERATOR
# ============================================================================

class OptimizationReportGenerator:
    """Generates comprehensive optimization reports"""
    
    @staticmethod
    def generate_html_report(
        session_dir: Path,
        optimization_result: Any  # OptimizationResult
    ) -> Path:
        """Generate HTML report for better visualization"""
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Optimization Report - {optimization_result.version.value}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 20px;
        }}
        .metric {{
            background: white;
            padding: 20px;
            margin: 10px 0;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .iteration {{
            background: white;
            padding: 15px;
            margin: 10px 0;
            border-left: 4px solid #667eea;
            border-radius: 4px;
        }}
        .success {{ color: #10b981; }}
        .warning {{ color: #f59e0b; }}
        .error {{ color: #ef4444; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e5e7eb;
        }}
        th {{
            background: #f9fafb;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 Optimization Report</h1>
        <p><strong>Version:</strong> {optimization_result.version.value}</p>
        <p><strong>Target:</strong> {optimization_result.target.value}</p>
        <p><strong>Session:</strong> {optimization_result.session_id}</p>
    </div>
    
    <div class="metric">
        <h2>📊 Summary</h2>
        <p><strong>Total Iterations:</strong> {len(optimization_result.iterations)}</p>
        <p><strong>Initial Score:</strong> {optimization_result.iterations[0].avg_score:.1f}/100</p>
        <p><strong>Final Score:</strong> {optimization_result.iterations[-1].avg_score:.1f}/100</p>
        <p class="{'success' if optimization_result.improvement_delta > 0 else 'error'}">
            <strong>Improvement:</strong> {optimization_result.improvement_delta:+.1f} points
        </p>
    </div>
    
    <div class="metric">
        <h2>📈 Evolution Path</h2>
"""
        
        for it in optimization_result.iterations:
            passed = it.metadata.get("passed_count", 0)
            total = it.metadata.get("total_tests", 0)
            
            html_content += f"""
        <div class="iteration">
            <h3>Iteration {it.iteration}</h3>
            <p><strong>Score:</strong> {it.avg_score:.1f}/100</p>
            <p><strong>Tests Passed:</strong> {passed}/{total}</p>
            <p><strong>Timestamp:</strong> {it.timestamp}</p>
        </div>
"""
        
        html_content += """
    </div>
</body>
</html>
"""
        
        report_path = session_dir / "report.html"
        report_path.write_text(html_content, encoding="utf-8")
        logger.info(f"Generated HTML report: {report_path}")
        
        return report_path



