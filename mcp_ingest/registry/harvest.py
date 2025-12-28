"""Harvest MCP servers from Registry API into catalog format."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import RegistryClient
from .normalize import normalize_registry_server

__all__ = ["harvest_registry"]

log = logging.getLogger(__name__)


def utc_now_iso() -> str:
    """Get current UTC timestamp in ISO format (Python 3.11 compatible)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_slug(s: str) -> str:
    """Convert string to safe filesystem slug."""
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "unknown"


def write_json(path: Path, obj: Any) -> None:
    """Write JSON object to file with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def group_and_variant(manifest: dict[str, Any]) -> tuple[str, str]:
    """
    Determine deterministic group and variant names for manifest.

    Group: based on server name namespace
    Variant: based on manifest ID (stable, collision-free)
    """
    name = manifest.get("name") or "unknown"
    # Extract namespace (e.g., "io.github.user" from "io.github.user/weather")
    group = safe_slug(name.split("/", 1)[0])

    # Variant based on manifest id (already includes transport + hash)
    variant = safe_slug(manifest.get("id") or "unknown")

    return group, variant


def harvest_registry(
    registry_base_url: str = "https://registry.modelcontextprotocol.io",
    out_dir: str | Path = "catalog",
    updated_since: str | None = None,
    top: int | None = None,
    limit: int = 10,
) -> Path:
    """
    Harvest MCP servers from Registry API into catalog format.

    This produces a clean, deterministic catalog with:
    - servers/** as source of truth
    - relative paths in index.json
    - proper lifecycle states
    - stable manifest IDs

    Parameters
    ----------
    registry_base_url : str
        Base URL of the MCP Registry API
    out_dir : str | Path
        Output directory for catalog
    updated_since : str | None
        ISO timestamp for incremental sync
    top : int | None
        Limit to first N servers (for testing)
    limit : int
        Page size for API pagination

    Returns
    -------
    Path
        Path to generated index.json
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info(
        "Starting registry harvest: registry=%s out=%s top=%s",
        registry_base_url,
        out_dir,
        top or "unlimited",
    )

    client = RegistryClient(base_url=registry_base_url)

    servers_dir = out_dir / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    manifests_active: list[str] = []
    server_count = 0
    manifest_count = 0

    for srv in client.iter_servers_latest(updated_since=updated_since, limit=limit, top=top):
        server_count += 1
        server_name = (srv.get("server") or {}).get("name", "unknown")

        log.debug("Processing server %d: %s", server_count, server_name)

        try:
            manifests = normalize_registry_server(srv, registry_base_url)

            for m in manifests:
                manifest_count += 1
                status = (m.get("lifecycle") or {}).get("status", "active")

                # Skip deleted servers (not installable)
                if status == "deleted":
                    log.debug("Skipping deleted manifest: %s", m["id"])
                    continue

                # Determine storage location
                group, variant = group_and_variant(m)
                folder = servers_dir / group / variant
                dest = folder / "manifest.json"

                # Write manifest
                write_json(dest, m)

                # Calculate relative path for index
                rel = str(dest.relative_to(out_dir)).replace("\\", "/")

                # Add to items list (includes deprecated for audit)
                items.append(
                    {
                        "type": "mcp_server",
                        "id": m["id"],
                        "name": m.get("name"),
                        "version": m.get("version"),
                        "transport": (m.get("mcp_registration") or {})
                        .get("server", {})
                        .get("transport"),
                        "status": status,
                        "manifest_path": rel,
                    }
                )

                # Add to active manifests list (for ingestion)
                if status == "active":
                    manifests_active.append(rel)

        except Exception as e:
            log.error("Failed to process server %s: %s", server_name, e, exc_info=True)
            continue

    log.info(
        "Harvest complete: %d servers, %d manifests (%d active, %d deprecated)",
        server_count,
        manifest_count,
        len(manifests_active),
        manifest_count - len(manifests_active),
    )

    # Build top-level index.json (MatrixHub-friendly)
    index = {
        "generated_at": utc_now_iso(),
        "source": {
            "kind": "mcp-registry",
            "registry_base_url": registry_base_url,
            "endpoint": "/v0.1/servers?version=latest",
            "updated_since": updated_since,
        },
        "counts": {
            "total_items": len(items),
            "active_manifests": len(set(manifests_active)),
            "deprecated": len(items) - len(set(manifests_active)),
        },
        "items": sorted(items, key=lambda x: (x["id"], x["manifest_path"])),
        "manifests": sorted(set(manifests_active)),
    }

    index_path = out_dir / "index.json"
    write_json(index_path, index)

    log.info("Wrote index to: %s", index_path)
    return index_path
