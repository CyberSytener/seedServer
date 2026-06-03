"""Unit tests for the GitHub fetch block (P0-29).

Tests cover:
  • URL validation (allowlist, rejection of non-GitHub URLs)
  • Redirect policy (allowlisted vs non-allowlisted targets)
  • Content-type validation
  • Size truncation at max_size_bytes
  • Binary-to-base64 fallback
  • Block registration via dynamic loader
  • Tool permissions configuration
  • Negative tests: non-GitHub URL, oversized payload, bad redirect
"""

from __future__ import annotations

import base64
from typing import Any, Dict
from unittest import mock

import pytest

from app.dynamic_registry.github_fetch_block import (
    DEFAULT_MAX_SIZE_BYTES,
    GitHubFetchBlock,
    is_content_type_allowed,
    is_redirect_allowed,
    validate_url,
)


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


class TestValidateUrl:
    def test_valid_github_url(self):
        assert validate_url("https://github.com/user/repo") is None

    def test_valid_api_github(self):
        assert validate_url("https://api.github.com/repos/foo/bar") is None

    def test_valid_raw(self):
        assert validate_url("https://raw.githubusercontent.com/u/r/main/f.py") is None

    def test_valid_codeload(self):
        assert validate_url("https://codeload.github.com/u/r/tar.gz/main") is None

    def test_empty_url(self):
        err = validate_url("")
        assert err is not None
        assert "required" in err.lower()

    def test_none_url(self):
        err = validate_url(None)  # type: ignore[arg-type]
        assert err is not None

    def test_non_github_url(self):
        err = validate_url("https://evil.com/payload")
        assert err is not None
        assert "not allowed" in err.lower()

    def test_http_not_https(self):
        """Only HTTPS allowed."""
        err = validate_url("http://github.com/user/repo")
        assert err is not None

    def test_ftp_rejected(self):
        err = validate_url("ftp://github.com/file")
        assert err is not None

    def test_github_io_rejected(self):
        err = validate_url("https://github.io/page")
        assert err is not None

    def test_subdomain_trick_rejected(self):
        """evil.github.com.attacker.com should NOT match."""
        err = validate_url("https://evil.github.com.attacker.com/payload")
        assert err is not None

    def test_numeric_value(self):
        err = validate_url(12345)  # type: ignore[arg-type]
        assert err is not None


# ---------------------------------------------------------------------------
# Redirect validation
# ---------------------------------------------------------------------------


class TestIsRedirectAllowed:
    def test_github_redirect(self):
        assert is_redirect_allowed("https://github.com/u/r") is True

    def test_raw_redirect(self):
        assert is_redirect_allowed("https://raw.githubusercontent.com/u/r/f") is True

    def test_evil_redirect(self):
        assert is_redirect_allowed("https://evil.com/pwned") is False

    def test_http_redirect_blocked(self):
        """HTTP (non-HTTPS) redirects are blocked."""
        assert is_redirect_allowed("http://github.com/u/r") is False

    def test_empty_location(self):
        assert is_redirect_allowed("") is False

    def test_subdomain_allowed(self):
        assert is_redirect_allowed("https://objects.githubusercontent.com/path") is False
        assert is_redirect_allowed("https://sub.api.github.com/path") is True


# ---------------------------------------------------------------------------
# Content-type validation
# ---------------------------------------------------------------------------


class TestIsContentTypeAllowed:
    def test_text_plain(self):
        assert is_content_type_allowed("text/plain") is True

    def test_text_html(self):
        assert is_content_type_allowed("text/html; charset=utf-8") is True

    def test_application_json(self):
        assert is_content_type_allowed("application/json") is True

    def test_octet_stream(self):
        assert is_content_type_allowed("application/octet-stream") is True

    def test_image_rejected(self):
        assert is_content_type_allowed("image/png") is False

    def test_video_rejected(self):
        assert is_content_type_allowed("video/mp4") is False

    def test_application_zip_rejected(self):
        assert is_content_type_allowed("application/zip") is False

    def test_empty_string(self):
        assert is_content_type_allowed("") is False


# ---------------------------------------------------------------------------
# Block execute (with mocked httpx)
# ---------------------------------------------------------------------------


def _make_block() -> GitHubFetchBlock:
    return GitHubFetchBlock(engine=None, params={})


class TestBlockExecute:
    """Tests for GitHubFetchBlock.execute with mocked HTTP calls."""

    @pytest.mark.asyncio
    async def test_invalid_url_returns_error(self):
        block = _make_block()
        result = await block.execute({}, {"url": "https://evil.com/bad"})
        assert result["error"]
        assert result["size_bytes"] == 0

    @pytest.mark.asyncio
    async def test_empty_url_returns_error(self):
        block = _make_block()
        result = await block.execute({}, {"url": ""})
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        block = _make_block()
        body = b'{"hello": "world"}'

        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = body

        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("app.dynamic_registry.github_fetch_block.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = mock.MagicMock()
            result = await block.execute({}, {"url": "https://api.github.com/repos/foo/bar"})

        assert result["content"] == '{"hello": "world"}'
        assert result["content_type"] == "application/json"
        assert result["size_bytes"] == len(body)
        assert result["truncated"] is False
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_truncation_at_max_size(self):
        block = _make_block()
        body = b"A" * 2000

        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.content = body

        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("app.dynamic_registry.github_fetch_block.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = mock.MagicMock()
            result = await block.execute(
                {}, {"url": "https://raw.githubusercontent.com/u/r/main/f", "max_size_bytes": 500}
            )

        assert result["truncated"] is True
        assert len(result["content"]) == 500
        assert result["size_bytes"] == 2000

    @pytest.mark.asyncio
    async def test_binary_content_base64(self):
        block = _make_block()
        body = bytes(range(256))  # non-UTF8

        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/octet-stream"}
        mock_response.content = body

        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("app.dynamic_registry.github_fetch_block.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = mock.MagicMock()
            result = await block.execute(
                {}, {"url": "https://github.com/user/repo/raw/main/img.bin"}
            )

        # Content should be base64
        decoded = base64.b64decode(result["content"])
        assert decoded == body
        assert "base64" in result["content_type"]

    @pytest.mark.asyncio
    async def test_redirect_to_allowed_domain(self):
        block = _make_block()

        # First response: redirect
        redirect_resp = mock.MagicMock()
        redirect_resp.status_code = 302
        redirect_resp.headers = {"location": "https://raw.githubusercontent.com/u/r/main/f"}

        # Second response: actual content
        final_resp = mock.MagicMock()
        final_resp.status_code = 200
        final_resp.headers = {"content-type": "text/plain"}
        final_resp.content = b"file content"

        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(side_effect=[redirect_resp, final_resp])
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("app.dynamic_registry.github_fetch_block.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = mock.MagicMock()
            result = await block.execute(
                {}, {"url": "https://github.com/user/repo/blob/main/f.py"}
            )

        assert result["content"] == "file content"
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_redirect_to_evil_domain_blocked(self):
        """Negative test: redirect to non-allowlisted domain → rejected."""
        block = _make_block()

        redirect_resp = mock.MagicMock()
        redirect_resp.status_code = 302
        redirect_resp.headers = {"location": "https://evil.com/malware"}

        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=redirect_resp)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("app.dynamic_registry.github_fetch_block.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = mock.MagicMock()
            result = await block.execute(
                {}, {"url": "https://github.com/user/repo"}
            )

        assert "error" in result
        assert "non-allowlisted" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_too_many_redirects(self):
        block = _make_block()

        redirect_resp = mock.MagicMock()
        redirect_resp.status_code = 301
        redirect_resp.headers = {"location": "https://github.com/redirect/loop"}

        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=redirect_resp)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("app.dynamic_registry.github_fetch_block.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = mock.MagicMock()
            result = await block.execute(
                {}, {"url": "https://github.com/start"}
            )

        assert "error" in result
        assert "redirect" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_disallowed_content_type(self):
        block = _make_block()

        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "image/png"}
        mock_response.content = b"\x89PNG"

        mock_client = mock.AsyncMock()
        mock_client.get = mock.AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("app.dynamic_registry.github_fetch_block.httpx") as mock_httpx:
            mock_httpx.AsyncClient.return_value = mock_client
            mock_httpx.Timeout = mock.MagicMock()
            result = await block.execute(
                {}, {"url": "https://github.com/user/repo/raw/main/image.png"}
            )

        assert "error" in result
        assert "content-type" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_httpx_not_available(self):
        """If httpx is None, returns a graceful error."""
        block = _make_block()
        with mock.patch("app.dynamic_registry.github_fetch_block.httpx", None):
            result = await block.execute(
                {}, {"url": "https://api.github.com/repos/foo/bar"}
            )
        assert "error" in result
        assert "httpx" in result["error"].lower()


# ---------------------------------------------------------------------------
# Block metadata & registration
# ---------------------------------------------------------------------------


class TestBlockMetadata:
    def test_name(self):
        assert GitHubFetchBlock.NAME == "github_fetch"

    def test_description_non_empty(self):
        assert len(GitHubFetchBlock.DESCRIPTION) > 20

    def test_input_schema_has_url(self):
        props = GitHubFetchBlock.INPUT_SCHEMA["properties"]
        assert "url" in props
        assert "max_size_bytes" in props
        assert "timeout_seconds" in props

    def test_output_schema_has_required_fields(self):
        required = GitHubFetchBlock.OUTPUT_SCHEMA["required"]
        assert "content" in required
        assert "content_type" in required
        assert "size_bytes" in required
        assert "truncated" in required


class TestBlockRegistration:
    """Ensure the block is auto-discovered by the dynamic loader."""

    def test_block_in_default_registry(self):
        from app.core.blocks import build_default_registry
        registry = build_default_registry()
        meta = registry.get_metadata("github_fetch")
        assert meta is not None
        assert meta.name == "github_fetch"

    def test_block_listed(self):
        from app.core.blocks import build_default_registry
        registry = build_default_registry()
        names = {m.name for m in registry.list_metadata()}
        assert "github_fetch" in names


class TestToolPermissions:
    """Verify tool_permissions.yaml has the github_fetch entry."""

    def test_permission_config_loaded(self):
        import yaml
        from pathlib import Path

        yaml_path = Path(__file__).resolve().parents[2] / "app" / "core" / "agent" / "tool_permissions.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        gh = data["tools"]["github_fetch"]
        assert gh["require_scope"] == "agent:tools:execute"
        assert gh["sandbox_required"] is True
        assert gh["allowed_in_sandbox"] is True
        assert gh["requires_confirmation"] is False
        assert gh["max_calls_per_session"] == 20
