[CmdletBinding()]
param(
    [string]$BaseUrl = "https://neoeats.no",
    [string]$ApiBaseUrl = "https://api.neoeats.no",
    [int]$TimeoutSec = 20
)

$ErrorActionPreference = "Stop"

function Invoke-Json {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [hashtable]$Headers = @{},
        [object]$Body = $null
    )

    $params = @{
        Method = $Method
        Uri = $Uri
        Headers = $Headers
        TimeoutSec = $TimeoutSec
    }
    if ($null -ne $Body) {
        $params.ContentType = "application/json"
        $params.Body = ($Body | ConvertTo-Json -Depth 8)
    }
    Invoke-RestMethod @params
}

$web = Invoke-WebRequest -Uri "$BaseUrl/" -UseBasicParsing -TimeoutSec $TimeoutSec
if ($web.StatusCode -ne 200 -or -not $web.Content.TrimStart().StartsWith("<!DOCTYPE html>")) {
    throw "Frontend check failed for $BaseUrl/"
}

$health = Invoke-Json -Method GET -Uri "$ApiBaseUrl/health"
if (-not $health.ok -or -not $health.redis -or -not $health.db) {
    throw "API health check failed: $($health | ConvertTo-Json -Compress)"
}

$suffix = [Guid]::NewGuid().ToString("N").Substring(0, 10)
$register = Invoke-Json -Method POST -Uri "$BaseUrl/api/v1/auth/register" -Body @{
    username = "smoke_$suffix"
    email = "smoke_$suffix@users.neoeats.local"
    password = "SmokePass123!"
}
if (-not $register.accessToken) {
    throw "Registration did not return accessToken"
}

$headers = @{ Authorization = "Bearer $($register.accessToken)" }

$confirm = Invoke-Json -Method POST -Uri "$BaseUrl/api/v1/vision/receipt/confirm" -Headers $headers -Body @{
    merchant_name = "Neo Market Smoke"
    total_amount = 42.50
    currency = "NOK"
    scanned_at = (Get-Date).ToUniversalTime().ToString("o")
    items = @(
        @{
            name = "Salmon Fillet"
            canonical_name = "salmon"
            original_name = "SALMON FILLET"
            qty = 2
            unit = "pcs"
            price = 42.50
            category = "seafood"
            is_food = $true
            match_id = "smoke-salmon"
            action = "CREATE"
        }
    )
}
if ($confirm.items_saved -lt 1) {
    throw "Receipt confirm did not save items"
}

$history = Invoke-Json -Method GET -Uri "$BaseUrl/api/v1/vision/receipt/history" -Headers $headers
if (@($history).Count -lt 1) {
    throw "Receipt history did not return confirmed receipt"
}

$memory = Invoke-Json -Method GET -Uri "$BaseUrl/api/v1/neoeats/memory?query=salmon%20receipt&limit=5" -Headers $headers
$events = @($memory.rag_memory.retrieved_events)
if (-not ($events | Where-Object { $_.event_type -eq "receipt_item_confirmed" })) {
    throw "Receipt confirmation did not appear in RAG memory"
}

[pscustomobject]@{
    ok = $true
    frontend = "$BaseUrl/"
    apiHealth = "$ApiBaseUrl/health"
    user = $register.user.userId
    receiptId = $confirm.receipt_id
    itemsSaved = $confirm.items_saved
    memoryEvents = $events.Count
} | ConvertTo-Json -Depth 5
