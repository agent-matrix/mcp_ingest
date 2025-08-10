from __future__ import annotations

from typing import Any


def score_entry(
    *,
    repo_metrics: dict[str, Any] | None,
    detect_report: dict[str, Any] | None,
    validation: dict[str, Any] | None,
) -> float:
    """Heuristic score in [0,1]: stars/recency/license + detector confidence + validation."""
    score = 0.0
    if detect_report:
        score += min(0.6, float(detect_report.get("confidence") or 0.0))
        if detect_report.get("tools") or []:
            score += 0.1
    if validation and validation.get("reachable"):
        score += 0.2
        if validation.get("tools"):
            score += 0.05
    if repo_metrics:
        stars = float(repo_metrics.get("stars", 0))
        score += min(0.05, stars / 100000.0)  # 100k stars -> +0.05
        if repo_metrics.get("license"):
            score += 0.02
        if repo_metrics.get("recent"):
            score += 0.03
    return max(0.0, min(1.0, score))
