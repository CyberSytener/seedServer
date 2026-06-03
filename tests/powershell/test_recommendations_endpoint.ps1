# Test personalized recommendations endpoint

$baseUrl = "http://localhost:8000"

Write-Host "Testing GET /v1/learning/recommendations" -ForegroundColor Cyan

# Get recommendations (using legacy X-User-ID header)
$response = Invoke-RestMethod -Uri "$baseUrl/v1/learning/recommendations" `
    -Method GET `
    -Headers @{
        "X-User-ID" = "test_user_recommendations"
        "Content-Type" = "application/json"
    } `
    -ErrorAction Stop

Write-Host "`nRecommendations Response:" -ForegroundColor Green
$response | ConvertTo-Json -Depth 5

Write-Host "`n✅ Recommendations endpoint test completed successfully!" -ForegroundColor Green
