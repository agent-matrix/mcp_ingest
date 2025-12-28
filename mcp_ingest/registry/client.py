"""MCP Registry API client with pagination and retry logic."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlencode

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

__all__ = ["RegistryClient"]

log = logging.getLogger(__name__)


@dataclass
class RegistryClient:
    """Client for MCP Registry API with pagination and retry support."""

    base_url: str = "https://registry.modelcontextprotocol.io"
    token: str | None = None
    timeout_s: int = 30
    max_retries: int = 5

    def _headers(self) -> dict[str, str]:
        """Build request headers with optional auth token."""
        h = {"Accept": "application/json"}
        tok = self.token or os.environ.get("MCP_REGISTRY_TOKEN")
        if tok:
            h["Authorization"] = f"Bearer {tok}"
        return h

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute GET request with retry logic for transient failures."""
        if httpx is None:
            raise RuntimeError(
                "httpx is required for registry client. Install with: pip install httpx"
            )

        url = f"{self.base_url.rstrip('/')}{path}"
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        full = f"{url}?{qs}" if qs else url

        backoff = 1.0
        for attempt in range(self.max_retries):
            try:
                r = httpx.get(full, headers=self._headers(), timeout=self.timeout_s)

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

            except httpx.TimeoutException:
                if attempt < self.max_retries - 1:
                    log.warning("Request timeout, retrying in %.1fs", backoff)
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
