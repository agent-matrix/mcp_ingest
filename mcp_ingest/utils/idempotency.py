from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class RetryConfig:
    def __init__(self, *, attempts: int = 3, base_delay: float = 0.5, max_delay: float = 5.0):
        self.attempts = max(1, attempts)
        self.base_delay = base_delay
        self.max_delay = max_delay


def is_transient(status: int | None, exc: Exception | None) -> bool:
    if status is None:
        return True
    if 500 <= status <= 599:
        return True
    return False


def backoff_sleep(attempt: int, cfg: RetryConfig) -> None:
    delay = min(cfg.base_delay * (2 ** (attempt - 1)), cfg.max_delay)
    time.sleep(delay)


class HTTPError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: object | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


# simple decorator-free retry helper
def retry_request(func: Callable[[], tuple[int, T]], *, cfg: RetryConfig) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, cfg.attempts + 1):
        try:
            status, value = func()
            if status == 409:
                # treat conflict as success for idempotent ops
                return value
            if 200 <= status < 300:
                return value
            # non-2xx
            if is_transient(status, None) and attempt < cfg.attempts:
                backoff_sleep(attempt, cfg)
                continue
            raise HTTPError(f"request failed ({status})", status=status, body=value)
        except Exception as e:
            last_exc = e
            if attempt < cfg.attempts and is_transient(None, e):
                backoff_sleep(attempt, cfg)
                continue
            raise
    # should not reach
    # FIX: Replaced `assert False` with `raise AssertionError` for safety.
    raise AssertionError(f"Retry loop finished unexpectedly. Last exception: {last_exc}")
