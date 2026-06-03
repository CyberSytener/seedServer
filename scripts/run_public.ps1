param(
    [switch]$NoBuild,
    [switch]$NoTunnel,
    [string]$ComposeFile = "docker-compose.public.yml",
    [string]$EnvFile = ".env.public",
    [string]$ProjectName = "seed_public"
)

$ErrorActionPreference = "Stop"

function Read-EnvFile {
    param([string]$Path)

    $result = @{}
    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }

        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2) {
            continue
        }

        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        $result[$key] = $value
    }

    return $result
}

function Test-Truthy {
    param([string]$Value)
    if (-not $Value) { return $false }
    return @("1", "true", "yes", "on") -contains $Value.Trim().ToLowerInvariant()
}

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

if (-not (Test-Path $ComposeFile)) {
    throw "Compose file '$ComposeFile' not found."
}

if (-not (Test-Path $EnvFile)) {
    throw "Env file '$EnvFile' not found. Copy .env.public.example to .env.public and set real values first."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed or not in PATH."
}

$envMap = Read-EnvFile -Path $EnvFile

if (-not (Test-Truthy $envMap["PUBLIC_MODE"])) {
    throw "PUBLIC_MODE must be set to 1/true in '$EnvFile'."
}

if (Test-Truthy $envMap["SEED_TEST_AUTH_MODE"]) {
    throw "SEED_TEST_AUTH_MODE must be 0/false for public deployment."
}

$adminKey = $envMap["SEED_ADMIN_KEY"]
if (-not $adminKey -or $adminKey -match "^change_me") {
    throw "SEED_ADMIN_KEY must be set to a real random value in '$EnvFile'."
}

if ($envMap["SEED_ENABLE_LEGACY_X_USER_ID"] -and (Test-Truthy $envMap["SEED_ENABLE_LEGACY_X_USER_ID"])) {
    throw "SEED_ENABLE_LEGACY_X_USER_ID must be 0/false in public mode."
}

$composeArgs = @("compose", "-p", $ProjectName, "-f", $ComposeFile, "--env-file", $EnvFile, "up", "-d")
if (-not $NoBuild) {
    $composeArgs += "--build"
}

Write-Host "Starting public stack..." -ForegroundColor Cyan
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed."
}

$bindPort = $envMap["PUBLIC_BIND_PORT"]
if (-not $bindPort) {
    $bindPort = "8000"
}

Write-Host "Running local health checks..." -ForegroundColor Cyan
$healthScript = Join-Path $PSScriptRoot "health_check.ps1"
$healthOk = $false
for ($attempt = 1; $attempt -le 10; $attempt++) {
    try {
        & $healthScript -BaseUrl "http://127.0.0.1:$bindPort"
        $healthOk = $true
        break
    } catch {
        if ($attempt -ge 10) {
            throw
        }
        Write-Host "Health check attempt $attempt failed, retrying in 3 seconds..." -ForegroundColor Yellow
        Start-Sleep -Seconds 3
    }
}

if (-not $healthOk) {
    throw "Health checks failed."
}

if ($NoTunnel) {
    Write-Host "Stack is running. Tunnel startup skipped (--NoTunnel)." -ForegroundColor Yellow
    exit 0
}

$cloudflaredPath = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflaredPath) {
    Write-Warning "cloudflared not found. Install it with scripts/install_cloudflared.ps1."
    exit 0
}

$configPath = Join-Path $env:USERPROFILE ".cloudflared\config.yml"
if (-not (Test-Path $configPath)) {
    Write-Warning "Cloudflared config not found at '$configPath'. Use cloudflared/config.example.yml and PUBLIC_DEPLOYMENT_GUIDE.md."
    exit 0
}

Write-Host "Starting cloudflared in foreground (Ctrl+C to stop tunnel)..." -ForegroundColor Cyan
& cloudflared tunnel --config $configPath run
