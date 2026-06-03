from __future__ import annotations

from typing import Any, Dict, List

from app.core.blocks import BlockBase


class RecipeGeneratorBlock(BlockBase):
    """Generate a simple recipe payload from inputs."""

    NAME = "recipe_generator"
    DESCRIPTION = "Generate a recipe from in-stock ingredients."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "dish_name": {"type": "string"},
            "ingredients": {
                "type": "array",
                "items": {"type": "object"},
            },
            "available_ingredients": {
                "type": "array",
                "items": {"type": "object"},
            },
            "missing_ingredients": {
                "type": "array",
                "items": {"type": "object"},
            },
            "servings": {"type": "integer"},
        },
        "required": [],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "recipe": {"type": "object"},
        },
        "required": ["recipe"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        missing = inputs.get("missing_ingredients") or []
        if missing:
            raise ValueError("missing_ingredients")

        dish_name = inputs.get("dish_name") or "Chef Special"
        ingredients = inputs.get("available_ingredients") or inputs.get("ingredients") or []
        servings = int(inputs.get("servings") or 1)

        recipe = {
            "title": dish_name,
            "servings": servings,
            "ingredients": ingredients,
            "steps": [
                "Prep all ingredients.",
                "Cook in a single pan until done.",
                "Plate and serve warm.",
            ],
        }
        return {"recipe": recipe}
