# Test optimized prompt v2 performance
$ErrorActionPreference = "Continue"

Write-Host "=== PROMPT V2 PERFORMANCE TEST ===" -ForegroundColor Cyan

# API Key (from previous user creation)
$userApiKey = "seed_qqu4l1bInecYfmamHk_yoAewtzIbcSmdfLfRh3pilJ4"
$headers = @{ "X-API-Key" = $userApiKey }

# Test blueprint
$blueprint = @(
    @{
        "skill" = "vocabulary"
        "subskill" = "word_meaning"
        "topic" = "daily_life"
        "difficulty" = 0.3
        "taskType" = "multiple_choice"
        "cefrBand" = "A1"
    },
    @{
        "skill" = "grammar"
        "subskill" = "tenses"
        "topic" = "present_simple"
        "difficulty" = 0.4
        "taskType" = "fill_blank"
        "cefrBand" = "A2"
    },
    @{
        "skill" = "vocabulary"
        "subskill" = "synonyms"
        "topic" = "emotions"
        "difficulty" = 0.6
        "taskType" = "multiple_choice"
        "cefrBand" = "B1"
    }
)

$testRequest = @{
    "nativeLang" = "Russian"
    "targetLang" = "English"
    "blueprint" = $blueprint
} | ConvertTo-Json -Depth 5

Write-Host "`n🧪 Testing optimized prompt v2..." -ForegroundColor Yellow
$startTime = Get-Date

$response = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/generate" -Method POST -Body $testRequest -ContentType "application/json" -Headers $headers

$endTime = Get-Date
$duration = ($endTime - $startTime).TotalSeconds
$itemsCount = $response.diagnosticSet.items.Count

Write-Host "✅ SUCCESS!" -ForegroundColor Green
Write-Host "📊 Generated: $itemsCount items" -ForegroundColor White
Write-Host "⏱️  Duration: $([math]::Round($duration, 2)) seconds" -ForegroundColor White
Write-Host "🚀 Speed: $([math]::Round($itemsCount / $duration, 1)) items/second" -ForegroundColor White

# Quality check
Write-Host "`n🔍 Quality Check:" -ForegroundColor Yellow
foreach ($item in $response.diagnosticSet.items) {
    $hasQuestion = ![string]::IsNullOrWhiteSpace($item.question)
    $hasAnswer = ![string]::IsNullOrWhiteSpace($item.correctAnswer)
    $hasCefr = ![string]::IsNullOrWhiteSpace($item.cefrLevel)
    $hasTask = ![string]::IsNullOrWhiteSpace($item.taskType)
    
    if ($hasQuestion -and $hasAnswer -and $hasCefr -and $hasTask) {
        Write-Host "  ✅ [$($item.cefrLevel)] $($item.taskType) - OK" -ForegroundColor Green
    } else {
        Write-Host "  ❌ [$($item.cefrLevel)] $($item.taskType) - INVALID" -ForegroundColor Red
    }
}

# Sample items
Write-Host "`n📋 Sample Generated Items:" -ForegroundColor Yellow
$response.diagnosticSet.items | Select-Object -First 2 | ForEach-Object {
    Write-Host "  🔤 [$($_.cefrLevel)] $($_.taskType)" -ForegroundColor Cyan
    Write-Host "     Q: $($_.question)" -ForegroundColor White
    Write-Host "     A: $($_.correctAnswer)" -ForegroundColor Green
    Write-Host ""
}

Write-Host "=== TEST COMPLETE ===" -ForegroundColor Cyan