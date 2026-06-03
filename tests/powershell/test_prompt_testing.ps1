# Test Prompt Testing System
# This script demonstrates the new A/B testing capabilities

Write-Host "🧪 Testing Prompt A/B Testing System" -ForegroundColor Blue
Write-Host "=" * 50

$baseUrl = "http://localhost:8000"

# Check if server is running
try {
    $statusResponse = Invoke-RestMethod -Uri "$baseUrl/api/status" -Method GET -TimeoutSec 5
    Write-Host "✅ Server is running" -ForegroundColor Green
} catch {
    Write-Host "❌ Server not accessible at $baseUrl" -ForegroundColor Red
    Write-Host "   Please start the server first: docker-compose up" -ForegroundColor Yellow
    exit 1
}

# Test auth token (using default test token)
$headers = @{
    "Authorization" = "Bearer test_user_token_123"
    "Content-Type" = "application/json"
}

Write-Host "`n🔧 Checking Prompt Testing Status" -ForegroundColor Blue
Write-Host "-" * 35

try {
    $testStatus = Invoke-RestMethod -Uri "$baseUrl/api/prompt-testing/status" -Method GET -Headers $headers
    
    Write-Host "Test mode active: $($testStatus.test_mode_active)" -ForegroundColor $(if ($testStatus.test_mode_active) { "Green" } else { "Yellow" })
    Write-Host "Current session: $($testStatus.current_session ?? 'None')"
    Write-Host "Available test prompts: $($testStatus.available_test_prompts -join ', ')"
    
    if (-not $testStatus.test_mode_active) {
        Write-Host "`n⚠️  Test mode not enabled!" -ForegroundColor Yellow
        Write-Host "   Set SEED_PROMPT_TEST_MODE=true in docker-compose.yml" -ForegroundColor Yellow
        Write-Host "   Then restart: docker-compose down && docker-compose up" -ForegroundColor Yellow
    }
} catch {
    Write-Host "❌ Failed to get test status: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response.StatusCode -eq 401) {
        Write-Host "   Authentication failed - check auth token" -ForegroundColor Yellow
    }
}

Write-Host "`n📊 Starting Test Session" -ForegroundColor Blue
Write-Host "-" * 25

$sessionRequest = @{
    session_name = "powershell_demo"
    description = "Demo of prompt testing via PowerShell"
} | ConvertTo-Json

try {
    $sessionResponse = Invoke-RestMethod -Uri "$baseUrl/api/prompt-testing/session/start" -Method POST -Headers $headers -Body $sessionRequest
    
    Write-Host "✅ Started session: $($sessionResponse.session_id)" -ForegroundColor Green
    Write-Host "   Status: $($sessionResponse.status)"
    Write-Host "   Message: $($sessionResponse.message)"
    
} catch {
    Write-Host "❌ Failed to start session: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response.StatusCode -eq 400) {
        Write-Host "   Test mode may not be enabled" -ForegroundColor Yellow
    }
}

Write-Host "`n📋 Listing Available Prompts" -ForegroundColor Blue
Write-Host "-" * 30

try {
    $promptList = Invoke-RestMethod -Uri "$baseUrl/api/prompt-testing/prompts" -Method GET -Headers $headers
    
    Write-Host "Baseline prompts: $($promptList.baseline_prompts -join ', ')"
    Write-Host "Test prompts: $($promptList.test_prompts -join ', ')"
    Write-Host "Prompt types: $($promptList.prompt_types -join ', ')"
    
} catch {
    Write-Host "❌ Failed to list prompts: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n🎯 Testing Lesson Generation" -ForegroundColor Blue
Write-Host "-" * 30

# Create lesson generation requests with different user IDs
$lessonRequests = @(
    @{
        user_id = "alice"
        request = @{
            mode = "mixed"
            target_lang = "Spanish"
            native_lang = "English"
            level = "beginner"
            lesson_length = 3
            topic = "basic_greetings"
        }
    },
    @{
        user_id = "bob" 
        request = @{
            mode = "mixed"
            target_lang = "French"
            native_lang = "English"
            level = "intermediate"
            lesson_length = 4
            topic = "restaurant_ordering"
        }
    }
)

foreach ($testCase in $lessonRequests) {
    Write-Host "`n  Testing with user: $($testCase.user_id)" -ForegroundColor Cyan
    
    $testHeaders = $headers.Clone()
    $testHeaders["X-User-ID"] = $testCase.user_id
    
    $requestBody = $testCase.request | ConvertTo-Json
    
    try {
        $startTime = Get-Date
        $lessonResponse = Invoke-RestMethod -Uri "$baseUrl/api/lesson/generate" -Method POST -Headers $testHeaders -Body $requestBody -TimeoutSec 30
        $endTime = Get-Date
        $duration = ($endTime - $startTime).TotalMilliseconds
        
        Write-Host "    ✅ Generated: $($lessonResponse.lesson.title)" -ForegroundColor Green
        Write-Host "    📝 Tasks: $($lessonResponse.lesson.tasks.Count) ($($lessonResponse.lesson.tasks.type -join ', '))"
        Write-Host "    ⏱️  Time: $([int]$duration)ms"
        
    } catch {
        Write-Host "    ❌ Failed: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.Exception.Response.StatusCode -eq 400) {
            $errorDetail = $_.Exception.Response | ConvertFrom-Json
            Write-Host "       Detail: $($errorDetail.detail)" -ForegroundColor Yellow
        }
    }
}

Write-Host "`n📈 Getting Session Summary" -ForegroundColor Blue
Write-Host "-" * 25

try {
    Start-Sleep 2  # Give system time to log results
    
    $summary = Invoke-RestMethod -Uri "$baseUrl/api/prompt-testing/session/summary" -Method GET -Headers $headers
    
    Write-Host "Session: $($summary.session ?? 'None')"
    Write-Host "Total tests: $($summary.total_tests)"
    Write-Host "Success rate: $([math]::Round($summary.success_rate * 100, 1))%"
    
    if ($summary.PSObject.Properties.Match('avg_execution_time_ms').Count -gt 0) {
        Write-Host "Average execution time: $([math]::Round($summary.avg_execution_time_ms, 0))ms"
    }
    
    if ($summary.PSObject.Properties.Match('total_tokens_used').Count -gt 0) {
        Write-Host "Total tokens used: $($summary.total_tokens_used)"
    }
    
    if ($summary.PSObject.Properties.Match('avg_input_tokens').Count -gt 0 -and $summary.avg_input_tokens -gt 0) {
        Write-Host "Average input tokens: $([math]::Round($summary.avg_input_tokens, 0))"
    }
    
    if ($summary.PSObject.Properties.Match('avg_output_tokens').Count -gt 0 -and $summary.avg_output_tokens -gt 0) {
        Write-Host "Average output tokens: $([math]::Round($summary.avg_output_tokens, 0))"
    }
    
    if ($summary.by_type) {
        Write-Host "`nResults by prompt type:"
        foreach ($typeKey in $summary.by_type.Keys) {
            $stats = $summary.by_type[$typeKey]
            Write-Host "  $typeKey):"
            Write-Host "    Count: $($stats.count)"
            Write-Host "    Success: $($stats.success_count)/$($stats.count)"
            Write-Host "    Avg time: $([math]::Round($stats.avg_time_ms, 0))ms"
            if ($stats.PSObject.Properties.Match('avg_tokens').Count -gt 0) {
                Write-Host "    Avg tokens: $([math]::Round($stats.avg_tokens, 0))"
            }
        }
    }
    
} catch {
    Write-Host "❌ Failed to get session summary: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n🔍 Testing Prompt Content Retrieval" -ForegroundColor Blue
Write-Host "-" * 35

$promptContentRequest = @{
    prompt_type = "lesson_generator"
    is_test_version = $false
} | ConvertTo-Json

try {
    $promptContent = Invoke-RestMethod -Uri "$baseUrl/api/prompt-testing/prompts/content" -Method POST -Headers $headers -Body $promptContentRequest
    
    Write-Host "✅ Retrieved baseline prompt: $($promptContent.prompt_type)"
    Write-Host "   Version: $($promptContent.version)"
    Write-Host "   File: $($promptContent.file_path)"
    Write-Host "   Length: $($promptContent.content.Length) characters"
    
    # Try test version if available
    $testPromptRequest = @{
        prompt_type = "lesson_generator"
        is_test_version = $true
    } | ConvertTo-Json
    
    try {
        $testPromptContent = Invoke-RestMethod -Uri "$baseUrl/api/prompt-testing/prompts/content" -Method POST -Headers $headers -Body $testPromptRequest
        Write-Host "✅ Retrieved test prompt: $($testPromptContent.prompt_type)"
        Write-Host "   Version: $($testPromptContent.version)"
        Write-Host "   Length: $($testPromptContent.content.Length) characters"
    } catch {
        Write-Host "ℹ️  No test version found for lesson_generator" -ForegroundColor Yellow
    }
    
} catch {
    Write-Host "❌ Failed to get prompt content: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host "`n🎉 Prompt Testing Demo Complete!" -ForegroundColor Green
Write-Host "=" * 35

Write-Host "`n📚 Next Steps:" -ForegroundColor Blue
Write-Host "  1. Create test prompts in prompts/test/ directory"
Write-Host "  2. Enable test mode with SEED_PROMPT_TEST_MODE=true"
Write-Host "  3. Generate lessons to see A/B testing in action"
Write-Host "  4. Monitor results via API endpoints"
Write-Host "  5. Compare performance between baseline and test prompts"

Write-Host "`n💡 Tip: Run with test mode enabled to see real A/B testing!" -ForegroundColor Yellow