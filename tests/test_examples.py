from __future__ import annotations

"""Basic smoke tests for mcp-ingest.

These tests are intentionally lightweight and offline:
- They exercise the SDK `describe(...)` using the bundled example server.
- They exercise the repo harvester against the local examples/watsonx folder.

Run with: pytest -q
"""

import json
from pathlib import Path

from mcp_ingest.harvest.repo import harvest_repo
from mcp_ingest.sdk import describe as sdk_describe


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_sdk_describe_generates_manifest_and_index(tmp_path: Path) -> None:
    """SDK describe should produce manifest.json and index.json for the example server."""
    root = _repo_root()
    example = root / "examples" / "watsonx"
    assert example.exists(), f"Example folder missing: {example}"
    server_py = example / "server.py"
    assert server_py.exists(), f"Example server missing: {server_py}"

    out_dir = tmp_path / "describe_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    res = sdk_describe(
        name="watsonx-mcp",
        url="http://127.0.0.1:6288/sse",  # normalized SSE endpoint
        tools=["chat"],
        resources=[{"uri": f"file://{server_py}", "name": "source"}],
        description="Watsonx SSE server (example)",
        version="0.1.0",
        out_dir=out_dir,
    )

    manifest_path = Path(res["manifest_path"]).resolve()
    index_path = Path(res["index_path"]).resolve()

    assert manifest_path.exists(), "manifest.json was not created"
    assert index_path.exists(), "index.json was not created"

    doc = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert doc.get("type") == "mcp_server"
    server = (doc.get("mcp_registration") or {}).get("server") or {}
    url = server.get("url", "")
    assert url.endswith("/sse"), "SSE URL should be normalized to /sse"


def test_harvest_repo_on_examples(tmp_path: Path) -> None:
    """Harvesting the example folder should yield at least one manifest and a repo index."""
    root = _repo_root()
    example = root / "examples" / "watsonx"
    assert example.exists(), f"Example folder missing: {example}"

    out_dir = tmp_path / "harvest_out"
    result = harvest_repo(str(example), out_dir=out_dir)

    # Expect at least one manifest and a repo-level index.json
    assert result.manifests, f"No manifests produced: errors={result.errors}"
    assert (result.index_path).exists(), "Repo-level index.json not found"

    # Ensure index contains references to the produced manifests
    index_doc = json.loads(result.index_path.read_text(encoding="utf-8"))
    manifests_in_index = index_doc.get("manifests") or []
    assert isinstance(manifests_in_index, list)
    # Convert to absolute paths for comparison (repo index is usually relative)
    abs_in_index = {str((out_dir / Path(p)).resolve()) for p in manifests_in_index}
    abs_produced = {str(p.resolve()) for p in result.manifests}
    assert abs_produced.issubset(abs_in_index), "Index should list all produced manifests"
