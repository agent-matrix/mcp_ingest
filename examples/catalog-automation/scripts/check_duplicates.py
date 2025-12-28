#!/usr/bin/env python3
"""
Check for duplicate manifest IDs in the catalog.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Check for duplicate manifest IDs")
    parser.add_argument("--catalog", required=True, help="Catalog directory")
    args = parser.parse_args()

    catalog = Path(args.catalog)

    # Collect all IDs
    ids_to_paths: dict[str, list[Path]] = {}

    for manifest_path in catalog.rglob("manifest.json"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_id = data.get("id")

            if not manifest_id:
                print(f"⚠️  Manifest without ID: {manifest_path}", file=sys.stderr)
                continue

            if manifest_id not in ids_to_paths:
                ids_to_paths[manifest_id] = []
            ids_to_paths[manifest_id].append(manifest_path)

        except Exception as e:
            print(f"⚠️  Cannot read {manifest_path}: {e}", file=sys.stderr)
            continue

    # Find duplicates
    duplicates = {id_: paths for id_, paths in ids_to_paths.items() if len(paths) > 1}

    if duplicates:
        print(f"❌ Found {len(duplicates)} duplicate IDs:", file=sys.stderr)
        for id_, paths in duplicates.items():
            print(f"\n  ID: {id_}", file=sys.stderr)
            for path in paths:
                print(f"    - {path}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"✅ No duplicate IDs found ({len(ids_to_paths)} unique manifests)")


if __name__ == "__main__":
    main()
