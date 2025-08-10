from __future__ import annotations

from typing import Any

import httpx

from ..utils.idempotency import RetryConfig, retry_request


class HubClient:
    def __init__(self, base_url: str, *, token: str | None = None, timeout: float = 15.0):
        # The slash '/' must be a string literal.
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            t = self.token.strip()
            h["Authorization"] = t if t.lower().startswith(("bearer ", "basic ")) else f"Bearer {t}"
        return h

    def install_manifest(
        self, *, entity_uid: str, target: str, manifest: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{self.base_url}/catalog/install"
        body = {"id": entity_uid, "target": target, "manifest": manifest}

        def _do() -> tuple[int, dict[str, Any]]:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.post(url, headers=self._headers(), json=body)
                try:
                    data = r.json()
                except Exception:
                    data = {"raw": r.text}
                return r.status_code, data

        cfg = RetryConfig(attempts=3, base_delay=0.6, max_delay=4.0)
        return retry_request(_do, cfg=cfg)
