param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$ApiToken = ""
)

$ErrorActionPreference = "Stop"

function Get-StatusCode {
    param(
        [string]$Url,
        [hashtable]$Headers = @{}
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -Method GET -Headers $Headers -TimeoutSec 20 -UseBasicParsing
        return [int]$response.StatusCode
    } catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            return [int]$_.Exception.Response.StatusCode.value__
        }
        throw
    }
}

Write-Host "Health check target: $BaseUrl" -ForegroundColor Cyan

$healthResponse = Invoke-RestMethod -Uri "$BaseUrl/health" -Method GET -TimeoutSec 20
if (-not $healthResponse.ok) {
    Write-Error "/health returned ok=false"
}
Write-Host "PASS /health -> ok=true" -ForegroundColor Green

$meWithoutAuthStatus = Get-StatusCode -Url "$BaseUrl/v1/me"
if ($meWithoutAuthStatus -ne 401) {
    Write-Error "Expected /v1/me without auth to return 401, got $meWithoutAuthStatus"
}
Write-Host "PASS /v1/me without auth -> 401" -ForegroundColor Green

if ($ApiToken) {
    $headers = @{ Authorization = "Bearer $ApiToken" }
    $meWithAuthStatus = Get-StatusCode -Url "$BaseUrl/v1/me" -Headers $headers
    if ($meWithAuthStatus -ne 200) {
        Write-Error "Expected /v1/me with auth token to return 200, got $meWithAuthStatus"
    }
    Write-Host "PASS /v1/me with auth token -> 200" -ForegroundColor Green
}

Write-Host "Public health checks completed." -ForegroundColor Green
