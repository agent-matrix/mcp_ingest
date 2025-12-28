#!/usr/bin/env python3
"""
Sync harvested MCP servers into the catalog structure.

This script:
1. Reads harvested manifests from the harvest directory
2. Deduplicates servers based on source fingerprint
3. Generates stable folder names (slugs)
4. Writes manifests to the catalog directory with stable paths
5. Creates per-folder index.json files
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def stable_slug(s: str, max_len: int = 80) -> str:
    """Generate a stable, filesystem-safe slug."""
    import re
    import unicodedata

    # Normalize unicode
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    # Replace non-alphanumeric with hyphens
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    # Collapse multiple hyphens
    s = re.sub(r"-{2,}", "-", s)
    # Default if empty
    if not s:
        s = "server"
    # Truncate with hash if too long
    if len(s) > max_len:
        h = hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]
        s = s[: max_len - 9].rstrip("-") + "-" + h
    return s


def fingerprint(manifest: dict) -> str:
    """Generate a unique fingerprint for deduplication."""
    # Use provenance if present, fallback to other identifying fields
    prov = manifest.get("provenance") or {}
    key = "|".join(
        [
            prov.get("source_repo", ""),
            prov.get("source_path", ""),
            manifest.get("name", ""),
            manifest.get("id", ""),
        ]
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync harvested data into catalog")
    parser.add_argument("--harvest", required=True, help="Harvest directory (input)")
    parser.add_argument("--catalog", required=True, help="Catalog directory (output)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    harvest = Path(args.harvest)
    catalog = Path(args.catalog)
    catalog.mkdir(parents=True, exist_ok=True)

    if not harvest.exists():
        print(f"❌ Harvest directory not found: {harvest}", file=sys.stderr)
        sys.exit(1)

    # Collect all harvested manifests
    manifests_by_fp: dict[str, Path] = {}
    total = 0
    duplicates = 0

    for manifest_path in harvest.rglob("manifest.json"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠️  Skipping invalid manifest {manifest_path}: {e}", file=sys.stderr)
            continue

        total += 1
        fp = fingerprint(data)

        if fp in manifests_by_fp:
            duplicates += 1
            if args.verbose:
                print(f"   Duplicate: {manifest_path} (matches {manifests_by_fp[fp]})")
            continue

        manifests_by_fp[fp] = manifest_path

    print(f"📊 Found {total} manifests, {len(manifests_by_fp)} unique ({duplicates} duplicates)")

    # Sync unique manifests to catalog
    synced = 0
    for _fp, manifest_path in manifests_by_fp.items():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))

        # Generate stable slug for folder name
        name = data.get("name") or data.get("id") or manifest_path.parent.name
        slug = stable_slug(name)

        # Destination folder
        dest_dir = catalog / slug
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Write manifest
        (dest_dir / "manifest.json").write_text(
            json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )

        # Write per-folder index
        (dest_dir / "index.json").write_text(
            json.dumps({"manifests": ["manifest.json"]}, indent=2) + "\n", encoding="utf-8"
        )

        synced += 1
        if args.verbose:
            print(f"   ✓ {slug}/manifest.json")

    print(f"✅ Synced {synced} manifests to {catalog}")


if __name__ == "__main__":
    main()
