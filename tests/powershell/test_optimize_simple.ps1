$headers = @{
    "Content-Type" = "application/json"
    "X-User-ID" = "test_optimize_user"
}

$body = @{
    mode = "vocabulary"
    targetLang = "Spanish"
    nativeLang = "English" 
    level = "A1"
    topic = "colors"
    lessonLength = 3
} | ConvertTo-Json

Write-Host "Testing optimized lesson generation..."
Write-Host "Body: $body"

$start = Get-Date
$response = Invoke-RestMethod -Uri "http://localhost:8000/v1/lessons/generate" -Method POST -Headers $headers -Body $body -ContentType "application/json"
$end = Get-Date
$duration = ($end - $start).TotalMilliseconds

Write-Host "Success! Duration: $duration ms" -ForegroundColor Green
Write-Host "Lesson ID: $($response.lesson.lessonId)"
Write-Host "Tasks count: $($response.lesson.tasks.Count)"

foreach ($task in $response.lesson.tasks) {
    Write-Host "- $($task.id): $($task.type) - $($task.prompt)"
}

$response | ConvertTo-Json -Depth 10 | Out-File -FilePath "test_optimize_lesson_response.json" -Encoding utf8
Write-Host "Response saved to test_optimize_lesson_response.json"