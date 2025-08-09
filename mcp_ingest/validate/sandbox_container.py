
from __future__ import annotations
import json, os, re, shlex, subprocess, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Optional: reuse MVP probe when network is allowed
try:  # pragma: no cover (optional at runtime)
    from ..validate.mcp_probe import probe_mcp as _probe_mcp  # type: ignore
except Exception:  # pragma: no cover
    _probe_mcp = None  # type: ignore

__all__ = [
    "ValidationReport",
    "run_in_container",
    "discover_endpoint",
]


@dataclass
class ValidationReport:
    image: str
    success: bool
    exit_code: Optional[int]
    timed_out: bool
    reachable: bool
    endpoint_url: Optional[str]
    transport: Optional[str]
    port: Optional[int]
    tools_confirmed: List[str]
    timings_ms: Dict[str, int]
    logs_excerpt: str
    error: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Ensure JSON-serializable values
        d["tools_confirmed"] = list(self.tools_confirmed)
        d["timings_ms"] = {str(k): int(v) for k, v in (self.timings_ms or {}).items()}
        return d


_ENDPOINT_RE = re.compile(r"(?i)(http://[\w\.-]+:(\d+)/(sse|messages))")
_PORT_RE = re.compile(r"(?i)(?:PORT\s*=\s*(\d{3,5})|port\s*[:=]\s*(\d{3,5}))")


def discover_endpoint(logs: str, *, default_port: int = 6288) -> Dict[str, Any]:
    """Heuristic endpoint discovery from container logs.
    Returns dict: {url, transport, port}
    """
    url = None
    transport = None
    port = None

    m = _ENDPOINT_RE.search(logs)
    if m:
        url = m.group(1)
        port = int(m.group(2)) if m.group(2) else None
        transport = "SSE" if m.group(3).lower() == "sse" else "WS"
    else:
        # Try to guess a port even if URL not found
        pm = _PORT_RE.search(logs)
        if pm:
            for g in pm.groups():
                if g and g.isdigit():
                    port = int(g)
                    break
        if port is None:
            port = default_port
        # Prefer /sse unless messages explicitly mentioned
        transport = "SSE" if "messages" not in logs.lower() else "WS"
        url = f"http://127.0.0.1:{port}/sse" if transport == "SSE" else f"http://127.0.0.1:{port}/messages"

    return {"url": url, "transport": transport, "port": port}


def _docker(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def run_in_container(
    image: str,
    cmd: List[str] | None,
    *,
    cpu: int = 1,
    mem_mb: int = 512,
    timeout: int = 90,
    allow_net: bool = False,
    guess_port: int = 6288,
) -> ValidationReport:
    """Run an MCP server image with limits, try to discover endpoint, and (optionally) probe it.

    If allow_net=False, we still publish the guessed port to localhost for probing,
    but the container will otherwise use default bridge network (egress limiting is out-of-scope for MVP).
    Set allow_net=True to keep default networking. In a future revision we can add more granular egress control.
    """
    t0 = time.perf_counter()
    timings: Dict[str, int] = {}
    logs_excerpt = ""
    endpoint_url: Optional[str] = None
    transport: Optional[str] = None
    port: Optional[int] = None
    reachable = False
    error: Optional[str] = None
    exit_code: Optional[int] = None
    tools = []

    # 1) Pull (best-effort)
    try:
        _docker("pull", image, timeout=max(60, timeout // 2))
    except Exception:
        pass

    # 2) Run container (detached)
    name = f"mcp-validate-{int(time.time())}"
    publish = ["-p", f"{guess_port}:{guess_port}"]
    network = []  # bridge by default (needed to map ports)
    limits = ["--cpus", str(cpu), "--memory", f"{mem_mb}m"]
    envs: List[str] = ["-e", f"PORT={guess_port}"]

    run_cmd = [
        "run", "-d", "--rm", "--name", name,
        *publish,
        *limits,
        *network,
        *envs,
        image,
        *(cmd or []),
    ]

    try:
        started = _docker(*run_cmd, timeout=timeout)
        if started.returncode != 0:
            raise RuntimeError(f"docker run failed: {started.stderr.strip()}")

        # 3) Wait a short period for logs to populate
        time.sleep(2.0)

        # 4) Fetch logs & discover endpoint
        logs = _docker("logs", name, timeout=timeout)
        combined = (logs.stdout or "") + "\n" + (logs.stderr or "")
        logs_excerpt = combined[-4000:]  # last chunk
        disc = discover_endpoint(combined, default_port=guess_port)
        endpoint_url, transport, port = disc["url"], disc["transport"], disc["port"]
        timings["container_start_ms"] = int((time.perf_counter() - t0) * 1000)

        # 5) Optional probe (requires network and host mapping)
        if endpoint_url and _probe_mcp is not None:
            t1 = time.perf_counter()
            try:
                # Light probe: handshake/ListTools/CallTool
                probe = _probe_mcp(endpoint_url, timeout=min(5.0, max(3.0, timeout - 2)))
                reachable = bool(probe.get("reachable"))
                tools = list(probe.get("tools") or [])
                timings["probe_ms"] = int((time.perf_counter() - t1) * 1000)
            except Exception as pe:  # pragma: no cover
                error = f"probe error: {pe}"
                tools = []
        else:
            tools = []

        # 6) Try graceful stop, then kill if needed at timeout
        t2 = time.perf_counter()
        _docker("stop", name, timeout=max(10, timeout // 3))
        timings["container_stop_ms"] = int((time.perf_counter() - t2) * 1000)
        exit_code = 0

    except subprocess.TimeoutExpired as te:
        error = f"timeout: {te}"
        try:
            _docker("kill", name, timeout=10)
        except Exception:
            pass
        exit_code = None
        return ValidationReport(
            image=image,
            success=False,
            exit_code=exit_code,
            timed_out=True,
            reachable=reachable,
            endpoint_url=endpoint_url,
            transport=transport,
            port=port,
            tools_confirmed=tools,
            timings_ms=timings,
            logs_excerpt=logs_excerpt,
            error=error,
        )
    except Exception as e:
        error = str(e)
        try:
            _docker("kill", name, timeout=10)
        except Exception:
            pass
        exit_code = None
        return ValidationReport(
            image=image,
            success=False,
            exit_code=exit_code,
            timed_out=False,
            reachable=reachable,
            endpoint_url=endpoint_url,
            transport=transport,
            port=port,
            tools_confirmed=tools,
            timings_ms=timings,
            logs_excerpt=logs_excerpt,
            error=error,
        )

    # Success path summary
    return ValidationReport(
        image=image,
        success=True,
        exit_code=exit_code,
        timed_out=False,
        reachable=reachable,
        endpoint_url=endpoint_url,
        transport=transport,
        port=port,
        tools_confirmed=tools,
        timings_ms=timings,
        logs_excerpt=logs_excerpt,
        error=None,
    )

