
from __future__ import annotations
from typing import Any, Dict, List, Optional
from ..utils.sse import ensure_sse

REQUIRED_TOP = ("type", "id", "name", "version")


def build_manifest(
    *,
    server_name: str,
    server_url: str,
    tool_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    tool_description: str = "",
    description: str = "",
    version: str = "0.1.0",
    entity_id: Optional[str] = None,
    entity_name: Optional[str] = None,
    resources: Optional[List[Dict[str, Any]]] = None,
    prompts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Construct a minimal mcp_server manifest with SSE normalized.
    Raises ValueError on missing/invalid inputs.
    """
    if not server_name or not server_url:
        raise ValueError("server_name and server_url are required")

    ent_id = entity_id or f"{server_name}-agent"
    ent_name = entity_name or server_name.replace("-", " ").title()

    sse_url = ensure_sse(server_url)

    # tool block is optional, but if provided ensure id/name
    tool_block: Dict[str, Any] | None = None
    if tool_id or tool_name:
        tool_block = {
            "id": tool_id or (tool_name or "tool").replace(" ", "-").lower(),
            "name": tool_name or tool_id or "tool",
            "description": tool_description or "",
            "integration_type": "MCP",
        }

    res_list = list(resources or [])
    pr_list = list(prompts or [])

    manifest: Dict[str, Any] = {
        "type": "mcp_server",
        "id": ent_id,
        "name": ent_name,
        "version": version,
        "description": description,
        "mcp_registration": {
            **({"tool": tool_block} if tool_block else {}),
            "resources": res_list,
            "prompts": pr_list,
            "server": {
                "name": server_name,
                "description": description,
                "url": sse_url,
                "associated_tools": [tool_block["id"]] if tool_block else [],
                "associated_resources": [r.get("id", r.get("name")) for r in res_list if isinstance(r, dict)],
                "associated_prompts": [p.get("id") for p in pr_list if isinstance(p, dict) and p.get("id")],
            },
        },
    }

    _validate_manifest(manifest)
    return manifest


def _validate_manifest(manifest: Dict[str, Any]) -> None:
    for k in REQUIRED_TOP:
        if not manifest.get(k):
            raise ValueError(f"manifest missing required field: {k}")
    mreg = manifest.get("mcp_registration")
    if not isinstance(mreg, dict):
        raise ValueError("manifest.mcp_registration must be a dict")
    server = mreg.get("server")
    if not isinstance(server, dict) or not server.get("url"):
        raise ValueError("manifest.mcp_registration.server.url is required")

