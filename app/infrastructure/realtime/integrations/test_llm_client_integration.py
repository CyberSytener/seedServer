import json
from app.infrastructure.realtime.integrations.advanced_reply_parser import AdvancedReplyParser, ParseStrategy, InterestLevel


def test_llm_client_returns_dict_response():
    class FakeLLM:
        def complete(self, prompt: str):
            return {"interest_level": "high", "confidence": 0.88, "reasoning": "positive signals"}

    parser = AdvancedReplyParser(strategy=ParseStrategy.LLM)
    res = parser.parse_reply("I am interested", llm_client=FakeLLM())

    assert res.interest_level == InterestLevel.HIGH
    assert res.confidence == 0.88


def test_llm_client_returns_json_string_response():
    class FakeLLM:
        def complete(self, prompt: str):
            return json.dumps({"interest_level": "neutral", "confidence": 0.6, "reasoning": "needs info"})

    parser = AdvancedReplyParser(strategy=ParseStrategy.LLM)
    res = parser.parse_reply("Maybe, need more info", llm_client=FakeLLM())

    assert res.interest_level == InterestLevel.NEUTRAL
    assert abs(res.confidence - 0.6) < 1e-6


def test_llm_client_raises_exception_falls_back_to_sentiment():
    class BadLLM:
        def complete(self, prompt: str):
            raise RuntimeError("LLM down")

    parser = AdvancedReplyParser(strategy=ParseStrategy.LLM)
    res = parser.parse_reply("No thanks, not interested", llm_client=BadLLM())

    # Sentiment parse should classify as LOW or NEUTRAL
    assert res.interest_level in (InterestLevel.LOW, InterestLevel.NEUTRAL)

