# Desktop Client Compatibility Test
# Test various scenarios that desktop client might use

Write-Host "=== DESKTOP CLIENT COMPATIBILITY TEST ===" -ForegroundColor Cyan

$baseUrl = "http://localhost:8000"

# Test 1: Regular user with custom ID (typical desktop client scenario)
Write-Host "`nTest 1: Desktop client creating user with custom ID..." -ForegroundColor Yellow
$body1 = @{
    "user_id" = "desktop_user_$(Get-Random)"
    "email" = "user@desktop.app"
    "is_admin" = $false
    "meta" = @{
        "client_type" = "desktop"
        "version" = "1.0"
    }
} | ConvertTo-Json

try {
    $response1 = Invoke-RestMethod -Uri "$baseUrl/v1/users" -Method POST -Body $body1 -ContentType "application/json" -ErrorAction Stop
    Write-Host "✅ SUCCESS: Created user ID: $($response1.user_id)" -ForegroundColor Green
} catch {
    Write-Host "❌ ERROR: $($_.Exception.Response.StatusCode) - $($_.Exception.Message)" -ForegroundColor Red
}

# Test 2: Auto-generated ID (fallback scenario)
Write-Host "`nTest 2: Auto-generated user ID..." -ForegroundColor Yellow
$body2 = @{
    "user_id" = ""
    "email" = "auto@desktop.app"
    "is_admin" = $false
    "meta" = @{
        "client_type" = "desktop"
    }
} | ConvertTo-Json

try {
    $response2 = Invoke-RestMethod -Uri "$baseUrl/v1/users" -Method POST -Body $body2 -ContentType "application/json" -ErrorAction Stop
    Write-Host "✅ SUCCESS: Created user ID: $($response2.user_id)" -ForegroundColor Green
} catch {
    Write-Host "❌ ERROR: $($_.Exception.Response.StatusCode) - $($_.Exception.Message)" -ForegroundColor Red
}

# Test 3: No email (optional field)
Write-Host "`nTest 3: User without email..." -ForegroundColor Yellow
$body3 = @{
    "user_id" = "no_email_user"
    "email" = ""
    "is_admin" = $false
    "meta" = @{}
} | ConvertTo-Json

try {
    $response3 = Invoke-RestMethod -Uri "$baseUrl/v1/users" -Method POST -Body $body3 -ContentType "application/json" -ErrorAction Stop
    Write-Host "✅ SUCCESS: Created user ID: $($response3.user_id)" -ForegroundColor Green
} catch {
    Write-Host "❌ ERROR: $($_.Exception.Response.StatusCode) - $($_.Exception.Message)" -ForegroundColor Red
}

# Test 4: Admin attempt (should fail)
Write-Host "`nTest 4: Admin attempt without key (should fail)..." -ForegroundColor Yellow
$body4 = @{
    "user_id" = "admin_attempt"
    "email" = "admin@desktop.app"
    "is_admin" = $true
    "meta" = @{}
} | ConvertTo-Json

try {
    $response4 = Invoke-RestMethod -Uri "$baseUrl/v1/users" -Method POST -Body $body4 -ContentType "application/json" -ErrorAction Stop
    Write-Host "❌ UNEXPECTED SUCCESS: $($response4.user_id)" -ForegroundColor Red
} catch {
    Write-Host "✅ EXPECTED ERROR: $($_.Exception.Response.StatusCode) - Admin operations properly blocked" -ForegroundColor Green
}

Write-Host "`n=== TEST COMPLETE ===" -ForegroundColor Cyan
Write-Host "Desktop client should be able to create users with scenarios 1, 2, and 3." -ForegroundColor White