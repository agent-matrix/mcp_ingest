# mcp_ingest/utils/slug.py
"""
Stable, deterministic slugification utilities for catalog paths.

This module ensures that catalog folder names:
- Are lowercase and ASCII-only
- Use hyphens as separators
- Are safe for filesystems and URLs
- Never collide (deterministic suffix for long names)
- Remain stable across harvests
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

__all__ = ["stable_slug", "slug_from_repo_and_path"]


def stable_slug(s: str, max_len: int = 80) -> str:
    """Create a stable, filesystem-safe slug from any string.

    Features:
    - Lowercase conversion
    - Unicode normalization (é → e)
    - Only allows alphanumeric and hyphens
    - Collapses multiple hyphens
    - Truncates with deterministic hash suffix for long names
    - Never returns empty string (defaults to "server")

    Args:
        s: Input string to slugify
        max_len: Maximum length (default 80 chars)

    Returns:
        A stable, filesystem-safe slug

    Examples:
        >>> stable_slug("My-Server_123")
        'my-server-123'
        >>> stable_slug("Café & Restaurant")
        'cafe-restaurant'
        >>> stable_slug("a" * 100)
        'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-12345678'
    """
    # Normalize unicode to ASCII (é → e, ñ → n, etc.)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")

    # Convert to lowercase
    s = s.lower()

    # Replace non-alphanumeric with hyphens
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")

    # Collapse multiple hyphens
    s = re.sub(r"-{2,}", "-", s)

    # Handle empty result
    if not s:
        return "server"

    # Truncate with deterministic hash if too long
    if len(s) > max_len:
        # Generate a short hash of the full string
        h = hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]
        # Keep the first part and append hash
        s = s[: max_len - 9].rstrip("-") + "-" + h

    return s


def slug_from_repo_and_path(
    owner: str, repo: str, subpath: str | None = None, *, max_len: int = 80
) -> str:
    """Create a stable slug from GitHub repo coordinates.

    Args:
        owner: Repository owner
        repo: Repository name
        subpath: Optional subpath within repo (e.g., "src/server-name")
        max_len: Maximum slug length

    Returns:
        A stable slug suitable for catalog folder names

    Examples:
        >>> slug_from_repo_and_path("modelcontextprotocol", "servers")
        'modelcontextprotocol-servers'
        >>> slug_from_repo_and_path("owner", "repo", "src/my-server")
        'owner-repo-src-my-server'
    """
    parts = [owner, repo]
    if subpath:
        # Normalize subpath (remove leading/trailing slashes)
        normalized_subpath = subpath.strip("/")
        if normalized_subpath:
            parts.append(normalized_subpath)

    # Join with hyphens and slugify
    combined = "-".join(parts)
    return stable_slug(combined, max_len=max_len)


def dedupe_slugs(slugs: list[str]) -> dict[str, str]:
    """Ensure slug uniqueness by appending numeric suffixes.

    Args:
        slugs: List of slugs that may contain duplicates

    Returns:
        Dictionary mapping original slug to unique slug

    Example:
        >>> dedupe_slugs(["server", "server", "other"])
        {'server': 'server', 'server': 'server-2', 'other': 'other'}
    """
    seen: dict[str, int] = {}
    result: dict[str, str] = {}

    for original in slugs:
        if original not in seen:
            seen[original] = 1
            result[original] = original
        else:
            seen[original] += 1
            count = seen[original]
            unique = f"{original}-{count}"
            result[original] = unique

    return result
