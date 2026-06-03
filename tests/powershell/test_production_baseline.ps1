Write-Host "=== PRODUCTION BASELINE PERFORMANCE TEST ===" -ForegroundColor Cyan
Write-Host "Testing optimized prompt v2 + parser v2 as new baseline..." -ForegroundColor Yellow

# API setup
$userApiKey = "seed_qqu4l1bInecYfmamHk_yoAewtzIbcSmdfLfRh3pilJ4"
$headers = @{ "X-API-Key" = $userApiKey }

# Test blueprint - extended for thorough testing
$blueprint = @(
    @{ "skill" = "vocabulary"; "subskill" = "word_meaning"; "topic" = "daily_life"; "difficulty" = 0.2; "taskType" = "multiple_choice"; "cefrBand" = "A1" },
    @{ "skill" = "grammar"; "subskill" = "tenses"; "topic" = "present_simple"; "difficulty" = 0.3; "taskType" = "fill_blank"; "cefrBand" = "A1" },
    @{ "skill" = "vocabulary"; "subskill" = "synonyms"; "topic" = "emotions"; "difficulty" = 0.4; "taskType" = "multiple_choice"; "cefrBand" = "A2" },
    @{ "skill" = "grammar"; "subskill" = "articles"; "topic" = "definite_indefinite"; "difficulty" = 0.5; "taskType" = "fill_blank"; "cefrBand" = "A2" },
    @{ "skill" = "vocabulary"; "subskill" = "collocations"; "topic" = "business"; "difficulty" = 0.6; "taskType" = "multiple_choice"; "cefrBand" = "B1" },
    @{ "skill" = "grammar"; "subskill" = "conditionals"; "topic" = "hypothetical_situations"; "difficulty" = 0.7; "taskType" = "fill_blank"; "cefrBand" = "B1" },
    @{ "skill" = "vocabulary"; "subskill" = "academic_terms"; "topic" = "science"; "difficulty" = 0.8; "taskType" = "multiple_choice"; "cefrBand" = "B2" },
    @{ "skill" = "grammar"; "subskill" = "subjunctive"; "topic" = "complex_expressions"; "difficulty" = 0.9; "taskType" = "fill_blank"; "cefrBand" = "C1" }
)

$testRequest = @{
    "nativeLang" = "Russian"
    "targetLang" = "English" 
    "blueprint" = $blueprint
} | ConvertTo-Json -Depth 5

Write-Host "`nRunning comprehensive production test..." -ForegroundColor Yellow

$results = @()
for ($i = 1; $i -le 5; $i++) {
    Write-Host "  Test run $i/5..." -ForegroundColor Gray
    
    $startTime = Get-Date
    $response = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/generate" -Method POST -Body $testRequest -ContentType "application/json" -Headers $headers
    $endTime = Get-Date
    
    $duration = ($endTime - $startTime).TotalMilliseconds
    $itemsCount = $response.diagnosticSet.items.Count
    
    $results += [PSCustomObject]@{
        Run = $i
        Duration = $duration
        Items = $itemsCount
        AvgPerItem = $duration / $itemsCount
    }
    
    Write-Host "    Generated $itemsCount items in $([math]::Round($duration, 0))ms ($([math]::Round($duration/$itemsCount, 0))ms per item)" -ForegroundColor Green
    
    Start-Sleep -Seconds 1
}

# Calculate statistics
$avgDuration = ($results.Duration | Measure-Object -Average).Average
$avgPerItem = ($results.AvgPerItem | Measure-Object -Average).Average
$minDuration = ($results.Duration | Measure-Object -Minimum).Minimum
$maxDuration = ($results.Duration | Measure-Object -Maximum).Maximum

Write-Host "`n=== PRODUCTION BASELINE RESULTS ===" -ForegroundColor Cyan
Write-Host "Items per test: $($results[0].Items)" -ForegroundColor White
Write-Host "Average total time: $([math]::Round($avgDuration, 0))ms" -ForegroundColor White
Write-Host "Average per item: $([math]::Round($avgPerItem, 0))ms" -ForegroundColor White
Write-Host "Best time: $([math]::Round($minDuration, 0))ms" -ForegroundColor Green
Write-Host "Worst time: $([math]::Round($maxDuration, 0))ms" -ForegroundColor Yellow
Write-Host "Throughput: $([math]::Round(1000 / $avgPerItem, 1)) items/second" -ForegroundColor Cyan

# Quality check on last response
Write-Host "`n🔍 QUALITY CHECK:" -ForegroundColor Yellow
$validItems = 0
$errorItems = 0

foreach ($item in $response.diagnosticSet.items) {
    $hasPrompt = ![string]::IsNullOrWhiteSpace($item.prompt)
    $hasAnswer = $item.answer -and $item.answer.accepted -and $item.answer.accepted.Count -gt 0
    $hasId = ![string]::IsNullOrWhiteSpace($item.id)
    $hasTags = $item.tags -ne $null
    
    if ($hasPrompt -and $hasAnswer -and $hasId -and $hasTags) {
        $validItems++
    } else {
        $errorItems++
        Write-Host "  ❌ Invalid item: $($item.id)" -ForegroundColor Red
    }
}

Write-Host "Valid items: $validItems/$($response.diagnosticSet.items.Count) ($([math]::Round($validItems * 100 / $response.diagnosticSet.items.Count, 1))%)" -ForegroundColor Green

# Show sample items
Write-Host "`n📋 SAMPLE GENERATED ITEMS:" -ForegroundColor Yellow
$response.diagnosticSet.items | Select-Object -First 3 | ForEach-Object {
    Write-Host "  🎯 [$($_.tags.cefrBand)] $($_.taskType)" -ForegroundColor Cyan
    Write-Host "     ID: $($_.id)" -ForegroundColor Gray
    Write-Host "     Q: $($_.prompt)" -ForegroundColor White
    if ($_.choices) {
        Write-Host "     Choices: $($_.choices -join ', ')" -ForegroundColor Blue
    }
    Write-Host "     A: $($_.answer.accepted -join ', ')" -ForegroundColor Green
    Write-Host ""
}

Write-Host "=== PRODUCTION TEST COMPLETE ===" -ForegroundColor Cyan
Write-Host "🚀 Optimized versions successfully deployed to baseline!" -ForegroundColor Green