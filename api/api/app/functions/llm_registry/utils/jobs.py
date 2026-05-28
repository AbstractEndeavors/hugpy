from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


JobStatus = Literal["queued", "running", "completed", "failed"]


@dataclass
class Job:
    id: str
    model_key: str
    status: JobStatus = "queued"
    message: str = ""
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "model_key": self.model_key,
            "status": self.status,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, model_key: str) -> Job:
        job = Job(id=str(uuid.uuid4()), model_key=model_key)

        with self._lock:
            self._jobs[job.id] = job

        return job

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> Job:
        with self._lock:
            job = self._jobs[job_id]

            if status is not None:
                job.status = status

            if message is not None:
                job.message = message

            if error is not None:
                job.error = error

            job.updated_at = datetime.now(timezone.utc).isoformat()
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())


job_store = JobStore()
