from __future__ import annotations

from typing import Any, Literal

from ..utils.sse import ensure_sse, strip_trailing_slash

__all__ = ["build_manifest"]

REQUIRED_TOP = ("type", "id", "name", "version")
AllowedTransport = Literal["SSE", "STDIO", "WS"]


def build_manifest(
    *,
    server_name: str,
    # Transport & endpoint/exec
    transport: AllowedTransport = "SSE",
    server_url: str | None = None,
    exec_cmd: list[str] | None = None,
    exec_cwd: str | None = None,
    exec_env: dict[str, str] | None = None,
    # Tool & metadata
    tool_id: str | None = None,
    tool_name: str | None = None,
    tool_description: str = "",
    description: str = "",
    version: str = "0.1.0",
    entity_id: str | None = None,
    entity_name: str | None = None,
    resources: list[dict[str, Any]] | None = None,
    prompts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Construct a valid *mcp_server* manifest, with transport-aware server block.

    Changes vs MVP:
      • Supports server.transport in {"SSE", "STDIO", "WS"}.
      • If transport=="SSE", normalize `server_url` to `/sse`.
      • If transport=="STDIO", require an `exec` block (no URL).
      • If transport=="WS", keep URL as-is (do not force `/sse`).

    Raises:
      ValueError with clear, actionable messages when required fields are missing/invalid.
    """
    if not server_name:
        raise ValueError("server_name is required")

    transport = (transport or "SSE").upper()  # type: ignore[assignment]
    if transport not in {"SSE", "STDIO", "WS"}:
        raise ValueError("transport must be one of: 'SSE', 'STDIO', 'WS'")

    ent_id = entity_id or f"{server_name}-agent"
    ent_name = entity_name or server_name.replace("-", " ").title()

    # ---- Build the server block based on transport ----
    server_block: dict[str, Any] = {
        "name": server_name,
        "description": description,
        "transport": transport,
    }

    if transport == "SSE":
        if not server_url:
            raise ValueError("server_url is required for transport='SSE'")
        # strip trailing slash then ensure /sse
        norm = ensure_sse(strip_trailing_slash(server_url))
        server_block["url"] = norm
        # no exec for SSE
        if exec_cmd:
            raise ValueError("exec_cmd is not allowed when transport='SSE'")

    elif transport == "WS":
        if not server_url:
            raise ValueError("server_url is required for transport='WS'")
        server_block["url"] = strip_trailing_slash(server_url)
        if exec_cmd:
            raise ValueError("exec_cmd is not allowed when transport='WS'")

    elif transport == "STDIO":
        # For STDIO, URL is not required; exec is required
        if (
            not exec_cmd
            or not isinstance(exec_cmd, list)
            or not all(isinstance(x, str) and x for x in exec_cmd)
        ):
            raise ValueError(
                "transport='STDIO' requires exec_cmd: List[str], e.g. ['npx','-y','@modelcontextprotocol/server-filesystem']"
            )
        exec_block: dict[str, Any] = {"cmd": exec_cmd}
        if exec_cwd:
            exec_block["cwd"] = exec_cwd
        if exec_env:
            if not isinstance(exec_env, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in exec_env.items()
            ):
                raise ValueError("exec_env must be a dict[str,str] if provided")
            exec_block["env"] = exec_env
        server_block["exec"] = exec_block
        # Do not allow URL in STDIO to avoid ambiguity
        if server_url:
            raise ValueError("server_url must be omitted when transport='STDIO'")

    # ---- Optional tool block ----
    tool_block: dict[str, Any] | None = None
    if tool_id or tool_name:
        _tid = tool_id or (tool_name or "tool").replace(" ", "-").lower()
        _tname = tool_name or tool_id or "tool"
        tool_block = {
            "id": _tid,
            "name": _tname,
            "description": tool_description or "",
            "integration_type": "MCP",
        }

    res_list = list(resources or [])
    pr_list = list(prompts or [])

    # Associated IDs
    assoc_tools = [tool_block["id"]] if tool_block else []
    assoc_resources = [r.get("id", r.get("name")) for r in res_list if isinstance(r, dict)]
    assoc_prompts = [p.get("id") for p in pr_list if isinstance(p, dict) and p.get("id")]

    server_block.update(
        {
            "associated_tools": assoc_tools,
            "associated_resources": assoc_resources,
            "associated_prompts": assoc_prompts,
        }
    )

    manifest: dict[str, Any] = {
        "type": "mcp_server",
        "id": ent_id,
        "name": ent_name,
        "version": version,
        "description": description,
        "mcp_registration": {
            **({"tool": tool_block} if tool_block else {}),
            "resources": res_list,
            "prompts": pr_list,
            "server": server_block,
        },
    }

    _validate_manifest(manifest)
    return manifest


def _validate_manifest(manifest: dict[str, Any]) -> None:
    # Top-level required
    for k in REQUIRED_TOP:
        if not manifest.get(k):
            raise ValueError(f"manifest missing required field: {k}")

    mreg = manifest.get("mcp_registration")
    if not isinstance(mreg, dict):
        raise ValueError("manifest.mcp_registration must be an object")

    server = mreg.get("server")
    if not isinstance(server, dict):
        raise ValueError("manifest.mcp_registration.server must be an object")

    transport = server.get("transport")
    if transport not in {"SSE", "STDIO", "WS"}:
        raise ValueError("server.transport must be one of: 'SSE', 'STDIO', 'WS'")

    if transport in {"SSE", "WS"}:
        if not server.get("url"):
            raise ValueError(f"server.url is required when transport='{transport}'")
        if transport == "SSE" and not str(server["url"]).endswith("/sse"):
            # Guard that SSE normalization took place
            raise ValueError("server.url must end with '/sse' when transport='SSE'")
        if server.get("exec") is not None:
            raise ValueError(f"server.exec must be omitted when transport='{transport}'")

    if transport == "STDIO":
        exec_block = server.get("exec")
        if not isinstance(exec_block, dict):
            raise ValueError("server.exec is required and must be an object when transport='STDIO'")
        cmd = exec_block.get("cmd")
        if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) and x for x in cmd):
            raise ValueError("server.exec.cmd must be a non-empty list[str]")
        if server.get("url"):
            raise ValueError("server.url must be omitted when transport='STDIO'")
