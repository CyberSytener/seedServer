Write-Host "=== SPECIALIZED TESTS COMPREHENSIVE EVALUATION ===" -ForegroundColor Cyan

$userApiKey = "seed_BwTp5n3bqw39ib5xJHp3QqXs4UcpOJxX10LzgjKH5qI"
$headers = @{ "X-API-Key" = $userApiKey }

Write-Host "`n1. Testing specialized tests discovery..." -ForegroundColor Yellow

try {
    $testsInfo = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/specialized/tests" -Method GET -Headers $headers
    Write-Host "✅ Available specialized tests:" -ForegroundColor Green
    Write-Host "   Available tests count: $($testsInfo.available_tests.Count)" -ForegroundColor White
    Write-Host "   Tests: $($testsInfo.available_tests -join ', ')" -ForegroundColor Cyan
} catch {
    Write-Host "❌ Failed to get tests info: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n2. Testing Business English specialized test..." -ForegroundColor Yellow

try {
    $startTime = Get-Date
    $businessTest = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/specialized/business_english" -Method POST -Headers $headers
    $duration = (Get-Date - $startTime).TotalMilliseconds
    
    Write-Host "✅ Business English test generated in $([math]::Round($duration, 0))ms" -ForegroundColor Green
    Write-Host "   Generated items: $($businessTest.diagnosticSet.items.Count)" -ForegroundColor White
    Write-Host "   Sample item: $($businessTest.diagnosticSet.items[0].prompt.Substring(0, [Math]::Min(100, $businessTest.diagnosticSet.items[0].prompt.Length)))..." -ForegroundColor Gray
} catch {
    Write-Host "❌ Business English test failed: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n3. Testing Medical English specialized test..." -ForegroundColor Yellow

try {
    $startTime = Get-Date  
    $medicalTest = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/specialized/medical_english" -Method POST -Headers $headers
    $duration = (Get-Date - $startTime).TotalMilliseconds
    
    Write-Host "✅ Medical English test generated in $([math]::Round($duration, 0))ms" -ForegroundColor Green
    Write-Host "   Generated items: $($medicalTest.diagnosticSet.items.Count)" -ForegroundColor White
    Write-Host "   Sample item: $($medicalTest.diagnosticSet.items[0].prompt.Substring(0, [Math]::Min(100, $medicalTest.diagnosticSet.items[0].prompt.Length)))..." -ForegroundColor Gray
} catch {
    Write-Host "❌ Medical English test failed: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n=== SPECIALIZED TESTS EVALUATION COMPLETE ===" -ForegroundColor Cyan
Write-Host "🎯 New specialized diagnostic capabilities successfully deployed!" -ForegroundColor Green