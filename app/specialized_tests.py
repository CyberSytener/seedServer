"""
Specialized test utilities for loading and managing domain-specific diagnostic tests.
"""
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

from app.models.api import DiagnosticBlueprint


SPECIALIZED_TESTS_DIR = Path(__file__).parent.parent / "specialized_tests"
TEMPLATES_FILE = SPECIALIZED_TESTS_DIR / "test_templates.json"


def load_test_templates() -> Dict[str, Any]:
    """Load all available specialized test templates."""
    try:
        if TEMPLATES_FILE.exists():
            with open(TEMPLATES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            logging.warning(f"Test templates file not found: {TEMPLATES_FILE}")
            return {}
    except Exception as e:
        logging.error(f"Failed to load test templates: {e}")
        return {}


def get_available_tests() -> List[str]:
    """Get list of available specialized test types."""
    templates = load_test_templates()
    return list(templates.keys())


def get_test_info(test_type: str) -> Optional[Dict[str, Any]]:
    """Get information about a specific test type."""
    templates = load_test_templates()
    return templates.get(test_type)


def create_specialized_blueprint(test_type: str) -> List[DiagnosticBlueprint]:
    """Create blueprint from specialized test template."""
    templates = load_test_templates()
    
    if test_type not in templates:
        raise ValueError(f"Unknown test type: {test_type}. Available: {list(templates.keys())}")
    
    test_config = templates[test_type]
    blueprint_data = test_config.get("blueprint", [])
    
    blueprints = []
    for item in blueprint_data:
        # Convert JSON data to DiagnosticBlueprint model using camelCase keys
        blueprint = DiagnosticBlueprint(
            skill=item["skill"],
            subskill=item["subskill"],
            topic=item["topic"],
            difficulty=item["difficulty"],
            taskType=item["taskType"],  # Use alias
            cefrBand=item["cefrBand"],  # Use alias
            domain=item.get("domain"),
            dialect=item.get("dialect"),
            context=item.get("context")
        )
        blueprints.append(blueprint)
    
    logging.info(f"Created specialized blueprint for '{test_type}' with {len(blueprints)} items")
    return blueprints


def list_domains() -> List[str]:
    """Get all available specialized domains."""
    templates = load_test_templates()
    domains = set()
    
    for test_config in templates.values():
        for item in test_config.get("blueprint", []):
            if "domain" in item and item["domain"]:
                domains.add(item["domain"])
    
    return sorted(list(domains))


def list_dialects() -> List[str]:
    """Get all available dialect variants."""
    templates = load_test_templates()
    dialects = set()
    
    for test_config in templates.values():
        for item in test_config.get("blueprint", []):
            if "dialect" in item and item["dialect"]:
                dialects.add(item["dialect"])
    
    return sorted(list(dialects))

