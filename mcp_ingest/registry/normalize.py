"""Normalize MCP Registry ServerResponse to MatrixHub-compatible manifests."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

__all__ = ["normalize_registry_server"]


def utc_now_iso() -> str:
    """Get current UTC timestamp in ISO format (Python 3.11 compatible)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def short_hash(s: str) -> str:
    """Generate short hash for stable identity keys."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:10]


def stable_manifest_id(server_name: str, transport: str, variant_key: str) -> str:
    """
    Generate collision-proof manifest ID for DB-safe upserts.

    Format: mcp.{server_name}.{transport}.{hash}
    Example: mcp.io.github.user-weather.stdio.a1b2c3d4e5
    """
    safe_name = server_name.replace("/", "-").replace(".", "-")
    return f"mcp.{safe_name}.{transport.lower()}.{short_hash(variant_key)}"


def pick_links(server: dict[str, Any]) -> dict[str, Any]:
    """Extract repository/homepage/documentation links from server metadata."""
    links: dict[str, Any] = {}

    # Repository can be a string or object with url field
    repo = server.get("repository")
    if isinstance(repo, dict):
        repo_url = repo.get("url")
    elif isinstance(repo, str):
        repo_url = repo
    else:
        repo_url = None

    if repo_url:
        links["repository"] = repo_url
        links["homepage"] = repo_url
        links["documentation"] = repo_url

    return links


def build_lifecycle(status: str) -> dict[str, Any]:
    """
    Build lifecycle object, omitting None values for schema compliance.

    The catalog schema requires deprecated_at/reason/replaced_by to be strings when present,
    so we omit them entirely when they are None.
    """
    lifecycle: dict[str, Any] = {"status": status}
    # Only include optional fields if they have values
    # deprecated_at, reason, replaced_by are omitted when None
    return lifecycle


def to_stdio_exec(pkg: dict[str, Any]) -> dict[str, Any]:
    """
    Convert registry package to exec command for STDIO transport.

    Registry packages include:
    - registryType (pypi/npm/oci/...)
    - identifier
    - version
    - runtimeHint (uvx/npx/docker/...)
    - runtimeArguments []
    """
    rt = (pkg.get("runtimeHint") or "").strip()
    args = pkg.get("runtimeArguments") or []
    ident = pkg.get("identifier")
    ver = pkg.get("version")

    # Build command based on runtime hint
    if rt and ident and ver:
        # Include version pin for deterministic installs
        return {"cmd": [rt, *args, f"{ident}=={ver}"], "env": {}}
    if rt and ident:
        return {"cmd": [rt, *args, str(ident)], "env": {}}

    # Fallback for incomplete metadata
    return {"cmd": ["echo", "missing-runtimeHint-or-identifier"], "env": {}}


def normalize_registry_server(
    server_response: dict[str, Any], registry_base_url: str
) -> list[dict[str, Any]]:
    """
    Convert a Registry ServerResponse into MatrixHub-compatible manifests.

    One registry server can produce multiple manifests:
    - Each package (stdio install) → one manifest
    - Each remote (SSE/WS URL) → one manifest

    Parameters
    ----------
    server_response : dict
        ServerResponse from registry API
    registry_base_url : str
        Base URL of the registry (for provenance)

    Returns
    -------
    list[dict]
        List of MatrixHub mcp_server manifests
    """
    server = server_response.get("server") or {}
    meta = server_response.get("_meta") or {}

    # Extract core server info
    server_name = server.get("name") or server.get("serverName") or "unknown"
    title = server.get("title")
    description = server.get("description")
    version = server.get("version")

    # Lifecycle status from registry metadata
    official_meta = meta.get("io.modelcontextprotocol.registry/official") or {}
    status = official_meta.get("status") or meta.get("status") or "active"
    published_at = official_meta.get("publishedAt") or meta.get("publishedAt")
    updated_at = official_meta.get("updatedAt") or meta.get("updatedAt")

    manifests: list[dict[str, Any]] = []
    links = pick_links(server)

    # Extract inputs/variables if present
    inputs = server.get("inputs") or {}
    variables = inputs.get("variables") or {}

    # 1) Process packages => STDIO manifests
    for pkg in server.get("packages") or []:
        reg_type = pkg.get("registryType")
        identifier = pkg.get("identifier")
        pkg_version = pkg.get("version")

        variant_key = f"{server_name}|package|{reg_type}|{identifier}|{pkg_version}"
        mid = stable_manifest_id(server_name, "STDIO", variant_key)

        manifest = {
            "type": "mcp_server",
            "id": mid,
            "name": server_name,
            "title": title,
            "description": description,
            "version": version,
            "mcp_registration": {"server": {"transport": "STDIO", "exec": to_stdio_exec(pkg)}},
            "packages": [pkg],
            "links": links,
            "provenance": {
                "source": "mcp-registry",
                "registry_base_url": registry_base_url,
                "server_name": server_name,
                "server_version": version,
                "published_at": published_at,
                "updated_at": updated_at,
                "identity_key": short_hash(variant_key),
            },
            "lifecycle": build_lifecycle(status),
            "harvest": {"seen_in_latest_run": True, "last_seen_at": utc_now_iso()},
        }

        # Add inputs/variables if present
        if variables:
            manifest["inputs"] = {"variables": variables}

        # Add tags and license if present
        if server.get("tags"):
            manifest["tags"] = server["tags"]
        if server.get("license"):
            manifest["license"] = server["license"]

        manifests.append(manifest)

    # 2) Process remotes => SSE/WS manifests
    for remote in server.get("remotes") or []:
        rtype = (remote.get("transport") or remote.get("type") or "").upper()
        url = remote.get("url")

        # Map registry transport names to MatrixHub supported transports
        if rtype in ("SSE", "STREAMABLE_HTTP", "HTTP"):
            transport = "SSE"
        elif rtype in ("WS", "WEBSOCKET"):
            transport = "WS"
        else:
            transport = "SSE"  # Default fallback

        variant_key = f"{server_name}|remote|{transport}|{url}"
        mid = stable_manifest_id(server_name, transport, variant_key)

        manifest = {
            "type": "mcp_server",
            "id": mid,
            "name": server_name,
            "title": title,
            "description": description,
            "version": version,
            "mcp_registration": {"server": {"transport": transport, "url": url}},
            "remotes": [remote],
            "links": links,
            "provenance": {
                "source": "mcp-registry",
                "registry_base_url": registry_base_url,
                "server_name": server_name,
                "server_version": version,
                "published_at": published_at,
                "updated_at": updated_at,
                "identity_key": short_hash(variant_key),
            },
            "lifecycle": build_lifecycle(status),
            "harvest": {"seen_in_latest_run": True, "last_seen_at": utc_now_iso()},
        }

        # Add inputs/variables if present
        if variables:
            manifest["inputs"] = {"variables": variables}

        # Add tags and license if present
        if server.get("tags"):
            manifest["tags"] = server["tags"]
        if server.get("license"):
            manifest["license"] = server["license"]

        manifests.append(manifest)

    return manifests
