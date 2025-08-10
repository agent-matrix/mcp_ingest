from __future__ import annotations

import threading
import uuid
from queue import Queue
from typing import Any

JobPayload = dict[str, Any]


class HarvesterQueue:
    """Abstract queue API."""

    def enqueue(self, job: JobPayload) -> str:
        raise NotImplementedError

    def dequeue(self, timeout: float = 1.0) -> tuple[str, JobPayload]:
        raise NotImplementedError

    def ack(self, job_id: str) -> None:
        raise NotImplementedError

    def nack(self, job_id: str) -> None:
        raise NotImplementedError


class InMemoryQueue(HarvesterQueue):
    """Dev-only in-memory queue with visibility timeout semantics (simplified)."""

    def __init__(self) -> None:
        self.q: Queue[tuple[str, JobPayload]] = Queue()
        self.inflight: dict[str, JobPayload] = {}
        self.lock = threading.Lock()

    def enqueue(self, job: JobPayload) -> str:
        jid = job.get("id") or str(uuid.uuid4())
        job["id"] = jid
        self.q.put((jid, job))
        return jid

    def dequeue(self, timeout: float = 1.0) -> tuple[str, JobPayload]:
        jid, payload = self.q.get(timeout=timeout)
        with self.lock:
            self.inflight[jid] = payload
        return jid, payload

    def ack(self, job_id: str) -> None:
        with self.lock:
            self.inflight.pop(job_id, None)

    def nack(self, job_id: str) -> None:
        with self.lock:
            payload = self.inflight.pop(job_id, None)
        if payload:
            self.q.put((job_id, payload))
