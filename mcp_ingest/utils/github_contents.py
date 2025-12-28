# mcp_ingest/utils/github_contents.py
"""
GitHub Contents API utilities for enumerating directories in monorepos.

This module provides fallback enumeration for cases where a repo's README
doesn't explicitly list all MCP servers. It uses the GitHub API to discover
directories under common roots like src/, servers/, packages/.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

__all__ = ["list_dirs", "enumerate_monorepo_servers", "GitHubContentsError"]

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_COMMON_SERVER_ROOTS = ["src", "servers", "packages", "examples", "tools"]


class GitHubContentsError(Exception):
    """Raised when GitHub Contents API operations fail."""


def _gh_headers() -> dict[str, str]:
    """Build headers for GitHub API requests with optional token."""
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "mcp-ingest-github-contents/0.1",
    }
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
        logger.debug("Using GITHUB_TOKEN for GitHub API requests")
    else:
        logger.debug("No GITHUB_TOKEN found, using anonymous GitHub API access")
    return h


def list_dirs(
    owner: str, repo: str, path: str, ref: str, *, timeout: float = 30.0, retry_count: int = 3
) -> list[str]:
    """List directories at a given path in a GitHub repository.

    Args:
        owner: Repository owner
        repo: Repository name
        path: Path within the repository (e.g., "src")
        ref: Git reference (branch, tag, or SHA)
        timeout: Request timeout in seconds
        retry_count: Number of retries for rate limiting (403)

    Returns:
        List of directory paths (relative to repo root)

    Raises:
        GitHubContentsError: If the API request fails after retries
    """
    url = f"{_GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": ref}

    logger.debug(f"Listing directories in {owner}/{repo}@{ref}:{path}")

    with httpx.Client(timeout=timeout, headers=_gh_headers(), follow_redirects=True) as client:
        for attempt in range(retry_count):
            try:
                r = client.get(url, params=params)

                # Handle rate limiting with exponential backoff
                if r.status_code == 403:
                    wait_time = 2**attempt
                    logger.warning(
                        f"Rate limited by GitHub API (attempt {attempt + 1}/{retry_count}), "
                        f"waiting {wait_time}s"
                    )
                    time.sleep(wait_time)
                    continue

                # Handle not found (path doesn't exist)
                if r.status_code == 404:
                    logger.debug(f"Path not found: {owner}/{repo}@{ref}:{path}")
                    return []

                # Raise for other errors
                r.raise_for_status()

                # Parse response
                data = r.json()

                # Handle single file response (not a directory)
                if isinstance(data, dict):
                    logger.debug(f"Path is a file, not a directory: {path}")
                    return []

                # Extract directories
                dirs = [item["path"] for item in data if item.get("type") == "dir"]
                logger.info(f"Found {len(dirs)} directories in {owner}/{repo}@{ref}:{path}")
                return dirs

            except httpx.HTTPStatusError as e:
                if attempt == retry_count - 1:
                    raise GitHubContentsError(
                        f"Failed to list dirs in {owner}/{repo}@{ref}:{path}: {e}"
                    ) from e
                logger.warning(f"HTTP error (attempt {attempt + 1}/{retry_count}): {e}")
                time.sleep(2**attempt)

            except Exception as e:
                raise GitHubContentsError(
                    f"Unexpected error listing dirs in {owner}/{repo}@{ref}:{path}: {e}"
                ) from e

        # If we exhausted retries
        raise GitHubContentsError(f"Exhausted retries listing dirs in {owner}/{repo}@{ref}:{path}")


def enumerate_monorepo_servers(
    owner: str,
    repo: str,
    ref: str,
    *,
    roots: list[str] | None = None,
    max_depth: int = 2,
) -> list[str]:
    """Enumerate potential MCP server directories in a monorepo.

    Searches common roots (src/, servers/, packages/, etc.) and returns
    a list of subdirectories that might contain MCP servers.

    Args:
        owner: Repository owner
        repo: Repository name
        ref: Git reference (branch, tag, or SHA)
        roots: Custom list of root directories to search (defaults to common roots)
        max_depth: Maximum depth to search (1 = direct children only)

    Returns:
        List of directory paths relative to repo root

    Example:
        >>> enumerate_monorepo_servers("modelcontextprotocol", "servers", "main")
        ["src/brave-search", "src/everything", "src/fetch", ...]
    """
    search_roots = roots or _COMMON_SERVER_ROOTS
    all_dirs: list[str] = []

    logger.info(
        f"Enumerating monorepo servers in {owner}/{repo}@{ref} "
        f"(roots={search_roots}, max_depth={max_depth})"
    )

    for root in search_roots:
        try:
            # Get immediate children
            level_1_dirs = list_dirs(owner, repo, root, ref)

            if not level_1_dirs:
                logger.debug(f"No directories found under {root}")
                continue

            all_dirs.extend(level_1_dirs)

            # Optionally search one level deeper
            if max_depth >= 2:
                for subdir in level_1_dirs:
                    try:
                        level_2_dirs = list_dirs(owner, repo, subdir, ref)
                        all_dirs.extend(level_2_dirs)
                    except GitHubContentsError as e:
                        logger.debug(f"Could not list subdirs of {subdir}: {e}")
                        continue

        except GitHubContentsError as e:
            logger.warning(f"Could not enumerate root '{root}': {e}")
            continue

    logger.info(f"Enumerated {len(all_dirs)} potential server directories in {owner}/{repo}@{ref}")
    return all_dirs
