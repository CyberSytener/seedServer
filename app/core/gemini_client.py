from __future__ import annotations

import asyncio
import base64
import logging
import warnings
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

try:  # Preferred SDK
    from google import genai as _google_genai
except Exception:  # pragma: no cover - optional dependency
    _google_genai = None

try:  # Optional config typing for preferred SDK
    from google.genai import types as _google_genai_types
except Exception:  # pragma: no cover - optional dependency
    _google_genai_types = None

_LEGACY_SENTINEL = object()
_legacy_genai_module: Any = _LEGACY_SENTINEL


def _load_legacy_genai() -> Any:
    global _legacy_genai_module
    if _legacy_genai_module is not _LEGACY_SENTINEL:
        return _legacy_genai_module
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            import google.generativeai as legacy_genai
    except Exception:  # pragma: no cover - optional dependency
        legacy_genai = None
    _legacy_genai_module = legacy_genai
    return _legacy_genai_module


def gemini_sdk_mode() -> str:
    if _google_genai is not None:
        return "google.genai"
    if _load_legacy_genai() is not None:
        return "google.generativeai"
    return "unavailable"


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.strip()

    if isinstance(response, dict):
        for key in ("text", "output_text", "content"):
            value = response.get(key)
            if isinstance(value, str):
                return value.strip()

    candidates = getattr(response, "candidates", None)
    if isinstance(candidates, list):
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None)
            if isinstance(parts, list):
                for part in parts:
                    part_text = getattr(part, "text", None)
                    if isinstance(part_text, str) and part_text.strip():
                        return part_text.strip()
    return ""


def _extract_embedding(response: Any) -> list[float]:
    if isinstance(response, dict):
        embedding = response.get("embedding")
        if isinstance(embedding, dict):
            values = embedding.get("values")
            if isinstance(values, list):
                return [float(item) for item in values]
        if isinstance(embedding, list):
            return [float(item) for item in embedding]

    embeddings = getattr(response, "embeddings", None)
    if isinstance(embeddings, list) and embeddings:
        values = getattr(embeddings[0], "values", None)
        if isinstance(values, list):
            return [float(item) for item in values]

    single = getattr(response, "embedding", None)
    values = getattr(single, "values", None)
    if isinstance(values, list):
        return [float(item) for item in values]
    if isinstance(single, list):
        return [float(item) for item in single]
    return []


def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _extract_provider_request_id(response: Any) -> Optional[str]:
    if isinstance(response, dict):
        for key in ("request_id", "response_id", "id"):
            value = response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for attr in ("request_id", "response_id", "id"):
        value = getattr(response, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_usage(response: Any) -> Dict[str, Optional[int]]:
    usage_raw: Any = None
    if isinstance(response, dict):
        usage_raw = response.get("usage") or response.get("usage_metadata")
    if usage_raw is None:
        usage_raw = getattr(response, "usage", None) or getattr(response, "usage_metadata", None)

    if usage_raw is None:
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}

    if hasattr(usage_raw, "__dict__"):
        usage = {
            "prompt_token_count": getattr(usage_raw, "prompt_token_count", None),
            "candidates_token_count": getattr(usage_raw, "candidates_token_count", None),
            "total_token_count": getattr(usage_raw, "total_token_count", None),
            "input_tokens": getattr(usage_raw, "input_tokens", None),
            "output_tokens": getattr(usage_raw, "output_tokens", None),
            "total_tokens": getattr(usage_raw, "total_tokens", None),
            "prompt_tokens": getattr(usage_raw, "prompt_tokens", None),
            "completion_tokens": getattr(usage_raw, "completion_tokens", None),
        }
    elif isinstance(usage_raw, dict):
        usage = usage_raw
    else:
        usage = {}

    input_tokens = _coerce_int(
        usage.get("input_tokens", usage.get("prompt_tokens", usage.get("prompt_token_count")))
    )
    output_tokens = _coerce_int(
        usage.get(
            "output_tokens",
            usage.get("completion_tokens", usage.get("candidates_token_count")),
        )
    )
    total_tokens = _coerce_int(usage.get("total_tokens", usage.get("total_token_count")))
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = int((input_tokens or 0) + (output_tokens or 0))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _extract_generation_meta(response: Any) -> Dict[str, Any]:
    return {
        "provider_request_id": _extract_provider_request_id(response),
        "usage": _extract_usage(response),
        "cost": None,
    }


def _normalize_new_sdk_content_item(item: Any) -> Any:
    if isinstance(item, list):
        return [_normalize_new_sdk_content_item(value) for value in item]

    if isinstance(item, tuple):
        return tuple(_normalize_new_sdk_content_item(value) for value in item)

    if not isinstance(item, dict):
        return item

    mime_type = item.get("mime_type")
    data = item.get("data")
    if isinstance(mime_type, str) and isinstance(data, (bytes, bytearray)):
        if _google_genai_types is not None:
            part_cls = getattr(_google_genai_types, "Part", None)
            if part_cls is not None and hasattr(part_cls, "from_bytes"):
                try:
                    return part_cls.from_bytes(data=bytes(data), mime_type=mime_type)
                except Exception:
                    logging.debug("Suppressed exception", exc_info=True)
        return {
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(bytes(data)).decode("ascii"),
            }
        }

    if isinstance(item.get("inline_data"), dict):
        normalized_inline = dict(item["inline_data"])
        inline_data = normalized_inline.get("data")
        if isinstance(inline_data, (bytes, bytearray)):
            normalized_inline["data"] = base64.b64encode(bytes(inline_data)).decode("ascii")
        return {"inline_data": normalized_inline}

    return item


def _normalize_contents_for_google_genai(contents: Any) -> Any:
    if isinstance(contents, (list, tuple)):
        return [_normalize_new_sdk_content_item(item) for item in contents]
    return _normalize_new_sdk_content_item(contents)


class GeminiClient:
    def __init__(self, *, api_key: str, default_model: str) -> None:
        if not str(api_key or "").strip():
            raise ValueError("Gemini api_key is required")
        self._api_key = str(api_key).strip()
        self._default_model = str(default_model or "gemini-2.0-flash-lite").strip()
        self._mode = "unavailable"
        self._client: Any = None
        self._legacy: Any = None

        if _google_genai is not None:
            try:
                self._client = _google_genai.Client(api_key=self._api_key)
                self._mode = "google.genai"
                return
            except Exception as exc:  # pragma: no cover - defensive path
                logger.warning("google.genai client init failed, trying legacy SDK: %s", exc)

        legacy = _load_legacy_genai()
        if legacy is not None:
            legacy.configure(api_key=self._api_key)
            self._legacy = legacy
            self._mode = "google.generativeai"
            return

        raise RuntimeError("Gemini SDK is not available (google.genai/google.generativeai)")

    @property
    def mode(self) -> str:
        return self._mode

    def _resolve_model(self, model: Optional[str]) -> str:
        return str(model or self._default_model).strip() or self._default_model

    @staticmethod
    def _legacy_model_generate(model_obj: Any, contents: Any, generation_config: Optional[Dict[str, Any]]) -> Any:
        if generation_config:
            return model_obj.generate_content(contents, generation_config=generation_config)
        return model_obj.generate_content(contents)

    def _new_config(self, generation_config: Optional[Dict[str, Any]]) -> Any:
        if not generation_config:
            return None
        if _google_genai_types is None:
            return generation_config
        try:
            return _google_genai_types.GenerateContentConfig(**generation_config)
        except Exception:
            return generation_config

    def generate_content(
        self,
        contents: Any,
        *,
        model: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        target_model = self._resolve_model(model)
        if self._mode == "google.genai":
            normalized_contents = _normalize_contents_for_google_genai(contents)
            kwargs: Dict[str, Any] = {"model": target_model, "contents": normalized_contents}
            config = self._new_config(generation_config)
            if config is not None:
                kwargs["config"] = config
            response = self._client.models.generate_content(**kwargs)
            return _extract_text(response)

        if self._mode == "google.generativeai":
            model_obj = self._legacy.GenerativeModel(target_model)
            response = self._legacy_model_generate(model_obj, contents, generation_config)
            return _extract_text(response)

        raise RuntimeError("Gemini SDK is not available")

    async def generate_content_async(
        self,
        contents: Any,
        *,
        model: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        text, _ = await self.generate_content_async_with_meta(
            contents,
            model=model,
            generation_config=generation_config,
        )
        return text

    async def generate_content_async_with_meta(
        self,
        contents: Any,
        *,
        model: Optional[str] = None,
        generation_config: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        target_model = self._resolve_model(model)
        if self._mode == "google.genai":
            normalized_contents = _normalize_contents_for_google_genai(contents)
            kwargs: Dict[str, Any] = {"model": target_model, "contents": normalized_contents}
            config = self._new_config(generation_config)
            if config is not None:
                kwargs["config"] = config
            response = await self._client.aio.models.generate_content(**kwargs)
            return _extract_text(response), _extract_generation_meta(response)

        if self._mode == "google.generativeai":
            model_obj = self._legacy.GenerativeModel(target_model)
            generate_async = getattr(model_obj, "generate_content_async", None)
            if callable(generate_async):
                if generation_config:
                    response = await generate_async(contents, generation_config=generation_config)
                else:
                    response = await generate_async(contents)
                return _extract_text(response), _extract_generation_meta(response)
            text = await asyncio.to_thread(
                self.generate_content,
                contents,
                model=target_model,
                generation_config=generation_config,
            )
            return text, {"provider_request_id": None, "usage": {"input_tokens": None, "output_tokens": None, "total_tokens": None}, "cost": None}

        raise RuntimeError("Gemini SDK is not available")

    def embed_content(
        self,
        *,
        content: str,
        model: str = "text-embedding-004",
        task_type: Optional[str] = "retrieval_document",
    ) -> list[float]:
        target_model = self._resolve_model(model)
        if self._mode == "google.genai":
            kwargs: Dict[str, Any] = {"model": target_model, "contents": content}
            if task_type and _google_genai_types is not None:
                try:
                    kwargs["config"] = _google_genai_types.EmbedContentConfig(task_type=task_type)
                except Exception:
                    logging.debug("Suppressed exception", exc_info=True)
            response = self._client.models.embed_content(**kwargs)
            return _extract_embedding(response)

        if self._mode == "google.generativeai":
            response = self._legacy.embed_content(
                model=target_model,
                content=content,
                task_type=task_type or "retrieval_document",
            )
            return _extract_embedding(response)

        raise RuntimeError("Gemini SDK is not available")
