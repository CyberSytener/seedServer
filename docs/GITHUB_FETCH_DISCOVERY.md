# P0-27 Discovery: GitHub Fetch — Sandbox Egress & Tool Contract

**Date:** 2026-02-27
**Branch:** `feature/phase0-followup`
**Status:** DONE

---

## Q1: Can `agent_sandbox_net` allow ONLY specific egress?

**Current state:** `docker-compose.yml` defines `agent_sandbox_net` with `internal: true`. The `agent_sandbox` service is connected to both `default` (for Redis) and `agent_sandbox_net`, with `read_only: true`, `cap_drop: ALL`, `no-new-privileges: true`, and a 100M tmpfs at `/work`.

**Problem:** Docker Compose `internal: true` is binary — blocks ALL external egress. Cannot allowlist `*.github.com:443` at the Compose level.

**Alternatives evaluated:**

| Approach | Pros | Cons | Verdict |
|---|---|---|---|
| **Forward proxy sidecar** (Squid/Tinyproxy) | Domain-based allowlist, declarative in Compose, `internal: true` stays intact, sandbox uses `HTTPS_PROXY` env | Extra container (~10MB), slight latency | **Recommended** |
| **iptables on Docker host** | No extra containers | GitHub IPs change, requires host access, not declarative | Not recommended |
| **K8s/Swarm network policies** | Native egress CIDR allowlists | Overkill for single-host Compose | Future option |

**Recommendation:** Add a **forward proxy sidecar** container on both `agent_sandbox_net` and `default` network. The proxy enforces domain allowlist (`github.com`, `api.github.com`, `raw.githubusercontent.com`, `codeload.github.com`). Sandbox worker configures `HTTPS_PROXY` pointing to the sidecar. `agent_sandbox_net` stays `internal: true`.

---

## Q2: HTTP client library for sandbox

**Already available:**
- **`httpx==0.27.0`** with HTTP/2 (`httpx[http2]`) — declared in `pyproject.toml`, already used by `NotificationBlock` in `app/core/blocks.py` for async HTTP.
- `urllib3==2.6.3` — transitive dependency.
- `requests==2.32.5` — transitive via `google-genai`.

**Recommendation:** Use **`httpx.AsyncClient`** — already a production dep with HTTP/2, async support, streaming, configurable timeouts, and native `HTTP_PROXY` / `HTTPS_PROXY` support that dovetails with the proxy sidecar approach.

---

## Q3: Size limits for fetched content

**No existing size limits** are enforced for HTTP response bodies anywhere in the codebase. The sandbox tmpfs (`100M`) provides a hard ceiling on disk writes.

**Recommended defaults:**

| Limit | Value | Rationale |
|---|---|---|
| **Response body max** | 512 KB raw bytes | GitHub API JSON rarely exceeds this; prevents accidental multi-MB downloads |
| **Streamed read timeout** | 15 seconds | Prevents slow-loris/hanging connections |
| **Connect timeout** | 5 seconds | Fast fail on DNS/network issues |
| **Post-truncation for LLM** | 50 KB (~12k tokens) | Keeps `tool_result` within context window budget |

All values should be configurable via `app/settings.py`, e.g., `SEED_FETCH_MAX_BYTES=524288`.

---

## Q4: Artifact store vs. direct pass-through

**Current pattern:** Tool results from sandbox pass **directly inline** via Redis RPC as `tool_output` and are fed into the LLM prompt as `[Tool Result]` text. The sandbox container has **no access to `ArtifactStore`** (read-only rootfs, no DB).

**Recommendation — hybrid approach:**

1. **Small responses (≤ 50 KB text):** Pass directly as `tool_output` → injected into LLM prompt. Matches existing pattern.
2. **Large responses (> 50 KB):** The **parent session** (API-side) stores full content via `ArtifactStore.store()`, truncates to ~50 KB summary for the LLM, and includes the artifact reference (`uri`, `sha256`, `bytes`) in the tool result.
3. **Sandbox worker does NOT store artifacts** — it returns raw bytes/text via Redis RPC. The artifact decision happens in `AgentSession._execute_tool()` where the parent has access to `self.artifact_store`.

---

## Summary: Recommended Architecture

```
┌─────────────────────────────────────────────────┐
│   agent_sandbox_net  (internal: true)           │
│                                                 │
│  ┌─────────────┐     ┌──────────────────────┐   │
│  │   sandbox    │───▶│  egress_proxy         │   │
│  │   worker     │    │  (tinyproxy/squid)    │   │
│  │  HTTPS_PROXY │    │  allowlist:           │   │
│  │  = proxy:3128│    │   *.github.com        │   │
│  └─────────────┘     │   *.githubusercontent │   │
│                      └──────────┬───────────┘   │
│                                 │                │
└─────────────────────────────────┼───────────────┘
                                  │ (default network)
                                  ▼
                          [ Internet ]
```

**Key decisions:**
- `httpx.AsyncClient` for HTTP, with proxy env var
- 512 KB response cap, 5s connect / 15s read timeouts
- Small results inline, large results stored as artifacts by parent session
- No archive extraction in fetch block — raw bytes only
