
from __future__ import annotations
from urllib.parse import urlparse, urlunparse

def strip_trailing_slash(url: str) -> str:
    return url[:-1] if url.endswith(/) else url

def ensure_sse(url: str) -> str:
    """Normalize to an SSE path.
    If the caller already provided a concrete SSE endpoint, keep it.
    If the URL ends with /messages or /messages/, replace with /sse.
    Otherwise, append /sse.
    """
    if not url:
        return url
    u = strip_trailing_slash(url)
    if u.endswith(/messages):
        return u.rsplit(/messages, 1)[0] + /sse
    if u.endswith(/sse):
        return u
    return u + /sse

__all__ = ["ensure_sse", "strip_trailing_slash"]

