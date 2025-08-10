from __future__ import annotations

from typing import Any

import httpx

from ..utils.idempotency import RetryConfig, retry_request

__all__ = [
    "GatewayClient",
    "register_tool",
    "register_resource",
    "register_prompt",
    "register_gateway",
]


class GatewayClient:
    """
    Minimal synchronous client for MCP Gateway (fallback path).

    This client talks directly to the admin endpoints when MatrixHubs
    "/catalog/install" is unavailable. It mirrors the idempotent behavior:
      • Retries transient errors with exponential backoff
      • Treats HTTP 409 (Conflict) as success for create operations

    Endpoints:
      POST /tools
      POST /resources
      POST /prompts
      POST /gateways
    """

    def __init__(self, base_url: str, *, token: str | None = None, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ---- internals ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.token:
            t = self.token.strip()
            h["Authorization"] = t if t.lower().startswith(("bearer ", "basic ")) else f"Bearer {t}"
        return h

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"

        def _do() -> tuple[int, dict[str, Any]]:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.post(url, headers=self._headers(), json=payload)
                try:
                    data = r.json()
                except Exception:
                    data = {"raw": r.text}
                return r.status_code, data

        return retry_request(_do, cfg=RetryConfig(attempts=3, base_delay=0.6, max_delay=4.0))

    # ---- public API --------------------------------------------------------

    def create_tool(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/tools", payload)

    def create_resource(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/resources", payload)

    def create_prompt(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/prompts", payload)

    def create_gateway(self, payload: dict[str, Any]) -> dict[str, Any]:
        # If caller provided an SSE base URL, keep it as-is (normalize earlier)
        return self._post("/gateways", payload)


# Convenience module-level helpers (tiny wrappers)


def register_tool(
    base_url: str, payload: dict[str, Any], *, token: str | None = None
) -> dict[str, Any]:
    return GatewayClient(base_url, token=token).create_tool(payload)


def register_resource(
    base_url: str, payload: dict[str, Any], *, token: str | None = None
) -> dict[str, Any]:
    return GatewayClient(base_url, token=token).create_resource(payload)


def register_prompt(
    base_url: str, payload: dict[str, Any], *, token: str | None = None
) -> dict[str, Any]:
    return GatewayClient(base_url, token=token).create_prompt(payload)


def register_gateway(
    base_url: str, payload: dict[str, Any], *, token: str | None = None
) -> dict[str, Any]:
    return GatewayClient(base_url, token=token).create_gateway(payload)
