# mcp_ingest/utils/extractor.py
"""
Utilities for discovering MCP server repositories referenced by a GitHub
repository's README.

Phase 1 (webstrapping):
- Given a GitHub repository URL, locate its README (best-effort across common
  branches/file names), fetch it, and extract all outbound URLs.
- From those URLs, identify candidate GitHub repositories and return
  normalized, de-duplicated links. (This is the list you can print as the
  "servers found in the README" before deeper analysis.)

Later phases (to be implemented next):
- For each candidate repository (or subdirectory), check for MCP server
  signals (manifest.json, known frameworks, etc.) and, when found, run the
  standard describe/emit flow to generate manifests.

This module intentionally sticks to the standard library + `httpx` (already a
runtime dependency of mcp-ingest) for portability.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

__all__ = [
    "RepoTarget",
    "fetch_readme_markdown",
    "extract_urls_from_markdown",
    "extract_github_repo_links_from_readme",
    "format_targets_as_lines",
    "configure_logging",
    "main",
]

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_RAW_BASE = "https://raw.githubusercontent.com"


@dataclass(frozen=True)
class RepoTarget:
    """Normalized representation of a GitHub target.

    A README might link directly to a repo, or to a subfolder under a specific
    ref (via `/tree/<ref>/<path>`). This captures both forms so later stages can
    clone the right ref and focus on a subpath if needed.
    """

    owner: str
    repo: str
    ref: str | None = None  # branch/tag/sha if present in `/tree/<ref>`
    subpath: str | None = None  # e.g., "javascript/mcp-server"

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"

    @property
    def pretty(self) -> str:
        if self.ref and self.subpath:
            return f"https://github.com/{self.owner}/{self.repo}/tree/{self.ref}/{self.subpath}"
        if self.ref:
            return f"https://github.com/{self.owner}/{self.repo}/tree/{self.ref}"
        return self.repo_url


class GitHubClient:
    """Very small GitHub HTTP client with optional token support.

    Uses `GITHUB_TOKEN` from the environment if present to raise rate limits
    and avoid anonymous throttling.
    """

    def __init__(self, client: httpx.Client | None = None):
        headers = {
            "User-Agent": "mcp-ingest-extractor/0.1",
            "Accept": "application/vnd.github+json",
        }
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = client or httpx.Client(headers=headers, timeout=20.0, follow_redirects=True)

    def get_json(self, url: str, ok_codes: Sequence[int] = (200,)) -> dict | None:
        try:
            resp = self.client.get(url)
            if resp.status_code not in ok_codes:
                logger.debug("GET %s -> %s", url, resp.status_code)
                return None
            return resp.json()
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("GET %s failed: %s", url, e)
            return None

    def get_text(self, url: str, ok_codes: Sequence[int] = (200,)) -> str | None:
        try:
            resp = self.client.get(url)
            if resp.status_code not in ok_codes:
                logger.debug("GET %s -> %s", url, resp.status_code)
                return None
            return resp.text
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("GET %s failed: %s", url, e)
            return None

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:  # pragma: no cover - defensive
            pass


# --- URL extraction -------------------------------------------------------
# Capture:
#  - Markdown links: [text](https://...)
#  - Images: ![alt](https://...)
#  - Autolinks: <https://...>
#  - Bare URLs: https://...
_MD_LINK_URL = re.compile(
    r"\((https?://[^)\s]+)\)"  # (https://...)
    r"|<(?P<angle>https?://[^>\s]+)>"  # <https://...>
    r"|(?P<bare>https?://[^\s)\]>}\"']+)"  # bare URL (avoid trailing punct/quotes)
)

# Clean trailing punctuation that often ends up attached to bare URLs in prose.
_TRAILING_PUNCT = ",.;:!?)]}\"'"


def _dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def extract_urls_from_markdown(md: str) -> list[str]:
    """Extract all HTTP/HTTPS URLs from a markdown string.

    Returns a de-duplicated list, *not* sorted, preserving first-seen order.
    """
    urls: list[str] = []
    for m in _MD_LINK_URL.finditer(md):
        url = m.group(1) or m.group("angle") or m.group("bare")
        if not url:
            continue
        # Trim common trailing punctuation from bare links
        while url and url[-1] in _TRAILING_PUNCT:
            url = url[:-1]
        urls.append(url)
    return _dedupe_preserve_order(urls)


# --- README discovery -----------------------------------------------------


def _parse_github_repo_url(repo_url: str) -> tuple[str, str]:
    """Return (owner, repo) from a GitHub repository URL.

    Supports:
      - https://github.com/owner/repo
      - https://github.com/owner/repo/
      - git@github.com:owner/repo.git (converted to https-like for parsing)
    """
    if repo_url.startswith("git@github.com:"):
        repo_url = repo_url.replace("git@github.com:", "https://github.com/")
    parsed = urlparse(repo_url)
    if parsed.netloc != "github.com":
        raise ValueError("Only github.com URLs are supported in this helper")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Expected a GitHub repo URL like https://github.com/owner/repo")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


def _default_branch(client: GitHubClient, owner: str, repo: str) -> str | None:
    data = client.get_json(f"{_GITHUB_API}/repos/{owner}/{repo}")
    if not data:
        return None
    return data.get("default_branch")


def _try_fetch_readme(client: GitHubClient, owner: str, repo: str, branch: str) -> str | None:
    candidates = [
        "README.md",
        "Readme.md",
        "readme.md",
        "README.MD",
        "README.rst",
        "README.txt",
        "README",
        "docs/README.md",
        "docs/readme.md",
    ]
    for path in candidates:
        raw_url = f"{_RAW_BASE}/{owner}/{repo}/{branch}/{path}"
        txt = client.get_text(raw_url)
        if txt:
            logger.debug("Fetched %s", raw_url)
            return txt
    return None


def fetch_readme_markdown(repo_url: str) -> str | None:
    """Fetch README markdown for a given GitHub repository URL.

    Tries the repository's default branch (via GitHub API), then falls back to
    common branches (main, master).
    """
    owner, repo = _parse_github_repo_url(repo_url)
    client = GitHubClient()
    try:
        branches: list[str] = []
        default = _default_branch(client, owner, repo)
        if default:
            branches.append(default)
        # common fallbacks
        for b in ("main", "master"):
            if b not in branches:
                branches.append(b)

        for branch in branches:
            md = _try_fetch_readme(client, owner, repo, branch)
            if md:
                return md
        logger.info("Could not find a README in %s/%s on %s", owner, repo, branches)
        return None
    finally:
        client.close()


# --- Candidate repo extraction -------------------------------------------


def _normalize_github_link(url: str) -> RepoTarget | None:
    """Return a RepoTarget if *url* looks like a GitHub repo or tree link.

    Handles forms:
      - https://github.com/owner/repo
      - https://github.com/owner/repo/
      - https://github.com/owner/repo/tree/<ref>
      - https://github.com/owner/repo/tree/<ref>/<path/to/subdir>
    """
    parsed = urlparse(url)
    if parsed.netloc != "github.com":
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if len(parts) >= 3 and parts[2] == "tree" and len(parts) >= 4:
        ref = parts[3]
        subpath = "/".join(parts[4:]) if len(parts) >= 5 else None
        return RepoTarget(owner, repo, ref=ref, subpath=subpath or None)
    return RepoTarget(owner, repo)


def extract_github_repo_links_from_readme(repo_url: str) -> list[RepoTarget]:
    """High-level helper: from a repo, read its README and extract GitHub repo links.

    Returns a de-duplicated list of :class:`RepoTarget` instances representing
    likely MCP server repositories mentioned in the README.
    """
    md = fetch_readme_markdown(repo_url)
    if not md:
        return []
    urls = extract_urls_from_markdown(md)
    targets: list[RepoTarget] = []
    for u in urls:
        t = _normalize_github_link(u)
        if t:
            targets.append(t)
    # de-dupe by (owner, repo, ref, subpath)
    seen = set()
    out: list[RepoTarget] = []
    for t in targets:
        key = (t.owner, t.repo, t.ref, t.subpath)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


# --- Pretty printing / CLI -----------------------------------------------


def format_targets_as_lines(targets: Sequence[RepoTarget], *, sort: bool = True) -> list[str]:
    lines = [t.pretty for t in targets]
    if sort:
        lines = sorted(lines)
    return lines


def configure_logging(verbosity: int, log_file: str | None = None) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers)
    logger.debug("Logging configured (level=%s, file=%s)", logging.getLevelName(level), log_file)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Extract ALL URLs from a repo's README, print them, and ask whether to proceed "
            "to analysis (test mode)."
        )
    )
    parser.add_argument(
        "repo",
        help="GitHub repository URL (e.g., https://github.com/modelcontextprotocol/servers)",
    )
    parser.add_argument("--no-sort", dest="sort", action="store_false", help="Do not sort output")
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv)"
    )
    parser.add_argument(
        "--log-file", help="Optional path to write debug logs as well", default=None
    )

    args = parser.parse_args(argv)
    configure_logging(args.verbose, args.log_file)

    logger.info("Starting README URL extraction for %s", args.repo)

    md = fetch_readme_markdown(args.repo)
    if not md:
        print("Could not fetch a README for the provided repository.")
        return 1

    all_urls = extract_urls_from_markdown(md)
    if not all_urls:
        print("No URLs were found in the README.")
        return 0

    # Print ALL URLs (deduped), as requested for testing.
    print(f"Found {len(all_urls)} URLs in the README:\n")
    for url in sorted(all_urls) if args.sort else all_urls:
        print(url)

    # Also show the GitHub repo candidates (useful context while testing)
    candidates = extract_github_repo_links_from_readme(args.repo)
    if candidates:
        print("\nGitHub repository candidates:\n")
        for line in format_targets_as_lines(candidates, sort=args.sort):
            print(line)

    # Test-mode confirmation prompt
    try:
        print("\nWould you like to proceed to analyze each of them? [y/N]: ", end="", flush=True)
        choice = sys.stdin.readline().strip().lower()
    except KeyboardInterrupt:  # pragma: no cover - UX nicety
        print("\nAborted.")
        return 130

    if choice in {"y", "yes"}:
        logger.info("User opted to proceed to analysis; placeholder stub will run.")
        print("Great! Analysis will run in the next phase (not implemented in this test mode).")
        # Placeholder: this is where we'd iterate and perform detection/describe.
    else:
        logger.info("User declined analysis step (test mode).")
        print("Okay, skipping analysis for now.")

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
