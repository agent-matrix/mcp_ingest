#!/usr/bin/env python3
"""
Check that index.json is consistent with actual manifests in catalog.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Check index.json consistency")
    parser.add_argument("--catalog", required=True, help="Catalog directory")
    parser.add_argument("--index", required=True, help="Root index.json file")
    args = parser.parse_args()

    catalog = Path(args.catalog)
    index_path = Path(args.index)

    if not index_path.exists():
        print(f"❌ Index file not found: {index_path}", file=sys.stderr)
        sys.exit(1)

    # Load index
    try:
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
        indexed_paths = {m.get("path") for m in index_data.get("manifests", []) if m.get("path")}
    except Exception as e:
        print(f"❌ Cannot read index: {e}", file=sys.stderr)
        sys.exit(1)

    # Find all actual manifests
    actual_paths = set()
    for manifest_path in catalog.rglob("manifest.json"):
        rel_path = manifest_path.relative_to(catalog.parent).as_posix()
        actual_paths.add(rel_path)

    # Compare
    missing_from_index = actual_paths - indexed_paths
    missing_from_catalog = indexed_paths - actual_paths

    errors = 0

    if missing_from_index:
        print(
            f"❌ Manifests in catalog but not in index ({len(missing_from_index)}):",
            file=sys.stderr,
        )
        for path in sorted(missing_from_index):
            print(f"   - {path}", file=sys.stderr)
        errors += len(missing_from_index)

    if missing_from_catalog:
        print(
            f"❌ Manifests in index but not in catalog ({len(missing_from_catalog)}):",
            file=sys.stderr,
        )
        for path in sorted(missing_from_catalog):
            print(f"   - {path}", file=sys.stderr)
        errors += len(missing_from_catalog)

    if errors > 0:
        print(f"\n❌ Index inconsistency: {errors} issues found", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"✅ Index is consistent ({len(actual_paths)} manifests)")


if __name__ == "__main__":
    main()
