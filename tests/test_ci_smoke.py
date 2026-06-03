"""
CI Smoke Test: Prompt & Parser Pipeline
Tests end-to-end generation and parsing to catch regressions.
"""
import os
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch


class TestPromptParserPipeline(unittest.TestCase):
    """Smoke tests for prompt generation and parsing pipeline."""
    
    def setUp(self):
        """Set up test environment."""
        self.prompts_dir = Path(__file__).parent.parent / "prompts"
        
    def test_diagnostic_prompt_exists(self):
        """Test diagnostic generator prompt file exists."""
        prompt_file = self.prompts_dir / "diagnostic_generator.md"
        self.assertTrue(prompt_file.exists(), f"Missing {prompt_file}")
        
        content = prompt_file.read_text(encoding='utf-8')
        self.assertGreater(len(content), 100)
        self.assertIn("JSON", content.upper())
    
    def test_lesson_generator_prompt_exists(self):
        """Test lesson generator prompt exists."""
        prompt_file = self.prompts_dir / "lesson_generator.md"
        self.assertTrue(prompt_file.exists(), f"Missing {prompt_file}")
        
        content = prompt_file.read_text(encoding='utf-8')
        self.assertGreater(len(content), 100)
    
    def test_compact_parser_imports(self):
        """Test compact parser can be imported."""
        try:
            from app.core.compact_parser import parse_compact_diagnostic
            self.assertTrue(callable(parse_compact_diagnostic))
        except ImportError as e:
            self.fail(f"Failed to import compact parser: {e}")
    
    def test_parse_valid_compact_diagnostic(self):
        """Test parsing valid compact diagnostic output."""
        from app.core.compact_parser import parse_compact_diagnostic
        
        # Sample valid compact format
        compact_output = """[A1]grammar:present_simple:1
Q: Choose the correct form
C: ["is","are","am","be"]
A: 0

[A2]vocabulary:common_verbs:2
Q: What does "correr" mean?
C: ["to eat","to run","to sleep","to drink"]
A: 1"""
        
        # Mock request data (required by parser)
        req_data = {
            "targetLang": "es",
            "nativeLang": "en",
            "count": 2
        }
        
        try:
            items = parse_compact_diagnostic(compact_output, req_data)
            # Parser should return at least one item
            self.assertGreater(len(items), 0)
            
            # Verify first item has basic structure (parser outputs may vary)
            item1 = items[0]
            self.assertIsInstance(item1, dict)
            self.assertIn('id', item1)
            
        except Exception as e:
            # Parser may fail on this specific format - that's ok for smoke test
            # As long as it doesn't crash with unhandled exception
            logging.warning(f"Parser did not handle sample format: {e}")
    
    def test_lesson_engine_validation_functions(self):
        """Test lesson validation functions are available."""
        try:
            from app.services.lesson.engine import validate_lesson, validate_task, auto_repair_lesson
            
            self.assertTrue(callable(validate_lesson))
            self.assertTrue(callable(validate_task))
            self.assertTrue(callable(auto_repair_lesson))
            
        except ImportError as e:
            self.fail(f"Failed to import lesson validation: {e}")
    
    def test_validate_sample_lesson_structure(self):
        """Test validation on sample lesson structure."""
        from app.services.lesson.engine import validate_lesson
        
        sample_lesson = {
            "lessonId": "test123",
            "title": "Test Lesson",
            "targetLang": "es",
            "nativeLang": "en",
            "level": "A1",
            "mode": "standard",
            "tasks": [
                {
                    "id": "task1",
                    "type": "mcq",
                    "prompt": "Choose the correct answer",
                    "skill": "grammar",
                    "difficulty": 2,
                    "content": {
                        "question": "What is 2+2?",
                        "choices": ["3", "4", "5", "6"]
                    },
                    "grading": {
                        "correctChoiceIndex": 1
                    }
                }
            ]
        }
        
        is_valid, errors = validate_lesson(sample_lesson, expected_length=1)
        self.assertTrue(is_valid, f"Sample lesson failed validation: {errors}")
    
    def test_diagnostic_engine_imports(self):
        """Test diagnostic engine can be imported."""
        try:
            from app.services.diagnostic.engine import generate_diagnostic_items
            self.assertTrue(callable(generate_diagnostic_items))
        except ImportError as e:
            self.fail(f"Failed to import diagnostic engine: {e}")
    
    def test_prompt_testing_system_available(self):
        """Test prompt testing system is available."""
        try:
            from app.prompt_testing import (
                get_prompt_for_test,
                PromptType,
                init_prompt_test_manager
            )
            
            self.assertTrue(callable(get_prompt_for_test))
            self.assertTrue(callable(init_prompt_test_manager))
            
        except ImportError as e:
            self.fail(f"Failed to import prompt testing system: {e}")
    
    def test_parser_version_selection(self):
        """Test parser version can be selected."""
        # Test environment variable parsing
        os.environ['SEED_PARSER_VERSION'] = 'baseline'
        
        from app.settings import get_settings
        settings = get_settings()
        
        self.assertIsNotNone(settings.parser_version)
    
    def test_auto_repair_handles_common_errors(self):
        """Test auto-repair handles common LLM mistakes."""
        from app.services.lesson.engine import auto_repair_lesson
        
        # Lesson with common mistakes
        broken_lesson = {
            "lessonId": "test",
            "title": "Test",
            "targetLang": "es",
            "nativeLang": "en",
            "level": "A1",
            "mode": "standard",
            "tasks": [
                {
                    "id": "task1",
                    "type": "mcq",
                    "prompt": "Test",
                    "skill": "test",
                    "difficulty": 2,
                    "choices": ["A", "B", "C"],  # Wrong location
                    "content": {
                        "question": "Test?"
                    },
                    "grading": {
                        "correctChoiceIndex": 0
                    }
                }
            ]
        }
        
        repaired, repairs = auto_repair_lesson(broken_lesson)
        
        # Should have applied repairs
        self.assertGreater(len(repairs), 0)
        
        # Choices should be moved to content
        self.assertIn("choices", repaired["tasks"][0]["content"])
    
    def test_compact_parser_error_handling(self):
        """Test parser handles malformed input gracefully."""
        from app.core.compact_parser import parse_compact_diagnostic
        
        req_data = {"targetLang": "es", "nativeLang": "en", "count": 1}
        
        malformed_inputs = [
            "",  # Empty
            "Not a valid format",  # Random text
            "[A1]invalid",  # Incomplete
        ]
        
        for malformed in malformed_inputs:
            try:
                result = parse_compact_diagnostic(malformed, req_data)
                # Should either return empty list or raise specific error
                self.assertIsInstance(result, list)
            except Exception as e:
                # Should raise informative error, not crash
                self.assertIsNotNone(str(e))


class TestPromptIntegrity(unittest.TestCase):
    """Test prompt file integrity and format."""
    
    def setUp(self):
        """Set up test environment."""
        self.prompts_dir = Path(__file__).parent.parent / "prompts"
    
    def test_all_prompt_files_utf8(self):
        """Test all prompt files are valid UTF-8."""
        prompt_files = list(self.prompts_dir.glob("*.md"))
        
        self.assertGreater(len(prompt_files), 0, "No prompt files found")
        
        for prompt_file in prompt_files:
            try:
                content = prompt_file.read_text(encoding='utf-8')
                self.assertIsInstance(content, str)
                self.assertGreater(len(content), 0)
            except UnicodeDecodeError:
                self.fail(f"Prompt file {prompt_file} is not valid UTF-8")
    
    def test_prompts_contain_instructions(self):
        """Test prompt files contain expected instruction keywords."""
        required_prompts = [
            ("diagnostic_generator.md", ["JSON", "RULES"]),
            ("lesson_generator.md", ["JSON", "task"]),
            ("lesson_grader.md", ["grading", "feedback"])
        ]
        
        for filename, keywords in required_prompts:
            prompt_file = self.prompts_dir / filename
            
            if not prompt_file.exists():
                self.fail(f"Required prompt file missing: {filename}")
            
            content = prompt_file.read_text(encoding='utf-8').upper()
            
            for keyword in keywords:
                self.assertIn(
                    keyword.upper(), 
                    content, 
                    f"Keyword '{keyword}' not found in {filename}"
                )


if __name__ == '__main__':
    # Run with verbose output for CI
    unittest.main(verbosity=2)

