from app.services.llm_engine import LLMEngine
from app.services.receipt_vision_engine import ReceiptVisionEngine


def test_llm_receipt_fallback_does_not_invent_items() -> None:
    result = LLMEngine().analyze_receipt(image_bytes=b"not-a-real-receipt")

    assert result["items"] == []
    assert result["validation_passed"] is False
    assert "No receipt items extracted" in result["validation_errors"]


def test_receipt_vision_fallback_does_not_invent_items() -> None:
    result = ReceiptVisionEngine().analyze_receipt(image_bytes=b"not-a-real-receipt")

    assert result["items"] == []
    assert result["validation_passed"] is False
    assert "No food receipt items extracted" in result["validation_errors"]
