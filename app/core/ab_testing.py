"""
Automated A/B testing framework for continuous improvement.
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict

from app.models.api import DiagnosticGenerateRequest, DiagnosticBlueprint
from app.core.interfaces.database import DatabaseProtocol


@dataclass
class ABTestResult:
    """Result of an A/B test run."""
    test_id: str
    variant_a: str
    variant_b: str
    timestamp: str
    
    # Variant A results
    a_duration_ms: float
    a_token_count: int
    a_item_count: int
    a_success: bool
    
    # Variant B results  
    b_duration_ms: float
    b_token_count: int
    b_item_count: int
    b_success: bool
    
    # Comparison
    duration_improvement_pct: float
    token_reduction_pct: float
    
    # Optional fields with defaults
    a_error: Optional[str] = None
    b_error: Optional[str] = None
    winner: Optional[str] = None


@dataclass
class ABTestSummary:
    """Summary of multiple A/B test runs."""
    test_id: str
    variant_a: str
    variant_b: str
    total_runs: int
    successful_runs: int
    
    # Average metrics
    avg_a_duration_ms: float
    avg_b_duration_ms: float
    avg_a_tokens: float
    avg_b_tokens: float
    
    # Win rates
    b_faster_count: int
    b_fewer_tokens_count: int
    
    # Overall verdict
    avg_duration_improvement_pct: float
    avg_token_reduction_pct: float
    recommended_winner: str


class ABTestRunner:
    """Run automated A/B tests comparing different configurations."""
    
    def __init__(self, db: DatabaseProtocol):
        self.db = db
        self._ensure_tables()
    
    def _ensure_tables(self):
        """Create A/B test results table."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS ab_test_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id TEXT NOT NULL,
                variant_a TEXT NOT NULL,
                variant_b TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                
                a_duration_ms REAL NOT NULL,
                a_token_count INTEGER NOT NULL,
                a_item_count INTEGER NOT NULL,
                a_success INTEGER NOT NULL,
                a_error TEXT,
                
                b_duration_ms REAL NOT NULL,
                b_token_count INTEGER NOT NULL,
                b_item_count INTEGER NOT NULL,
                b_success INTEGER NOT NULL,
                b_error TEXT,
                
                duration_improvement_pct REAL,
                token_reduction_pct REAL,
                winner TEXT,
                
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_ab_test_id 
            ON ab_test_results(test_id)
        """)
    
    def run_single_test(
        self,
        test_id: str,
        variant_a_config: Dict[str, Any],
        variant_b_config: Dict[str, Any],
        test_request: DiagnosticGenerateRequest
    ) -> ABTestResult:
        """
        Run a single A/B test comparing two variants.
        
        Args:
            test_id: Unique identifier for this test
            variant_a_config: Configuration for variant A (baseline)
            variant_b_config: Configuration for variant B (new version)
            test_request: Diagnostic generation request to test with
            
        Returns:
            ABTestResult with comparison metrics
        """
        from app.services.diagnostic import engine as diagnostic_engine
        
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Run variant A
        logging.info(f"🧪 A/B Test '{test_id}': Running variant A - {variant_a_config.get('name', 'baseline')}")
        a_start = time.perf_counter()
        a_success = True
        a_error = None
        a_token_count = 0
        a_item_count = 0
        
        try:
            a_response = diagnostic_engine.generate_diagnostic_items(
                request=test_request,
                user_id="ab_test_runner",
                persona_id_override=variant_a_config.get('persona_id'),
                optimize_mode=variant_a_config.get('optimize_mode', False)
            )
            a_item_count = len(a_response.diagnosticSet.items)
            # Estimate tokens (rough approximation)
            a_token_count = sum(len(item.prompt.split()) * 1.3 for item in a_response.diagnosticSet.items)
        except Exception as e:
            a_success = False
            a_error = str(e)
            logging.error(f"Variant A failed: {e}")
        
        a_duration_ms = (time.perf_counter() - a_start) * 1000
        
        # Run variant B
        logging.info(f"🧪 A/B Test '{test_id}': Running variant B - {variant_b_config.get('name', 'new version')}")
        b_start = time.perf_counter()
        b_success = True
        b_error = None
        b_token_count = 0
        b_item_count = 0
        
        try:
            b_response = diagnostic_engine.generate_diagnostic_items(
                request=test_request,
                user_id="ab_test_runner",
                persona_id_override=variant_b_config.get('persona_id'),
                optimize_mode=variant_b_config.get('optimize_mode', False)
            )
            b_item_count = len(b_response.diagnosticSet.items)
            b_token_count = sum(len(item.prompt.split()) * 1.3 for item in b_response.diagnosticSet.items)
        except Exception as e:
            b_success = False
            b_error = str(e)
            logging.error(f"Variant B failed: {e}")
        
        b_duration_ms = (time.perf_counter() - b_start) * 1000
        
        # Calculate improvements
        duration_improvement = 0.0
        token_reduction = 0.0
        winner = None
        
        if a_success and b_success:
            if a_duration_ms > 0:
                duration_improvement = ((a_duration_ms - b_duration_ms) / a_duration_ms) * 100
            if a_token_count > 0:
                token_reduction = ((a_token_count - b_token_count) / a_token_count) * 100
            
            # Determine winner (weighted: 60% duration, 40% tokens)
            combined_score_b = (duration_improvement * 0.6) + (token_reduction * 0.4)
            if combined_score_b > 5:  # At least 5% combined improvement
                winner = 'B'
            elif combined_score_b < -5:
                winner = 'A'
            else:
                winner = 'tie'
        elif a_success:
            winner = 'A'
        elif b_success:
            winner = 'B'
        
        result = ABTestResult(
            test_id=test_id,
            variant_a=variant_a_config.get('name', 'A'),
            variant_b=variant_b_config.get('name', 'B'),
            timestamp=timestamp,
            a_duration_ms=a_duration_ms,
            a_token_count=int(a_token_count),
            a_item_count=a_item_count,
            a_success=a_success,
            a_error=a_error,
            b_duration_ms=b_duration_ms,
            b_token_count=int(b_token_count),
            b_item_count=b_item_count,
            b_success=b_success,
            b_error=b_error,
            duration_improvement_pct=duration_improvement,
            token_reduction_pct=token_reduction,
            winner=winner
        )
        
        # Save result
        self._save_result(result)
        
        logging.info(f"✅ A/B Test complete: Winner={winner}, Duration Δ={duration_improvement:.1f}%, Tokens Δ={token_reduction:.1f}%")
        
        return result
    
    def _save_result(self, result: ABTestResult):
        """Save test result to database."""
        self.db.execute("""
            INSERT INTO ab_test_results (
                test_id, variant_a, variant_b, timestamp,
                a_duration_ms, a_token_count, a_item_count, a_success, a_error,
                b_duration_ms, b_token_count, b_item_count, b_success, b_error,
                duration_improvement_pct, token_reduction_pct, winner
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.test_id, result.variant_a, result.variant_b, result.timestamp,
            result.a_duration_ms, result.a_token_count, result.a_item_count,
            1 if result.a_success else 0, result.a_error,
            result.b_duration_ms, result.b_token_count, result.b_item_count,
            1 if result.b_success else 0, result.b_error,
            result.duration_improvement_pct, result.token_reduction_pct, result.winner
        ))
    
    def get_test_summary(self, test_id: str) -> Optional[ABTestSummary]:
        """Get summary of all runs for a specific test."""
        rows = self.db.fetchall("""
            SELECT * FROM ab_test_results 
            WHERE test_id = ? AND a_success = 1 AND b_success = 1
            ORDER BY timestamp DESC
        """, (test_id,))
        
        if not rows:
            return None
        
        total_runs = len(rows)
        
        # Calculate averages
        avg_a_duration = sum(r['a_duration_ms'] for r in rows) / total_runs
        avg_b_duration = sum(r['b_duration_ms'] for r in rows) / total_runs
        avg_a_tokens = sum(r['a_token_count'] for r in rows) / total_runs
        avg_b_tokens = sum(r['b_token_count'] for r in rows) / total_runs
        
        # Count wins
        b_faster = sum(1 for r in rows if r['b_duration_ms'] < r['a_duration_ms'])
        b_fewer_tokens = sum(1 for r in rows if r['b_token_count'] < r['a_token_count'])
        
        # Overall improvements
        avg_duration_improvement = ((avg_a_duration - avg_b_duration) / avg_a_duration) * 100 if avg_a_duration > 0 else 0
        avg_token_reduction = ((avg_a_tokens - avg_b_tokens) / avg_a_tokens) * 100 if avg_a_tokens > 0 else 0
        
        # Determine winner
        combined_score = (avg_duration_improvement * 0.6) + (avg_token_reduction * 0.4)
        if combined_score > 5:
            winner = rows[0]['variant_b']
        elif combined_score < -5:
            winner = rows[0]['variant_a']
        else:
            winner = 'inconclusive'
        
        return ABTestSummary(
            test_id=test_id,
            variant_a=rows[0]['variant_a'],
            variant_b=rows[0]['variant_b'],
            total_runs=total_runs,
            successful_runs=total_runs,
            avg_a_duration_ms=avg_a_duration,
            avg_b_duration_ms=avg_b_duration,
            avg_a_tokens=avg_a_tokens,
            avg_b_tokens=avg_b_tokens,
            b_faster_count=b_faster,
            b_fewer_tokens_count=b_fewer_tokens,
            avg_duration_improvement_pct=avg_duration_improvement,
            avg_token_reduction_pct=avg_token_reduction,
            recommended_winner=winner
        )


def create_standard_test_blueprint() -> List[DiagnosticBlueprint]:
    """Create a standard test blueprint for A/B testing."""
    return [
        DiagnosticBlueprint(
            skill="vocabulary",
            subskill="basic",
            topic="daily_life",
            difficulty=0.5,
            taskType="mcq",
            cefrBand="A2"
        ),
        DiagnosticBlueprint(
            skill="grammar",
            subskill="tenses",
            topic="present_simple",
            difficulty=0.4,
            taskType="fill_blank",
            cefrBand="A2"
        ),
        DiagnosticBlueprint(
            skill="vocabulary",
            subskill="intermediate",
            topic="work",
            difficulty=0.6,
            taskType="mcq",
            cefrBand="B1"
        )
    ]



