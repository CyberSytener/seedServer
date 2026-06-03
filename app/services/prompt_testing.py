"""
Prompt testing system for A/B testing different prompt strategies.

Allows switching between baseline prompts and experimental test prompts
while collecting metrics for comparison.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

# Import settings to access prompt_test_mode flag
from app.settings import get_settings


class PromptType(str, Enum):
    """Types of prompts that can be tested."""
    LESSON_GENERATOR = "lesson_generator"
    DIAGNOSTIC_GENERATOR = "diagnostic_generator"
    LESSON_GRADER = "lesson_grader"
    LESSON_GENERATOR_COMPACT = "lesson_generator_compact"
    DIAGNOSTIC_GENERATOR_COMPACT = "diagnostic_generator_compact"


@dataclass
class PromptTestResult:
    """Result of a prompt test execution."""
    test_id: str
    prompt_type: PromptType
    prompt_version: str  # "baseline" or "test"
    user_id: str
    request_data: Dict[str, Any]
    response_data: Dict[str, Any]
    execution_time_ms: int
    success: bool
    error: Optional[str]
    timestamp: str
    tokens_used: Optional[int] = None
    input_tokens: Optional[int] = None  # New: tokens in prompt + user message
    output_tokens: Optional[int] = None  # New: tokens in AI response
    quality_score: Optional[float] = None  # For future quality assessment


class PromptTestManager:
    """Manages prompt testing and A/B experiments."""
    
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.test_dir = self.base_dir / "test"
        self.results_dir = self.base_dir.parent / "prompt_test_results"
        
        # Ensure directories exist
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        self._current_test_session: Optional[str] = None
        self._test_results: List[PromptTestResult] = []
    
    def is_test_mode_active(self) -> bool:
        """Check if prompt test mode is enabled."""
        settings = get_settings()
        return settings.prompt_test_mode
    
    def get_prompt_content(self, prompt_type: PromptType, use_test_version: bool = False) -> str:
        """
        Get prompt content for specified type.
        
        Args:
            prompt_type: Type of prompt to load
            use_test_version: If True and test mode is active, try to load test version
            
        Returns:
            Prompt content as string
        """
        # Determine file path
        if use_test_version and self.is_test_mode_active():
            # Try test version first
            test_file = self.test_dir / f"{prompt_type.value}.md"
            if test_file.exists():
                logging.info(f"Using TEST version of prompt: {prompt_type.value}")
                return test_file.read_text(encoding="utf-8")
            else:
                logging.warning(f"Test prompt not found: {test_file}, falling back to baseline")
        
        # Use baseline version
        baseline_file = self.base_dir / f"{prompt_type.value}.md"
        if baseline_file.exists():
            logging.info(f"Using BASELINE version of prompt: {prompt_type.value}")
            return baseline_file.read_text(encoding="utf-8")
        else:
            raise FileNotFoundError(f"Baseline prompt not found: {baseline_file}")
    
    def start_test_session(self, session_name: str) -> str:
        """Start a new test session."""
        self._current_test_session = f"{session_name}_{int(time.time())}"
        self._test_results = []
        logging.info(f"Started prompt test session: {self._current_test_session}")
        return self._current_test_session
    
    def log_test_result(self, 
                       prompt_type: PromptType,
                       prompt_version: str,
                       user_id: str,
                       request_data: Dict[str, Any],
                       response_data: Dict[str, Any],
                       execution_time_ms: int,
                       success: bool,
                       error: Optional[str] = None,
                       tokens_used: Optional[int] = None,
                       input_tokens: Optional[int] = None,
                       output_tokens: Optional[int] = None) -> None:
        """Log a test result for analysis."""
        
        if not self.is_test_mode_active():
            return  # Skip logging if not in test mode
            
        test_id = f"{int(time.time())}_{len(self._test_results)}"
        result = PromptTestResult(
            test_id=test_id,
            prompt_type=prompt_type,
            prompt_version=prompt_version,
            user_id=user_id,
            request_data=request_data,
            response_data=response_data,
            execution_time_ms=execution_time_ms,
            success=success,
            error=error,
            timestamp=datetime.now(timezone.utc).isoformat(),
            tokens_used=tokens_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )
        
        self._test_results.append(result)
        
        # Also save to file immediately for persistence
        self._save_result_to_file(result)
        
        logging.info(f"Logged prompt test result: {test_id} ({prompt_type.value}:{prompt_version}) - {execution_time_ms}ms, success={success}")
    
    def _save_result_to_file(self, result: PromptTestResult) -> None:
        """Save individual result to JSON file."""
        session_dir = self.results_dir / (self._current_test_session or "default")
        session_dir.mkdir(exist_ok=True)
        
        result_file = session_dir / f"{result.test_id}.json"
        
        # Convert to dict for JSON serialization
        result_dict = {
            "test_id": result.test_id,
            "prompt_type": result.prompt_type.value,
            "prompt_version": result.prompt_version,
            "user_id": result.user_id,
            "request_data": result.request_data,
            "response_data": result.response_data,
            "execution_time_ms": result.execution_time_ms,
            "success": result.success,
            "error": result.error,
            "timestamp": result.timestamp,
            "tokens_used": result.tokens_used,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "quality_score": result.quality_score
        }
        
        try:
            result_file.write_text(json.dumps(result_dict, indent=2), encoding="utf-8")
        except Exception as e:
            logging.error(f"Failed to save test result to file: {e}")
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of current test session."""
        if not self._test_results:
            return {"session": self._current_test_session, "total_tests": 0}
        
        # Group by prompt type and version
        summary = {
            "session": self._current_test_session,
            "total_tests": len(self._test_results),
            "by_type": {},
            "success_rate": sum(1 for r in self._test_results if r.success) / len(self._test_results) if self._test_results else 0,
            "avg_execution_time_ms": sum(r.execution_time_ms for r in self._test_results) / len(self._test_results) if self._test_results else 0,
            "total_tokens_used": sum(r.tokens_used or 0 for r in self._test_results),
            "avg_input_tokens": sum(r.input_tokens or 0 for r in self._test_results) / len([r for r in self._test_results if r.input_tokens]) if any(r.input_tokens for r in self._test_results) else 0,
            "avg_output_tokens": sum(r.output_tokens or 0 for r in self._test_results) / len([r for r in self._test_results if r.output_tokens]) if any(r.output_tokens for r in self._test_results) else 0
        }
        
        for result in self._test_results:
            key = f"{result.prompt_type.value}:{result.prompt_version}"
            if key not in summary["by_type"]:
                summary["by_type"][key] = {
                    "count": 0,
                    "success_count": 0,
                    "avg_time_ms": 0,
                    "total_time_ms": 0
                }
            
            summary["by_type"][key]["count"] += 1
            summary["by_type"][key]["total_time_ms"] += result.execution_time_ms
            summary["by_type"][key]["avg_time_ms"] = summary["by_type"][key]["total_time_ms"] / summary["by_type"][key]["count"]
            
            if result.success:
                summary["by_type"][key]["success_count"] += 1
        
        return summary
    
    def should_use_test_prompt(self, user_id: str, prompt_type: PromptType) -> bool:
        """Determine whether to use test prompt for this user/request."""
        if not self.is_test_mode_active():
            return False
        
        # Simple hash-based A/B split: 50% baseline, 50% test
        # This ensures consistent assignment per user
        hash_input = f"{user_id}:{prompt_type.value}:{self._current_test_session}"
        hash_value = hash(hash_input) % 100
        return hash_value < 50  # 50% get test version
    
    def list_available_test_prompts(self) -> List[str]:
        """List all available test prompt files."""
        if not self.test_dir.exists():
            return []
        
        test_files = []
        for file_path in self.test_dir.glob("*.md"):
            test_files.append(file_path.stem)
        
        return sorted(test_files)


# Global instance
_prompt_test_manager: Optional[PromptTestManager] = None


def init_prompt_test_manager(base_dir: str | Path) -> None:
    """Initialize the global prompt test manager."""
    global _prompt_test_manager
    
    if _prompt_test_manager is not None:
        logging.warning("PromptTestManager already initialized, skipping")
        return
    
    _prompt_test_manager = PromptTestManager(base_dir)
    
    # Validate prompt files on startup
    _validate_prompt_files(_prompt_test_manager)
    
    logging.info("PromptTestManager initialized successfully")


def _validate_prompt_files(manager: PromptTestManager) -> None:
    """Validate that all required prompt files exist and are readable."""
    validation_errors = []
    
    # Check baseline prompts
    for prompt_type in PromptType:
        baseline_file = manager.base_dir / f"{prompt_type.value}.md"
        if not baseline_file.exists():
            validation_errors.append(f"Missing baseline prompt: {baseline_file}")
        elif not baseline_file.is_file():
            validation_errors.append(f"Not a file: {baseline_file}")
        else:
            try:
                content = baseline_file.read_text(encoding="utf-8")
                if not content.strip():
                    validation_errors.append(f"Empty baseline prompt: {baseline_file}")
            except Exception as e:
                validation_errors.append(f"Cannot read baseline prompt {baseline_file}: {e}")
    
    # Check test prompts (optional, but log if missing)
    test_prompts = manager.list_available_test_prompts()
    if not test_prompts:
        logging.warning("No test prompts found in prompts/test/ directory. A/B testing will not be active.")
    else:
        logging.info(f"Found {len(test_prompts)} test prompt(s): {', '.join(test_prompts)}")
    
    # Report validation results
    if validation_errors:
        error_msg = f"Prompt validation failed ({len(validation_errors)} errors):\n" + "\n".join(f"  - {err}" for err in validation_errors)
        logging.error(error_msg)
        raise RuntimeError(f"Prompt validation failed: {len(validation_errors)} errors. Check logs for details.")
    else:
        logging.info("All baseline prompts validated successfully")


def get_prompt_test_manager() -> PromptTestManager:
    """Get the global prompt test manager."""
    if _prompt_test_manager is None:
        raise RuntimeError("PromptTestManager not initialized")
    return _prompt_test_manager


def get_prompt_for_test(prompt_type: PromptType, user_id: str) -> tuple[str, str]:
    """Get prompt content and determine which version to use.
    
    Returns:
        (prompt_content, version) where version is "baseline" or "test"
    """
    manager = get_prompt_test_manager()
    
    if manager.should_use_test_prompt(user_id, prompt_type):
        try:
            content = manager.get_prompt_content(prompt_type, use_test_version=True)
            return content, "test"
        except FileNotFoundError:
            # Test version not found, fall back to baseline
            content = manager.get_prompt_content(prompt_type, use_test_version=False)
            return content, "baseline"
    else:
        content = manager.get_prompt_content(prompt_type, use_test_version=False)
        return content, "baseline"