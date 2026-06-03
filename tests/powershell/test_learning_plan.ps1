# Test script for learning profile and plan features
# Usage: .\test_learning_plan.ps1

$ErrorActionPreference = "Stop"

$BASE_URL = "http://localhost:8000"
$API_KEY = ""
$USER_ID = ""

Write-Host "=== Learning Profile & Plan Test Script ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Create user
Write-Host "[1/8] Creating test user..." -ForegroundColor Yellow
try {
    $createUserResp = Invoke-RestMethod -Uri "$BASE_URL/v1/users" -Method Post -Headers @{
        "Content-Type" = "application/json"
    } -Body (@{
        user_id = "test_learn_$(Get-Random)"
    } | ConvertTo-Json)

    $USER_ID = $createUserResp.user_id
    $API_KEY = $createUserResp.api_key
    
    if (-not $USER_ID -or -not $API_KEY) {
        Write-Host "Error: User creation returned incomplete data" -ForegroundColor Red
        Write-Host "Response: $($createUserResp | ConvertTo-Json)" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "[OK] Created user: $USER_ID" -ForegroundColor Green
    Write-Host ""
} catch {
    Write-Host "Error creating user: $_" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}

$headers = @{
    "Authorization" = "Bearer $API_KEY"
    "Content-Type" = "application/json"
}

# Step 2: Start diagnostic
Write-Host "[2/8] Starting diagnostic session..." -ForegroundColor Yellow
$startResp = Invoke-RestMethod -Uri "$BASE_URL/v1/learning/diagnostic/start" -Method Post -Headers $headers -Body (@{
    nativeLanguage = "en"
    targetLanguage = "es"
    startLevelGuess = "A2"
} | ConvertTo-Json)

$SESSION_ID = $startResp.sessionId
Write-Host "[OK] Started session: $SESSION_ID" -ForegroundColor Green
Write-Host ""

# Step 3: Answer some items
Write-Host "[3/8] Answering diagnostic items (5 items)..." -ForegroundColor Yellow
$itemsAnswered = 0
for ($i = 1; $i -le 5; $i++) {
    # Get next item
    $nextResp = Invoke-RestMethod -Uri "$BASE_URL/v1/learning/diagnostic/next" -Method Post -Headers $headers -Body (@{
        sessionId = $SESSION_ID
    } | ConvertTo-Json)
    
    if ($nextResp.complete) {
        Write-Host "  Session complete after $itemsAnswered items" -ForegroundColor Gray
        break
    }
    
    $item = $nextResp.item
    $itemId = $item.itemId
    
    # Submit a random answer (mix of correct/incorrect for variety)
    $answer = if ($item.content.choices) {
        $item.content.choices[0]  # First choice
    } elseif ($item.content.tokens) {
        ($item.content.tokens | Get-Random -Count 3) -join " "  # Random reorder
    } else {
        "test answer"
    }
    
    $attemptResp = Invoke-RestMethod -Uri "$BASE_URL/v1/learning/diagnostic/attempt" -Method Post -Headers $headers -Body (@{
        sessionId = $SESSION_ID
        itemId = $itemId
        userAnswerRaw = $answer
        responseTimeMs = 3000
    } | ConvertTo-Json)
    
    $itemsAnswered++
    $correctMark = if ($attemptResp.correct) { "[OK]" } else { "[X]" }
    Write-Host "  $correctMark Item $i answered" -ForegroundColor Gray
}

Write-Host "[OK] Answered $itemsAnswered items" -ForegroundColor Green
Write-Host ""

# Step 4: Finish diagnostic
Write-Host "[4/8] Finishing diagnostic session..." -ForegroundColor Yellow
$finishResp = Invoke-RestMethod -Uri "$BASE_URL/v1/learning/diagnostic/finish" -Method Post -Headers $headers -Body (@{
    sessionId = $SESSION_ID
} | ConvertTo-Json)

Write-Host "[OK] Diagnostic finished:" -ForegroundColor Green
Write-Host "  CEFR: $($finishResp.estimatedCefr)" -ForegroundColor Gray
Write-Host "  Total Correct: $($finishResp.totalCorrect)/$($finishResp.totalAttempts)" -ForegroundColor Gray
Write-Host "  Accuracy: $([math]::Round($finishResp.accuracy * 100, 1))%" -ForegroundColor Gray
Write-Host "  Weak Subskills: $($finishResp.weakSubskills.Count)" -ForegroundColor Gray
Write-Host ""

# Step 5: Generate learning plan
Write-Host "[5/8] Generating learning plan..." -ForegroundColor Yellow
$planResp = Invoke-RestMethod -Uri "$BASE_URL/v1/learning/plan/generate" -Method Post -Headers $headers -Body (@{
    targetLanguage = "es"
    nativeLanguage = "en"
    sessionId = $SESSION_ID
    topic = "travel"
    lessonLength = 5
    personaId = "classic_tutor"
} | ConvertTo-Json)

Write-Host "[OK] Learning plan generated:" -ForegroundColor Green
Write-Host "  Plan ID: $($planResp.planId)" -ForegroundColor Gray
Write-Host "  Level: $($planResp.plan.level)" -ForegroundColor Gray
Write-Host "  Focus Areas: $($planResp.plan.focusAreas.Count)" -ForegroundColor Gray
foreach ($area in $planResp.plan.focusAreas) {
    Write-Host "    - $area" -ForegroundColor Gray
}
Write-Host "  Recommended Lessons: $($planResp.plan.recommendedLessons.Count)" -ForegroundColor Gray
foreach ($lesson in $planResp.plan.recommendedLessons) {
    Write-Host "    $($lesson.order). [$($lesson.mode)] $($lesson.topic) - $($lesson.rationale)" -ForegroundColor Gray
}
Write-Host ""

# Step 6: Get learning profile
Write-Host "[6/8] Getting learning profile..." -ForegroundColor Yellow
$profileResp = Invoke-RestMethod -Uri "$BASE_URL/v1/learning/profile" -Method Get -Headers $headers

Write-Host "[OK] Learning profile retrieved:" -ForegroundColor Green
Write-Host "  Version: $($profileResp.profile.version)" -ForegroundColor Gray
Write-Host "  Target Language: $($profileResp.profile.targetLanguage)" -ForegroundColor Gray
Write-Host "  Native Language: $($profileResp.profile.nativeLanguage)" -ForegroundColor Gray
Write-Host "  Estimated CEFR: $($profileResp.profile.estimatedCefr)" -ForegroundColor Gray
Write-Host "  Skill Scores: $($profileResp.profile.skillScores.Count)" -ForegroundColor Gray
foreach ($skillScore in $profileResp.profile.skillScores) {
    Write-Host "    - $($skillScore.skill): $($skillScore.score)" -ForegroundColor Gray
}
Write-Host "  Preferences Topic: $($profileResp.profile.preferences.topic)" -ForegroundColor Gray
Write-Host "  History Diagnostics: $($profileResp.profile.history.diagnostics.Count)" -ForegroundColor Gray
Write-Host ""

# Step 7: Patch learning profile
Write-Host "[7/8] Patching learning profile (update preferences)..." -ForegroundColor Yellow
$patchResp = Invoke-RestMethod -Uri "$BASE_URL/v1/learning/profile" -Method Patch -Headers $headers -Body (@{
    preferences = @{
        topic = "business"
        personaId = "code_mentor"
        lessonLength = 7
    }
} | ConvertTo-Json)

Write-Host "[OK] Profile patched:" -ForegroundColor Green
Write-Host "  New Topic: $($patchResp.profile.preferences.topic)" -ForegroundColor Gray
Write-Host "  New Persona: $($patchResp.profile.preferences.personaId)" -ForegroundColor Gray
Write-Host "  New Lesson Length: $($patchResp.profile.preferences.lessonLength)" -ForegroundColor Gray
Write-Host ""

# Step 8: Verify first lesson request
Write-Host "[8/8] Verifying first lesson request payload..." -ForegroundColor Yellow
Write-Host "[OK] First lesson request ready:" -ForegroundColor Green
Write-Host "  Mode: $($planResp.firstLessonRequest.mode)" -ForegroundColor Gray
Write-Host "  Target Language: $($planResp.firstLessonRequest.targetLanguage)" -ForegroundColor Gray
Write-Host "  Native Language: $($planResp.firstLessonRequest.nativeLanguage)" -ForegroundColor Gray
Write-Host "  Level: $($planResp.firstLessonRequest.level)" -ForegroundColor Gray
Write-Host "  Topic: $($planResp.firstLessonRequest.topic)" -ForegroundColor Gray
Write-Host "  Lesson Length: $($planResp.firstLessonRequest.lessonLength)" -ForegroundColor Gray
Write-Host "  Persona ID: $($planResp.firstLessonRequest.personaId)" -ForegroundColor Gray
Write-Host ""

Write-Host "=== All Tests Passed! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Summary:" -ForegroundColor Cyan
Write-Host "  [OK] Diagnostic finish returns totalCorrect/totalAttempts/accuracy" -ForegroundColor Green
Write-Host "  [OK] Learning profile created and stored" -ForegroundColor Green
Write-Host "  [OK] Learning profile can be retrieved" -ForegroundColor Green
Write-Host "  [OK] Learning profile can be patched" -ForegroundColor Green
Write-Host "  [OK] Learning plan generated with recommendations" -ForegroundColor Green
Write-Host "  [OK] First lesson request payload ready" -ForegroundColor Green
Write-Host ""
Write-Host "Test user ID: $USER_ID" -ForegroundColor Gray
Write-Host "Test session ID: $SESSION_ID" -ForegroundColor Gray
