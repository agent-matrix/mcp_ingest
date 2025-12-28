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
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

__all__ = [
    "RepoTarget",
    "fetch_readme_markdown",
    "extract_urls_from_markdown",
    "extract_github_repo_links_from_readme",
    "format_targets_as_lines",
    "configure_logging",
    "main",
    "extract_relative_paths_from_markdown",
    "resolve_repo_relative_links",
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
    """Very small GitHub client with optional token support.

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
            logger.debug("Using GITHUB_TOKEN for authentication.")
            headers["Authorization"] = f"Bearer {token}"
        else:
            logger.debug("No GITHUB_TOKEN found, proceeding with anonymous requests.")
        self.client = client or httpx.Client(headers=headers, timeout=20.0, follow_redirects=True)

    def get_json(self, url: str, ok_codes: Sequence[int] = (200,)) -> dict | None:
        logger.debug(f"Requesting JSON from: {url}")
        try:
            resp = self.client.get(url)
            if resp.status_code not in ok_codes:
                logger.warning("GET %s -> %s (expected %s)", url, resp.status_code, ok_codes)
                logger.debug("Response body: %s", resp.text)
                return None
            return resp.json()
        except Exception as e:  # pragma: no cover - defensive
            logger.error("GET %s failed: %s", url, e, exc_info=True)
            return None

    def get_text(self, url: str, ok_codes: Sequence[int] = (200,)) -> str | None:
        logger.debug(f"Requesting text from: {url}")
        try:
            resp = self.client.get(url)
            if resp.status_code not in ok_codes:
                logger.debug("GET %s -> %s (expected %s)", url, resp.status_code, ok_codes)
                return None
            return resp.text
        except Exception as e:  # pragma: no cover - defensive
            logger.error("GET %s failed: %s", url, e, exc_info=True)
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
    logger.debug("Starting URL extraction from markdown content.")
    for m in _MD_LINK_URL.finditer(md):
        url = m.group(1) or m.group("angle") or m.group("bare")
        if not url:
            continue
        # Trim common trailing punctuation from bare links
        original_url = url
        while url and url[-1] in _TRAILING_PUNCT:
            url = url[:-1]
        if original_url != url:
            logger.debug(f"Trimmed trailing punctuation from '{original_url}' -> '{url}'")
        urls.append(url)

    deduped_urls = _dedupe_preserve_order(urls)
    logger.info(f"Extracted {len(deduped_urls)} unique URLs from markdown.")
    return deduped_urls


# --- Relative link extraction and resolution ------------------------------

# Regex to capture markdown links including relative paths
_REL_MD_LINK = re.compile(r"\[([^\]]*)\]\((?P<href>[^)]+)\)")


def extract_relative_paths_from_markdown(md: str) -> list[str]:
    """Extract relative paths from markdown links.

    Filters out absolute URLs, mailto links, and anchors.
    Returns a de-duplicated list of relative paths.
    """
    out = []
    for m in _REL_MD_LINK.finditer(md):
        href = (m.group("href") or "").strip()
        if not href:
            continue
        # Ignore absolute URLs, mailto, and anchors
        if "://" in href or href.startswith("#") or href.startswith("mailto:"):
            continue
        # Strip surrounding quotes
        href = href.strip("\"'")
        # Ignore images and data URIs
        if href.lower().startswith("data:"):
            continue
        # Ignore if it looks like an absolute path to another domain
        if href.startswith("//"):
            continue
        logger.debug(f"Found relative path in markdown: {href}")
        out.append(href)

    deduped = _dedupe_preserve_order(out)
    logger.info(f"Extracted {len(deduped)} relative paths from markdown.")
    return deduped


def resolve_repo_relative_links(
    *,
    owner: str,
    repo: str,
    default_branch: str,
    rel_links: list[str],
) -> list[str]:
    """Resolve relative markdown links into absolute GitHub tree URLs.

    Converts relative paths like:
      - ./src/server
      - src/server/README.md
      - /tree/main/src/server

    Into canonical GitHub tree URLs:
      - https://github.com/{owner}/{repo}/tree/{default_branch}/src/server
    """
    base = f"https://github.com/{owner}/{repo}/tree/{default_branch}/"
    resolved = []

    for rl in rel_links:
        # Normalize leading ./ and /
        rl = rl.lstrip("./")
        if rl.startswith("/"):
            rl = rl.lstrip("/")

        # If the link already contains /tree/, extract the path after it
        if "/tree/" in rl:
            parts = rl.split("/tree/", 1)
            if len(parts) == 2:
                # Skip the ref, take only the path
                sub_parts = parts[1].split("/", 1)
                rl = sub_parts[1] if len(sub_parts) > 1 else ""

        # Skip empty paths
        if not rl:
            continue

        # Remove file extensions from paths to get directories
        # (README.md links should point to the directory containing them)
        if rl.endswith((".md", ".MD", ".txt", ".rst")):
            rl = str(Path(rl).parent) if Path(rl).parent != Path(".") else ""
            if not rl or rl == ".":
                continue

        resolved_url = urljoin(base, rl)
        logger.debug(f"Resolved relative link '{rl}' to '{resolved_url}'")
        resolved.append(resolved_url)

    deduped = _dedupe_preserve_order(resolved)
    logger.info(f"Resolved {len(deduped)} relative links to absolute GitHub URLs.")
    return deduped


# --- README discovery -----------------------------------------------------


def _parse_github_repo_url(repo_url: str) -> tuple[str, str]:
    """Return (owner, repo) from a GitHub repository identifier or URL.

    Accepts:
      - https://github.com/owner/repo
      - github.com/owner/repo
      - owner/repo
      - git@github.com:owner/repo.git
      - with/without .git and trailing slash
    """
    logger.debug(f"Attempting to parse GitHub repo URL: '{repo_url}'")
    s = (repo_url or "").strip()

    # SSH form → normalize to https
    if s.startswith("git@github.com:"):
        s_before = s
        s = s.replace("git@github.com:", "https://github.com/")
        logger.debug(f"Normalized SSH form '{s_before}' to '{s}'")

    # If it starts with 'github.com/', add scheme
    if s.lower().startswith("github.com/"):
        s_before = s
        s = "https://" + s
        logger.debug(f"Added scheme to '{s_before}' -> '{s}'")

    # If it's just 'owner/repo', expand to https://github.com/owner/repo
    if "://" not in s and s.count("/") == 1 and not s.endswith("/"):
        owner, repo = s.split("/", 1)
        if owner and repo:
            logger.debug(f"Recognized short form '{s}' as owner='{owner}', repo='{repo}'")
            return owner, repo

    logger.debug(f"Parsing '{s}' as a standard URL.")
    parsed = urlparse(s)
    logger.debug(f"Parsed URL: netloc='{parsed.netloc}', path='{parsed.path}'")
    if parsed.netloc.lower() != "github.com":
        logger.error(f"URL netloc is '{parsed.netloc}', but expected 'github.com'.")
        raise ValueError(
            "Only github.com URLs (or owner/repo short form) are supported in this helper"
        )

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        logger.error(f"URL path '{parsed.path}' does not contain owner/repo components.")
        raise ValueError("Expected a GitHub repo like https://github.com/owner/repo or owner/repo")

    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
        logger.debug(f"Removed '.git' suffix from repo name -> '{repo}'")

    logger.debug(f"Successfully parsed owner='{owner}', repo='{repo}'")
    return owner, repo


def _default_branch(client: GitHubClient, owner: str, repo: str) -> str | None:
    logger.debug(f"Fetching repository details for {owner}/{repo} to find default branch.")
    data = client.get_json(f"{_GITHUB_API}/repos/{owner}/{repo}")
    if not data:
        logger.warning(f"Failed to fetch repo details for {owner}/{repo}.")
        return None
    branch = data.get("default_branch")
    if branch:
        logger.info(f"Found default branch for {owner}/{repo}: '{branch}'")
    else:
        logger.warning(f"Could not determine default branch for {owner}/{repo} from API response.")
    return branch


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
    logger.debug(f"Searching for README in {owner}/{repo} on branch '{branch}'")
    for path in candidates:
        raw_url = f"{_RAW_BASE}/{owner}/{repo}/{branch}/{path}"
        logger.debug(f"Trying to fetch README candidate: {raw_url}")
        txt = client.get_text(raw_url)
        if txt is not None:
            logger.info("Fetched README from %s", raw_url)
            return txt
    return None


def fetch_readme_markdown(repo_url: str) -> str | None:
    """Fetch README markdown for a given GitHub repository URL.

    Tries the repository's default branch (via GitHub API), then falls back to
    common branches (main, master).
    """
    logger.info(f"Fetching README for repository: {repo_url}")
    try:
        owner, repo = _parse_github_repo_url(repo_url)
    except ValueError as e:
        logger.error(f"Could not parse repository URL '{repo_url}': {e}", exc_info=True)
        # Re-raise the exception to match original behavior
        raise

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

        logger.debug(f"Will search for README on branches in this order: {branches}")

        for branch in branches:
            md = _try_fetch_readme(client, owner, repo, branch)
            if md:
                return md
        logger.warning(
            "Could not find a README in %s/%s on any of the tried branches: %s",
            owner,
            repo,
            branches,
        )
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
    if parsed.netloc.lower() != "github.com":
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None

    owner, repo = parts[0], parts[1]

    if len(parts) >= 4 and parts[2] == "tree":
        ref = parts[3]
        subpath = "/".join(parts[4:]) if len(parts) >= 5 else None
        target = RepoTarget(owner, repo, ref=ref, subpath=subpath or None)
        logger.debug(f"Normalized '{url}' to RepoTarget with subpath: {target}")
        return target

    if len(parts) == 2:
        target = RepoTarget(owner, repo)
        logger.debug(f"Normalized '{url}' to base RepoTarget: {target}")
        return target

    return None


def extract_github_repo_links_from_readme(repo_url: str) -> list[RepoTarget]:
    """High-level helper: from a repo, read its README and extract GitHub repo links.

    Returns a de-duplicated list of :class:`RepoTarget` instances representing
    likely MCP server repositories mentioned in the README.

    This function now also resolves relative links in the README to absolute GitHub URLs,
    which is critical for harvesting repos like modelcontextprotocol/servers that use
    relative paths to reference MCP servers.
    """
    md = fetch_readme_markdown(repo_url)
    if not md:
        logger.warning(
            f"Cannot extract links because README for '{repo_url}' could not be fetched."
        )
        return []

    # Extract absolute URLs (existing functionality)
    urls = extract_urls_from_markdown(md)
    targets: list[RepoTarget] = []
    for u in urls:
        t = _normalize_github_link(u)
        if t:
            targets.append(t)

    # NEW: Also extract and resolve relative links
    try:
        owner, repo = _parse_github_repo_url(repo_url)
        client = GitHubClient()
        try:
            default_branch = _default_branch(client, owner, repo) or "main"
            logger.info(
                f"Extracting relative links from README and resolving against {owner}/{repo}@{default_branch}"
            )

            # Extract relative paths from markdown
            rel_paths = extract_relative_paths_from_markdown(md)

            if rel_paths:
                logger.info(f"Found {len(rel_paths)} relative paths in README")

                # Resolve them to absolute GitHub tree URLs
                abs_tree_urls = resolve_repo_relative_links(
                    owner=owner, repo=repo, default_branch=default_branch, rel_links=rel_paths
                )

                # Normalize them to RepoTargets
                for url in abs_tree_urls:
                    t = _normalize_github_link(url)
                    if t:
                        logger.debug(f"Added target from relative link: {t.pretty}")
                        targets.append(t)
        finally:
            client.close()
    except Exception as e:
        # Don't fail the entire extraction if relative link resolution fails
        logger.warning(f"Failed to resolve relative links: {e}", exc_info=True)

    # de-dupe by (owner, repo, ref, subpath)
    seen = set()
    out: list[RepoTarget] = []
    for t in targets:
        key = (t.owner, t.repo, t.ref, t.subpath)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)

    logger.info(f"Found {len(out)} unique GitHub repository targets in the README.")
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

    fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    # Use force=True to allow re-configuration in tests or interactive sessions
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, handlers=handlers, force=True)
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
        help="GitHub repository URL (e.g., https://github.com/modelcontextprotocol/servers) or short form (owner/repo)",
    )
    parser.add_argument("--no-sort", dest="sort", action="store_false", help="Do not sort output")
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="Increase verbosity (-v, -vv)"
    )
    parser.add_argument(
        "--log-file", help="Optional path to write debug logs as well", default=None
    )
    parser.add_argument(
        "--list-candidates-only",
        action="store_true",
        help="Only print the final list of candidate repo URLs and exit.",
    )

    args = parser.parse_args(argv)
    configure_logging(args.verbose, args.log_file)

    logger.info("Starting README URL extraction for %s", args.repo)

    try:
        # NOTE: The traceback shows the error happens in this function call
        md = fetch_readme_markdown(args.repo)
    except ValueError:
        # The error is already logged inside the function, but we add context here.
        logger.critical(
            f"A fatal error occurred while parsing the input repository: '{args.repo}'. Please check the format."
        )
        # The original code would print the traceback and exit, so we return a non-zero exit code.
        return 1

    if not md:
        print("Could not fetch a README for the provided repository.", file=sys.stderr)
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
    # Re-running this is inefficient but matches the original structure.
    # We add a try-except block here as well for safety, though it should have failed above if it was going to.
    try:
        # 1. First, get the list of candidates
        candidates = extract_github_repo_links_from_readme(args.repo)

        # --- ADD THIS ENTIRE LOGIC BLOCK HERE ---
        # 2. Check if we are in "data-only" mode. If so, print the data and exit.
        if args.list_candidates_only:
            if candidates:
                # Loop through the results and print ONLY the clean URLs
                for line in format_targets_as_lines(candidates, sort=args.sort):
                    print(line)
            # Exit successfully right after printing the list
            return 0
        # --- END OF NEW LOGIC BLOCK ---

        # 3. If not in "data-only" mode, proceed with the normal interactive output.

        if candidates:
            print("\nGitHub repository candidates:\n")
            for line in format_targets_as_lines(candidates, sort=args.sort):
                print(line)
    except ValueError:
        # This case is unlikely if the first call succeeded, but it's good practice.
        logger.error("Failed to extract GitHub repo links on the second pass.")
        # We can continue since the main URL list was already printed.

    # Test-mode confirmation prompt
    try:
        print("\nWould you like to proceed to analyze each of them? [y/N]: ", end="", flush=True)
        # Check if stdin is a tty, otherwise skip the prompt (for non-interactive use)
        if not sys.stdin.isatty():
            print("Non-interactive mode detected, skipping analysis.")
            logger.info("Non-interactive session; skipping user prompt.")
            return 0
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
