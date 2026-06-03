from __future__ import annotations

import json
import logging
import re
import hashlib
import os
from typing import Any, Dict, List, Optional

from app.core.gemini_client import GeminiClient

from app.services.hybrid_recipes import suggest_hybrid_recipes
from app.services.pantry_normalizer import (
    canonicalize_product,
    extract_items_from_message,
    normalize_quantity_unit,
)

logger = logging.getLogger(__name__)


class LLMEngine:
    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        chat_model: Optional[str] = None,
        vision_model: Optional[str] = None,
        embedding_model: Optional[str] = None,
        llm_service: Optional[Any] = None,
    ) -> None:
        self._api_key = gemini_api_key
        self._chat_model = chat_model or "gemini-2.0-flash"
        self._vision_model = vision_model or "gemini-2.0-flash-lite"
        self._embedding_model = embedding_model or os.getenv("SEED_GEMINI_EMBED_MODEL") or "text-embedding-004"
        self._gemini: Optional[GeminiClient] = None
        self._llm_service = llm_service
        self._enabled = bool(self._api_key) or (llm_service is not None)
        if llm_service is None and self._api_key:
            try:
                self._gemini = GeminiClient(api_key=self._api_key, default_model=self._chat_model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini client init failed: %s", exc)
                self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    @property
    def embedding_available(self) -> bool:
        if self._llm_service is not None and hasattr(self._llm_service, "embed_text"):
            return True
        return self._gemini is not None

    def embed_text(
        self,
        text: str,
        *,
        model: Optional[str] = None,
        task_type: str = "retrieval_document",
    ) -> List[float]:
        if self._llm_service is not None and hasattr(self._llm_service, "embed_text"):
            try:
                result = self._llm_service.embed_text(text)
                if isinstance(result, list):
                    return [float(value) for value in result]
            except Exception as exc:  # noqa: BLE001
                logger.warning("UnifiedLLMService.embed_text failed, falling back to GeminiClient: %s", exc)
        if not self._gemini:
            return []
        try:
            return self._gemini.embed_content(
                content=text,
                model=model or self._embedding_model,
                task_type=task_type,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini embedding failed: %s", exc)
            return []

    def _generate_content(
        self,
        *,
        contents: Any,
        model_name: str,
        generation_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        # Route through UnifiedLLMService when available (text-only path).
        if self._llm_service is not None and isinstance(contents, str):
            try:
                return self._llm_service.generate(
                    prompt=contents,
                    model=model_name,
                    max_tokens=int((generation_config or {}).get("maxOutputTokens", 4096)),
                    temperature=float((generation_config or {}).get("temperature", 0.7)),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("UnifiedLLMService.generate failed, falling back to GeminiClient: %s", exc)
        if not self._gemini:
            return ""
        return self._gemini.generate_content(
            contents,
            model=model_name,
            generation_config=generation_config,
        )

    def analyze_vision(
        self,
        *,
        image_bytes: Optional[bytes],
        mime_type: str = "image/jpeg",
    ) -> List[Dict[str, Any]]:
        if self._enabled and image_bytes:
            try:
                prompt = (
                    "Identify the main grocery product in the image. "
                    "Apply a strict hierarchy filter: prioritize real food/container content over packaging artwork. "
                    "Ignore decorative illustrations, seasonal characters, mascots, people/faces, cartoons, "
                    "or promotional games depicted ON the packaging. "
                    "Focus on brand text (for example Tine, Q-meieriene), product type (for example Milk, Yogurt), "
                    "and expiration date. If multiple items are shown only as part of package design, identify only "
                    "the liquid or solid content of the actual container. "
                    "Be strictly conservative: if an object is unrecognizable, ambiguous, blurry, or looks like "
                    "background noise, DO NOT include it. "
                    "If no real grocery product is confidently recognizable, return an empty JSON array [] and do not guess. "
                    "Return ONLY a JSON array. Each item must have: name (string), quantity (number, estimate if needed), "
                    "unit (kg/g/pcs/L), expiry_date (YYYY-MM-DD when reliable, otherwise null), confidence_score (0..1), "
                    "is_primary_product (boolean), source_type (one of: label_text, product_title, barcode, packaging_illustration, mascot, promotional_graphic, background_noise)."
                )
                text = self._generate_content(
                    contents=[
                        prompt,
                        {"mime_type": mime_type or "image/jpeg", "data": image_bytes},
                    ],
                    model_name=self._vision_model,
                    generation_config={"maxOutputTokens": 300, "temperature": 0.1},
                )
                payload = self._extract_json(text)
                if isinstance(payload, list):
                    normalized = self._normalize_vision_items(payload)
                    if normalized:
                        return normalized
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini vision failed, using fallback: %s", exc)

        return self._fallback_vision_items()

    def orchestrate_chat(
        self,
        *,
        message: str,
        user_inventory: List[Dict[str, Any]],
        store_inventory: List[Dict[str, Any]],
        user_taste_profile: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if self._enabled:
            try:
                prompt = (
                    "Role: NeoEats Master Chef & Inventory Sync Agent.\n"
                    "You are generating recipes based on the user's Neural Pantry.\n\n"
                    "CRITICAL INTENT RULES:\n"
                    "- If the user asks for a recipe, meal suggestion, cooking idea, or anything about \n"
                    "  eating/preparing food -> intent=COOK\n"
                    "- If the user says they bought, have, or want to add a specific product -> intent=ADD_FOOD\n"
                    "- Otherwise -> intent=CHAT\n\n"
                    "EXAMPLES:\n"
                    "  'Suggest a high-protein lunch' -> intent=COOK\n"
                    "  'What can I cook for dinner?' -> intent=COOK\n"
                    "  'Plan a healthy meal' -> intent=COOK\n"
                    "  'I just bought eggs and milk' -> intent=ADD_FOOD, detected_items=[eggs, milk]\n"
                    "  'I have 500g chicken breast' -> intent=ADD_FOOD, detected_items=[chicken breast]\n"
                    "  'How are you?' -> intent=CHAT\n\n"
                    "NEVER put the user's question text into detected_items. Only real food product names go there.\n\n"
                    "Status Awareness: when suggesting recipes, check item freshness and prioritize items closest to expiring.\n"
                    "If intent is COOK: return a full ingredient list for each recipe and cross-reference inventory.\n"
                    "For each ingredient set status=owned or missing.\n\n"
                    "Return ONLY JSON object with keys: intent, persona_message, detected_items, recommendations.\n"
                    "intent must be one of: ADD_FOOD, COOK, CHAT.\n"
                    "detected_items[] item keys: name, quantity, unit, expiry_date, confidence, brand(optional), "
                    "category, display_name, is_perishable.\n"
                    "recommendations[] keys: recipe_id, name, description, confidence, ingredients[].\n"
                    "ingredients[] keys: name, amount, status, pantry_item_id(optional).\n\n"
                    f"USER_MESSAGE: {message}\n"
                    f"USER_INVENTORY: {json.dumps(user_inventory, ensure_ascii=False, default=self._json_default)}\n"
                    f"STORE_INVENTORY: {json.dumps(store_inventory, ensure_ascii=False, default=self._json_default)}\n"
                    f"USER_TASTE_PROFILE: {json.dumps(user_taste_profile or {}, ensure_ascii=False, default=self._json_default)}\n"
                    f"CONTEXT: {json.dumps(context or {}, ensure_ascii=False, default=self._json_default)}"
                )
                text = self._generate_content(
                    contents=prompt,
                    model_name=self._chat_model,
                    generation_config={"maxOutputTokens": 1024, "temperature": 0.4},
                )
                payload = self._extract_json(text)
                if isinstance(payload, dict):
                    normalized = self._normalize_chat_payload(payload)
                    if normalized:
                        return normalized
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini chat failed, using fallback: %s", exc)

        return self._fallback_chat_payload(
            message=message,
            user_inventory=user_inventory,
            store_inventory=store_inventory,
        )

    def analyze_receipt(
        self,
        *,
        image_bytes: Optional[bytes],
        mime_type: str = "image/jpeg",
        pantry_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        extracted = self._fallback_receipt_payload()

        if self._enabled and image_bytes:
            try:
                extracted = self._extract_receipt_once(
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    pantry_items=pantry_items or [],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini receipt extraction failed, using fallback: %s", exc)

        normalized = self._normalize_receipt_payload(extracted)
        validation_errors = self._validate_receipt_payload(normalized)
        validation_passed = len(validation_errors) == 0

        if not validation_passed and self._enabled and image_bytes:
            try:
                refined_raw = self._refine_receipt_extraction(
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    previous_payload=normalized,
                    errors=validation_errors,
                    pantry_items=pantry_items or [],
                )
                refined = self._normalize_receipt_payload(refined_raw)
                refined_errors = self._validate_receipt_payload(refined)
                if len(refined_errors) <= len(validation_errors):
                    normalized = refined
                    validation_errors = refined_errors
                    validation_passed = len(refined_errors) == 0
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini receipt refinement failed: %s", exc)

        normalized["validation_passed"] = validation_passed
        normalized["validation_errors"] = validation_errors
        return normalized

    def _fallback_vision_items(self) -> List[Dict[str, Any]]:
        # Safe public fallback: no hallucinated products when vision provider fails.
        return []

    def _fallback_chat_payload(
        self,
        *,
        message: str,
        user_inventory: List[Dict[str, Any]],
        store_inventory: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        text = (message or "").lower()
        if any(marker in text for marker in ["cook", "recipe", "what can i"]):
            recs = suggest_hybrid_recipes(user_inventory, store_inventory)
            return {
                "intent": "COOK",
                "persona_message": "Here are recipes based on your current inventory.",
                "detected_items": [],
                "recommendations": [rec.model_dump() for rec in recs],
            }

        detected_items = self._parse_items_from_text(message)
        if detected_items:
            return {
                "intent": "ADD_FOOD",
                "persona_message": "I can add these items to your fridge.",
                "detected_items": detected_items,
                "recommendations": [],
            }

        return {
            "intent": "CHAT",
            "persona_message": "Tell me what food you have, or ask what you can cook.",
            "detected_items": [],
            "recommendations": [],
        }

    def _parse_items_from_text(self, message: str) -> List[Dict[str, Any]]:
        parsed_items = extract_items_from_message(message)
        normalized: List[Dict[str, Any]] = []
        for item in parsed_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            canonical_name = str(item.get("canonical_name") or name).strip().lower()
            if not canonical_name:
                continue
            quantity, unit = normalize_quantity_unit(
                item.get("quantity"),
                item.get("unit"),
                name=name,
            )
            normalized.append(
                {
                    "name": name or canonical_name,
                    "canonical_name": canonical_name,
                    "display_name": str(item.get("display_name") or name or canonical_name).strip(),
                    "category": item.get("category"),
                    "quantity": quantity,
                    "unit": unit,
                    "expiry_date": item.get("expiry_date"),
                    "confidence": float(item.get("confidence") or 0.82),
                    "original_name": str(item.get("original_name") or name).strip(),
                }
            )
        return normalized

    def _normalize_vision_items(self, payload: List[Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            name = str(row.get("canonical_name") or row.get("name") or row.get("product_name") or "").strip()
            if not name:
                continue
            brand = str(row.get("brand") or "").strip() or None
            canonicalized = canonicalize_product(name, brand=brand, preferred_language="en")
            canonical_name = str(canonicalized.get("canonical_name") or name).strip().lower()
            display_name = str(canonicalized.get("display_name") or canonical_name).strip()
            quantity, unit = normalize_quantity_unit(
                row.get("quantity"),
                row.get("unit"),
                name=display_name,
            )
            expiry = row.get("expiry_date") or row.get("expires_at")
            try:
                confidence_raw = float(
                    row.get("confidence_score")
                    if row.get("confidence_score") is not None
                    else row.get("confidence")
                    if row.get("confidence") is not None
                    else 0.8
                )
            except Exception:
                confidence_raw = 0.8
            confidence = confidence_raw / 100.0 if confidence_raw > 1.0 else confidence_raw
            confidence_pct = max(0.0, min(100.0, confidence * 100.0))
            source_type = str(row.get("source_type") or "label_text").strip().lower() or "label_text"
            is_primary_product = bool(
                row.get("is_primary_product")
                if row.get("is_primary_product") is not None
                else True
            )
            out.append(
                {
                    "name": display_name,
                    "canonical_name": canonical_name,
                    "display_name": display_name,
                    "category": row.get("category") or canonicalized.get("category"),
                    "brand": brand,
                    "quantity": quantity,
                    "unit": unit,
                    "expiry_date": expiry,
                    "confidence": confidence_pct,
                    "confidence_score": confidence,
                    "source_type": source_type,
                    "is_primary_product": is_primary_product,
                    "original_name": str(row.get("name") or row.get("product_name") or name).strip(),
                }
            )
        return out

    def _normalize_chat_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        intent = str(payload.get("intent") or "CHAT").upper().strip()
        if intent not in {"ADD_FOOD", "COOK", "CHAT"}:
            intent = "CHAT"
        persona_message = str(payload.get("persona_message") or "")
        detected_items = self._normalize_detected_items(payload.get("detected_items") or [])

        recommendations: List[Dict[str, Any]] = []
        for row in payload.get("recommendations") or []:
            if not isinstance(row, dict):
                continue
            recipe_id = str(row.get("recipe_id") or row.get("id") or "").strip()
            name = str(row.get("name") or "").strip()
            if not recipe_id or not name:
                continue
            ingredients: List[Dict[str, Any]] = []
            for ing in row.get("ingredients") or []:
                if not isinstance(ing, dict):
                    continue
                ing_name = str(ing.get("name") or "").strip()
                if not ing_name:
                    continue
                taxonomy_fields = self._normalize_taxonomy_fields(ing)
                ingredients.append(
                    {
                        "name": ing_name,
                        "amount": ing.get("amount"),
                        "status": ing.get("status"),
                        "pantry_item_id": ing.get("pantry_item_id"),
                        **taxonomy_fields,
                    }
                )
            recommendations.append(
                {
                    "recipe_id": recipe_id,
                    "name": name,
                    "description": row.get("description"),
                    "available_items": list(row.get("available_items") or []),
                    "missing_items": list(row.get("missing_items") or []),
                    "ingredients": ingredients,
                    "confidence": row.get("confidence"),
                }
            )

        return {
            "intent": intent,
            "persona_message": persona_message or "I analyzed your request.",
            "detected_items": detected_items,
            "recommendations": recommendations,
        }

    def _normalize_taxonomy_fields(self, row: Dict[str, Any]) -> Dict[str, Any]:
        category = str(row.get("category") or "").strip() or None
        display_name = str(row.get("display_name") or row.get("name") or "").strip() or None
        if not category and display_name:
            name_hint = display_name.lower()
            fallback_map = {
                "Meat": ["beef", "pork", "chicken", "turkey", "ham", "sausage", "bacon"],
                "Fish": ["salmon", "tuna", "cod", "shrimp", "fish"],
                "Dairy": ["milk", "cheese", "yogurt", "butter", "cream"],
                "Vegetables": ["potato", "onion", "carrot", "lettuce", "tomato", "cucumber", "pepper", "broccoli"],
                "Fruit": ["apple", "banana", "orange", "berry", "grape", "pear"],
                "Bakery": ["bread", "bun", "roll", "croissant", "pastry"],
                "Staples (Spices/Oil)": ["rice", "pasta", "oil", "spice", "salt", "flour", "sugar"],
                "Ready Meals": ["salad", "lasagna", "pizza", "soup", "stew", "wrap", "ready", "instant"],
            }
            for fallback_category, keywords in fallback_map.items():
                if any(keyword in name_hint for keyword in keywords):
                    category = fallback_category
                    break
        is_perishable = row.get("is_perishable")
        if is_perishable is None:
            perishable_categories = {
                "meat",
                "vegetables",
                "fruit",
                "fish",
                "dairy",
                "bakery",
                "ready meals",
            }
            is_perishable = bool(category and category.strip().lower() in perishable_categories)

        expanded_details = row.get("expanded_details")
        expanded_details = expanded_details if isinstance(expanded_details, dict) else {}
        storage_advice = expanded_details.get("storage_advice") or expanded_details.get("storage_tip")
        nutrition_preview = expanded_details.get("nutrition_preview")
        purchase_history = expanded_details.get("purchase_history")

        possible_substitutes = expanded_details.get("possible_substitutes")
        if not isinstance(possible_substitutes, list):
            possible_substitutes = []

        return {
            "category": category,
            "display_name": display_name,
            "is_perishable": bool(is_perishable),
            "expanded_details": {
                "storage_advice": storage_advice,
                "possible_substitutes": possible_substitutes,
                "nutrition_preview": nutrition_preview,
                "purchase_history": purchase_history,
            },
        }

    def _normalize_detected_items(self, payload_items: List[Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for row in payload_items:
            if not isinstance(row, dict):
                continue
            name = str(row.get("canonical_name") or row.get("name") or row.get("product_name") or "").strip()
            if not name:
                continue
            brand = str(row.get("brand") or "").strip() or None
            canonicalized = canonicalize_product(name, brand=brand, preferred_language="en")
            canonical_name = str(canonicalized.get("canonical_name") or name).strip().lower()
            display_name = str(canonicalized.get("display_name") or canonical_name).strip()
            quantity, unit = normalize_quantity_unit(
                row.get("quantity"),
                row.get("unit"),
                name=display_name,
            )
            expiry = row.get("expiry_date") or row.get("expires_at")
            try:
                confidence_raw = float(
                    row.get("confidence_score")
                    if row.get("confidence_score") is not None
                    else row.get("confidence")
                    if row.get("confidence") is not None
                    else 0.8
                )
            except Exception:
                confidence_raw = 0.8
            confidence = confidence_raw / 100.0 if confidence_raw > 1.0 else confidence_raw
            confidence_pct = max(0.0, min(100.0, confidence * 100.0))
            normalized_for_taxonomy = dict(row)
            normalized_for_taxonomy["name"] = display_name
            normalized_for_taxonomy["category"] = row.get("category") or canonicalized.get("category")
            normalized_for_taxonomy["display_name"] = display_name
            taxonomy_fields = self._normalize_taxonomy_fields(normalized_for_taxonomy)
            out.append(
                {
                    "name": display_name,
                    "canonical_name": canonical_name,
                    "quantity": quantity,
                    "unit": unit,
                    "expiry_date": expiry,
                    "confidence": confidence_pct,
                    "confidence_score": confidence,
                    "brand": brand,
                    "original_name": str(row.get("name") or row.get("product_name") or name).strip(),
                    **taxonomy_fields,
                }
            )
        return out

    def _extract_receipt_once(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        pantry_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        pantry_snapshot = []
        for row in pantry_items[:100]:
            if not isinstance(row, dict):
                continue
            pantry_snapshot.append(
                {
                    "name": row.get("name"),
                    "product_name_norm": row.get("product_name_norm"),
                    "product_id": row.get("product_id"),
                }
            )
        prompt = (
            "Role: High-precision Receipt Analytics Engine for NeoEats.\n"
            "Task: Analyze the provided receipt image.\n"
            "Data Extraction: For every line item, extract original_name, quantity, unit_price, total_item_price.\n"
            "Categorization: set is_food=true for groceries and is_food=false for bags, service fees, or non-edible items.\n"
            "Normalization: provide canonical_name in English.\n"
            "Currency: identify currency (e.g. RUB).\n"
            "Anti-Duplication Logic: suggest match_id and action=UPDATE if item already exists in Neural Pantry, else CREATE.\n"
            "Output Format: Strict JSON with keys receipt_info and items.\n"
            "receipt_info fields: store, date, total_sum, currency.\n"
            "items fields: original_name, canonical_name, quantity, unit_price, total_item_price, is_food, match_id, action.\n"
            f"NEURAL_PANTRY_SNAPSHOT: {json.dumps(pantry_snapshot, ensure_ascii=False, default=self._json_default)}"
        )
        text = self._generate_content(
            contents=[
                prompt,
                {"mime_type": mime_type or "image/jpeg", "data": image_bytes},
            ],
            model_name=self._vision_model,
            generation_config={"maxOutputTokens": 512, "temperature": 0.1},
        )
        payload = self._extract_json(text)
        if not isinstance(payload, dict):
            return self._fallback_receipt_payload()
        return payload

    def _refine_receipt_extraction(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        previous_payload: Dict[str, Any],
        errors: List[str],
        pantry_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        pantry_snapshot = []
        for row in pantry_items[:100]:
            if not isinstance(row, dict):
                continue
            pantry_snapshot.append(
                {
                    "name": row.get("name"),
                    "product_name_norm": row.get("product_name_norm"),
                    "product_id": row.get("product_id"),
                }
            )
        prompt = (
            "You extracted this JSON, but total_amount doesn't match the sum of items prices. "
            "Re-analyze the image and fix the prices and item totals. "
            "Return ONLY valid JSON with keys receipt_info and items.\n"
            f"PREVIOUS_JSON: {json.dumps(previous_payload, ensure_ascii=False, default=self._json_default)}\n"
            f"VALIDATION_ERRORS: {json.dumps(errors, ensure_ascii=False)}\n"
            f"NEURAL_PANTRY_SNAPSHOT: {json.dumps(pantry_snapshot, ensure_ascii=False, default=self._json_default)}"
        )
        text = self._generate_content(
            contents=[
                prompt,
                {"mime_type": mime_type or "image/jpeg", "data": image_bytes},
            ],
            model_name=self._vision_model,
            generation_config={"maxOutputTokens": 512, "temperature": 0.1},
        )
        payload = self._extract_json(text)
        if not isinstance(payload, dict):
            return previous_payload
        return payload

    def _normalize_receipt_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        receipt_info = payload.get("receipt_info") if isinstance(payload.get("receipt_info"), dict) else {}
        merchant_name = str(
            payload.get("merchant_name")
            or payload.get("merchant")
            or receipt_info.get("store")
            or ""
        ).strip() or None
        currency = str(payload.get("currency") or receipt_info.get("currency") or "NOK").strip().upper() or "NOK"
        items_in = payload.get("items") or payload.get("line_items") or []

        normalized_items: List[Dict[str, Any]] = []
        total_sum = 0.0
        for row in items_in:
            if not isinstance(row, dict):
                continue
            original_name = str(row.get("original_name") or row.get("name") or row.get("raw_name") or "").strip()
            canonical_name = str(row.get("canonical_name") or row.get("name") or row.get("product_name") or "").strip()
            name = canonical_name or original_name
            if not name:
                continue
            is_food = bool(row.get("is_food") if row.get("is_food") is not None else True)
            if not is_food:
                continue
            try:
                qty = float(row.get("qty") if row.get("qty") is not None else row.get("quantity") or 1.0)
            except Exception:
                qty = 1.0
            unit_price = row.get("unit_price") if row.get("unit_price") is not None else row.get("price_per_unit")
            total_item_price = (
                row.get("total_item_price")
                if row.get("total_item_price") is not None
                else row.get("price")
                if row.get("price") is not None
                else row.get("price_paid")
            )
            unit = str(row.get("unit") or row.get("uom") or "pcs").strip() or "pcs"
            try:
                price = float(total_item_price if total_item_price is not None else 0.0)
            except Exception:
                price = 0.0
            if price <= 0 and unit_price is not None:
                try:
                    price = float(unit_price) * max(float(qty), 1.0)
                except Exception:
                    price = 0.0
            category = row.get("category")
            normalized_name = re.sub(r"\s+", " ", name.strip().lower())
            match_id = str(row.get("match_id") or "").strip() or hashlib.sha1(normalized_name.encode("utf-8")).hexdigest()[:20]
            action = str(row.get("action") or "").strip().upper()
            if action not in {"UPDATE", "CREATE"}:
                action = "CREATE"

            normalized_items.append(
                {
                    "name": name,
                    "original_name": original_name or None,
                    "canonical_name": canonical_name or name,
                    "qty": qty,
                    "unit": unit,
                    "price": round(max(0.0, price), 2),
                    "category": str(category).strip() if category is not None else None,
                    "is_food": True,
                    "match_id": match_id,
                    "action": action,
                }
            )
            total_sum += max(0.0, price)

        try:
            total_amount = float(
                payload.get("total_amount")
                if payload.get("total_amount") is not None
                else payload.get("total")
                if payload.get("total") is not None
                else receipt_info.get("total_sum")
                if receipt_info.get("total_sum") is not None
                else total_sum
            )
        except Exception:
            total_amount = total_sum

        return {
            "merchant_name": merchant_name,
            "total_amount": round(max(0.0, total_amount), 2),
            "currency": currency,
            "items": normalized_items,
        }

    def _validate_receipt_payload(self, payload: Dict[str, Any]) -> List[str]:
        errors: List[str] = []
        total_amount = float(payload.get("total_amount") or 0.0)
        items = list(payload.get("items") or [])
        item_sum = sum(float((item or {}).get("price") or 0.0) for item in items)

        if not items:
            errors.append("No receipt items extracted")
        if total_amount <= 0:
            errors.append("Receipt total_amount must be greater than zero")
        if item_sum <= 0:
            errors.append("Sum of item prices must be greater than zero")

        if total_amount > 0 and item_sum > 0:
            diff_ratio = abs(item_sum - total_amount) / total_amount
            if diff_ratio > 0.05:
                errors.append(
                    f"Total mismatch: item_sum={round(item_sum, 2)} total_amount={round(total_amount, 2)} diff_ratio={round(diff_ratio, 4)}"
                )

        for item in items:
            name = str((item or {}).get("name") or "").strip()
            qty = float((item or {}).get("qty") or 0.0)
            unit = str((item or {}).get("unit") or "pcs").strip().lower()
            if self._is_weird_unit(name=name, qty=qty, unit=unit):
                errors.append(f"Weird unit/quantity detected: {qty} {unit} of {name}")

        return errors

    @staticmethod
    def _is_weird_unit(*, name: str, qty: float, unit: str) -> bool:
        if qty <= 0:
            return True
        thresholds = {
            "kg": 25.0,
            "g": 50000.0,
            "l": 20.0,
            "ml": 10000.0,
            "pcs": 500.0,
            "pc": 500.0,
            "pack": 100.0,
            "portion": 100.0,
            "jar": 100.0,
            "bottle": 100.0,
            "can": 200.0,
        }
        if unit in thresholds and qty > thresholds[unit]:
            return True
        if unit not in thresholds and qty > 1000:
            return True
        return False

    def _fallback_receipt_payload(self) -> Dict[str, Any]:
        return {
            "merchant_name": "Unknown",
            "total_amount": 0.0,
            "currency": "NOK",
            "items": [],
        }

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
        start_arr = raw.find("[")
        end_arr = raw.rfind("]")
        if start_arr != -1 and end_arr > start_arr:
            candidate = raw[start_arr : end_arr + 1]
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
