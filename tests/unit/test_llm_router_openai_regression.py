from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.core.llm.router import ActionResult, OpenAIProvider, execute_action, execute_llm_request


def test_openai_provider_run_preserves_persona_id_used(monkeypatch):
    provider = OpenAIProvider(api_key="test-openai-key", base_url="https://api.openai.com")

    async def fake_call_responses(
        client,
        headers,
        model,
        instructions,
        input_text,
        max_output_tokens,
    ):
        return {
            "output_text": "ok",
            "usage": {"input_tokens": 3, "output_tokens": 7},
        }

    monkeypatch.setattr(provider, "_call_responses", fake_call_responses)

    async def _run():
        return await provider.run(
            model="gpt-4.1-mini",
            instructions="system prompt",
            input_text="hello",
            persona_id_used="kitchen_mentor",
        )

    result = asyncio.run(_run())

    assert result.persona_id_used == "kitchen_mentor"
    assert result.provider == "openai"
    assert result.text == "ok"


def test_openai_provider_run_uses_keyword_arguments_for_responses_call(monkeypatch):
    provider = OpenAIProvider(api_key="test-openai-key", base_url="https://api.openai.com")
    captured: dict[str, object] = {}

    async def fake_call_responses(*, client, headers, model, instructions, input_text, max_output_tokens):
        captured.update(
            {
                "model": model,
                "instructions": instructions,
                "input_text": input_text,
                "max_output_tokens": max_output_tokens,
            }
        )
        return {"output_text": "ok", "usage": {"input_tokens": 1, "output_tokens": 2}}

    monkeypatch.setattr(provider, "_call_responses", fake_call_responses)

    async def _run():
        return await provider.run(
            model="gpt-4.1-mini",
            instructions="system prompt",
            input_text="hello",
            max_output_tokens=123,
        )

    result = asyncio.run(_run())

    assert captured["model"] == "gpt-4.1-mini"
    assert captured["instructions"] == "system prompt"
    assert captured["input_text"] == "hello"
    assert captured["max_output_tokens"] == 123
    assert result.text == "ok"


def test_execute_action_passes_resolved_persona_to_openai_provider(monkeypatch):
    monkeypatch.setenv("SEED_DEFAULT_PROVIDER_FAST", "openai")
    monkeypatch.setenv("SEED_DEFAULT_PROVIDER_BATCH", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("SEED_OPENAI_MODEL_FAST", "gpt-4.1-mini")
    monkeypatch.setenv("SEED_OPENAI_BASE_URL", "https://api.openai.com")

    monkeypatch.setattr(
        "app.core.persona_prompts.get_persona_prompt",
        lambda _persona_id: SimpleNamespace(
            persona_id_used="kitchen_mentor",
            prompt_text="You are a kitchen mentor.",
            fallback_reason=None,
        ),
    )

    captured: dict[str, object] = {}

    async def fake_run(self, **kwargs):
        captured.update(kwargs)
        return ActionResult(
            provider="openai",
            model=str(kwargs["model"]),
            text="response",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            persona_id_used=str(kwargs["persona_id_used"]),
        )

    monkeypatch.setattr(OpenAIProvider, "run", fake_run)

    async def _run():
        return await execute_action(
            action="ask",
            input_text="hello",
            options={},
            mode="fast",
            persona_id="ignored_by_mock",
        )

    result = asyncio.run(_run())

    assert captured["persona_id_used"] == "kitchen_mentor"
    assert result.persona_id_used == "kitchen_mentor"


def test_openai_parse_responses_handles_malformed_usage_payload():
    provider = OpenAIProvider(api_key="test-openai-key", base_url="https://api.openai.com")

    text, tokens_in, tokens_out = provider._parse_responses(
        {
            "output_text": "ok",
            "usage": "not-a-dict",
        }
    )

    assert text == "ok"
    assert tokens_in == 0
    assert tokens_out == 0


def test_execute_llm_request_openai_respects_timeout_sec(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("SEED_OPENAI_BASE_URL", "https://api.openai.com")

    captured: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "choices": [
                    {
                        "message": {
                            "content": "ok"
                        }
                    }
                ]
            }

    class _FakeClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = json
            return _FakeResponse()

    monkeypatch.setattr("httpx.Client", _FakeClient)

    result = execute_llm_request(
        system_prompt="You are concise.",
        user_prompt="Say hello",
        provider="openai",
        model="gpt-4.1-mini",
        timeout_sec=17,
    )

    assert result == "ok"
    assert captured["timeout"] == 17.0


def test_execute_llm_request_openai_metadata_contains_usage_and_ledger(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("SEED_OPENAI_BASE_URL", "https://api.openai.com")

    class _FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            }

    class _FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            return _FakeResponse()

    monkeypatch.setattr("httpx.Client", _FakeClient)

    result = execute_llm_request(
        system_prompt="You are concise.",
        user_prompt="Say hello",
        provider="openai",
        model="gpt-4.1-mini",
        timeout_sec=10,
        return_metadata=True,
        endpoint="/v1/test/openai-metadata",
        feature="router_regression",
        stage="candidate",
        attempt=2,
        trace_id="trace-router-1",
    )

    assert isinstance(result, dict)
    assert result["text"] == "ok"
    assert result["usage"]["prompt_tokens"] == 12
    assert result["usage"]["completion_tokens"] == 8
    assert result["usage"]["total_tokens"] == 20
    assert result["cost"]["estimated_cost_usd"] > 0.0
    assert result["ledger_event"]["attempt"] == 2
    assert str(result["ledger_event"].get("pricing_version") or "").strip()
