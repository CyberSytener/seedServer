$ErrorActionPreference = "Stop"

Write-Host "Checking for cloudflared..." -ForegroundColor Cyan
if (Get-Command cloudflared -ErrorAction SilentlyContinue) {
    cloudflared --version
    Write-Host "cloudflared is already installed." -ForegroundColor Green
    exit 0
}

if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Installing cloudflared with winget..." -ForegroundColor Yellow
    winget install --id Cloudflare.cloudflared -e --accept-package-agreements --accept-source-agreements
} elseif (Get-Command choco -ErrorAction SilentlyContinue) {
    Write-Host "Installing cloudflared with chocolatey..." -ForegroundColor Yellow
    choco install cloudflared -y
} else {
    Write-Error "No supported package manager found. Install cloudflared manually from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
}

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Error "cloudflared installation completed but command is still unavailable. Open a new terminal and retry."
}

cloudflared --version
Write-Host "cloudflared installation completed." -ForegroundColor Green
Write-Host "Next step: run 'cloudflared tunnel login' and follow PUBLIC_DEPLOYMENT_GUIDE.md." -ForegroundColor Cyan
