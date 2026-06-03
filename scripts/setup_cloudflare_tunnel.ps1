<#
.SYNOPSIS
  Sets up the Cloudflare Tunnel for neoeats.no after `cloudflared tunnel login`.
.DESCRIPTION
  Reuses the tunnel name from .env.public (CLOUDFLARE_TUNNEL_NAME) or defaults to
  "neoeats-prod", writes ~/.cloudflared/config.yml, and routes DNS for the app and API.
#>

$ErrorActionPreference = "Stop"

function Read-EnvFile {
    param([string]$Path)

    $result = @{}
    if (-not (Test-Path $Path)) {
        return $result
    }

    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }

        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -eq 2) {
            $result[$parts[0].Trim()] = $parts[1].Trim()
        }
    }

    return $result
}

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvFile = Join-Path $ProjectRoot ".env.public"
$EnvMap = Read-EnvFile -Path $EnvFile
$TunnelName = $EnvMap["CLOUDFLARE_TUNNEL_NAME"]
if (-not $TunnelName) {
    $TunnelName = "neoeats-prod"
}

$ApiBindPort = $EnvMap["PUBLIC_BIND_PORT"]
if (-not $ApiBindPort) {
    $ApiBindPort = "8001"
}

$FrontendBindPort = $EnvMap["FRONTEND_PUBLIC_PORT"]
if (-not $FrontendBindPort) {
    $FrontendBindPort = "8080"
}

$CfDir = Join-Path $env:USERPROFILE ".cloudflared"
if (-not (Test-Path (Join-Path $CfDir "cert.pem"))) {
    throw "No Cloudflare certificate found. Run 'cloudflared tunnel login' first."
}

$existing = cloudflared tunnel list --output json 2>$null | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName }
if ($existing) {
    $TunnelId = $existing.id
    Write-Host "Tunnel '$TunnelName' already exists: $TunnelId" -ForegroundColor Green
} else {
    Write-Host "Creating tunnel '$TunnelName'..." -ForegroundColor Cyan
    cloudflared tunnel create $TunnelName
    $existing = cloudflared tunnel list --output json 2>$null | ConvertFrom-Json | Where-Object { $_.name -eq $TunnelName }
    $TunnelId = $existing.id
    Write-Host "Tunnel created: $TunnelId" -ForegroundColor Green
}

$configPath = Join-Path $CfDir "config.yml"
$credentialsPath = Join-Path $CfDir "$TunnelId.json"
$configContent = @"
tunnel: $TunnelId
credentials-file: $credentialsPath

ingress:
  - hostname: neoeats.no
    service: http://localhost:$FrontendBindPort
  - hostname: www.neoeats.no
    service: http://localhost:$FrontendBindPort
  - hostname: api.neoeats.no
    service: http://localhost:$ApiBindPort
  - service: http_status:404
"@

Set-Content -Path $configPath -Value $configContent -Encoding UTF8
Write-Host "Config written to $configPath" -ForegroundColor Green

foreach ($hostname in @("neoeats.no", "www.neoeats.no", "api.neoeats.no")) {
    Write-Host "Routing DNS: $hostname" -ForegroundColor Cyan
    cloudflared tunnel route dns $TunnelName $hostname 2>&1 | Out-Null
}

if (Test-Path $EnvFile) {
    $content = Get-Content $EnvFile -Raw
    $content = $content -replace "CLOUDFLARE_TUNNEL_ID=.*", "CLOUDFLARE_TUNNEL_ID=$TunnelId"
    $content = $content -replace "CLOUDFLARE_TUNNEL_NAME=.*", "CLOUDFLARE_TUNNEL_NAME=$TunnelName"
    Set-Content -Path $EnvFile -Value $content -NoNewline -Encoding UTF8
    Write-Host "Updated .env.public tunnel metadata" -ForegroundColor Green
}

Write-Host "Tunnel '$TunnelName' is ready. Start with: cloudflared tunnel --config $configPath run" -ForegroundColor Cyan
