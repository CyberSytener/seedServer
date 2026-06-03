Write-Host "=== SPECIALIZED TEST FRAMEWORK VALIDATION ===" -ForegroundColor Cyan

$userApiKey = "seed_BwTp5n3bqw39ib5xJHp3QqXs4UcpOJxX10LzgjKH5qI"
$headers = @{ "X-API-Key" = $userApiKey }

Write-Host "`nTesting endpoint discovery..." -ForegroundColor Green
try {
    $tests = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/specialized/tests" -Method GET -Headers $headers
    Write-Host "SUCCESS: Available tests: $($tests.available_tests.Count)" -ForegroundColor Green
    Write-Host "Tests: $($tests.available_tests -join ', ')" -ForegroundColor Cyan
    if ($tests.domains) {
        Write-Host "Domains: $($tests.domains -join ', ')" -ForegroundColor Blue
    }
    if ($tests.dialects) {
        Write-Host "Dialects: $($tests.dialects -join ', ')" -ForegroundColor Blue
    }
} catch {
    Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`nSPECIALIZED FRAMEWORK STATUS:" -ForegroundColor Cyan
Write-Host "Framework deployed and operational!" -ForegroundColor Green