from __future__ import annotations

import time
from typing import Any

# Optional deps: MCP client
try:  # pragma: no cover - optional
    import anyio
    from mcp.client.session import ClientSession  # type: ignore
    from mcp.client.sse import sse_client  # type: ignore
except Exception:  # pragma: no cover
    anyio = None  # type: ignore
    sse_client = None  # type: ignore
    ClientSession = None  # type: ignore

import httpx

__all__ = ["probe_mcp", "validate_server"]


async def _probe_async(
    url: str,
    *,
    tool: str | None = None,
    sample: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Async probe using MCP SSE client if available; falls back to HTTP preflight."""
    t0 = time.perf_counter()
    result: dict[str, Any] = {
        "url": url,
        "reachable": False,
        "handshake_ms": None,
        "list_tools_ms": None,
        "call_tool_ms": None,
        "tools": [],
        "tool_invoked": None,
        "response_excerpt": None,
        "error": None,
    }

    # If MCP client is missing, do a simple HTTP preflight
    if any(x is None for x in (anyio, sse_client, ClientSession)):
        try:
            with httpx.Client(timeout=timeout) as c:
                r = c.get(url)
                result["reachable"] = r.status_code < 400
        except Exception as e:  # pragma: no cover
            result["error"] = str(e)
        finally:
            result["handshake_ms"] = int((time.perf_counter() - t0) * 1000)
        return result

    # Full MCP handshake/ListTools/CallTool path
    try:
        async with anyio.move_on_after(timeout):
            t1 = time.perf_counter()
            async with sse_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result["reachable"] = True
                    result["handshake_ms"] = int((time.perf_counter() - t1) * 1000)

                    t2 = time.perf_counter()
                    tools = await session.list_tools()
                    names = [t.name for t in getattr(tools, "tools", [])] or []
                    result["tools"] = names
                    result["list_tools_ms"] = int((time.perf_counter() - t2) * 1000)

                    # Choose tool if not provided
                    chosen = tool or (names[0] if names else None)
                    if chosen:
                        t3 = time.perf_counter()
                        try:
                            resp = await session.call_tool(chosen, sample or {})
                            # Extract a short excerpt
                            content = getattr(resp, "content", None)
                            text = None
                            if content and len(content) and getattr(content[0], "text", None):
                                text = content[0].text
                            result["tool_invoked"] = chosen
                            if text:
                                result["response_excerpt"] = text[:300]
                            result["call_tool_ms"] = int((time.perf_counter() - t3) * 1000)
                        except Exception as e:
                            result["error"] = f"call_tool error: {e}"
    except Exception as e:  # pragma: no cover
        result["error"] = str(e)
    finally:
        # total wall clock if handshake_ms not set
        if result["handshake_ms"] is None:
            result["handshake_ms"] = int((time.perf_counter() - t0) * 1000)

    return result


def probe_mcp(
    url: str,
    *,
    tool: str | None = None,
    sample: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Public entry: perform an MCP probe (async-aware if available)."""
    if anyio is None:
        # fallback to sync path if anyio not available
        return http_preflight(url, timeout=timeout)

    return anyio.run(_probe_async, url, tool=tool, sample=sample, timeout=timeout)


# ---- simple HTTP preflight ----


def http_preflight(url: str, *, timeout: float = 3.0) -> dict[str, Any]:
    out = {"url": url, "reachable": False, "status": None, "error": None}
    try:
        with httpx.Client(timeout=timeout) as c:
            r = c.get(url)
            out["status"] = r.status_code
            out["reachable"] = r.status_code < 400
    except Exception as e:  # pragma: no cover
        out["error"] = str(e)
    return out


# Backward-compatible alias
validate_server = probe_mcp
