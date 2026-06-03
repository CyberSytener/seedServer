[CmdletBinding()]
param(
    [switch]$SkipDocker,
    [switch]$SkipTunnel,
    [switch]$SkipSmoke,
    [switch]$RestartTunnel
)

$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel).Trim()
Set-Location $repoRoot

$dockerDesktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$cloudflaredConfig = "C:\Users\Exempel\.cloudflared\config.yml"
$logDir = Join-Path $repoRoot "logs\public"
$caddyfile = Join-Path $repoRoot "Caddyfile"
$composeArgs = @(
    "compose",
    "-p", "seed_public",
    "-f", "docker-compose.public.yml",
    "--env-file", ".env.public"
)
$publicServices = @("postgres", "redis", "api", "scheduler", "worker_fast", "worker_batch", "worker_low")

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host ("== {0} ==" -f $Message) -ForegroundColor Cyan
}

function Read-EnvValue {
    param(
        [string]$Path,
        [string]$Name
    )
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -eq 2 -and $parts[0].Trim() -eq $Name) {
            return $parts[1].Trim()
        }
    }
    return $null
}

function Get-PublicBindPort {
    $value = Read-EnvValue -Path ".env.public" -Name "PUBLIC_BIND_PORT"
    if ([string]::IsNullOrWhiteSpace($value)) {
        return "8000"
    }
    return $value
}

function Test-Http {
    param(
        [string]$Uri,
        [int]$TimeoutSec = 10
    )
    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Wait-Http {
    param(
        [string]$Uri,
        [int]$Attempts = 20,
        [int]$DelaySec = 3
    )
    for ($i = 1; $i -le $Attempts; $i++) {
        if (Test-Http -Uri $Uri) {
            return $true
        }
        Start-Sleep -Seconds $DelaySec
    }
    return $false
}

function Get-HealthJson {
    param(
        [string]$Uri,
        [int]$TimeoutSec = 10
    )
    try {
        return Invoke-RestMethod -Uri $Uri -TimeoutSec $TimeoutSec
    } catch {
        return $null
    }
}

function Wait-ApiHealth {
    param(
        [string]$Uri,
        [int]$Attempts = 20,
        [int]$DelaySec = 3,
        [switch]$RequireRedis
    )
    for ($i = 1; $i -le $Attempts; $i++) {
        $health = Get-HealthJson -Uri $Uri
        if ($health -and $health.ok -eq $true) {
            $redisOk = $true
            if ($RequireRedis) {
                $redisOk = ($health.PSObject.Properties.Name -contains "redis") -and ([bool]$health.redis)
            }
            if ($redisOk) {
                return $true
            }
        }
        Start-Sleep -Seconds $DelaySec
    }
    return $false
}

function Wait-AppHtml {
    param(
        [string]$Uri,
        [int]$Attempts = 10,
        [int]$DelaySec = 3
    )
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 10
            $contentType = [string]$response.Headers["Content-Type"]
            $content = [string]$response.Content
            if (
                $response.StatusCode -eq 200 -and
                $contentType.Contains("text/html") -and
                $content.Contains('<div id="root"') -and
                -not ($content -match '"name"\s*:\s*"seed-server"')
            ) {
                return $true
            }
        } catch {
        }
        Start-Sleep -Seconds $DelaySec
    }
    return $false
}

function Stop-StaleManualPublicApi {
    param([string]$Port)
    $listeners = @(Get-NetTCPConnection -LocalPort ([int]$Port) -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        if (-not $listener.OwningProcess) {
            continue
        }
        $process = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $listener.OwningProcess) -ErrorAction SilentlyContinue
        if (-not $process) {
            continue
        }
        $commandLine = [string]$process.CommandLine
        if ($process.Name -eq "python.exe" -and $commandLine -match "uvicorn\s+app\.main:app") {
            Write-Host ("Stopping stale manual API process on port {0}: PID {1}" -f $Port, $listener.OwningProcess) -ForegroundColor Yellow
            Stop-Process -Id $listener.OwningProcess -Force
            Start-Sleep -Seconds 2
        }
    }
}

function Test-DockerReady {
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & docker version *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

$publicBindPort = Get-PublicBindPort
$localApiHealthUri = "http://127.0.0.1:$publicBindPort/health"

if (-not $SkipDocker) {
    Write-Step "Docker"
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found in PATH."
    }

    if (-not (Test-DockerReady)) {
        if (-not (Test-Path -LiteralPath $dockerDesktop)) {
            throw "Docker daemon is unavailable and Docker Desktop was not found at $dockerDesktop."
        }
        Write-Host "Starting Docker Desktop..."
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        $ready = $false
        for ($i = 1; $i -le 30; $i++) {
            Start-Sleep -Seconds 3
            if (Test-DockerReady) {
                $ready = $true
                break
            }
        }
        if (-not $ready) {
            throw "Docker did not become ready in time."
        }
    }

    Stop-StaleManualPublicApi -Port $publicBindPort

    Write-Host "Starting seed_public compose services..."
    & docker @composeArgs up -d @publicServices
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed."
    }

    & docker @composeArgs ps
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose ps failed."
    }
}

Write-Step "Local API"
if (-not (Wait-ApiHealth -Uri $localApiHealthUri -Attempts 20 -DelaySec 3 -RequireRedis)) {
    if (-not $SkipDocker) {
        Stop-StaleManualPublicApi -Port $publicBindPort
        Write-Host "Recreating API container after unhealthy local API check..."
        & docker @composeArgs up -d --force-recreate api
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose api recreate failed."
        }
    }
}
if (-not (Wait-ApiHealth -Uri $localApiHealthUri -Attempts 20 -DelaySec 3 -RequireRedis)) {
    throw "Local public API did not become healthy with Redis on $localApiHealthUri."
}
Write-Host "Local API is healthy with Redis."

Write-Step "Caddy"
if (-not (Test-Http -Uri "http://127.0.0.1:8080/" -TimeoutSec 5)) {
    if (-not (Test-Path -LiteralPath $caddyfile)) {
        throw "Caddyfile not found at $caddyfile."
    }
    $caddy = Get-Command caddy -ErrorAction SilentlyContinue
    if (-not $caddy) {
        throw "Caddy is not running on 8080 and caddy command was not found."
    }
    Write-Host "Starting Caddy with $caddyfile..."
    Start-Process `
        -FilePath $caddy.Source `
        -ArgumentList @("run", "--config", $caddyfile, "--adapter", "caddyfile") `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden

    if (-not (Wait-Http -Uri "http://127.0.0.1:8080/" -Attempts 10 -DelaySec 2)) {
        throw "Caddy did not become healthy on http://127.0.0.1:8080/."
    }
}
Write-Host "Caddy is healthy."

if (-not $SkipTunnel) {
    Write-Step "Cloudflare Tunnel"
    if (-not (Test-Path -LiteralPath $cloudflaredConfig)) {
        throw "cloudflared config was not found at $cloudflaredConfig."
    }

    New-Item -ItemType Directory -Force -Path $logDir | Out-Null

    $existing = @(Get-Process cloudflared -ErrorAction SilentlyContinue)
    if ($existing.Count -gt 0 -and $RestartTunnel) {
        Write-Host "Stopping existing cloudflared processes..."
        $existing | Stop-Process -Force
        Start-Sleep -Seconds 2
        $existing = @()
    }

    if ($existing.Count -eq 0) {
        $cloudflaredCandidates = @(
            "C:\Program Files (x86)\cloudflared\cloudflared.exe",
            "C:\Program Files\cloudflared\cloudflared.exe",
            "$env:LOCALAPPDATA\Programs\cloudflared\cloudflared.exe"
        )
        $cloudflared = $cloudflaredCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $cloudflared) {
            $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
            if ($cmd) {
                $cloudflared = $cmd.Source
            }
        }
        if (-not $cloudflared) {
            throw "cloudflared executable was not found."
        }

        Write-Host "Starting cloudflared..."
        Start-Process `
            -FilePath $cloudflared `
            -ArgumentList @("tunnel", "--config", $cloudflaredConfig, "run") `
            -RedirectStandardOutput (Join-Path $logDir "cloudflared.out.log") `
            -RedirectStandardError (Join-Path $logDir "cloudflared.err.log") `
            -WindowStyle Hidden
        Start-Sleep -Seconds 5
    } else {
        Write-Host ("cloudflared already running: {0}" -f (($existing | Select-Object -ExpandProperty Id) -join ", "))
    }
}

Write-Step "Public checks"
$publicAppChecks = @(
    "https://neoeats.no/",
    "https://www.neoeats.no/"
)
foreach ($uri in $publicAppChecks) {
    if (-not (Wait-AppHtml -Uri $uri -Attempts 10 -DelaySec 3)) {
        throw ("Public check failed: {0}" -f $uri)
    }
    Write-Host ("OK {0}" -f $uri)
}
if (-not (Wait-ApiHealth -Uri "https://api.neoeats.no/health" -Attempts 10 -DelaySec 3 -RequireRedis)) {
    throw "Public API check failed: https://api.neoeats.no/health did not report redis=true."
}
Write-Host "OK https://api.neoeats.no/health"

if (-not $SkipSmoke) {
    Write-Step "Public smoke"
    & powershell -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\smoke_public_neoeats.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Public smoke failed."
    }
}

Write-Step "Done"
Write-Host "Public NeoEats runtime is healthy."
