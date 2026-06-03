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
                       tokens_used: Optional[int] = None) -> None:
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
            tokens_used=tokens_used
        )
        
        self._test_results.append(result)
        
        # Also save to file immediately for persistence
        self._save_result_to_file(result)
        
        logging.info(f"Logged prompt test result: {test_id} ({prompt_type.value}:{prompt_version})")\n    \n    def _save_result_to_file(self, result: PromptTestResult) -> None:\n        \"\"\"Save individual result to JSON file.\"\"\"\n        session_dir = self.results_dir / (self._current_test_session or \"default\")\n        session_dir.mkdir(exist_ok=True)\n        \n        result_file = session_dir / f\"{result.test_id}.json\"\n        \n        # Convert to dict for JSON serialization\n        result_dict = {\n            \"test_id\": result.test_id,\n            \"prompt_type\": result.prompt_type.value,\n            \"prompt_version\": result.prompt_version,\n            \"user_id\": result.user_id,\n            \"request_data\": result.request_data,\n            \"response_data\": result.response_data,\n            \"execution_time_ms\": result.execution_time_ms,\n            \"success\": result.success,\n            \"error\": result.error,\n            \"timestamp\": result.timestamp,\n            \"tokens_used\": result.tokens_used,\n            \"quality_score\": result.quality_score\n        }\n        \n        try:\n            result_file.write_text(json.dumps(result_dict, indent=2), encoding=\"utf-8\")\n        except Exception as e:\n            logging.error(f\"Failed to save test result to file: {e}\")\n    \n    def get_session_summary(self) -> Dict[str, Any]:\n        \"\"\"Get summary of current test session.\"\"\"\n        if not self._test_results:\n            return {\"session\": self._current_test_session, \"total_tests\": 0}\n        \n        # Group by prompt type and version\n        summary = {\n            \"session\": self._current_test_session,\n            \"total_tests\": len(self._test_results),\n            \"by_type\": {},\n            \"success_rate\": sum(1 for r in self._test_results if r.success) / len(self._test_results)\n        }\n        \n        for result in self._test_results:\n            key = f\"{result.prompt_type.value}:{result.prompt_version}\"\n            if key not in summary[\"by_type\"]:\n                summary[\"by_type\"][key] = {\n                    \"count\": 0,\n                    \"success_count\": 0,\n                    \"avg_time_ms\": 0,\n                    \"total_time_ms\": 0\n                }\n            \n            summary[\"by_type\"][key][\"count\"] += 1\n            summary[\"by_type\"][key][\"total_time_ms\"] += result.execution_time_ms\n            summary[\"by_type\"][key][\"avg_time_ms\"] = summary[\"by_type\"][key][\"total_time_ms\"] / summary[\"by_type\"][key][\"count\"]\n            \n            if result.success:\n                summary[\"by_type\"][key][\"success_count\"] += 1\n        \n        return summary\n    \n    def should_use_test_prompt(self, user_id: str, prompt_type: PromptType) -> bool:\n        \"\"\"Determine whether to use test prompt for this user/request.\"\"\"\n        if not self.is_test_mode_active():\n            return False\n        \n        # Simple hash-based A/B split: 50% baseline, 50% test\n        # This ensures consistent assignment per user\n        hash_input = f\"{user_id}:{prompt_type.value}:{self._current_test_session}\"\n        hash_value = hash(hash_input) % 100\n        return hash_value < 50  # 50% get test version\n    \n    def list_available_test_prompts(self) -> List[str]:\n        \"\"\"List all available test prompt files.\"\"\"\n        if not self.test_dir.exists():\n            return []\n        \n        test_files = []\n        for file_path in self.test_dir.glob(\"*.md\"):\n            test_files.append(file_path.stem)\n        \n        return sorted(test_files)\n\n\n# Global instance\n_prompt_test_manager: Optional[PromptTestManager] = None\n\n\ndef init_prompt_test_manager(base_dir: str | Path) -> None:\n    \"\"\"Initialize the global prompt test manager.\"\"\"\n    global _prompt_test_manager\n    _prompt_test_manager = PromptTestManager(base_dir)\n\n\ndef get_prompt_test_manager() -> PromptTestManager:\n    \"\"\"Get the global prompt test manager.\"\"\"\n    if _prompt_test_manager is None:\n        raise RuntimeError(\"PromptTestManager not initialized\")\n    return _prompt_test_manager\n\n\ndef get_prompt_for_test(prompt_type: PromptType, user_id: str) -> tuple[str, str]:\n    \"\"\"Get prompt content and determine which version to use.\n    \n    Returns:\n        (prompt_content, version) where version is \"baseline\" or \"test\"\n    \"\"\"\n    manager = get_prompt_test_manager()\n    \n    if manager.should_use_test_prompt(user_id, prompt_type):\n        try:\n            content = manager.get_prompt_content(prompt_type, use_test_version=True)\n            return content, \"test\"\n        except FileNotFoundError:\n            # Test version not found, fall back to baseline\n            content = manager.get_prompt_content(prompt_type, use_test_version=False)\n            return content, \"baseline\"\n    else:\n        content = manager.get_prompt_content(prompt_type, use_test_version=False)\n        return content, \"baseline\"\n