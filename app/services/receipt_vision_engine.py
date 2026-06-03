from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)


class ReceiptVisionEngine:
    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        vision_model: Optional[str] = None,
    ) -> None:
        self._api_key = gemini_api_key
        self._vision_model = vision_model or "gemini-2.0-flash-lite"
        self._gemini: Optional[GeminiClient] = None
        self._enabled = bool(self._api_key)
        if self._enabled and self._api_key:
            try:
                self._gemini = GeminiClient(api_key=self._api_key, default_model=self._vision_model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini client init failed for receipt engine: %s", exc)
                self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

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

    def _extract_receipt_once(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        pantry_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self._gemini:
            raise RuntimeError("Gemini SDK is not available")
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

        text = self._gemini.generate_content(
            [
                prompt,
                {"mime_type": mime_type or "image/jpeg", "data": image_bytes},
            ],
            model=self._vision_model,
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
        if not self._gemini:
            raise RuntimeError("Gemini SDK is not available")
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

        text = self._gemini.generate_content(
            [
                prompt,
                {"mime_type": mime_type or "image/jpeg", "data": image_bytes},
            ],
            model=self._vision_model,
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
            errors.append("No food receipt items extracted")
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
            qty = float((item or {}).get("qty") or 0.0)
            unit = str((item or {}).get("unit") or "pcs").strip().lower()
            if self._is_weird_unit(qty=qty, unit=unit):
                errors.append(f"Weird unit/quantity detected: {qty} {unit}")

        return errors

    @staticmethod
    def _is_weird_unit(*, qty: float, unit: str) -> bool:
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
