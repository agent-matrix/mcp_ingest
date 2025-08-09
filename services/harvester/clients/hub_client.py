from __future__ import annotations
from typing import Any, Dict, Tuple, Optional
import httpx
import time

class HubClient:
    """Minimal client for MatrixHub /catalog/install (idempotent; retries)."""
    def __init__(self, base_url: str, *, token: Optional[str] = None, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
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
        attempts = 3
        for i in range(1, attempts + 1):
            try:
                with httpx.Client(timeout=self.timeout) as c:
                    r = c.post(url, headers=self._headers(), json=body)
                    data = r.json() if r.headers.get("content-type","").startswith("application/json") else {"raw": r.text}
                    if r.status_code in (200, 201, 202, 409):
                        return data
                    if 500 <= r.status_code <= 599 and i < attempts:
                        time.sleep(min(0.5 * (2 ** (i - 1)), 4.0))
                        continue
                    raise RuntimeError(f"hub install failed: {r.status_code} {data}")
            except Exception as e:
                if i == attempts:
                    raise
                time.sleep(min(0.5 * (2 ** (i - 1)), 4.0))
        raise RuntimeError("unreachable")
