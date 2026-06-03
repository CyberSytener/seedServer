param(
    [Parameter(Mandatory = $false)]
    [string]$LanIp
)

$ErrorActionPreference = "Stop"

if (-not $LanIp) {
    $LanIp = (ipconfig | Select-String -Pattern 'IPv4[^:]*:\s*([0-9\.]+)' |
        ForEach-Object { $_.Matches[0].Groups[1].Value } |
        Where-Object { $_ -notlike '127.*' } |
        Select-Object -First 1)
}

if (-not $LanIp) {
    Write-Error "Could not resolve LAN IPv4. Pass explicitly: .\\scripts\\lan_smoke_test.ps1 -LanIp 192.168.1.45"
}

Write-Host "LAN_IP=$LanIp" -ForegroundColor Cyan

$docsResp = Invoke-WebRequest -Uri "http://${LanIp}:8000/docs" -UseBasicParsing -TimeoutSec 10
Write-Host "GET /docs => $($docsResp.StatusCode) $($docsResp.StatusDescription)" -ForegroundColor Green

$payload = @{
    message = "what can i cook"
    action = @{ name = "chat" }
    session_id = "lan_test_session"
} | ConvertTo-Json -Depth 6

$echoResp = Invoke-WebRequest -Uri "http://${LanIp}:8000/api/v1/test/action-echo" -Method Post -Headers @{
    "Content-Type" = "application/json"
    "X-User-ID" = "test_user"
} -Body $payload -UseBasicParsing -TimeoutSec 20

Write-Host "POST /api/v1/test/action-echo => $($echoResp.StatusCode) $($echoResp.StatusDescription)" -ForegroundColor Green

try {
    ($echoResp.Content | ConvertFrom-Json) | ConvertTo-Json -Depth 6
} catch {
    $echoResp.Content
}
