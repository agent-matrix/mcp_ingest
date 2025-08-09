from __future__ import annotations
from typing import Dict, List, Optional
import os
import time
import httpx

GITHUB_API = "https://api.github.com"

QUERIES = [
    'FastMCP filename:server.py in:path language:Python',
    '@mcp.tool language:Python',
    '"model-context-protocol" language:Python',
    '"MCP server" language:Python',
]

def _headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h

def search_sources(limit: int = 100) -> List[str]:
    """Return a list of canonical sources (e.g., repo clone URLs)."""
    out: List[str] = []
    seen = set()
    with httpx.Client(timeout=20.0, headers=_headers()) as c:
        for q in QUERIES:
            try:
                r = c.get(f"{GITHUB_API}/search/code", params={"q": q, "per_page": 30})
                if r.status_code == 403:  # rate limited
                    time.sleep(2.0); continue
                r.raise_for_status()
                data = r.json()
                for item in data.get("items", []):
                    repo = item.get("repository", {})
                    clone = repo.get("clone_url")
                    if clone and clone not in seen:
                        seen.add(clone)
                        out.append(clone)
                    if len(out) >= limit:
                        return out
            except httpx.RequestError:
                # Ignore search errors for single queries
                continue
    return out
