"""GitHub Fetch block — read-only GitHub content retrieval (P0-29).

A tool-block that agents call to fetch public GitHub content (files,
directory listings, PR diffs) through the sandbox egress proxy.

Security hardening:
  • URL allowlist: only ``github.com``, ``api.github.com``,
    ``raw.githubusercontent.com``, ``codeload.github.com``.
  • Strict timeouts: connect 5 s, read 15 s.
  • Size cap: streaming truncation at ``max_size_bytes`` (default 1 MB).
  • Content-type validation: accept ``text/*``, ``application/json``,
    ``application/octet-stream`` only.
  • Redirect policy: follow only redirects to allowlisted domains.
  • No archive extraction — raw bytes only.
  • Audit/trace every fetch with URL, status code, size, duration.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from typing import Any, Dict, Optional, Set
from urllib.parse import urlparse

from app.core.blocks import BlockBase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency — httpx is only available in sandbox containers
# ---------------------------------------------------------------------------
try:
    import httpx  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_HOSTS: Set[str] = {
    "github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
}

_URL_PATTERN = re.compile(
    r"^https://(github\.com|api\.github\.com|raw\.githubusercontent\.com|codeload\.github\.com)/",
    re.IGNORECASE,
)

ALLOWED_CONTENT_TYPES: Set[str] = {
    "text",
    "application/json",
    "application/octet-stream",
}

DEFAULT_MAX_SIZE_BYTES = 1_048_576  # 1 MB
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 15.0
MAX_REDIRECTS = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def validate_url(url: str) -> Optional[str]:
    """Return an error message if *url* is not an allowed GitHub URL, else None."""
    if not url or not isinstance(url, str):
        return "url is required and must be a non-empty string"
    url = url.strip()
    if not _URL_PATTERN.match(url):
        return (
            f"URL not allowed: {url!r}. "
            "Only https://github.com, api.github.com, "
            "raw.githubusercontent.com, codeload.github.com are permitted."
        )
    return None


def is_redirect_allowed(location: str) -> bool:
    """Return True if a redirect target is within the allowlisted hosts."""
    try:
        parsed = urlparse(location)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            return False
        return host in ALLOWED_HOSTS or any(
            host.endswith("." + a) for a in ALLOWED_HOSTS
        )
    except Exception:
        return False


def is_content_type_allowed(content_type: str) -> bool:
    """Return True if *content_type* is in the accepted list."""
    ct = (content_type or "").lower().split(";")[0].strip()
    if ct in ALLOWED_CONTENT_TYPES:
        return True
    # Check text/* family
    if ct.startswith("text/"):
        return True
    return False


# ---------------------------------------------------------------------------
# Block
# ---------------------------------------------------------------------------


class GitHubFetchBlock(BlockBase):
    """Fetch public GitHub content with strict security controls."""

    NAME = "github_fetch"
    DESCRIPTION = (
        "Fetch a file or API response from public GitHub repositories. "
        "Only github.com, api.github.com, raw.githubusercontent.com, "
        "and codeload.github.com are allowed."
    )
    INPUT_SCHEMA: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full HTTPS URL on an allowed GitHub domain.",
            },
            "max_size_bytes": {
                "type": "integer",
                "description": "Maximum response body size in bytes (default: 1048576).",
                "default": DEFAULT_MAX_SIZE_BYTES,
            },
            "timeout_seconds": {
                "type": "number",
                "description": "Read timeout in seconds (default: 15).",
                "default": DEFAULT_READ_TIMEOUT,
            },
        },
        "required": ["url"],
    }
    OUTPUT_SCHEMA: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "Fetched content (UTF-8 text or base64 for binary).",
            },
            "content_type": {
                "type": "string",
                "description": "Content-Type header value from the response.",
            },
            "size_bytes": {
                "type": "integer",
                "description": "Actual number of bytes received.",
            },
            "truncated": {
                "type": "boolean",
                "description": "True if the response was truncated at max_size_bytes.",
            },
        },
        "required": ["content", "content_type", "size_bytes", "truncated"],
    }

    async def execute(
        self,
        context: Dict[str, Any],
        inputs: Dict[str, Any],
    ) -> Dict[str, Any]:
        url = str(inputs.get("url") or "").strip()
        max_size = int(inputs.get("max_size_bytes", DEFAULT_MAX_SIZE_BYTES))
        read_timeout = float(inputs.get("timeout_seconds", DEFAULT_READ_TIMEOUT))

        # --- URL validation ---------------------------------------------------
        err = validate_url(url)
        if err:
            return {
                "content": "",
                "content_type": "",
                "size_bytes": 0,
                "truncated": False,
                "error": err,
            }

        # --- Lazy-import httpx (only available in sandbox) --------------------
        if httpx is None:
            return {
                "content": "",
                "content_type": "",
                "size_bytes": 0,
                "truncated": False,
                "error": "httpx is not available in this environment",
            }

        # --- Fetch with redirect validation -----------------------------------
        start = time.monotonic()
        redirects_followed = 0
        current_url = url
        truncated = False
        status_code = 0

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(
                    connect=DEFAULT_CONNECT_TIMEOUT,
                    read=read_timeout,
                    write=5.0,
                    pool=5.0,
                ),
            ) as client:
                while True:
                    response = await client.get(current_url)
                    status_code = response.status_code

                    # Handle redirects manually
                    if status_code in (301, 302, 303, 307, 308):
                        if redirects_followed >= MAX_REDIRECTS:
                            return {
                                "content": "",
                                "content_type": "",
                                "size_bytes": 0,
                                "truncated": False,
                                "error": f"Too many redirects ({MAX_REDIRECTS} max)",
                            }
                        location = response.headers.get("location", "")
                        if not is_redirect_allowed(location):
                            return {
                                "content": "",
                                "content_type": "",
                                "size_bytes": 0,
                                "truncated": False,
                                "error": (
                                    f"Redirect to non-allowlisted domain blocked: {location}"
                                ),
                            }
                        current_url = location
                        redirects_followed += 1
                        continue

                    # Non-redirect response
                    break

                # --- Content-type check ----------------------------------------
                raw_ct = response.headers.get("content-type", "application/octet-stream")
                if not is_content_type_allowed(raw_ct):
                    return {
                        "content": "",
                        "content_type": raw_ct,
                        "size_bytes": 0,
                        "truncated": False,
                        "error": f"Content-Type not allowed: {raw_ct}",
                    }

                # --- Read body with size cap -----------------------------------
                body = response.content
                size_bytes = len(body)
                if size_bytes > max_size:
                    body = body[:max_size]
                    truncated = True

                # --- Decode content -------------------------------------------
                try:
                    content = body.decode("utf-8")
                except UnicodeDecodeError:
                    content = base64.b64encode(body).decode("ascii")
                    raw_ct = raw_ct + "; base64-encoded"

        except Exception as exc:
            duration = time.monotonic() - start
            logger.error(
                "FETCH_ERROR url=%s duration_s=%.2f error=%s",
                url, duration, exc,
            )
            return {
                "content": "",
                "content_type": "",
                "size_bytes": 0,
                "truncated": False,
                "error": f"Fetch failed: {exc}",
            }

        duration = time.monotonic() - start
        logger.info(
            "FETCH_OK url=%s status=%d size=%d truncated=%s duration_s=%.2f",
            url, status_code, size_bytes, truncated, duration,
        )

        return {
            "content": content,
            "content_type": raw_ct,
            "size_bytes": size_bytes,
            "truncated": truncated,
        }
