Write-Host "=== PROMPT V2 ANALYSIS ===" -ForegroundColor Cyan

# Проверяем структуру ответа
$itemsCount = $response.diagnosticSet.items.Count
Write-Host "✅ Generated $itemsCount diagnostic items" -ForegroundColor Green

Write-Host "`n📊 QUALITY ANALYSIS:" -ForegroundColor Yellow
$validItems = 0
$errorItems = 0

foreach ($item in $response.diagnosticSet.items) {
    $hasPrompt = ![string]::IsNullOrWhiteSpace($item.prompt)
    $hasChoices = $item.choices -and $item.choices.Count -gt 0
    $hasAnswer = $item.answer -and $item.answer.accepted -and $item.answer.accepted.Count -gt 0
    $hasId = ![string]::IsNullOrWhiteSpace($item.id)
    $hasTags = $item.tags -ne $null
    
    if ($hasPrompt -and $hasChoices -and $hasAnswer -and $hasId -and $hasTags) {
        $validItems++
        Write-Host "  ✅ $($item.id) - VALID" -ForegroundColor Green
    } else {
        $errorItems++
        Write-Host "  ❌ $($item.id) - INVALID" -ForegroundColor Red
    }
}

Write-Host "`n📈 SUMMARY:" -ForegroundColor Yellow
Write-Host "  Valid items: $validItems/$itemsCount ($([math]::Round($validItems * 100 / $itemsCount, 1))%)" -ForegroundColor Green
Write-Host "  Error items: $errorItems/$itemsCount ($([math]::Round($errorItems * 100 / $itemsCount, 1))%)" -ForegroundColor Red

Write-Host "`n🔍 SAMPLE ITEMS:" -ForegroundColor Yellow
$response.diagnosticSet.items | ForEach-Object {
    Write-Host "  🎯 [$($_.tags.cefrBand)] $($_.taskType)" -ForegroundColor Cyan
    Write-Host "     ID: $($_.id)" -ForegroundColor Gray
    Write-Host "     Q: $($_.prompt)" -ForegroundColor White
    Write-Host "     Choices: $($_.choices -join ', ')" -ForegroundColor Blue
    Write-Host "     Answer: $($_.answer.accepted -join ', ')" -ForegroundColor Green
    Write-Host ""
}

Write-Host "=== ANALYSIS COMPLETE ===" -ForegroundColor Cyan