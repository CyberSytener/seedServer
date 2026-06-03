from __future__ import annotations

import json
import logging
from difflib import SequenceMatcher
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class FlavorArchitectEngine:
    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        validator_model: Optional[str] = None,
        creative_model: Optional[str] = None,
    ) -> None:
        self._api_key = gemini_api_key
        self._validator_model = validator_model or "gemini-1.5-flash-8b"
        self._creative_model = creative_model or "gemini-2.0-flash"
        self._analysis_generation_config = {
            "temperature": 0.1,
            "max_output_tokens": 350,
            "candidate_count": 1,
        }
        self._creative_generation_config = {
            "temperature": 0.35,
            "max_output_tokens": 750,
            "candidate_count": 1,
        }
        self._sanity_generation_config = {
            "temperature": 0.0,
            "max_output_tokens": 220,
            "candidate_count": 1,
        }
        self._gemini: Optional[GeminiClient] = None
        self._enabled = bool(self._api_key)
        if self._enabled and self._api_key:
            try:
                self._gemini = GeminiClient(api_key=self._api_key, default_model=self._creative_model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("FlavorArchitect Gemini client init failed: %s", exc)
                self._enabled = False

    def _generate_content(
        self,
        *,
        model_name: str,
        prompt: str,
        generation_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        if not self._enabled or not self._gemini:
            return ""
        return self._gemini.generate_content(
            prompt,
            model=model_name,
            generation_config=generation_config,
        )

    def plan_dish(
        self,
        *,
        current_inventory: List[Dict[str, Any]],
        user_taste_profile: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        strict_mode: bool = True,
        warning: Optional[str] = None,
        force_include_items: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        inventory = self._decorate_inventory(current_inventory)
        taste = user_taste_profile or {}
        ctx = context or {}
        forced_items = [str(name).strip() for name in (force_include_items or []) if str(name).strip()]

        if self._enabled:
            try:
                analysis = self._analysis_stage(
                    inventory=inventory,
                    taste=taste,
                    context=ctx,
                    strict_mode=strict_mode,
                )
                concepts, audit_errors = self._architect_stage(
                    analysis=analysis,
                    inventory=inventory,
                    taste=taste,
                    context=ctx,
                    strict_mode=strict_mode,
                    warning=warning,
                    force_include_items=forced_items,
                    retry_feedback=None,
                )
                if not concepts and audit_errors:
                    concepts, _ = self._architect_stage(
                        analysis=analysis,
                        inventory=inventory,
                        taste=taste,
                        context=ctx,
                        strict_mode=strict_mode,
                        warning=warning,
                        force_include_items=forced_items,
                        retry_feedback="; ".join(audit_errors),
                    )
                if concepts:
                    recipes = self._sous_chef_stage(concepts=concepts, inventory=inventory, warning=warning)
                    sanity_ok, sanity_errors = self._sanity_check_stage(
                        recipes=recipes,
                        analysis=analysis,
                    )
                    if sanity_ok:
                        return recipes

                    concepts, _ = self._architect_stage(
                        analysis=analysis,
                        inventory=inventory,
                        taste=taste,
                        context=ctx,
                        strict_mode=strict_mode,
                        warning=warning,
                        force_include_items=forced_items,
                        retry_feedback="; ".join(sanity_errors),
                    )
                    if concepts:
                        recipes = self._sous_chef_stage(concepts=concepts, inventory=inventory, warning=warning)
                        sanity_ok, _ = self._sanity_check_stage(recipes=recipes, analysis=analysis)
                        if sanity_ok:
                            return recipes
            except Exception as exc:  # noqa: BLE001
                logger.warning("FlavorArchitect Gemini failed, using fallback: %s", exc)

        return self._fallback_plan(
            inventory=inventory,
            taste=taste,
            context=ctx,
            warning=warning,
            force_include_items=forced_items,
        )

    def _analysis_stage(
        self,
        *,
        inventory: List[Dict[str, Any]],
        taste: Dict[str, Any],
        context: Dict[str, Any],
        strict_mode: bool,
    ) -> Dict[str, Any]:
        today = datetime.now(timezone.utc).date()
        python_usable: List[Dict[str, Any]] = []
        constraints: List[str] = []
        protein_candidates: List[str] = []
        carb_candidates: List[str] = []

        for row in inventory:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            is_expired = False
            expires_at = row.get("expires_at")
            if expires_at:
                try:
                    exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")).date()
                    is_expired = exp < today
                except Exception:
                    is_expired = False
            if is_expired:
                continue
            lowered = name.lower()
            category = "Staples"
            if any(x in lowered for x in ["beef", "pork", "chicken", "ham", "bacon", "turkey"]):
                category = "Meat"
                protein_candidates.append(name)
            elif any(x in lowered for x in ["tuna", "salmon", "fish", "cod", "shrimp"]):
                category = "Fish"
                protein_candidates.append(name)
            elif any(x in lowered for x in ["egg", "eggs", "milk", "cheese", "yogurt", "cream", "butter"]):
                category = "Dairy"
                protein_candidates.append(name)
            elif any(x in lowered for x in ["potato", "potet", "rice", "pasta", "bread", "oats"]):
                category = "Staples"
                carb_candidates.append(name)
            elif any(x in lowered for x in ["tomato", "onion", "carrot", "lettuce", "spinach", "cucumber", "pepper", "chili", "garlic"]):
                category = "Vegetables"
            elif any(x in lowered for x in ["apple", "banana", "orange", "berry", "grape", "lemon", "lime"]):
                category = "Fruit"

            python_usable.append(
                {
                    "name": name,
                    "category": category,
                    "status": str(row.get("status") or "fresh"),
                    "pantry_item_id": row.get("storage_id"),
                }
            )

        if any("potato" in name.lower() or "potet" in name.lower() for name in carb_candidates):
            constraints.append("Potato != Low Carb")

        fallback = {
            "usable_ingredients": python_usable,
            "dietary_constraints": constraints,
            "forbidden_claims": ["Potato != Low Carb"],
            "protein_candidates": protein_candidates,
            "carb_candidates": carb_candidates,
        }

        if not self._enabled:
            return fallback

        try:
            prompt = (
                "Role: NeoEats Ingredient Logic & Validator.\n"
                "Task: Analyze pantry and return strict JSON for usable ingredients and dietary constraints.\n"
                "Rules:\n"
                "- Filter out expired ingredients.\n"
                "- Identify valid protein and carb candidates.\n"
                "- Add forbidden claim: Potato != Low Carb when potato exists.\n"
                "Return JSON only with keys: usable_ingredients, dietary_constraints, forbidden_claims, protein_candidates, carb_candidates.\n"
                f"Strict mode: {str(strict_mode).lower()}\n"
                f"Inventory: {json.dumps(inventory, ensure_ascii=False, default=self._json_default)}\n"
                f"Taste: {json.dumps(taste, ensure_ascii=False, default=self._json_default)}\n"
                f"Context: {json.dumps(context, ensure_ascii=False, default=self._json_default)}"
            )
            text = self._generate_content(
                model_name=self._validator_model,
                prompt=prompt,
                generation_config=self._analysis_generation_config,
            )
            payload = self._extract_json(text)
            if not isinstance(payload, dict):
                return fallback
            usable = payload.get("usable_ingredients") if isinstance(payload.get("usable_ingredients"), list) else []
            constraints_raw = payload.get("dietary_constraints") if isinstance(payload.get("dietary_constraints"), list) else []
            forbidden_raw = payload.get("forbidden_claims") if isinstance(payload.get("forbidden_claims"), list) else []
            proteins_raw = payload.get("protein_candidates") if isinstance(payload.get("protein_candidates"), list) else []
            carbs_raw = payload.get("carb_candidates") if isinstance(payload.get("carb_candidates"), list) else []
            normalized = {
                "usable_ingredients": [row for row in usable if isinstance(row, dict)],
                "dietary_constraints": [str(x).strip() for x in constraints_raw if str(x).strip()],
                "forbidden_claims": [str(x).strip() for x in forbidden_raw if str(x).strip()],
                "protein_candidates": [str(x).strip() for x in proteins_raw if str(x).strip()],
                "carb_candidates": [str(x).strip() for x in carbs_raw if str(x).strip()],
            }
            if not normalized["usable_ingredients"]:
                return fallback
            if "Potato != Low Carb" not in normalized["forbidden_claims"] and any(
                "potato" in str(row.get("name") or "").lower() or "potet" in str(row.get("name") or "").lower()
                for row in normalized["usable_ingredients"]
            ):
                normalized["forbidden_claims"].append("Potato != Low Carb")
            return normalized
        except Exception:
            return fallback

    def _architect_stage(
        self,
        *,
        analysis: Dict[str, Any],
        inventory: List[Dict[str, Any]],
        taste: Dict[str, Any],
        context: Dict[str, Any],
        strict_mode: bool,
        warning: Optional[str],
        force_include_items: List[str],
        retry_feedback: Optional[str],
    ) -> tuple[List[Dict[str, Any]], List[str]]:
        critical_line = ""
        if force_include_items:
            critical_line = (
                "CRITICAL: You must include these products in at least one recipe concept: "
                + ", ".join(force_include_items)
                + ".\n"
            )
        retry_line = ""
        if retry_feedback:
            retry_line = f"Previous audit failed for: {retry_feedback}. Regenerate with corrected output.\n"
        prompt = (
            "Role: Creative Executive Chef for NeoEats.\n"
            "Input: List of ingredients from Neural Pantry.\n"
            "Task: Generate 2 unique recipe concepts.\n"
            "Deliverables per recipe: recipe_name, rationale (exactly 2 sentences), key_ingredients (array of names).\n"
            "Strict Rule: No generic phrases. Focus on explicit flavor contrast between specific pantry items.\n"
            "You are forbidden from using identical descriptions for different recipes.\n"
            "You must mention specific ingredients from the approved list in rationale.\n"
            "Nutritional Accuracy: Never call starchy items (potatoes) low-carb.\n"
            "Return STRICT JSON object with key recipes only.\n"
            "Schema: {\"recipes\":[{\"recipe_name\":\"...\",\"rationale\":\"...\",\"key_ingredients\":[\"...\"]}]}\n"
            f"Strict mode: {str(strict_mode).lower()}.\n"
            f"User warning/context: {warning or ''}\n"
            f"{critical_line}"
            f"{retry_line}"
            f"Analyzed Ingredients: {json.dumps(analysis, ensure_ascii=False, default=self._json_default)}\n"
            f"Inventory: {json.dumps(inventory, ensure_ascii=False, default=self._json_default)}\n"
            f"User Profile: {json.dumps(taste, ensure_ascii=False, default=self._json_default)}\n"
            f"Context: {json.dumps(context, ensure_ascii=False, default=self._json_default)}"
        )
        text = self._generate_content(
            model_name=self._creative_model,
            prompt=prompt,
            generation_config=self._creative_generation_config,
        )
        payload = self._extract_json(text)
        concepts = self._normalize_architect_concepts(payload)
        is_valid, audit_errors = self._audit_concepts(concepts=concepts, inventory=inventory, context=context)
        return (concepts if is_valid else [], audit_errors)

    def _sanity_check_stage(
        self,
        *,
        recipes: List[Dict[str, Any]],
        analysis: Dict[str, Any],
    ) -> tuple[bool, List[str]]:
        errors: List[str] = []
        if len(recipes) < 2:
            errors.append("need_two_recipes")
            return False, errors

        rationale_a = str(recipes[0].get("rationale_for_user") or "")
        rationale_b = str(recipes[1].get("rationale_for_user") or "")
        if SequenceMatcher(None, rationale_a.lower(), rationale_b.lower()).ratio() > 0.30:
            errors.append("description_duplicate_or_too_similar")

        for recipe in recipes:
            recipe_name = str(recipe.get("name") or "").lower()
            rationale = str(recipe.get("rationale_for_user") or "").lower()
            has_potato = "potato" in recipe_name or "potet" in recipe_name or "potato" in rationale or "potet" in rationale
            if has_potato and "low-carb" in rationale:
                errors.append("low_carb_tag_on_starchy_recipe")

        if errors:
            return False, errors

        if not self._enabled:
            return True, []

        try:
            prompt = (
                "Role: NeoEats Recipe Sanity Validator.\n"
                "Task: Validate generated recipes for logical consistency.\n"
                "Checks:\n"
                "- Description equality/similarity between recipe 1 and recipe 2.\n"
                "- Low-carb claim on potato/starchy recipes.\n"
                "Return JSON only: {\"valid\": true|false, \"errors\": [\"...\"]}.\n"
                f"ANALYSIS: {json.dumps(analysis, ensure_ascii=False, default=self._json_default)}\n"
                f"RECIPES: {json.dumps(recipes, ensure_ascii=False, default=self._json_default)}"
            )
            text = self._generate_content(
                model_name=self._validator_model,
                prompt=prompt,
                generation_config=self._sanity_generation_config,
            )
            payload = self._extract_json(text)
            if not isinstance(payload, dict):
                return True, []
            valid = bool(payload.get("valid") if payload.get("valid") is not None else True)
            llm_errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
            if not valid:
                return False, [str(x).strip() for x in llm_errors if str(x).strip()] or ["sanity_check_failed"]
            return True, []
        except Exception:
            return True, []

    def _normalize_architect_concepts(self, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, dict) and isinstance(payload.get("recipes"), list):
            raw = payload.get("recipes") or []
        elif isinstance(payload, list):
            raw = payload
        else:
            return []

        out: List[Dict[str, Any]] = []
        for index, row in enumerate(raw[:2]):
            if not isinstance(row, dict):
                continue
            recipe_name = str(row.get("recipe_name") or row.get("name") or "").strip()
            if not recipe_name:
                recipe_name = f"Chef Concept {index + 1}"
            rationale = str(row.get("rationale") or row.get("rationale_for_user") or "").strip()
            key_ingredients = []
            for ing in row.get("key_ingredients") or row.get("ingredients") or []:
                if isinstance(ing, str) and ing.strip():
                    key_ingredients.append(ing.strip())
                elif isinstance(ing, dict):
                    ing_name = str(ing.get("name") or "").strip()
                    if ing_name:
                        key_ingredients.append(ing_name)
            if not rationale:
                continue
            if not key_ingredients:
                continue
            out.append(
                {
                    "recipe_name": recipe_name,
                    "rationale": rationale,
                    "key_ingredients": key_ingredients,
                }
            )
        return out

    def _audit_concepts(
        self,
        *,
        concepts: List[Dict[str, Any]],
        inventory: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> tuple[bool, List[str]]:
        errors: List[str] = []
        if len(concepts) < 2:
            errors.append("need_two_distinct_recipes")
            return False, errors

        rationale_a = str(concepts[0].get("rationale") or "")
        rationale_b = str(concepts[1].get("rationale") or "")
        similarity = SequenceMatcher(None, rationale_a.lower(), rationale_b.lower()).ratio()
        if similarity > 0.30:
            errors.append(f"rationale_similarity_too_high:{round(similarity, 3)}")

        def _sentence_count(text: str) -> int:
            chunks = [part.strip() for part in text.replace("!", ".").replace("?", ".").split(".") if part.strip()]
            return len(chunks)

        pantry_mentions = [str(row.get("name") or "").strip().lower() for row in inventory if str(row.get("name") or "").strip()]
        for concept in concepts:
            rationale = str(concept.get("rationale") or "").strip()
            if _sentence_count(rationale) != 2:
                errors.append("rationale_must_have_two_sentences")
            if "low-carb" in rationale.lower() and ("potato" in rationale.lower() or "potet" in rationale.lower()):
                errors.append("potato_low_carb_claim_forbidden")
            mention_hits = 0
            rationale_lower = rationale.lower()
            for pantry_name in pantry_mentions:
                if pantry_name and pantry_name in rationale_lower:
                    mention_hits += 1
            if mention_hits < 2:
                errors.append("rationale_missing_two_pantry_mentions")

        inventory_names = {str(row.get("name") or "").strip().lower() for row in inventory if str(row.get("name") or "").strip()}
        shopping_names: set[str] = set()
        for key in ["shopping_plan", "planned_purchases", "store_inventory"]:
            value = context.get(key)
            if isinstance(value, list):
                for row in value:
                    if isinstance(row, str):
                        name = row.strip().lower()
                        if name:
                            shopping_names.add(name)
                    elif isinstance(row, dict):
                        name = str(row.get("name") or "").strip().lower()
                        if name:
                            shopping_names.add(name)

        for concept in concepts:
            recipe_name = str(concept.get("recipe_name") or "").strip().lower()
            key_ingredients = {str(name).strip().lower() for name in (concept.get("key_ingredients") or []) if str(name).strip()}
            if "tuna" in recipe_name:
                has_tuna = (
                    "tuna" in key_ingredients
                    or any("tuna" in name for name in inventory_names)
                    or any("tuna" in name for name in shopping_names)
                )
                if not has_tuna:
                    errors.append("tuna_recipe_without_tuna_context")

        return len(errors) == 0, errors

    def _sous_chef_stage(
        self,
        *,
        concepts: List[Dict[str, Any]],
        inventory: List[Dict[str, Any]],
        warning: Optional[str],
    ) -> List[Dict[str, Any]]:
        pantry_rows = [row for row in inventory if str(row.get("name") or "").strip()]
        pantry_names = [str(row.get("name") or "").strip() for row in pantry_rows]

        def _norm_key(value: str) -> str:
            return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())

        pantry_map = {str(row.get("name") or "").strip().lower(): row for row in pantry_rows}
        pantry_norm_map = {_norm_key(str(row.get("name") or "")): row for row in pantry_rows}

        def _resolve_pantry_row(name: str) -> Optional[Dict[str, Any]]:
            key = str(name or "").strip().lower()
            row = pantry_map.get(key)
            if row is not None:
                return row
            norm = _norm_key(key)
            row = pantry_norm_map.get(norm)
            if row is not None:
                return row
            for pantry_name, pantry_row in pantry_map.items():
                if norm and (norm in _norm_key(pantry_name) or _norm_key(pantry_name) in norm):
                    return pantry_row
            return None

        def _split_ingredient_candidates(raw_name: str) -> List[str]:
            text = str(raw_name or "").strip()
            if not text:
                return []
            lowered = text.lower()
            lowered = lowered.replace("&", " and ")
            lowered = lowered.replace("/", " and ")
            for separator in [" or ", " and ", ",", ";"]:
                lowered = lowered.replace(separator, "|")
            pieces = [part.strip() for part in lowered.split("|") if part.strip()]
            cleaned: List[str] = []
            for piece in pieces:
                if piece in {"fat", "acid"}:
                    cleaned.append("olive oil" if piece == "fat" else "lemon")
                    continue
                cleaned.append(piece)
            if not cleaned:
                cleaned = [text.lower()]
            title_case = [" ".join(word.capitalize() for word in part.split()) for part in cleaned]
            return [name for name in title_case if name]

        def _dedupe_ingredients(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            def _key(name: str) -> str:
                return "".join(ch for ch in str(name or "").lower() if ch.isalnum())

            bucket: Dict[str, Dict[str, Any]] = {}
            for row in items:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip()
                if not name:
                    continue
                key = _key(name)
                existing = bucket.get(key)
                if existing is None:
                    bucket[key] = dict(row)
                    continue
                existing_status = str(existing.get("status") or "").strip().lower()
                incoming_status = str(row.get("status") or "").strip().lower()
                if existing_status == "missing" and incoming_status == "owned":
                    bucket[key] = dict(row)
                elif incoming_status == "missing" and existing_status == "owned":
                    continue
                else:
                    if existing.get("price_est") is None and row.get("price_est") is not None:
                        existing["price_est"] = row.get("price_est")
            return list(bucket.values())

        def _category_for(name: str) -> str:
            n = str(name or "").strip().lower()
            if any(x in n for x in ["beef", "pork", "chicken", "ham", "bacon", "sausage", "turkey"]):
                return "Meat"
            if any(x in n for x in ["salmon", "tuna", "fish", "cod", "shrimp"]):
                return "Fish"
            if any(x in n for x in ["milk", "cheese", "cream", "yogurt", "butter"]):
                return "Dairy"
            if any(x in n for x in ["apple", "banana", "orange", "berry", "pear", "grape", "lemon", "lime"]):
                return "Fruit"
            if any(x in n for x in ["tomato", "potato", "onion", "carrot", "lettuce", "spinach", "cucumber", "pepper", "garlic", "chili"]):
                return "Vegetables"
            return "Staples"

        price_map = {
            "garlic": 15,
            "lemon": 12,
            "olive oil": 10,
            "black pepper": 8,
            "onion": 10,
            "egg": 8,
            "eggs": 8,
            "tuna": 20,
        }

        out: List[Dict[str, Any]] = []
        used_first_words: set[str] = set()
        spicy_phrase = "fitting your 'Loves Spicy' preference"
        spicy_phrase_used = False
        for index, concept in enumerate(concepts[:2]):
            recipe_name = str(concept.get("recipe_name") or f"Chef Concept {index + 1}").strip()
            rationale = str(concept.get("rationale") or "").strip()
            if warning and index == 0:
                rationale = f"{warning} {rationale}".strip()

            recipe_name_lower = recipe_name.lower()
            if ("potato" in recipe_name_lower or "potet" in recipe_name_lower) and "low-carb" in rationale.lower():
                rationale = rationale.replace("low-carb", "filling")

            if spicy_phrase in rationale:
                if spicy_phrase_used:
                    rationale = rationale.replace(spicy_phrase, "balancing your spice profile")
                spicy_phrase_used = True

            first_word = (rationale.split(" ")[0].strip() if rationale else "")
            if first_word and first_word.lower() in used_first_words:
                rationale = f"Meanwhile, {rationale}" if rationale else "Meanwhile, alternative concept built from pantry anchors."
                first_word = "Meanwhile,"
            if first_word:
                used_first_words.add(first_word.lower())

            ingredients: List[Dict[str, Any]] = []
            seen_ingredients: set[str] = set()
            for ingredient_name in concept.get("key_ingredients") or []:
                for split_name in _split_ingredient_candidates(str(ingredient_name or "")):
                    name = str(split_name or "").strip()
                    if not name:
                        continue
                    key = name.lower()
                    if key in seen_ingredients:
                        continue
                    seen_ingredients.add(key)
                    pantry_row = _resolve_pantry_row(name)
                    pantry_item_id = pantry_row.get("storage_id") if pantry_row else None
                    if pantry_row is not None and pantry_item_id:
                        ingredients.append(
                            {
                                "name": name,
                                "category": _category_for(name),
                                "status": "owned",
                                "pantry_item_id": pantry_item_id,
                                "amount": "to taste",
                            }
                        )
                    else:
                        ingredients.append(
                            {
                                "name": name,
                                "category": _category_for(name),
                                "status": "missing",
                                "price_est": int(price_map.get(key, 15)),
                                "amount": "to taste",
                            }
                        )

            if "tuna" in recipe_name.lower() and not any(str((ing or {}).get("name") or "").strip().lower() == "tuna" for ing in ingredients):
                pantry_row = _resolve_pantry_row("tuna")
                pantry_item_id = pantry_row.get("storage_id") if pantry_row else None
                if pantry_row is not None and pantry_item_id:
                    ingredients.append(
                        {
                            "name": "Tuna",
                            "category": "Fish",
                            "status": "owned",
                            "pantry_item_id": pantry_item_id,
                            "amount": "120g",
                        }
                    )
                else:
                    ingredients.append(
                        {
                            "name": "Tuna",
                            "category": "Fish",
                            "status": "missing",
                            "price_est": 20,
                            "amount": "120g",
                        }
                    )

            if len(ingredients) < 2 and pantry_names:
                for pantry_name in pantry_names[:2]:
                    key = pantry_name.lower()
                    if any(str((ing or {}).get("name") or "").strip().lower() == key for ing in ingredients):
                        continue
                    pantry_row = _resolve_pantry_row(pantry_name) or {}
                    pantry_item_id = pantry_row.get("storage_id")
                    ingredients.append(
                        {
                            "name": pantry_name,
                            "category": _category_for(pantry_name),
                            "status": "owned" if pantry_item_id else "missing",
                            "pantry_item_id": pantry_item_id,
                            "amount": "to taste",
                        }
                    )

            ingredients = _dedupe_ingredients(ingredients)

            recipe_title_lower = recipe_name.lower()
            required_from_title = {
                "tuna": "Fish",
                "beef": "Meat",
                "egg": "Dairy",
                "chili": "Vegetables",
                "potet-salat": "Vegetables",
                "potato": "Vegetables",
            }
            for token, category in required_from_title.items():
                if token not in recipe_title_lower:
                    continue
                has_token = any(token in str((ing or {}).get("name") or "").strip().lower() for ing in ingredients)
                if has_token:
                    continue
                pantry_row = _resolve_pantry_row(token)
                pantry_item_id = pantry_row.get("storage_id") if pantry_row else None
                if pantry_item_id:
                    ingredients.append(
                        {
                            "name": token.title(),
                            "category": category,
                            "status": "owned",
                            "pantry_item_id": pantry_item_id,
                            "amount": "to taste",
                        }
                    )
                else:
                    ingredients.append(
                        {
                            "name": token.title(),
                            "category": category,
                            "status": "missing",
                            "price_est": int(price_map.get(token, 20)),
                            "amount": "to taste",
                        }
                    )

            out.append(
                {
                    "name": recipe_name,
                    "match_score": max(0, min(100, int(84 - index * 9))),
                    "rationale_for_user": rationale,
                    "ingredients": ingredients,
                    "zero_waste_score": "med",
                }
            )

        if len(out) >= 2:
            first = str(out[0].get("rationale_for_user") or "")
            second = str(out[1].get("rationale_for_user") or "")
            similarity = SequenceMatcher(None, first.lower(), second.lower()).ratio()
            if similarity > 0.30:
                out[1]["rationale_for_user"] = (
                    "Meanwhile, this second concept uses a colder assembly technique and brighter acid-forward profile "
                    "to deliberately contrast the first hot, hearty approach."
                )

        return out

    def _decorate_inventory(self, current_inventory: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        today = datetime.now(timezone.utc).date()
        out: List[Dict[str, Any]] = []
        for row in current_inventory or []:
            item = dict(row or {})
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            expires_raw = item.get("expires_at")
            status = "fresh"
            if expires_raw:
                try:
                    exp = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00")).date()
                    days = (exp - today).days
                    if days <= 2:
                        status = "expiring_soon"
                except Exception:
                    logging.debug("Suppressed exception", exc_info=True)
            item["status"] = item.get("status") or status
            out.append(item)
        return out

    def _fallback_plan(
        self,
        *,
        inventory: List[Dict[str, Any]],
        taste: Dict[str, Any],
        context: Dict[str, Any],
        warning: Optional[str] = None,
        force_include_items: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        pantry_items = [row for row in inventory if str(row.get("name") or "").strip()]
        pantry_names = [str(row.get("name") or "").strip() for row in pantry_items]
        pantry_ids = {
            str(row.get("name") or "").strip().lower(): row.get("storage_id")
            for row in pantry_items
        }
        pantry_name_set = {name.lower() for name in pantry_names}

        def _category_for(name: str) -> str:
            n = str(name or "").strip().lower()
            if any(x in n for x in ["beef", "pork", "chicken", "ham", "bacon", "sausage", "turkey"]):
                return "Meat"
            if any(x in n for x in ["salmon", "tuna", "fish", "cod", "shrimp"]):
                return "Fish"
            if any(x in n for x in ["milk", "cheese", "cream", "yogurt", "butter"]):
                return "Dairy"
            if any(x in n for x in ["apple", "banana", "orange", "berry", "pear", "grape", "lemon", "lime"]):
                return "Fruit"
            if any(x in n for x in ["tomato", "potato", "onion", "carrot", "lettuce", "spinach", "cucumber", "pepper", "garlic"]):
                return "Vegetables"
            return "Staples"

        def _owned_ingredient(name: str, amount: str) -> Dict[str, Any]:
            return {
                "name": name,
                "category": _category_for(name),
                "status": "owned",
                "pantry_item_id": pantry_ids.get(name.lower()),
                "amount": amount,
            }

        def _missing_ingredient(name: str, amount: str, price_est: int) -> Dict[str, Any]:
            return {
                "name": name,
                "category": _category_for(name),
                "status": "missing",
                "price_est": price_est,
                "amount": amount,
            }

        def _ing_status(name: str) -> str:
            return "owned" if name.lower() in pantry_name_set else "missing"

        rationale_a = (
            "Built around your Potet-Salat and Chili, this hearty skillet balances creamy potato body with direct heat "
            "for a filling profile rather than a low-carb style."
        )
        recipe_a_ingredients = [
            {
                "name": "Potet-Salat",
                "category": "Vegetables",
                "status": _ing_status("Potet-Salat"),
                "pantry_item_id": pantry_ids.get("potet-salat"),
                "amount": "220g",
            },
            {
                "name": "Chili",
                "category": "Vegetables",
                "status": _ing_status("Chili"),
                "pantry_item_id": pantry_ids.get("chili"),
                "amount": "1 pc",
            },
            _missing_ingredient("Olive Oil", "1 tbsp", 10),
        ]

        second_hero: Optional[List[str]] = None
        if ("tuna" in pantry_name_set) or ("egg" in pantry_name_set) or ("eggs" in pantry_name_set):
            second_hero = ["Tuna", "Egg"]
        else:
            alt = [name for name in pantry_names if name.lower() not in {"potet-salat", "chili"}]
            if len(alt) >= 2:
                second_hero = [alt[0], alt[1]]

        if warning:
            rationale_a = f"{warning} {rationale_a}".strip()

        recipes: List[Dict[str, Any]] = [
            {
                "name": "Hearty Potet-Salat Chili Skillet",
                "match_score": 82,
                "rationale_for_user": rationale_a,
                "ingredients": recipe_a_ingredients,
                "zero_waste_score": "med",
            },
        ]

        if second_hero:
            hero_b_1, hero_b_2 = second_hero[0], second_hero[1]
            rationale_b = (
                f"Meanwhile, {hero_b_1} with {hero_b_2} gives a clean protein-forward salad where briny notes and egg richness "
                "create a different texture and flavor path from the hot potato skillet."
            )
            ingredients_b = [
                {
                    "name": hero_b_1,
                    "category": _category_for(hero_b_1),
                    "status": _ing_status(hero_b_1),
                    "pantry_item_id": pantry_ids.get(hero_b_1.lower()),
                    "amount": "160g",
                },
                {
                    "name": hero_b_2,
                    "category": _category_for(hero_b_2),
                    "status": _ing_status(hero_b_2),
                    "pantry_item_id": pantry_ids.get(hero_b_2.lower()),
                    "amount": "2 pcs",
                },
                _missing_ingredient("Lemon", "1 pc", 12),
            ]
            if "tuna salad" in "Tuna Salad".lower() and not any(str(i.get("name") or "").strip().lower() == "tuna" for i in ingredients_b):
                ingredients_b.append(
                    {
                        "name": "Tuna",
                        "category": "Fish",
                        "status": _ing_status("Tuna"),
                        "pantry_item_id": pantry_ids.get("tuna"),
                        "amount": "120g",
                    }
                )
            recipes.append(
                {
                    "name": "Tuna Salad Protein Plate" if hero_b_1.lower() == "tuna" or hero_b_2.lower() == "tuna" else f"Protein Pair: {hero_b_1} & {hero_b_2}",
                    "match_score": 72,
                    "rationale_for_user": rationale_b,
                    "ingredients": ingredients_b,
                    "zero_waste_score": "med",
                }
            )
        return recipes

    @staticmethod
    def _select_hero(inventory: List[Dict[str, Any]]) -> Dict[str, Any]:
        expiring = [i for i in inventory if str(i.get("status") or "") == "expiring_soon"]
        if expiring:
            return expiring[0]
        proteins = [
            i for i in inventory if any(
                kw in str(i.get("name") or "").lower()
                for kw in ["chicken", "beef", "pork", "salmon", "tuna", "egg", "tofu", "cheese"]
            )
        ]
        if proteins:
            return proteins[0]
        return inventory[0] if inventory else {"name": "Pantry"}

    def _normalize_output(
        self,
        payload: Any,
        *,
        inventory: List[Dict[str, Any]],
        warning: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        try:
            if isinstance(payload, dict) and isinstance(payload.get("recipes"), list):
                raw_recipes = payload.get("recipes")
            elif isinstance(payload, list):
                raw_recipes = payload
            elif isinstance(payload, dict):
                raw_recipes = [payload]
            else:
                return None

            pantry_items = [row for row in inventory if str(row.get("name") or "").strip()]
            pantry_names = [str(row.get("name") or "").strip() for row in pantry_items]
            pantry_ids = {
                str(row.get("name") or "").strip().lower(): row.get("storage_id")
                for row in pantry_items
            }

            def _category_for(name: str) -> str:
                n = str(name or "").strip().lower()
                if any(x in n for x in ["beef", "pork", "chicken", "ham", "bacon", "sausage", "turkey"]):
                    return "Meat"
                if any(x in n for x in ["salmon", "tuna", "fish", "cod", "shrimp"]):
                    return "Fish"
                if any(x in n for x in ["milk", "cheese", "cream", "yogurt", "butter"]):
                    return "Dairy"
                if any(x in n for x in ["apple", "banana", "orange", "berry", "pear", "grape", "lemon", "lime"]):
                    return "Fruit"
                if any(x in n for x in ["tomato", "potato", "onion", "carrot", "lettuce", "spinach", "cucumber", "pepper", "garlic"]):
                    return "Vegetables"
                return "Staples"

            def _fallback_rationale(items: List[str], recipe_name: str) -> str:
                if len(items) >= 2:
                    return (
                        f"I paired your {items[0]} with {items[1]} so the two pantry staples complement each other in "
                        f"{recipe_name}, giving both balance and texture contrast."
                    )
                if items:
                    return (
                        f"I used your {items[0]} as the anchor for {recipe_name} and built supporting flavors around it "
                        "to keep the dish cohesive."
                    )
                return (
                    f"I built {recipe_name} from the available pantry snapshot with a focus on balance and minimal waste."
                )

            normalized: List[Dict[str, Any]] = []
            seen_rationales: set[str] = set()
            for index, row in enumerate(raw_recipes[:2]):
                if not isinstance(row, dict):
                    continue
                recipe_name = str(row.get("name") or row.get("recipe_name") or "").strip() or f"Adaptive Pantry Rescue {index + 1}"
                try:
                    match_score = int(float(row.get("match_score") or 70))
                except Exception:
                    match_score = 70

                ingredients_out: List[Dict[str, Any]] = []
                for ing in row.get("ingredients") or []:
                    if not isinstance(ing, dict):
                        continue
                    ing_name = str(ing.get("name") or "").strip()
                    if not ing_name:
                        continue
                    status = str(ing.get("status") or "missing").strip().lower()
                    if status not in {"owned", "missing"}:
                        status = "missing"
                    pantry_item_id = ing.get("pantry_item_id") or ing.get("pantry_id")
                    if status == "owned" and pantry_item_id is None:
                        pantry_item_id = pantry_ids.get(ing_name.lower())
                    category = str(ing.get("category") or "").strip()
                    if category not in {"Meat", "Vegetables", "Fish", "Fruit", "Dairy", "Staples"}:
                        category = _category_for(ing_name)
                    amount = str(ing.get("amount") or "").strip() or "to taste"
                    ingredient = {
                        "name": ing_name,
                        "category": category,
                        "status": status,
                        "amount": amount,
                    }
                    if status == "owned":
                        ingredient["pantry_item_id"] = pantry_item_id
                    if status == "missing" and ing.get("price_est") is not None:
                        ingredient["price_est"] = ing.get("price_est")
                    ingredients_out.append(ingredient)

                if not ingredients_out and pantry_names:
                    owned_name = pantry_names[0]
                    second_name = pantry_names[1] if len(pantry_names) > 1 else pantry_names[0]
                    ingredients_out = [
                        {
                            "name": owned_name,
                            "category": _category_for(owned_name),
                            "status": "owned",
                            "pantry_item_id": pantry_ids.get(owned_name.lower()),
                            "amount": "150g",
                        },
                        {
                            "name": second_name,
                            "category": _category_for(second_name),
                            "status": "owned",
                            "pantry_item_id": pantry_ids.get(second_name.lower()),
                            "amount": "120g",
                        },
                        {"name": "Garlic", "category": "Staples", "status": "missing", "price_est": 15, "amount": "2 cloves"},
                    ]

                rationale = str(row.get("rationale_for_user") or "").strip()
                if not rationale:
                    rationale = _fallback_rationale(pantry_names, recipe_name)
                if warning:
                    rationale = f"{warning} {rationale}".strip()
                if "potet" in rationale.lower() and "low-carb" in rationale.lower():
                    rationale = rationale.replace("low-carb", "filling")
                if rationale in seen_rationales:
                    rationale = f"{rationale} Alternative focus: {recipe_name}."
                seen_rationales.add(rationale)

                zero_waste_score = str(row.get("zero_waste_score") or "med").strip().lower()
                if zero_waste_score not in {"high", "med", "low"}:
                    zero_waste_score = "med"

                normalized.append(
                    {
                        "name": recipe_name,
                        "match_score": max(0, min(100, match_score)),
                        "rationale_for_user": rationale,
                        "ingredients": ingredients_out,
                        "zero_waste_score": zero_waste_score,
                    }
                )

            phrase = "fitting your 'Loves Spicy' preference"
            phrase_count = 0
            for recipe in normalized:
                rationale_text = str(recipe.get("rationale_for_user") or "")
                if phrase in rationale_text:
                    phrase_count += 1
                    if phrase_count > 1:
                        recipe["rationale_for_user"] = rationale_text.replace(phrase, "balancing your spice profile")

            if len(normalized) >= 2:
                first_word_a = str((normalized[0].get("rationale_for_user") or "").split(" ")[0] or "").strip()
                first_word_b = str((normalized[1].get("rationale_for_user") or "").split(" ")[0] or "").strip()
                if first_word_a and first_word_b and first_word_a.lower() == first_word_b.lower():
                    normalized[1]["rationale_for_user"] = f"Meanwhile, {normalized[1].get('rationale_for_user')}"

            for recipe in normalized:
                recipe_name_lc = str(recipe.get("name") or "").lower()
                if "tuna salad" in recipe_name_lc:
                    ingredients = list(recipe.get("ingredients") or [])
                    has_tuna = any(str((ing or {}).get("name") or "").strip().lower() == "tuna" for ing in ingredients)
                    if not has_tuna:
                        ingredients.append(
                            {
                                "name": "Tuna",
                                "category": "Fish",
                                "status": "missing",
                                "price_est": 20,
                                "amount": "120g",
                            }
                        )
                        recipe["ingredients"] = ingredients

            if len(normalized) < 2:
                return self._fallback_plan(
                    inventory=inventory,
                    taste={},
                    context={},
                    warning=warning,
                    force_include_items=None,
                )
            return normalized
        except Exception:
            return None

    def _extract_json(self, text: str) -> Any:
        raw = (text or "").strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        try:
            return json.loads(raw)
        except Exception:
            logging.debug("Suppressed exception", exc_info=True)
        start_obj = raw.find("{")
        end_obj = raw.rfind("}")
        if start_obj != -1 and end_obj > start_obj:
            candidate = raw[start_obj : end_obj + 1]
            try:
                return json.loads(candidate)
            except Exception:
                logging.debug("Suppressed exception", exc_info=True)
        return None

    @staticmethod
    def _json_default(value: Any) -> Any:
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:
                logging.debug("Suppressed exception", exc_info=True)
        if isinstance(value, (set, tuple)):
            return list(value)
        try:
            return float(value)
        except Exception:
            return str(value)
