from __future__ import annotations

import re
from pathlib import Path

from .base import DetectReport

__all__ = ["detect_path"]


_SSE_HINTS = ("/sse", 'transport="sse"', "transport=sse")
_MSG_HINTS = ("/messages", 'transport="sse" and /messages')
_PORT_HINTS = re.compile(r"(?i)(PORT\s*=\s*(\d{3,5}))|(host=\"127\.0\.0\.1\",\s*port=(\d{3,5}))")


def _candidate_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix == ".py" else []
    names = {"server.py", "app.py", "main.py"}
    out: list[Path] = []
    for p in root.rglob("*.py"):
        if p.name in names or "/server/" in str(p.as_posix()):
            out.append(p)
    return out


def detect_path(source: str) -> DetectReport:
    """
    Fallback detector for generic MCP servers when no framework is recognized.

    Heuristics:
      • Look for server-like files (server.py/app.py/main.py)
      • Grep for SSE or /messages hints to choose route
      • Guess port from common patterns, else default to 6288
      • Emit a low-confidence report with a resource pointer
    """
    root = Path(source).expanduser().resolve()
    report = DetectReport(confidence=0.15)

    files = _candidate_files(root)
    if not files:
        return report

    # prefer exact server.py if present
    files.sort(key=lambda p: (p.name != "server.py", len(str(p))))

    chosen = files[0]
    try:
        text = chosen.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = ""

    # route
    route = "/sse"
    if any(h in text for h in _MSG_HINTS) and "/sse" not in text:
        route = "/messages"

    # port
    port = 6288
    m = _PORT_HINTS.search(text)
    if m:
        # pick the last captured group that is a digit
        for g in m.groups()[::-1]:
            if g and g.isdigit():
                port = int(g)
                break
    elif "http.server" in text:
        port = 8000

    # server_url guess
    report.server_url = f"http://127.0.0.1:{port}{route}"

    # resource pointer
    report.resources.append(
        {
            "id": f"{chosen.stem}-source",
            "name": "server source",
            "type": "inline",
            "uri": f"file://{chosen.name}",
        }
    )

    report.notes.append(f"heuristic route={route}; port={port}; file={chosen.name}")
    report.confidence = max(report.confidence, 0.3)
    return report
