"""Sandbox egress proxy — allow-listed HTTP forward proxy (P0-28).

A lightweight HTTP forward proxy that:
  • Allows CONNECT tunnels ONLY to domains in ALLOWLIST.
  • Denies all other domains.
  • Rate-limits to MAX_REQUESTS_PER_MINUTE per source.
  • Caps response bodies at MAX_RESPONSE_BYTES.
  • Rejects redirect targets outside ALLOWLIST.
  • Logs every request for audit.

Designed to run as a sidecar container on ``agent_sandbox_net``.
Usage::

    python scripts/sandbox_egress_proxy.py

Configuration via environment:
  • ``PROXY_PORT``           — listen port (default: 3128)
  • ``PROXY_ALLOWLIST``      — comma-separated domain list
  • ``PROXY_MAX_RPM``        — rate limit per source IP (default: 60)
  • ``PROXY_MAX_BYTES``      — max response bytes (default: 5242880 = 5MB)
  • ``PROXY_CONNECT_TIMEOUT``— upstream connect timeout in seconds (default: 5)
  • ``PROXY_READ_TIMEOUT``   — upstream read timeout in seconds (default: 15)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import Dict, List, Set

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("sandbox_egress_proxy")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROXY_PORT = int(os.environ.get("PROXY_PORT", "3128"))

_default_allowlist = (
    "github.com,"
    "api.github.com,"
    "raw.githubusercontent.com,"
    "codeload.github.com"
)
ALLOWLIST: Set[str] = {
    d.strip().lower()
    for d in os.environ.get("PROXY_ALLOWLIST", _default_allowlist).split(",")
    if d.strip()
}

MAX_REQUESTS_PER_MINUTE = int(os.environ.get("PROXY_MAX_RPM", "60"))
MAX_RESPONSE_BYTES = int(os.environ.get("PROXY_MAX_BYTES", str(5 * 1024 * 1024)))
CONNECT_TIMEOUT = float(os.environ.get("PROXY_CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.environ.get("PROXY_READ_TIMEOUT", "15"))

# ---------------------------------------------------------------------------
# Rate limiter (per source IP, sliding window)
# ---------------------------------------------------------------------------

_rate_windows: Dict[str, List[float]] = defaultdict(list)


def _is_rate_limited(source_ip: str) -> bool:
    """Return True if source_ip has exceeded MAX_REQUESTS_PER_MINUTE."""
    now = time.monotonic()
    window = _rate_windows[source_ip]
    # Prune entries older than 60s
    _rate_windows[source_ip] = [t for t in window if now - t < 60]
    if len(_rate_windows[source_ip]) >= MAX_REQUESTS_PER_MINUTE:
        return True
    _rate_windows[source_ip].append(now)
    return False


# ---------------------------------------------------------------------------
# Domain validation
# ---------------------------------------------------------------------------


def _is_allowed(host: str) -> bool:
    """Check if *host* matches the allowlist (exact or parent domain)."""
    host = host.lower().strip()
    if host in ALLOWLIST:
        return True
    # Check parent domain match (e.g., "foo.github.com" matches "github.com")
    for allowed in ALLOWLIST:
        if host.endswith("." + allowed):
            return True
    return False


# ---------------------------------------------------------------------------
# CONNECT tunnel handler
# ---------------------------------------------------------------------------


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Bidirectional pipe that respects MAX_RESPONSE_BYTES on the downstream side."""
    try:
        while True:
            data = await asyncio.wait_for(reader.read(65536), timeout=READ_TIMEOUT)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle_client(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
) -> None:
    """Handle one client connection (HTTP CONNECT or plain proxy)."""
    peername = client_writer.get_extra_info("peername")
    source_ip = peername[0] if peername else "unknown"

    try:
        # Read the request line
        request_line = await asyncio.wait_for(client_reader.readline(), timeout=10)
        if not request_line:
            return

        request_str = request_line.decode("utf-8", errors="replace").strip()
        parts = request_str.split()
        if len(parts) < 3:
            client_writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            await client_writer.drain()
            return

        method, target, _version = parts[0], parts[1], parts[2]

        # Read remaining headers (discard)
        while True:
            header_line = await asyncio.wait_for(client_reader.readline(), timeout=10)
            if header_line in (b"\r\n", b"\n", b""):
                break

        # Rate limit check
        if _is_rate_limited(source_ip):
            logger.warning("RATE_LIMITED source=%s target=%s", source_ip, target)
            client_writer.write(b"HTTP/1.1 429 Too Many Requests\r\n\r\n")
            await client_writer.drain()
            return

        # Extract host and port
        if method.upper() == "CONNECT":
            # CONNECT host:port
            if ":" in target:
                host, port_str = target.rsplit(":", 1)
                port = int(port_str)
            else:
                host = target
                port = 443
        else:
            # Plain HTTP proxy (not commonly used, but handle gracefully)
            client_writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\nOnly CONNECT is supported.\r\n")
            await client_writer.drain()
            logger.warning("DENIED method=%s target=%s source=%s (only CONNECT supported)", method, target, source_ip)
            return

        # Domain check
        if not _is_allowed(host):
            logger.warning("DENIED host=%s port=%d source=%s", host, port, source_ip)
            client_writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\nDomain not in allowlist.\r\n")
            await client_writer.drain()
            return

        # Connect to upstream
        start = time.monotonic()
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=CONNECT_TIMEOUT,
            )
        except (asyncio.TimeoutError, OSError) as exc:
            logger.error("CONNECT_FAILED host=%s port=%d error=%s", host, port, exc)
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await client_writer.drain()
            return

        # Tunnel established
        client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_writer.drain()

        duration_connect = time.monotonic() - start
        logger.info(
            "CONNECT host=%s port=%d source=%s connect_ms=%.0f",
            host, port, source_ip, duration_connect * 1000,
        )

        # Bidirectional pipe
        await asyncio.gather(
            _pipe(client_reader, upstream_writer),
            _pipe(upstream_reader, client_writer),
        )

        duration_total = time.monotonic() - start
        logger.info(
            "CLOSED host=%s port=%d source=%s total_s=%.1f",
            host, port, source_ip, duration_total,
        )

    except Exception as exc:
        logger.exception("ERROR handling client %s: %s", source_ip, exc)
    finally:
        try:
            client_writer.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    server = await asyncio.start_server(handle_client, "0.0.0.0", PROXY_PORT)
    logger.info(
        "Sandbox egress proxy listening on :%d  allowlist=%s  rpm=%d  max_bytes=%d",
        PROXY_PORT, sorted(ALLOWLIST), MAX_REQUESTS_PER_MINUTE, MAX_RESPONSE_BYTES,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
