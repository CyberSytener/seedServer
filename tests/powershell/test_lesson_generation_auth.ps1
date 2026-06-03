# Test lesson generation endpoint with different auth methods

$baseUrl = "http://localhost:8000"

Write-Host "Testing POST /v1/lessons/generate authentication" -ForegroundColor Cyan
Write-Host ""

# Test payload
$payload = @{
    targetLang = "en"
    nativeLang = "ru"
    level = "beginner"
    mode = "mixed"
    lessonLength = 10
    personaId = "classic_tutor"
} | ConvertTo-Json

Write-Host "Test 1: No authentication" -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$baseUrl/v1/lessons/generate" `
        -Method POST `
        -ContentType "application/json" `
        -Body $payload `
        -ErrorAction Stop
    Write-Host "✅ Success (unexpected!)" -ForegroundColor Green
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    Write-Host "❌ Failed with status $statusCode (expected)" -ForegroundColor Red
}

Write-Host ""
Write-Host "Test 2: With X-User-ID header (legacy mode)" -ForegroundColor Yellow
try {
    $response = Invoke-RestMethod -Uri "$baseUrl/v1/lessons/generate" `
        -Method POST `
        -Headers @{
            "X-User-ID" = "desktop_test_user_123"
        } `
        -ContentType "application/json" `
        -Body $payload `
        -ErrorAction Stop
    Write-Host "✅ Success! Lesson generated:" -ForegroundColor Green
    Write-Host "   Lesson ID: $($response.lessonId)"
    Write-Host "   Tasks: $($response.tasks.Count)"
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    $errorBody = $_.ErrorDetails.Message
    Write-Host "❌ Failed with status $statusCode" -ForegroundColor Red
    Write-Host "   Error: $errorBody"
}

Write-Host ""
Write-Host "Test 3: Check legacy mode setting" -ForegroundColor Yellow
Write-Host "   SEED_ENABLE_LEGACY_X_USER_ID should be: true (default)"
Write-Host "   This allows X-User-ID header without API key"

Write-Host ""
Write-Host "💡 Fix for desktop client:" -ForegroundColor Cyan
Write-Host "   Ensure all HTTP requests include X-User-ID header"
Write-Host "   Example: headers: { 'X-User-ID': userId }"
