#!/usr/bin/env python3
"""
Daily sync for agent-matrix/catalog using mcp_ingest.

Outputs to servers/** with deterministic paths and lifecycle tracking.
Prevents catalog pollution, ID collisions, and index corruption.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Import from installed mcp_ingest package
try:
    from mcp_ingest.harvest.source import harvest_source
except ImportError:
    print("❌ mcp_ingest not installed. Run: pip install mcp-ingest")
    import sys

    sys.exit(1)


# ---------------------------
# Utilities
# ---------------------------


def now_iso() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> Any:
    """Read and parse JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    """Write JSON with consistent formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def norm_repo_full(repo_url: str) -> str:
    """Normalize GitHub repo URL to owner/repo format."""
    s = (repo_url or "").strip().rstrip("/")
    if "github.com/" in s:
        s = s.split("github.com/", 1)[1]
    if s.endswith(".git"):
        s = s[:-4]
    return s.strip("/")


def safe_slug(s: str) -> str:
    """Convert string to filesystem-safe slug."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unknown"


def subpath_to_variant(repo: str, subpath: str) -> str:
    """Build variant directory name: <repo>__<subpath>."""
    sp = (subpath or "").lstrip("/").strip()
    if not sp:
        sp = "."
    sp = sp.replace("\\", "/").replace("/", "__")
    return f"{repo}__{sp}"


def resolve_manifest_path(harvest_out: Path, mp: str) -> Path | None:
    """Resolve manifest path from harvester output."""
    p = Path(mp)

    # Try absolute path
    if p.is_absolute() and p.exists():
        return p

    # Try relative to harvest output
    p2 = (harvest_out / p).resolve()
    if p2.exists():
        return p2

    # Last resort: search by filename
    matches = list(harvest_out.rglob(p.name))
    if len(matches) == 1:
        return matches[0]

    return None


# ---------------------------
# Catalog key for deduplication
# ---------------------------


@dataclass(frozen=True)
class CatalogKey:
    """Stable key for identifying unique servers."""

    repo_full: str  # owner/repo
    subpath: str  # empty string or 'src/...'
    transport: str  # SSE/STDIO/WS/UNKNOWN


def extract_source_repo_path(manifest: dict[str, Any]) -> tuple[str, str]:
    """Extract repo and subpath from manifest provenance."""
    prov = manifest.get("provenance") or {}
    repo_url = prov.get("repo_url") or prov.get("repo") or prov.get("source_repo") or ""
    subpath = prov.get("subpath") or prov.get("path") or prov.get("source_path") or ""
    repo_full = norm_repo_full(str(repo_url)) if repo_url else "unknown/unknown"
    return repo_full, str(subpath or "").lstrip("/")


def extract_transport(manifest: dict[str, Any]) -> str:
    """Extract transport type from manifest."""
    reg = manifest.get("mcp_registration") or {}
    server = reg.get("server") or {}
    t = str(server.get("transport") or "").upper().strip()
    return t or "UNKNOWN"


# ---------------------------
# Lifecycle tracking
# ---------------------------


def mark_active_seen(manifest: dict[str, Any]) -> dict[str, Any]:
    """Mark manifest as active and seen in current run."""
    ts = now_iso()

    lifecycle = manifest.get("lifecycle") or {}
    if lifecycle.get("status") == "deprecated":
        lifecycle["status"] = "active"
        lifecycle["reactivated_at"] = ts
    lifecycle.setdefault("status", "active")
    manifest["lifecycle"] = lifecycle

    harvest = manifest.get("harvest") or {}
    harvest["seen_in_latest_run"] = True
    harvest["last_seen_at"] = ts
    manifest["harvest"] = harvest

    return manifest


def mark_deprecated(manifest: dict[str, Any], reason: str) -> dict[str, Any]:
    """Mark manifest as deprecated."""
    ts = now_iso()

    lifecycle = manifest.get("lifecycle") or {}
    if lifecycle.get("status") != "disabled":
        lifecycle["status"] = "deprecated"
    lifecycle.setdefault("deprecated_at", ts)
    lifecycle["reason"] = reason
    lifecycle.setdefault("replaced_by", None)
    manifest["lifecycle"] = lifecycle

    harvest = manifest.get("harvest") or {}
    harvest["seen_in_latest_run"] = False
    harvest.setdefault("last_seen_at", ts)
    manifest["harvest"] = harvest

    return manifest


# ---------------------------
# Existing catalog scanning
# ---------------------------


def iter_existing_manifests(servers_dir: Path) -> Iterable[Path]:
    """Yield all manifest.json files in servers directory."""
    yield from servers_dir.glob("**/manifest.json")


def load_existing_by_key(servers_dir: Path) -> dict[CatalogKey, Path]:
    """Map stable keys to existing manifest paths."""
    out: dict[CatalogKey, Path] = {}
    for mf in iter_existing_manifests(servers_dir):
        try:
            m = read_json(mf)
        except Exception:
            continue
        if m.get("type") != "mcp_server":
            continue
        repo_full, subpath = extract_source_repo_path(m)
        transport = extract_transport(m)
        key = CatalogKey(repo_full=repo_full, subpath=subpath, transport=transport)
        out[key] = mf
    return out


# ---------------------------
# Path building
# ---------------------------


def build_group_dir(servers_dir: Path, repo_full: str) -> Path:
    """Build group directory: servers/<owner>-<repo>."""
    owner, repo = (repo_full.split("/", 1) + ["unknown"])[:2]
    group = f"{safe_slug(owner)}-{safe_slug(repo)}"
    return servers_dir / group


def build_variant_dir(group_dir: Path, repo_full: str, subpath: str) -> Path:
    """Build variant directory: servers/<group>/<repo>__<subpath>."""
    _, repo = (repo_full.split("/", 1) + ["unknown"])[:2]
    variant = subpath_to_variant(safe_slug(repo), subpath)
    return group_dir / variant


def rebuild_group_indexes(servers_dir: Path) -> None:
    """Rebuild group-level index.json files."""
    for group in servers_dir.iterdir():
        if not group.is_dir():
            continue
        relpaths: list[str] = []
        for mf in group.glob("**/manifest.json"):
            rel = str(mf.relative_to(group)).replace("\\", "/")
            relpaths.append(rel)
        relpaths = sorted(set(relpaths))
        write_json(group / "index.json", {"manifests": relpaths})


# ---------------------------
# Main sync logic
# ---------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync MCP servers catalog")
    ap.add_argument("--source-repo", required=True, help="Source repository URL")
    ap.add_argument("--catalog-root", default=".", help="Catalog root directory")
    ap.add_argument("--servers-dir", default="servers", help="Servers output directory")
    ap.add_argument("--index-file", default="index.json", help="Top-level index file")
    ap.add_argument("--max-parallel", type=int, default=8, help="Max parallel workers")
    args = ap.parse_args()

    catalog_root = Path(args.catalog_root).resolve()
    servers_dir = (catalog_root / args.servers_dir).resolve()
    index_file = (catalog_root / args.index_file).resolve()

    # Temporary harvest directory
    harvest_out = catalog_root / ".tmp" / "harvest"
    if harvest_out.exists():
        shutil.rmtree(harvest_out)
    harvest_out.mkdir(parents=True, exist_ok=True)

    servers_dir.mkdir(parents=True, exist_ok=True)

    print(f"🔍 Harvesting from: {args.source_repo}")
    print(f"📁 Output directory: {servers_dir}")

    # Load existing manifests for deprecation tracking
    existing_by_key = load_existing_by_key(servers_dir)
    seen_keys: set[CatalogKey] = set()

    # Run mcp_ingest harvester
    print("\n⚡ Running mcp_ingest harvester...")
    harvest_source(
        repo_url=args.source_repo,
        out_dir=harvest_out,
        yes=True,
        max_parallel=args.max_parallel,
        only_github=True,
        register=False,
        matrixhub=None,
        log_file=None,
    )

    # Read harvested index
    top_index_path = harvest_out / "index.json"
    if not top_index_path.exists():
        raise SystemExit(f"❌ Harvester did not produce index at {top_index_path}")

    harvested_index = read_json(top_index_path)
    manifest_paths = harvested_index.get("manifests") or harvested_index.get("manifest_paths") or []

    if not manifest_paths:
        raise SystemExit("❌ No manifests found in harvested index")

    print(f"✅ Found {len(manifest_paths)} manifests in harvest")

    # Track for collision detection
    id_to_key: dict[str, CatalogKey] = {}
    top_items: list[dict[str, Any]] = []
    active_manifest_relpaths: list[str] = []

    # Process each harvested manifest
    for mp in manifest_paths:
        src_path = resolve_manifest_path(harvest_out, mp)
        if not src_path:
            print(f"⚠️  Could not resolve: {mp}")
            continue

        manifest = read_json(src_path)
        if manifest.get("type") != "mcp_server":
            continue

        repo_full, subpath = extract_source_repo_path(manifest)
        transport = extract_transport(manifest)
        key = CatalogKey(repo_full=repo_full, subpath=subpath, transport=transport)

        # Mark as active/seen
        manifest = mark_active_seen(manifest)

        # Validate ID
        mid = str(manifest.get("id") or "").strip()
        if not mid:
            raise SystemExit(f"❌ Manifest missing 'id' (repo={repo_full}, subpath={subpath})")

        # Check for ID collisions
        if mid in id_to_key and id_to_key[mid] != key:
            raise SystemExit(
                f"❌ ID collision detected:\n"
                f"  ID: {mid}\n"
                f"  Key 1: {id_to_key[mid]}\n"
                f"  Key 2: {key}\n"
            )
        id_to_key[mid] = key

        # Write to catalog
        group_dir = build_group_dir(servers_dir, repo_full)
        variant_dir = build_variant_dir(group_dir, repo_full, subpath)
        variant_dir.mkdir(parents=True, exist_ok=True)

        dest_manifest = variant_dir / "manifest.json"
        write_json(dest_manifest, manifest)

        # Write provenance
        prov = manifest.get("provenance") or {}
        if not prov:
            prov = {
                "repo_url": f"https://github.com/{repo_full}",
                "subpath": subpath,
                "transport": transport,
                "harvested_from": args.source_repo,
                "harvested_at": now_iso(),
            }
        write_json(variant_dir / "provenance.json", prov)

        # Write variant index
        write_json(variant_dir / "index.json", {"manifests": ["./manifest.json"]})

        # Track for top-level index
        rel_manifest = str(dest_manifest.relative_to(catalog_root)).replace("\\", "/")

        # Validate path (critical for avoiding index corruption)
        if rel_manifest.startswith("http://") or rel_manifest.startswith("https://"):
            raise SystemExit(f"❌ BUG: manifest path is URL: {rel_manifest}")
        if not dest_manifest.exists():
            raise SystemExit(f"❌ BUG: manifest missing on disk: {rel_manifest}")

        seen_keys.add(key)
        status = (manifest.get("lifecycle") or {}).get("status", "active")

        top_items.append(
            {
                "type": "mcp_server",
                "id": mid,
                "name": manifest.get("name"),
                "transport": transport,
                "status": status,
                "manifest_path": rel_manifest,
                "repo": f"https://github.com/{repo_full}",
                "subpath": subpath,
            }
        )

        # Only active manifests go into ingestion list
        if status == "active":
            active_manifest_relpaths.append(rel_manifest)

    # Deprecate missing manifests
    deprecated_added = 0
    for key, mf_path in existing_by_key.items():
        if key in seen_keys:
            continue
        try:
            m = read_json(mf_path)
        except Exception:
            continue
        if m.get("type") != "mcp_server":
            continue

        m = mark_deprecated(m, reason=f"Not found in latest harvest from {args.source_repo}")
        write_json(mf_path, m)
        deprecated_added += 1

        repo_full, subpath = extract_source_repo_path(m)
        transport = extract_transport(m)
        mid = str(m.get("id") or "").strip()
        rel_manifest = str(mf_path.relative_to(catalog_root)).replace("\\", "/")

        top_items.append(
            {
                "type": "mcp_server",
                "id": mid,
                "name": m.get("name"),
                "transport": transport,
                "status": "deprecated",
                "manifest_path": rel_manifest,
                "repo": f"https://github.com/{repo_full}",
                "subpath": subpath,
            }
        )

    # Rebuild group indexes
    rebuild_group_indexes(servers_dir)

    # Sort deterministically
    top_items.sort(key=lambda x: (str(x.get("id") or ""), str(x.get("manifest_path") or "")))
    active_manifest_relpaths = sorted(set(active_manifest_relpaths))

    # Final validation: all active paths must exist
    for rel in active_manifest_relpaths:
        p = catalog_root / rel
        if not p.exists():
            raise SystemExit(f"❌ index.json.manifests contains missing path: {rel}")

    # Build top-level index
    top_index = {
        "generated_at": now_iso(),
        "source": {
            "harvester": "mcp_ingest.harvest_source",
            "root_repo": args.source_repo,
        },
        "counts": {
            "total_items": len(top_items),
            "active_manifests": len(active_manifest_relpaths),
            "deprecated_added_this_run": deprecated_added,
        },
        "items": top_items,
        "manifests": active_manifest_relpaths,  # ONLY ACTIVE, RELATIVE PATHS
    }

    write_json(index_file, top_index)

    print("\n✅ Sync complete!")
    print(f"   Total items: {len(top_items)}")
    print(f"   Active manifests: {len(active_manifest_relpaths)}")
    print(f"   Newly deprecated: {deprecated_added}")
    print(f"   Index written: {index_file}")


if __name__ == "__main__":
    main()
