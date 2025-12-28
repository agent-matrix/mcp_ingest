# mcp_ingest/emit/enrich.py
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

__all__ = ["enrich_manifest", "guess_license"]


def _owner_repo_from_github_url(u: str) -> tuple[str, str] | None:
    """
    Accepts https://github.com/<owner>/<repo>[.git][/...]
    Returns (owner, repo) without .git.
    """
    try:
        parsed = urlparse(u)
        if parsed.netloc.lower() != "github.com":
            return None
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            return None
        owner, repo = parts[0], parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        return owner, repo
    except Exception:
        return None


def _raw_url(owner: str, repo: str, ref: str, relpath: str) -> str:
    # ref can be branch, tag, or sha; sha is best for determinism
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{relpath.lstrip('/')}"


def guess_license(repo_root: Path) -> str:
    """
    Tiny heuristic: read first line of LICENSE* if small.
    Returns a best-guess string or "".
    """
    try:
        # Try common files
        for cand in ["LICENSE", "LICENSE.txt", "LICENSE.md", "LICENSE-MIT", "COPYING"]:
            p = repo_root / cand
            if p.exists() and p.is_file() and p.stat().st_size < 128_000:
                text = p.read_text(encoding="utf-8", errors="ignore")
                first = text.strip().splitlines()[0] if text.strip() else ""
                # crude mapping
                up = text.upper()
                if "MIT LICENSE" in up or "PERMISSION IS HEREBY GRANTED" in up:
                    return "MIT"
                if "APACHE LICENSE" in up and "2.0" in up:
                    return "Apache-2.0"
                if "BSD" in up:
                    return "BSD"
                if "GPL" in up:
                    return "GPL"
                return first[:80] if first else ""
    except Exception:
        pass
    return ""


def enrich_manifest(
    manifest_path: Path,
    *,
    homepage: str | None = None,
    git_origin: str | None = None,
    git_ref: str | None = None,  # branch/tag/sha (sha preferred)
    server_relpath_from_repo_root: str | None = None,
    repo_root: Path | None = None,  # used for license guessing
    detector: str | None = None,  # NEW: detection framework (e.g., "fastmcp", "langchain")
    confidence: float | None = None,  # NEW: detector confidence score (0.0-1.0)
    stars: int | None = None,  # NEW: GitHub stars count
    forks: int | None = None,  # NEW: GitHub forks count
) -> dict[str, Any]:
    """
    Load manifest.json, add optional rich fields with safe defaults, and write back.
    Returns the updated manifest dict.

    NEW in this version:
    - Adds provenance metadata for tracking harvest source and timestamp
    - Captures detector information and confidence scores
    - Includes optional GitHub repository metrics (stars, forks)
    - All additions are backward-compatible and safe
    """
    import json
    from datetime import datetime

    doc = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Always include schema_version
    doc.setdefault("schema_version", 1)

    # Summary: best-effort—derive from description if missing
    if "summary" not in doc or not doc["summary"]:
        desc = doc.get("description") or ""
        doc["summary"] = desc[:120] if desc else ""

    # Homepage (prefer explicit; else try from git origin)
    if homepage:
        doc["homepage"] = homepage
    elif git_origin:
        # strip .git
        doc["homepage"] = git_origin[:-4] if git_origin.endswith(".git") else git_origin
    else:
        doc.setdefault("homepage", "")

    # License (best-effort)
    if "license" not in doc or not doc["license"]:
        if repo_root is not None:
            doc["license"] = guess_license(repo_root) or ""
        else:
            doc.setdefault("license", "")

    # NEW: Provenance metadata (for tracking harvest source and quality)
    doc.setdefault("provenance", {})
    prov = doc["provenance"]

    # Harvest timestamp
    if "harvested_at" not in prov:
        prov["harvested_at"] = datetime.now(datetime.UTC).isoformat()

    # Source repository information
    if git_origin:
        prov.setdefault("source_repo", git_origin)
    elif homepage:
        prov.setdefault("source_repo", homepage)

    if git_ref:
        prov.setdefault("source_ref", git_ref)

    if server_relpath_from_repo_root:
        prov.setdefault("source_path", server_relpath_from_repo_root)

    # Detection metadata
    if detector:
        prov.setdefault("detector", detector)

    if confidence is not None:
        prov.setdefault("confidence", confidence)

    # Repository metrics (for ranking and display)
    if stars is not None:
        prov.setdefault("stars", stars)

    if forks is not None:
        prov.setdefault("forks", forks)

    # Harvester version (useful for debugging)
    prov.setdefault("harvester", "mcp-ingest")
    prov.setdefault("harvester_version", "0.1.1")

    # Artifacts: ensure a git entry if we have origin/ref
    arts = doc.setdefault("artifacts", [])
    if git_origin:
        has_git = any(isinstance(a, dict) and a.get("kind") == "git" for a in arts)
        if not has_git:
            arts.append({"kind": "git", "spec": {"repo": git_origin, "ref": git_ref or ""}})

    # Registration scaffold
    reg = doc.setdefault("mcp_registration", {})
    reg.setdefault("resources", [])
    reg.setdefault("prompts", [])
    reg.setdefault(
        "server",
        {
            "name": doc.get("name") or doc.get("id") or "",
            "description": doc.get("description") or "",
            "transport": "SSE",
            "url": "",
            "associated_tools": [],
            "associated_resources": [],
            "associated_prompts": [],
        },
    )

    # Optional 'tool' scaffold (kept minimal unless detectors filled it already)
    reg.setdefault(
        "tool",
        {
            "id": f"{doc.get('id', 'tool')}-tool",
            "name": doc.get("name") or doc.get("id") or "",
            "description": doc.get("summary") or doc.get("description") or "",
            "integration_type": "MCP",
            "url": reg["server"].get("url", ""),
            "input_schema": {"type": "object", "properties": {}},
        },
    )

    # Add a URL resource to server.py if we know a GitHub ref + relative path
    if server_relpath_from_repo_root and git_origin and git_ref:
        owner_repo = _owner_repo_from_github_url(git_origin)
        if not owner_repo:  # git_origin may be https://github.com/.../.git or ssh
            # Try homepage if git_origin isn't github-like
            if doc.get("homepage"):
                owner_repo = _owner_repo_from_github_url(str(doc["homepage"]))
        if owner_repo:
            o, r = owner_repo
            raw = _raw_url(o, r, git_ref, server_relpath_from_repo_root)
            resources = reg["resources"]
            if not any(res.get("uri") == raw for res in resources if isinstance(res, dict)):
                resources.append(
                    {
                        "id": "server-url",
                        "name": "server.py (raw)",
                        "type": "url",
                        "uri": raw,
                    }
                )
            srv = reg["server"]
            assoc = set(srv.get("associated_resources") or [])
            assoc.add("server-url")
            srv["associated_resources"] = list(assoc)

    # Write back
    manifest_path.write_text(json.dumps(doc, indent=2, sort_keys=False), encoding="utf-8")
    return doc
