Write-Host "=== PROMPT V2 PERFORMANCE TEST ===" -ForegroundColor Cyan

# API setup
$userApiKey = "seed_qqu4l1bInecYfmamHk_yoAewtzIbcSmdfLfRh3pilJ4"
$headers = @{ "X-API-Key" = $userApiKey }

# Test blueprint
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

Write-Host "Testing optimized prompt v2..." -ForegroundColor Yellow
$startTime = Get-Date

$response = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/generate" -Method POST -Body $testRequest -ContentType "application/json" -Headers $headers

$duration = (Get-Date - $startTime).TotalSeconds
$itemsCount = $response.diagnosticSet.items.Count

Write-Host "SUCCESS! Generated $itemsCount items in $([math]::Round($duration, 2)) seconds" -ForegroundColor Green

Write-Host "`nSample items:" -ForegroundColor Yellow
$response.diagnosticSet.items | ForEach-Object {
    Write-Host "[$($_.cefrLevel)] $($_.taskType): $($_.question)" -ForegroundColor Cyan
}

Write-Host "`n=== COMPLETE ===" -ForegroundColor Cyan