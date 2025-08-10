from __future__ import annotations

from pathlib import Path

from ..utils.io import write_json

__all__ = ["write_server_adapter", "write_tool_adapter"]


def write_server_adapter(
    out_dir: str | Path,
    *,
    name: str,
    url: str,
    description: str = "",
    filename: str | None = None,
) -> Path:
    """
    Emit a minimal MatrixHub server adapter stub (pure data file).

    Shape (MVP, subject to change):
      {
        "type": "server_adapter",
        "name": "watsonx-mcp",
        "description": "...",
        "url": "http://127.0.0.1:6288/sse"
      }
    """
    p = Path(out_dir).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    fname = filename or f"{name}-server.adapter.json"
    out = p / fname
    payload: dict[str, object] = {
        "type": "server_adapter",
        "name": name,
        "description": description,
        "url": url,
    }
    write_json(out, payload)  # writes with indentation and stable ordering
    return out


def write_tool_adapter(
    out_dir: str | Path,
    *,
    name: str,
    tool_id: str,
    server_url: str,
    description: str = "",
    filename: str | None = None,
) -> Path:
    """
    Emit a minimal MatrixHub tool adapter stub that points to a gateway/server URL.

    Shape:
      {
        "type": "tool_adapter",
        "name": "watsonx-chat",
        "description": "...",
        "tool_id": "watsonx-chat",
        "server_url": "http://127.0.0.1:6288/sse"
      }
    """
    p = Path(out_dir).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    fname = filename or f"{name}-tool.adapter.json"
    out = p / fname
    payload: dict[str, object] = {
        "type": "tool_adapter",
        "name": name,
        "description": description,
        "tool_id": tool_id,
        "server_url": server_url,
    }
    write_json(out, payload)
    return out
