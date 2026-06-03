"""
Test script for bug reports endpoint backward compatibility.

Tests:
1. x-api-key header with captureAt field
2. Authorization: Bearer header with capturedAt field (legacy)
"""
import json
import sys

try:
    import requests
except ImportError:
    print("Error: requests library not installed")
    print("Install with: pip install requests")
    sys.exit(1)


# Configuration
BASE_URL = "http://localhost:8000"
API_KEY = "your-test-api-key-here"  # Replace with actual API key

def test_x_api_key_with_capture_at():
    """Test with x-api-key header and captureAt field (canonical)."""
    print("Test 1: x-api-key header + captureAt field")
    print("-" * 50)
    
    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "kind": "grading_mismatch",
        "severity": "major",
        "userMessage": "Test with x-api-key and captureAt",
        "context": {
            "feature": "diagnostic",
            "sessionId": "diag_test_001"
        },
        "client": {
            "app": "seed-desktop",
            "appVersion": "1.0.0"
        },
        "debug": {
            "includeDetails": True,
            "captureAt": "2026-01-10T12:00:00Z"  # Canonical field
        }
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/v1/feedback/bug-reports",
            headers=headers,
            json=payload,
            timeout=5
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            print("✓ Test PASSED")
            return True
        else:
            print("✗ Test FAILED")
            return False
    except requests.exceptions.ConnectionError:
        print("✗ Test FAILED: Cannot connect to server")
        print("  Make sure server is running: docker-compose up")
        return False
    except Exception as e:
        print(f"✗ Test FAILED: {e}")
        return False


def test_bearer_auth_with_captured_at():
    """Test with Authorization: Bearer header and capturedAt field (legacy)."""
    print("\nTest 2: Authorization: Bearer header + capturedAt field (legacy)")
    print("-" * 50)
    
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "kind": "ui_bug",
        "severity": "minor",
        "userMessage": "Test with Bearer auth and capturedAt",
        "context": {
            "feature": "lesson",
            "sessionId": "lesson_test_002"
        },
        "client": {
            "app": "seed-desktop",
            "appVersion": "0.9.5"  # Legacy version
        },
        "debug": {
            "includeDetails": False,
            "capturedAt": "2026-01-10T12:05:00Z"  # Legacy field name
        }
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/v1/feedback/bug-reports",
            headers=headers,
            json=payload,
            timeout=5
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        if response.status_code == 200:
            print("✓ Test PASSED")
            return True
        else:
            print("✗ Test FAILED")
            return False
    except requests.exceptions.ConnectionError:
        print("✗ Test FAILED: Cannot connect to server")
        print("  Make sure server is running: docker-compose up")
        return False
    except Exception as e:
        print(f"✗ Test FAILED: {e}")
        return False


def test_both_fields_present():
    """Test with both captureAt and capturedAt (captureAt should take precedence)."""
    print("\nTest 3: Both captureAt and capturedAt present")
    print("-" * 50)
    
    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "kind": "other",
        "severity": "minor",
        "userMessage": "Test with both fields",
        "context": {},
        "client": {
            "app": "seed-desktop"
        },
        "debug": {
            "captureAt": "2026-01-10T12:10:00Z",     # Should be stored
            "capturedAt": "2026-01-10T11:00:00Z"      # Should be ignored
        }
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/v1/feedback/bug-reports",
            headers=headers,
            json=payload,
            timeout=5
        )
        
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        print("Note: When both fields present, captureAt takes precedence")
        
        if response.status_code == 200:
            print("✓ Test PASSED")
            return True
        else:
            print("✗ Test FAILED")
            return False
    except Exception as e:
        print(f"✗ Test FAILED: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Bug Report Backward Compatibility Test Suite")
    print("=" * 60)
    print()
    
    if API_KEY == "your-test-api-key-here":
        print("⚠ WARNING: Please update API_KEY in this script")
        print()
        print("To get an API key:")
        print("1. Start the server: docker-compose up")
        print("2. Create a user (if needed)")
        print("3. Update API_KEY variable in this script")
        print()
        sys.exit(1)
    
    results = []
    
    # Run tests
    results.append(("x-api-key + captureAt", test_x_api_key_with_capture_at()))
    results.append(("Bearer + capturedAt", test_bearer_auth_with_captured_at()))
    results.append(("Both fields present", test_both_fields_present()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{status}: {test_name}")
    
    print()
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print(f"\n⚠ {total - passed} test(s) failed")
        sys.exit(1)
