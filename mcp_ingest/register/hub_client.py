
from __future__ import annotations
from typing import Any, Dict, Tuple
import httpx
from ..utils.idempotency import retry_request, RetryConfig

class HubClient:
    def __init__(self, base_url: str, *, token: str | None = None, timeout: float = 15.0):
        self.base_url = base_url.rstrip(/)
        self.token = token
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            t = self.token.strip()
            h["Authorization"] = t if t.lower().startswith(("bearer ", "basic ")) else f"Bearer {t}"
        return h

    def install_manifest(self, *, entity_uid: str, target: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/catalog/install"
        body = {"id": entity_uid, "target": target, "manifest": manifest}

        def _do() -> Tuple[int, Dict[str, Any]]:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.post(url, headers=self._headers(), json=body)
                try:
                    data = r.json()
                except Exception:
                    data = {"raw": r.text}
                return r.status_code, data

        cfg = RetryConfig(attempts=3, base_delay=0.6, max_delay=4.0)
        return retry_request(_do, cfg=cfg)

