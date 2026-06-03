Write-Host "=== PRODUCTION BASELINE TEST ===" -ForegroundColor Cyan

# API setup
$userApiKey = "seed_qqu4l1bInecYfmamHk_yoAewtzIbcSmdfLfRh3pilJ4"
$headers = @{ "X-API-Key" = $userApiKey }

# Test blueprint
$blueprint = @(
    @{ "skill" = "vocabulary"; "subskill" = "word_meaning"; "topic" = "daily_life"; "difficulty" = 0.3; "taskType" = "multiple_choice"; "cefrBand" = "A1" },
    @{ "skill" = "grammar"; "subskill" = "tenses"; "topic" = "present_simple"; "difficulty" = 0.4; "taskType" = "fill_blank"; "cefrBand" = "A2" },
    @{ "skill" = "vocabulary"; "subskill" = "synonyms"; "topic" = "emotions"; "difficulty" = 0.6; "taskType" = "multiple_choice"; "cefrBand" = "B1" },
    @{ "skill" = "grammar"; "subskill" = "conditionals"; "topic" = "hypothetical_situations"; "difficulty" = 0.8; "taskType" = "fill_blank"; "cefrBand" = "B2" },
    @{ "skill" = "vocabulary"; "subskill" = "academic_terms"; "topic" = "science"; "difficulty" = 0.9; "taskType" = "multiple_choice"; "cefrBand" = "C1" }
)

$testRequest = @{
    "nativeLang" = "Russian"
    "targetLang" = "English" 
    "blueprint" = $blueprint
} | ConvertTo-Json -Depth 5

Write-Host "Testing new production baseline (optimized prompt v2 + parser v2)..." -ForegroundColor Yellow

$totalDuration = 0
$totalItems = 0
$runs = 3

for ($i = 1; $i -le $runs; $i++) {
    Write-Host "Run $i/$runs..." -ForegroundColor Gray
    
    $startTime = Get-Date
    $response = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/generate" -Method POST -Body $testRequest -ContentType "application/json" -Headers $headers
    $duration = (Get-Date - $startTime).TotalMilliseconds
    
    $itemsCount = $response.diagnosticSet.items.Count
    $totalDuration += $duration
    $totalItems += $itemsCount
    
    Write-Host "  Generated $itemsCount items in $([math]::Round($duration, 0))ms" -ForegroundColor Green
    Start-Sleep -Seconds 2
}

$avgDuration = $totalDuration / $runs
$avgPerItem = $avgDuration / ($totalItems / $runs)

Write-Host "`n=== RESULTS ===" -ForegroundColor Cyan
Write-Host "Average: $([math]::Round($avgDuration, 0))ms total, $([math]::Round($avgPerItem, 0))ms per item" -ForegroundColor White
Write-Host "Throughput: $([math]::Round(1000 / $avgPerItem, 1)) items/second" -ForegroundColor Green

# Quality check
Write-Host "`nQuality check on last generated items:" -ForegroundColor Yellow
$response.diagnosticSet.items | ForEach-Object {
    $valid = ![string]::IsNullOrWhiteSpace($_.prompt) -and $_.answer -and $_.answer.accepted
    $status = if ($valid) { "✅" } else { "❌" }
    Write-Host "$status [$($_.tags.cefrBand)] $($_.id)" -ForegroundColor $(if ($valid) { "Green" } else { "Red" })
}

Write-Host "`nSample items:" -ForegroundColor Yellow
$response.diagnosticSet.items | Select-Object -First 2 | ForEach-Object {
    Write-Host "[$($_.tags.cefrBand)] $($_.prompt)" -ForegroundColor Cyan
    Write-Host "Answer: $($_.answer.accepted -join ', ')" -ForegroundColor Green
    Write-Host ""
}

Write-Host "=== PRODUCTION MIGRATION COMPLETE ===" -ForegroundColor Green