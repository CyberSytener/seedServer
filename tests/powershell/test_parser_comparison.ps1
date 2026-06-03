Write-Host "=== PARSER PERFORMANCE COMPARISON ===" -ForegroundColor Cyan

# API setup
$userApiKey = "seed_qqu4l1bInecYfmamHk_yoAewtzIbcSmdfLfRh3pilJ4"
$headers = @{ "X-API-Key" = $userApiKey }

# Test blueprint (same as before)
$blueprint = @(
    @{ "skill" = "vocabulary"; "subskill" = "word_meaning"; "topic" = "daily_life"; "difficulty" = 0.3; "taskType" = "multiple_choice"; "cefrBand" = "A1" },
    @{ "skill" = "grammar"; "subskill" = "tenses"; "topic" = "present_simple"; "difficulty" = 0.4; "taskType" = "fill_blank"; "cefrBand" = "A2" },
    @{ "skill" = "vocabulary"; "subskill" = "synonyms"; "topic" = "emotions"; "difficulty" = 0.6; "taskType" = "multiple_choice"; "cefrBand" = "B1" }
)

$testRequest = @{
    "nativeLang" = "Russian"
    "targetLang" = "English" 
    "blueprint" = $blueprint
} | ConvertTo-Json -Depth 5

# Test 1: Baseline parser
Write-Host "`n1. Testing BASELINE parser..." -ForegroundColor Yellow

$baselineResults = @()
for ($i = 1; $i -le 3; $i++) {
    Write-Host "  Run $i/3..." -ForegroundColor Gray
    
    $startTime = Get-Date
    $response = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/generate" -Method POST -Body $testRequest -ContentType "application/json" -Headers $headers
    $endTime = Get-Date
    
    $duration = ($endTime - $startTime).TotalMilliseconds
    $itemsCount = $response.diagnosticSet.items.Count
    
    $baselineResults += $duration
    Write-Host "    Generated $itemsCount items in $([math]::Round($duration, 0))ms" -ForegroundColor Green
    
    Start-Sleep -Seconds 2  # Small delay between tests
}

# Switch to v2 parser
Write-Host "`n2. Switching to V2 parser..." -ForegroundColor Yellow
$envContent = Get-Content ".env" -Raw
$envContent = $envContent -replace "SEED_PARSER_VERSION=baseline", "SEED_PARSER_VERSION=v2"
Set-Content ".env" -Value $envContent

# Restart API
Write-Host "   Restarting API..." -ForegroundColor Gray
docker-compose restart api | Out-Null
Start-Sleep -Seconds 5

# Test 2: V2 parser  
Write-Host "3. Testing V2 OPTIMIZED parser..." -ForegroundColor Yellow

$v2Results = @()
for ($i = 1; $i -le 3; $i++) {
    Write-Host "  Run $i/3..." -ForegroundColor Gray
    
    $startTime = Get-Date
    $response = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/generate" -Method POST -Body $testRequest -ContentType "application/json" -Headers $headers
    $endTime = Get-Date
    
    $duration = ($endTime - $startTime).TotalMilliseconds
    $itemsCount = $response.diagnosticSet.items.Count
    
    $v2Results += $duration
    Write-Host "    Generated $itemsCount items in $([math]::Round($duration, 0))ms" -ForegroundColor Green
    
    Start-Sleep -Seconds 2
}

# Calculate averages and comparison
$baselineAvg = ($baselineResults | Measure-Object -Average).Average
$v2Avg = ($v2Results | Measure-Object -Average).Average
$improvement = (($baselineAvg - $v2Avg) / $baselineAvg) * 100

Write-Host "`n=== RESULTS ===" -ForegroundColor Cyan
Write-Host "Baseline Parser Average: $([math]::Round($baselineAvg, 0))ms" -ForegroundColor White
Write-Host "V2 Parser Average: $([math]::Round($v2Avg, 0))ms" -ForegroundColor White

if ($improvement -gt 0) {
    Write-Host "IMPROVEMENT: $([math]::Round($improvement, 1))% faster with V2 parser" -ForegroundColor Green
} else {
    Write-Host "REGRESSION: $([math]::Round([math]::Abs($improvement), 1))% slower with V2 parser" -ForegroundColor Red
}

# Reset to baseline for consistency
Write-Host "`nResetting to baseline parser..." -ForegroundColor Gray
$envContent = $envContent -replace "SEED_PARSER_VERSION=v2", "SEED_PARSER_VERSION=baseline"
Set-Content ".env" -Value $envContent

Write-Host "=== PARSER COMPARISON COMPLETE ===" -ForegroundColor Cyan