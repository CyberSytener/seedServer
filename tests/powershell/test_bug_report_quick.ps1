# Quick test for bug reports endpoint compatibility
# Tests both x-api-key and Authorization: Bearer headers

$BASE_URL = "http://localhost:8000"
$API_KEY = "seed_test_key_123"  # Replace with actual API key

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Bug Report Compatibility Test" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Test 1: x-api-key with captureAt
Write-Host "Test 1: x-api-key header + captureAt field" -ForegroundColor Yellow
Write-Host "--------------------------------------------------" -ForegroundColor Gray

$headers1 = @{
    "x-api-key" = $API_KEY
    "Content-Type" = "application/json"
}

$body1 = @{
    kind = "grading_mismatch"
    severity = "major"
    userMessage = "Test with x-api-key and captureAt"
    context = @{
        feature = "diagnostic"
        sessionId = "diag_test_001"
    }
    client = @{
        app = "seed-desktop"
        appVersion = "1.0.0"
    }
    debug = @{
        includeDetails = $true
        captureAt = "2026-01-10T12:00:00Z"
    }
} | ConvertTo-Json

try {
    $response1 = Invoke-WebRequest -Uri "$BASE_URL/v1/feedback/bug-reports" -Method POST -Headers $headers1 -Body $body1 -UseBasicParsing -ErrorAction Stop
    $result1 = $response1.Content | ConvertFrom-Json
    Write-Host "Status: $($response1.StatusCode)" -ForegroundColor Green
    Write-Host "Report ID: $($result1.reportId)" -ForegroundColor Green
    Write-Host "✓ Test 1 PASSED" -ForegroundColor Green
} catch {
    Write-Host "✗ Test 1 FAILED: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
        $errorBody = $reader.ReadToEnd()
        Write-Host "Error details: $errorBody" -ForegroundColor Red
    }
}

Write-Host ""

# Test 2: Authorization: Bearer with capturedAt (legacy)
Write-Host "Test 2: Authorization: Bearer + capturedAt field (legacy)" -ForegroundColor Yellow
Write-Host "--------------------------------------------------" -ForegroundColor Gray

$headers2 = @{
    "Authorization" = "Bearer $API_KEY"
    "Content-Type" = "application/json"
}

$body2 = @{
    kind = "ui_bug"
    severity = "minor"
    userMessage = "Test with Bearer auth and capturedAt"
    context = @{
        feature = "lesson"
        sessionId = "lesson_test_002"
    }
    client = @{
        app = "seed-desktop"
        appVersion = "0.9.5"
    }
    debug = @{
        includeDetails = $false
        capturedAt = "2026-01-10T12:05:00Z"  # Legacy field
    }
} | ConvertTo-Json

try {
    $response2 = Invoke-WebRequest -Uri "$BASE_URL/v1/feedback/bug-reports" -Method POST -Headers $headers2 -Body $body2 -UseBasicParsing -ErrorAction Stop
    $result2 = $response2.Content | ConvertFrom-Json
    Write-Host "Status: $($response2.StatusCode)" -ForegroundColor Green
    Write-Host "Report ID: $($result2.reportId)" -ForegroundColor Green
    Write-Host "✓ Test 2 PASSED" -ForegroundColor Green
} catch {
    Write-Host "✗ Test 2 FAILED: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $reader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
        $errorBody = $reader.ReadToEnd()
        Write-Host "Error details: $errorBody" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Note: Update API_KEY variable to test with real key" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
