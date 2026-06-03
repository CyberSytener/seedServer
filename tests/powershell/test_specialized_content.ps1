Write-Host "=== SPECIALIZED CONTENT GENERATION TESTING ===" -ForegroundColor Cyan

$userApiKey = "seed_YzHs9jecpfaBCugDitpEfeWQDBf45c3MO5NVwu7jdno"
$headers = @{ "X-API-Key" = $userApiKey }

Write-Host "`n1. FRAMEWORK VERIFICATION" -ForegroundColor Yellow
try {
    $tests = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/specialized/tests" -Method GET -Headers $headers
    Write-Host "✅ Discovery endpoint: $($tests.available_tests.Count) tests available" -ForegroundColor Green
    Write-Host "   Tests: $($tests.available_tests -join ', ')" -ForegroundColor Cyan
    Write-Host "   Domains: $($tests.domains -join ', ')" -ForegroundColor Blue  
    Write-Host "   Dialects: $($tests.dialects -join ', ')" -ForegroundColor Magenta
} catch {
    Write-Host "❌ Discovery failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "`n2. BUSINESS ENGLISH CONTENT GENERATION" -ForegroundColor Yellow
try {
    $startTime = Get-Date
    $business = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/specialized/business_english" -Method POST -Headers $headers
    $duration = (Get-Date - $startTime).TotalMilliseconds
    
    Write-Host "✅ Business test generated in $([math]::Round($duration, 0))ms" -ForegroundColor Green
    Write-Host "   Items generated: $($business.diagnosticSet.items.Count)" -ForegroundColor White
    
    # Validate content quality
    $validItems = 0
    $businessItems = $business.diagnosticSet.items
    
    foreach ($item in $businessItems) {
        $valid = $true
        if (-not $item.taskType -or $item.taskType -notin @('mcq', 'fill_blank', 'reorder_sentence', 'translate', 'reading_mcq')) {
            Write-Host "   ⚠️ Invalid taskType: $($item.taskType)" -ForegroundColor Yellow
            $valid = $false
        }
        if (-not $item.tags.domain -or $item.tags.domain -ne 'business') {
            Write-Host "   ⚠️ Missing/incorrect domain: $($item.tags.domain)" -ForegroundColor Yellow  
            $valid = $false
        }
        if ($item.taskType -eq 'mcq' -and $item.choices.Count -ne 4) {
            Write-Host "   ⚠️ MCQ without 4 choices: $($item.choices.Count)" -ForegroundColor Yellow
            $valid = $false
        }
        if ($valid) { $validItems++ }
    }
    
    Write-Host "   📊 Valid items: $validItems / $($businessItems.Count)" -ForegroundColor White
    Write-Host "   📋 Sample item: $($businessItems[0].prompt.Substring(0, [Math]::Min(80, $businessItems[0].prompt.Length)))..." -ForegroundColor Gray
    
} catch {
    Write-Host "❌ Business generation failed: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n3. MEDICAL ENGLISH CONTENT GENERATION" -ForegroundColor Yellow  
try {
    $startTime = Get-Date
    $medical = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/specialized/medical_english" -Method POST -Headers $headers
    $duration = (Get-Date - $startTime).TotalMilliseconds
    
    Write-Host "✅ Medical test generated in $([math]::Round($duration, 0))ms" -ForegroundColor Green
    Write-Host "   Items generated: $($medical.diagnosticSet.items.Count)" -ForegroundColor White
    
    # Sample medical content
    $medicalSample = $medical.diagnosticSet.items | Select-Object -First 1
    Write-Host "   🏥 Sample medical item:" -ForegroundColor Cyan
    Write-Host "      ID: $($medicalSample.id)" -ForegroundColor White
    Write-Host "      Type: $($medicalSample.taskType)" -ForegroundColor White
    Write-Host "      Level: $($medicalSample.tags.cefrBand)" -ForegroundColor White
    Write-Host "      Domain: $($medicalSample.tags.domain)" -ForegroundColor White
    Write-Host "      Prompt: $($medicalSample.prompt)" -ForegroundColor Gray
    
} catch {
    Write-Host "❌ Medical generation failed: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n4. DIALECT DIFFERENCES CONTENT GENERATION" -ForegroundColor Yellow
try {
    $startTime = Get-Date
    $dialect = Invoke-RestMethod -Uri "http://localhost:8000/v1/diagnostics/specialized/british_vs_american" -Method POST -Headers $headers
    $duration = (Get-Date - $startTime).TotalMilliseconds
    
    Write-Host "✅ Dialect test generated in $([math]::Round($duration, 0))ms" -ForegroundColor Green
    Write-Host "   Items generated: $($dialect.diagnosticSet.items.Count)" -ForegroundColor White
    
    # Sample dialect content
    $dialectSample = $dialect.diagnosticSet.items | Select-Object -First 1
    Write-Host "   🌍 Sample dialect item:" -ForegroundColor Cyan
    Write-Host "      ID: $($dialectSample.id)" -ForegroundColor White
    Write-Host "      Type: $($dialectSample.taskType)" -ForegroundColor White
    Write-Host "      Dialect: $($dialectSample.tags.dialect)" -ForegroundColor White
    Write-Host "      Prompt: $($dialectSample.prompt)" -ForegroundColor Gray
    
} catch {
    Write-Host "❌ Dialect generation failed: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n=== SPECIALIZED CONTENT GENERATION SUMMARY ===" -ForegroundColor Cyan
Write-Host "🎯 COMPREHENSIVE TESTING COMPLETED!" -ForegroundColor Green