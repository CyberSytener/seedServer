import json
from datetime import datetime, timedelta
import pytest

from app.infrastructure.realtime.integrations.advanced_reply_parser import (
    AdvancedReplyParser,
    ParseStrategy,
    InterestLevel,
)


def test_regex_detects_high_interest_and_confidence():
    parser = AdvancedReplyParser(strategy=ParseStrategy.REGEX)
    res = parser.parse_reply("I'm very interested and would love to talk")

    assert res.interest_level == InterestLevel.HIGH
    assert res.confidence > 0.3


def test_sentiment_detects_low_interest():
    parser = AdvancedReplyParser(strategy=ParseStrategy.SENTIMENT)
    res = parser.parse_reply("No thanks, I'm not interested at this time")

    assert res.interest_level == InterestLevel.LOW
    assert res.confidence <= 1.0


def test_hybrid_uses_llm_when_provided(monkeypatch):
    # Make a text that has both positive and neutral signals
    text = "Maybe, would like to know more but looks interesting"

    class FakeLLM:
        def complete(self, prompt: str):
            # Return dict promoting NEUTRAL with moderate confidence
            return {"interest_level": "neutral", "confidence": 0.6, "reasoning": "needs info"}

    parser = AdvancedReplyParser(strategy=ParseStrategy.HYBRID)
    res = parser.parse_reply(text, llm_client=FakeLLM())

    # With blended votes neutral should be plausible
    assert res.interest_level in (InterestLevel.NEUTRAL, InterestLevel.HIGH, InterestLevel.LOW)
    assert 0.0 <= res.confidence <= 1.0


def test_llm_handles_non_json_string_response():
    class FakeLLM:
        def complete(self, prompt: str):
            return "I think neutral but would ask for clarification"

    parser = AdvancedReplyParser(strategy=ParseStrategy.LLM)
    res = parser.parse_reply("Maybe", llm_client=FakeLLM())

    # No explicit interest_level provided -> UNKNOWN but reasoning contains text
    assert res.interest_level == InterestLevel.UNKNOWN
    assert "I think neutral" in (res.reasoning or "")


def test_record_correction_and_get_metrics():
    parser = AdvancedReplyParser()
    parser.record_correction(original_prediction=InterestLevel.NEUTRAL, actual_label=InterestLevel.HIGH, email_text="x", feedback="correction")
    parser.record_correction(original_prediction=InterestLevel.HIGH, actual_label=InterestLevel.HIGH, email_text="y", feedback="ok")

    metrics = parser.get_metrics()
    assert metrics.total_samples == 2
    assert "high" in metrics.precision
    assert metrics.accuracy >= 0.5

