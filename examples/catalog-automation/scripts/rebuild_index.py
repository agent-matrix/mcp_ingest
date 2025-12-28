#!/usr/bin/env python3
"""
Rebuild the root index.json file from all manifests in the catalog.

This script generates a deterministic index that points to all manifest files,
optionally using absolute GitHub raw URLs for direct consumption by Matrix Hub.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild root index.json")
    parser.add_argument("--catalog", required=True, help="Catalog directory to scan")
    parser.add_argument("--out", required=True, help="Output index.json path")
    parser.add_argument(
        "--base-url",
        help="Base URL for absolute manifest URLs (e.g., https://raw.githubusercontent.com/...)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    catalog = Path(args.catalog)
    if not catalog.exists():
        print(f"❌ Catalog directory not found: {catalog}")
        return

    # Find all manifest.json files
    manifests = []
    for manifest_path in sorted(catalog.rglob("manifest.json")):
        # Get relative path from catalog root
        rel_path = manifest_path.relative_to(catalog.parent).as_posix()

        entry = {"path": rel_path}

        # Add absolute URL if base URL provided
        if args.base_url:
            base = args.base_url.rstrip("/")
            entry["url"] = f"{base}/{rel_path}"

        # Optionally include manifest metadata (name, id, type)
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry["id"] = data.get("id", "")
            entry["name"] = data.get("name", "")
            entry["type"] = data.get("type", "mcp_server")
        except Exception:
            pass

        manifests.append(entry)

        if args.verbose:
            print(f"   ✓ {rel_path}")

    # Build index
    index = {
        "version": "1.0.0",
        "generated_at": datetime.now(datetime.UTC).isoformat(),
        "manifest_count": len(manifests),
        "manifests": manifests,
    }

    # Write index
    out_path = Path(args.out)
    out_path.write_text(json.dumps(index, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    print(f"✅ Rebuilt {args.out} with {len(manifests)} manifests")


if __name__ == "__main__":
    main()
