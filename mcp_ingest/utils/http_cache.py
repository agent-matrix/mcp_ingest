# mcp_ingest/utils/http_cache.py
"""
HTTP caching and rate limiting utilities for GitHub API calls.

This module provides:
- ETag-based caching to avoid re-downloading unchanged resources
- Exponential backoff for rate limiting (403/429 responses)
- Persistent cache storage to disk
- Automatic retry logic

Essential for daily automation that hits GitHub APIs repeatedly.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

__all__ = ["get_with_etag", "CachedResponse", "clear_cache", "get_cache_stats"]

logger = logging.getLogger(__name__)

# Cache location (configurable via env)
_CACHE_DIR = Path(os.getenv("MCP_INGEST_HTTP_CACHE", ".cache"))
_CACHE_FILE = _CACHE_DIR / "http_etags.json"


class CachedResponse:
    """Wrapper for cached HTTP response data."""

    def __init__(
        self,
        *,
        status_code: int,
        headers: dict[str, str],
        body: str | bytes,
        from_cache: bool = False,
    ):
        self.status_code = status_code
        self.headers = headers
        self.body = body
        self.from_cache = from_cache

    @property
    def text(self) -> str:
        """Get response body as text."""
        if isinstance(self.body, bytes):
            return self.body.decode("utf-8")
        return self.body

    def json(self) -> Any:
        """Parse response body as JSON."""
        return json.loads(self.text)


def _load_cache() -> dict[str, dict[str, Any]]:
    """Load ETag cache from disk."""
    if _CACHE_FILE.exists():
        try:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            logger.debug(f"Loaded HTTP cache with {len(data)} entries")
            return data
        except Exception as e:
            logger.warning(f"Failed to load cache from {_CACHE_FILE}: {e}")
    return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    """Save ETag cache to disk."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        logger.debug(f"Saved HTTP cache with {len(cache)} entries to {_CACHE_FILE}")
    except Exception as e:
        logger.warning(f"Failed to save cache to {_CACHE_FILE}: {e}")


def get_with_etag(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    max_retries: int = 6,
    follow_redirects: bool = True,
) -> CachedResponse:
    """Fetch a URL with ETag caching and exponential backoff for rate limits.

    Features:
    - Sends If-None-Match header if we have a cached ETag
    - Returns cached body on 304 Not Modified
    - Retries on 403/429 with exponential backoff (2^attempt seconds)
    - Persists ETags across runs for efficient daily automation

    Args:
        url: URL to fetch
        headers: Optional additional headers
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts for rate limiting
        follow_redirects: Whether to follow HTTP redirects

    Returns:
        CachedResponse with status, headers, and body

    Raises:
        httpx.HTTPError: If request fails after retries
    """
    cache = _load_cache()
    h = dict(headers or {})

    # Add If-None-Match header if we have a cached ETag
    cache_entry = cache.get(url, {})
    etag = cache_entry.get("etag")
    cached_body = cache_entry.get("body")

    if etag:
        h["If-None-Match"] = etag
        logger.debug(f"Using cached ETag for {url}: {etag}")

    with httpx.Client(timeout=timeout, follow_redirects=follow_redirects) as client:
        for attempt in range(max_retries):
            try:
                r = client.get(url, headers=h)

                # Handle 304 Not Modified (use cached body)
                if r.status_code == 304:
                    logger.info(f"Cache hit (304) for {url}")
                    if cached_body is None:
                        # We have an ETag but no body - re-fetch without ETag
                        logger.warning(f"Cache has ETag but no body for {url}, re-fetching")
                        del h["If-None-Match"]
                        continue

                    return CachedResponse(
                        status_code=304,
                        headers=dict(r.headers),
                        body=cached_body,
                        from_cache=True,
                    )

                # Handle rate limiting (403/429)
                if r.status_code in (403, 429):
                    wait_time = 2**attempt
                    reset_time = r.headers.get("X-RateLimit-Reset")

                    logger.warning(
                        f"Rate limited ({r.status_code}) on {url} "
                        f"(attempt {attempt + 1}/{max_retries}), waiting {wait_time}s"
                    )

                    if reset_time:
                        try:
                            reset_ts = int(reset_time)
                            now = int(time.time())
                            wait_until_reset = max(0, reset_ts - now)
                            if wait_until_reset < 300:  # Don't wait more than 5 min
                                logger.info(f"Rate limit resets in {wait_until_reset}s")
                                time.sleep(min(wait_time, wait_until_reset))
                                continue
                        except ValueError:
                            pass

                    time.sleep(wait_time)
                    continue

                # Raise for other HTTP errors
                r.raise_for_status()

                # Success - update cache if ETag present
                new_etag = r.headers.get("ETag")
                if new_etag:
                    cache[url] = {
                        "etag": new_etag,
                        "body": r.text,
                        "timestamp": time.time(),
                    }
                    _save_cache(cache)
                    logger.debug(f"Cached new ETag for {url}: {new_etag}")

                return CachedResponse(
                    status_code=r.status_code,
                    headers=dict(r.headers),
                    body=r.text,
                    from_cache=False,
                )

            except httpx.HTTPStatusError as e:
                # Already handled above, but catch in case we missed something
                if attempt == max_retries - 1:
                    logger.error(f"HTTP error after {max_retries} attempts: {e}")
                    raise
                wait_time = 2**attempt
                logger.warning(
                    f"HTTP error (attempt {attempt + 1}/{max_retries}): {e}, "
                    f"waiting {wait_time}s"
                )
                time.sleep(wait_time)

            except httpx.RequestError as e:
                # Network errors, timeouts, etc.
                if attempt == max_retries - 1:
                    logger.error(f"Request error after {max_retries} attempts: {e}")
                    raise
                wait_time = 2**attempt
                logger.warning(
                    f"Request error (attempt {attempt + 1}/{max_retries}): {e}, "
                    f"waiting {wait_time}s"
                )
                time.sleep(wait_time)

        # Should not reach here, but safety fallback
        raise httpx.HTTPError(f"Exhausted {max_retries} retries for {url}")


def clear_cache() -> int:
    """Clear the HTTP ETag cache.

    Returns:
        Number of cache entries cleared
    """
    if not _CACHE_FILE.exists():
        return 0

    try:
        cache = _load_cache()
        count = len(cache)
        _CACHE_FILE.unlink()
        logger.info(f"Cleared HTTP cache ({count} entries)")
        return count
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return 0


def get_cache_stats() -> dict[str, Any]:
    """Get statistics about the HTTP cache.

    Returns:
        Dictionary with cache statistics
    """
    if not _CACHE_FILE.exists():
        return {"exists": False, "entries": 0, "size_bytes": 0}

    try:
        cache = _load_cache()
        size = _CACHE_FILE.stat().st_size

        # Calculate age statistics
        now = time.time()
        ages = [
            now - entry.get("timestamp", now) for entry in cache.values() if "timestamp" in entry
        ]

        return {
            "exists": True,
            "entries": len(cache),
            "size_bytes": size,
            "oldest_entry_age_seconds": max(ages) if ages else 0,
            "newest_entry_age_seconds": min(ages) if ages else 0,
            "path": str(_CACHE_FILE),
        }
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return {"exists": True, "error": str(e)}
