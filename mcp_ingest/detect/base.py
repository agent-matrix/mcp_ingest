from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DetectReport:
    tools: list[dict[str, Any]] = field(default_factory=list)
    resources: list[dict[str, Any]] = field(default_factory=list)
    prompts: list[dict[str, Any]] = field(default_factory=list)
    server_url: str | None = None
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tools": self.tools,
            "resources": self.resources,
            "prompts": self.prompts,
            "server_url": self.server_url,
            "confidence": self.confidence,
            "notes": self.notes,
        }

    def suggest_name(self, default: str = "mcp-server") -> str:
        # prefer a tool name if present, fallback to default
        if self.tools:
            t = (self.tools[0].get("name") or self.tools[0].get("id") or "").strip()
            if t:
                return t
        return default

    def summarize_description(self) -> str:
        if self.notes:
            return "; ".join(self.notes[:3])
        return ""


class Detector:
    def detect(self, source: str) -> DetectReport:  # pragma: no cover - interface
        raise NotImplementedError


def merge_reports(*reports: DetectReport) -> DetectReport:
    out = DetectReport()
    for r in reports:
        out.tools.extend([t for t in r.tools if t not in out.tools])
        out.resources.extend([x for x in r.resources if x not in out.resources])
        out.prompts.extend([p for p in r.prompts if p not in out.prompts])
        out.notes.extend([n for n in r.notes if n not in out.notes])
        # pick first non-empty server_url
        if not out.server_url and r.server_url:
            out.server_url = r.server_url
        out.confidence = max(out.confidence, r.confidence)
    return out
