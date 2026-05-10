"""MCP Registry API client with pagination and retry logic."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

__all__ = ["RegistryClient"]

log = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        log.warning("Invalid integer for %s=%r, using default %d", name, raw, default)
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class RegistryClient:
    """Client for MCP Registry API with pagination and retry support.

    All resilience knobs are env-overridable so operators can tune in CI
    without a code change:

    - MCP_REGISTRY_TIMEOUT_S   (default 60)  per-request timeout in seconds
    - MCP_REGISTRY_MAX_RETRIES (default 5)   retries on transient failures
    - MCP_REGISTRY_HTTP2       (default 0)   force HTTP/2 (off by default)
    - MCP_REGISTRY_TOKEN                     bearer token for Authorization
    """

    base_url: str = "https://registry.modelcontextprotocol.io"
    token: str | None = None
    timeout_s: int = field(default_factory=lambda: _env_int("MCP_REGISTRY_TIMEOUT_S", 60))
    max_retries: int = field(default_factory=lambda: _env_int("MCP_REGISTRY_MAX_RETRIES", 5))
    # Force HTTP/1.1 by default. HTTP/2 from GitHub Actions runners to
    # the registry has been observed to stall in connect/header phase for
    # the full read timeout, exhausting all retries (catalog repo Sync
    # run #28). Set MCP_REGISTRY_HTTP2=1 to opt back in.
    use_http2: bool = field(default_factory=lambda: _env_bool("MCP_REGISTRY_HTTP2", False))

    _client: Any = field(default=None, init=False, repr=False, compare=False)

    def _headers(self) -> dict[str, str]:
        """Build request headers with optional auth token."""
        h = {"Accept": "application/json"}
        tok = self.token or os.environ.get("MCP_REGISTRY_TOKEN")
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        return h

    def _get_client(self) -> Any:
        """Lazily build a single httpx.Client so the pagination loop
        benefits from connection pooling instead of paying TLS/TCP setup
        on every page."""
        if self._client is None:
            if httpx is None:
                raise RuntimeError(
                    "httpx is required for registry client. Install with: pip install httpx"
                )
            self._client = httpx.Client(
                http2=self.use_http2,
                timeout=self.timeout_s,
                headers=self._headers(),
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute GET request with retry logic for transient failures."""
        if httpx is None:
            raise RuntimeError(
                "httpx is required for registry client. Install with: pip install httpx"
            )

        url = f"{self.base_url.rstrip('/')}{path}"
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        full = f"{url}?{qs}" if qs else url

        client = self._get_client()
        backoff = 1.0
        for attempt in range(self.max_retries):
            try:
                r = client.get(full)

                # Retry on rate limiting or server errors
                if r.status_code in (429, 502, 503, 504):
                    if attempt < self.max_retries - 1:
                        log.warning(
                            "Registry returned %d, retrying in %.1fs (attempt %d/%d)",
                            r.status_code,
                            backoff,
                            attempt + 1,
                            self.max_retries,
                        )
                        time.sleep(backoff)
                        backoff = min(backoff * 2, 30)
                        continue

                r.raise_for_status()
                return r.json()

            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.RemoteProtocolError,
            ) as exc:
                if attempt < self.max_retries - 1:
                    log.warning(
                        "Registry request failed (%s), retrying in %.1fs (attempt %d/%d)",
                        exc.__class__.__name__,
                        backoff,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                raise

        raise RuntimeError(f"Registry GET failed after {self.max_retries} retries: {full}")

    def iter_servers_latest(
        self,
        updated_since: str | None = None,
        limit: int = 200,
        top: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Iterate over servers from GET /v0.1/servers?version=latest.

        Parameters
        ----------
        updated_since : str | None
            ISO timestamp for incremental sync
        limit : int
            Page size for pagination
        top : int | None
            Maximum number of servers to fetch (for testing)

        Yields
        ------
        dict
            ServerResponse entries from the registry
        """
        cursor = None
        count = 0

        try:
            while True:
                log.info(
                    "Fetching servers from registry (cursor=%s, count=%d/%s)",
                    cursor or "initial",
                    count,
                    top or "unlimited",
                )

                # Try without version parameter first (API may not support it)
                params = {
                    "cursor": cursor,
                    "limit": limit,
                }
                if updated_since:
                    params["updated_since"] = updated_since

                data = self._get("/v0.1/servers", params)

                items = data.get("servers") or data.get("items") or []
                meta = data.get("metadata") or {}

                for it in items:
                    yield it
                    count += 1
                    if top is not None and count >= top:
                        log.info("Reached top limit of %d servers", top)
                        return

                cursor = meta.get("nextCursor") or meta.get("next_cursor")
                if not cursor:
                    log.info("No more pages, total fetched: %d servers", count)
                    return
        finally:
            self.close()
