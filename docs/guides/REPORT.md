# Seed Server v5 — Fixes + provider integration (2025-12-23)

## Why this update
Your local Docker run was healthy (`/health`), but two things were blocking real work:

1) **Provider integration was hard to enable** because `docker-compose.yml` forced `stub` providers (so even with a key you wouldn't reach a real model).
2) **User creation could 500** due to SQLite unique constraints (duplicate emails) -> should be a clean 409.

Also, the repo archive contained local artifacts (`.venv`, `seed.db`, caches) and tests/docs were out of sync.

## What changed

### API
- Added `GET /v1/limits` (auth): returns `{ plan, usage }` so the Desktop client can sync state.
- `POST /v1/actions` now optionally supports **inline fast execution**:
  - Enabled when `SEED_FAST_TIMEOUT_SEC > 0` and policy decides `mode=fast`.
  - If it finishes within timeout, response returns `status=done` and `result_text`.
  - If it times out, job is queued as before.
- Added `POST /v1/jobs/{job_id}/cancel` (auth) and `JobStatus.cancelled`.
- `POST /v1/users` now returns **409** on conflicts (duplicate email / other integrity issues).
- `POST /v1/users` is **admin-locked** when `SEED_ADMIN_KEY` is set (requires header `X-Admin-Key`).

### Router / Providers
- OpenAI provider:
  - Primary: `POST /v1/responses`
  - Fallback: `POST /v1/chat/completions` (automatically used if `/v1/responses` is unavailable).
- `execute_action` now treats `provider: "auto"|"default"|""` as "use server defaults".
- `max_output_tokens` can be passed via options; otherwise plan default is applied server-side.

### Docker Compose
- Removed obsolete `version:`.
- Compose now uses `.env` (included) and no longer forces `stub` providers.
  - To enable a real provider: set `SEED_DEFAULT_PROVIDER_FAST=openai` and `OPENAI_API_KEY=...` in `.env`.

### Hygiene
- Removed local artifacts from the shipped archive: `.venv`, `seed.db`, `__pycache__`, `.pytest_cache`.
- Added `.dockerignore`.
- README updated to match the real endpoints and env var names.

### Tests
- Replaced stale tests with a small pytest integration test suite.
  - Tests auto-skip if Redis is not available.

## How to enable a real provider (OpenAI)
Edit `.env`:

```
SEED_DEFAULT_PROVIDER_FAST=openai
SEED_DEFAULT_PROVIDER_BATCH=openai
OPENAI_API_KEY=YOUR_KEY_HERE
```

Then restart:

```
docker compose down
docker compose up --build
```

## Smoke test (PowerShell)
Create a user:

```powershell
$base = "http://localhost:8000"
$email = "local_" + (Get-Random) + "@seed.dev"
$user = Invoke-RestMethod -Method Post -Uri "$base/v1/users" -ContentType "application/json" -Body (@{ user_id = "local_user_" + (Get-Random); email = $email; meta = @{} } | ConvertTo-Json -Depth 10)
$apiKey = $user.api_key
```

Create an action:

```powershell
$job = Invoke-RestMethod -Method Post -Uri "$base/v1/actions" -Headers @{ Authorization = "Bearer $apiKey" } -ContentType "application/json" -Body (@{ action = "fix"; text = "helo   world"; options = @{ provider = "auto" } } | ConvertTo-Json)
$job
```

Fetch job:

```powershell
Invoke-RestMethod -Method Get -Uri "$base/v1/jobs/$($job.job_id)" -Headers @{ Authorization = "Bearer $apiKey" }
```
