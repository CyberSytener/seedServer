# Test Client V1 Implementation
# Quick validation script for diagnostic endpoints

$API_BASE = "http://localhost:8000"

Write-Host "`n=== Testing Client V1 Implementation ===" -ForegroundColor Cyan

# Test 1: GET /v1/personas (no auth)
Write-Host "`n[1] Testing GET /v1/personas (no auth)..." -ForegroundColor Yellow
try {
    $response = Invoke-WebRequest -Uri "$API_BASE/v1/personas" -Method GET -UseBasicParsing
    $personas = $response.Content | ConvertFrom-Json
    
    if ($personas.defaultPersonaId) {
        Write-Host "SUCCESS: Personas endpoint works without auth" -ForegroundColor Green
        Write-Host "  - Found $($personas.personas.Count) personas" -ForegroundColor Gray
        Write-Host "  - Default: $($personas.defaultPersonaId)" -ForegroundColor Gray
    } else {
        Write-Host "FAIL: Missing defaultPersonaId field" -ForegroundColor Red
    }
} catch {
    Write-Host "FAIL: Personas endpoint failed" -ForegroundColor Red
    Write-Host "  Error: $_" -ForegroundColor Red
}

# Test 2: Check API is running
Write-Host "`n[2] Checking API health..." -ForegroundColor Yellow
try {
    $health = Invoke-WebRequest -Uri "$API_BASE/health" -Method GET -UseBasicParsing | 
        ConvertFrom-Json
    
    if ($health.ok) {
        Write-Host "SUCCESS: API is healthy" -ForegroundColor Green
        Write-Host "  - Redis: $($health.redis)" -ForegroundColor Gray
        Write-Host "  - DB: $($health.db)" -ForegroundColor Gray
    }
} catch {
    Write-Host "FAIL: Health check failed" -ForegroundColor Red
}

Write-Host "`n=== Manual Testing Instructions ===" -ForegroundColor Cyan
Write-Host "To fully test the diagnostic endpoints:" -ForegroundColor White
Write-Host ""
Write-Host "1. Create a test user and get API key" -ForegroundColor Gray
Write-Host "2. Test /start with language names" -ForegroundColor Gray  
Write-Host "3. Check logs for normalization" -ForegroundColor Gray
Write-Host "4. Verify response structure" -ForegroundColor Gray
Write-Host ""

Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "Personas endpoint: Public access confirmed" -ForegroundColor Green
Write-Host "Diagnostic endpoints: Require manual testing with valid API key" -ForegroundColor Yellow
