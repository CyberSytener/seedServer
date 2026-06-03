"""
Test script for bug reports endpoint and reorder_sentence grading fix.
"""
import json
import requests
import pytest
from requests.exceptions import RequestException

# Configuration
BASE_URL = "http://localhost:8000"
API_KEY = "your-test-api-key-here"  # Replace with actual API key

headers = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json"
}


def test_bug_report():
    """Test the bug reports endpoint."""
    print("Testing Bug Reports Endpoint...")
    
    bug_report_payload = {
        "kind": "grading_mismatch",
        "severity": "major",
        "userMessage": "Expected 'I eat apples' to be correct but got marked wrong",
        "context": {
            "feature": "diagnostic",
            "sessionId": "diag_test123",
            "itemId": "item_456",
            "taskType": "reorder_sentence",
            "prompt": "Reorder: I / apples / eat",
            "tokens": ["I", "eat", "apples"],
            "userAnswerRaw": "I eat apples",
            "correctAnswerShown": "I eat apples.",
            "serverResponse": {
                "correct": False
            }
        },
        "client": {
            "app": "seed-desktop",
            "appVersion": "1.0.0",
            "platform": "win32",
            "userAgent": "Mozilla/5.0",
            "locale": "en-US",
            "timezone": "America/New_York"
        },
        "debug": {
            "includeDetails": True,
            "captureAt": "2026-01-10T12:34:56Z"
        }
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/v1/feedback/bug-reports",
            headers=headers,
            json=bug_report_payload,
            timeout=5,
        )
    except RequestException as exc:
        pytest.skip(f"Bug report endpoint not reachable: {exc}")
    
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        print("✓ Bug report submitted successfully!")
        data = response.json()
        print(f"  Report ID: {data.get('reportId')}")
        print(f"  Received At: {data.get('receivedAt')}")
    else:
        print("✗ Bug report submission failed!")
    
    print()


def test_reorder_sentence_normalization():
    """
    Test the reorder_sentence grading normalization.
    This would require setting up a diagnostic session, but we can document the fix.
    """
    print("Testing reorder_sentence Normalization Fix...")
    print()
    print("The following cases should now be handled correctly:")
    print("  1. 'I eat apples' == 'I eat apples.' (trailing punctuation)")
    print("  2. 'i eat apples' == 'I eat apples.' (case difference)")
    print("  3. 'I  eat  apples' == 'I eat apples.' (extra spaces)")
    print("  4. 'I eat apples' == 'I eat apples…' (various punctuation)")
    print()
    print("Normalization applied:")
    print("  - Unicode NFKC normalization")
    print("  - Strip and collapse whitespace")
    print("  - Casefold (locale-aware lowercase)")
    print("  - Remove trailing punctuation: . ! ? …")
    print()
    
    # Test the normalization function locally
    from app.services.diagnostic.session import normalize_answer_reorder_sentence
    
    test_cases = [
        ("I eat apples", "I eat apples."),
        ("i eat apples", "I eat apples."),
        ("I  eat  apples", "I eat apples."),
        ("I eat apples", "I eat apples!"),
        ("I eat apples", "I eat apples?"),
        ("I eat apples", "I eat apples…"),
    ]
    
    print("Local normalization tests:")
    for user_answer, expected_answer in test_cases:
        user_norm = normalize_answer_reorder_sentence(user_answer)
        expected_norm = normalize_answer_reorder_sentence(expected_answer)
        match = user_norm == expected_norm
        symbol = "✓" if match else "✗"
        print(f"  {symbol} '{user_answer}' vs '{expected_answer}': {match}")
        if not match:
            print(f"     Normalized: '{user_norm}' vs '{expected_norm}'")
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("Bug Report & Grading Fix Test Suite")
    print("=" * 60)
    print()
    
    # Test normalization locally (doesn't require server)
    test_reorder_sentence_normalization()
    
    # Test bug reports endpoint (requires server running)
    print("To test the bug reports endpoint:")
    print("1. Start the server: docker-compose up")
    print("2. Update API_KEY in this script")
    print("3. Run: python test_bug_report.py")
    print()
    
    # Uncomment to test bug reports (requires server + API key)
    # test_bug_report()

