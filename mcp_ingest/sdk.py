from __future__ import annotations

from pathlib import Path
from typing import Any

from .emit.manifest import build_manifest
from .register.hub_client import HubClient
from .utils.io import write_json

__all__ = ["describe", "autoinstall"]


def describe(
    *,
    name: str,
    url: str,
    tools: list[str] | None = None,
    resources: list[dict[str, Any]] | None = None,
    description: str = "",
    version: str = "0.1.0",
    entity_id: str | None = None,
    entity_name: str | None = None,
    out_dir: str | Path = ".",
) -> dict[str, str]:
    """Create manifest.json and index.json without running the server.
    Returns paths {manifest_path, index_path}.
    """
    tool_id = (tools or [None])[0]
    manifest = build_manifest(
        server_name=name,
        server_url=url,
        tool_id=tool_id,
        tool_name=tool_id,
        tool_description=description or "",
        description=description or "",
        version=version,
        entity_id=entity_id,
        entity_name=entity_name,
        resources=resources or [],
        prompts=[],
    )

    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "manifest.json"
    index_path = out / "index.json"

    write_json(manifest_path, manifest)
    write_json(index_path, {"manifests": ["./manifest.json"]})

    return {"manifest_path": str(manifest_path), "index_path": str(index_path)}


def autoinstall(
    *,
    matrixhub_url: str,
    manifest: dict[str, Any] | None = None,
    manifest_path: str | Path | None = None,
    entity_uid: str | None = None,
    target: str = "./",
    token: str | None = None,
) -> dict[str, Any]:
    """POST inline manifest to MatrixHub /catalog/install.
    If manifest is not supplied, read it from manifest_path (default ./manifest.json).
    """
    if manifest is None:
        mpath = Path(manifest_path or "./manifest.json").expanduser()
        import json

        manifest = json.loads(mpath.read_text(encoding="utf-8"))

    # compute uid if missing
    if not entity_uid:
        t = manifest.get("type", "mcp_server")
        i = manifest.get("id")
        v = manifest.get("version", "0.1.0")
        if not i:
            raise ValueError("manifest.id is required to compute entity_uid")
        entity_uid = f"{t}:{i}@{v}"

    client = HubClient(matrixhub_url, token=token)
    return client.install_manifest(entity_uid=entity_uid, target=target, manifest=manifest)
