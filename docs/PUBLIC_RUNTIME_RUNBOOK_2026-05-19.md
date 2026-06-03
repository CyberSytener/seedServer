# Public Runtime Runbook - 2026-05-19

This runbook restores and verifies the public NeoEats runtime on the current Windows host.

## Public Topology

Public DNS and tunnel:

- `https://neoeats.no` -> Cloudflare Tunnel -> `http://localhost:8080`
- `https://www.neoeats.no` -> Cloudflare Tunnel -> `http://localhost:8080`
- `https://api.neoeats.no` -> Cloudflare Tunnel -> `http://localhost:8001`

Local origin:

- Caddy serves `front-neoeats-snapshot/dist` on `localhost:8080`.
- Caddy proxies backend paths from `localhost:8080` to `127.0.0.1:8001`.
- Docker compose publishes API as `127.0.0.1:8001 -> container:8000`.

Important files:

- Caddy config: `C:\Users\Exempel\Desktop\seed.server.v5\seed_server\Caddyfile`
- Cloudflare config: `C:\Users\Exempel\.cloudflared\config.yml`
- Public compose: `C:\Users\Exempel\Desktop\seed.server.v5\seed_server\docker-compose.public.yml`
- Public env: `C:\Users\Exempel\Desktop\seed.server.v5\seed_server\.env.public`
- Frontend dist: `C:\Users\Exempel\Desktop\seed.server.v5\front-neoeats-snapshot\dist`

## Symptoms

Cloudflare `530` usually means Cloudflare cannot reach the tunnel/origin. On this host, likely causes are:

- Docker Desktop is not running.
- `seed_public-api-1` is not running or not healthy.
- Caddy is not running on `localhost:8080`.
- `cloudflared` is not running.

Other public-runtime failure modes seen on this host:

- `https://api.neoeats.no/health` returns `redis=false`: usually a stale manual `python -m uvicorn app.main:app --port 8001` process is serving traffic instead of the compose API, or Redis is not available to the active API runtime.
- `https://neoeats.no/` returns `{"name":"seed-server","version":"0.5"}`: Caddy/tunnel routing is sending the app hostname to the backend root instead of serving `front-neoeats-snapshot/dist`.

## Restore Procedure

Run in PowerShell.

### One-Command Wrapper

The current helper is:

```powershell
Set-Location C:\Users\Exempel\Desktop\seed.server.v5\seed_server
.\scripts\restore_public_runtime.ps1
```

The helper now verifies the useful public state, not just HTTP 200:

- local and public `/health` must report `redis=true`
- `neoeats.no` and `www.neoeats.no` must return frontend HTML with `<div id="root">`
- a stale manual `uvicorn app.main:app` listener on the public API port is stopped before compose API recreation

Useful non-invasive checks:

```powershell
.\scripts\restore_public_runtime.ps1 -SkipDocker -SkipTunnel -SkipSmoke
.\scripts\restore_public_runtime.ps1 -SkipDocker -SkipTunnel
```

Use `-RestartTunnel` only when intentionally replacing the current `cloudflared` process.

### Manual Recovery

1. Start Docker Desktop if the daemon is down:

```powershell
Start-Process -FilePath 'C:\Program Files\Docker\Docker\Docker Desktop.exe' -WindowStyle Hidden
docker version
```

2. Start public services:

```powershell
Set-Location C:\Users\Exempel\Desktop\seed.server.v5\seed_server
docker compose -p seed_public -f docker-compose.public.yml --env-file .env.public up -d postgres redis api scheduler worker_fast worker_batch worker_low
docker compose -p seed_public -f docker-compose.public.yml --env-file .env.public ps
```

3. Verify local API:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8001/health -TimeoutSec 10
```

Expected: `ok=true`, `redis=true`, `db=true`.

4. Verify Caddy:

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8080/ -UseBasicParsing -TimeoutSec 10
```

If Caddy is not running, start it with the active `Caddyfile` or reinstall/run it through the existing local package path.

5. Start Cloudflare Tunnel:

```powershell
$logDir = 'C:\Users\Exempel\Desktop\seed.server.v5\seed_server\logs\public'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Start-Process `
  -FilePath 'C:\Program Files (x86)\cloudflared\cloudflared.exe' `
  -ArgumentList @('tunnel','--config','C:\Users\Exempel\.cloudflared\config.yml','run') `
  -RedirectStandardOutput "$logDir\cloudflared.out.log" `
  -RedirectStandardError "$logDir\cloudflared.err.log" `
  -WindowStyle Hidden
```

6. Check tunnel process and logs:

```powershell
Get-Process cloudflared
Get-Content C:\Users\Exempel\Desktop\seed.server.v5\seed_server\logs\public\cloudflared.err.log -Tail 80
```

Expected log signs:

- `Starting tunnel`
- `Registered tunnel connection`

## Verification

Manual checks:

```powershell
Invoke-WebRequest -Uri https://neoeats.no/ -UseBasicParsing -TimeoutSec 15
Invoke-WebRequest -Uri https://www.neoeats.no/ -UseBasicParsing -TimeoutSec 15
Invoke-RestMethod -Uri https://api.neoeats.no/health -TimeoutSec 15
```

Expected app hosts: frontend HTML, not backend root JSON.
Expected API health: `ok=true`, `redis=true`, `db=true`.

Full public NeoEats smoke:

```powershell
Set-Location C:\Users\Exempel\Desktop\seed.server.v5\seed_server
.\scripts\smoke_public_neoeats.ps1
```

The script verifies:

- frontend HTML
- API health
- open registration
- receipt confirmation
- receipt history
- receipt RAG memory

## Rebuild After Backend Code Changes

```powershell
Set-Location C:\Users\Exempel\Desktop\seed.server.v5\seed_server
docker compose -p seed_public -f docker-compose.public.yml --env-file .env.public up -d --build api scheduler worker_fast worker_batch worker_low
```

## Rebuild Frontend Dist

```powershell
Set-Location C:\Users\Exempel\Desktop\seed.server.v5\front-neoeats-snapshot
npm run build
```

Caddy serves `dist` directly, so a frontend rebuild is enough if Caddy is already running.

## Operational Follow-Ups

1. Run `cloudflared` as a Windows service instead of a manually started process.
2. Add a scheduled external health monitor for:
   - `https://neoeats.no/`
   - `https://www.neoeats.no/`
   - `https://api.neoeats.no/health` with `redis=true`
3. Keep `scripts/restore_public_runtime.ps1` as the one-command wrapper for Docker/Caddy/cloudflared restore.
4. Keep the public smoke script in CI or a scheduled local monitor.
