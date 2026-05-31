"""GPU worker registry.

A *worker* is a remote box that runs the standalone worker agent
(``abstract_hugpy.worker_agent``), exposes an HTTP inference endpoint, and
joins this central node so its GPU(s) can serve one or more models from the
manifest.

This module is the single source of truth for the pool. It owns:

    - persistence of the worker list to a JSON file beside the model manifest
      (so the pool survives restarts),
    - registration / heartbeat / removal,
    - model assignment (which worker may serve which model_key),
    - liveness (a worker is ``online`` only if it has heartbeat-ed recently),
    - selection (pick an online worker that is assigned + ready for a model).

Routing (chat/streaming) and the ``/llm/workers`` routes are dumb consumers of
the functions exported here.
"""
from __future__ import annotations

import os
import json
import time
import uuid
import threading
from typing import Any, Dict, List, Optional

from .schemas import settings


def _default_workers_path() -> str:
    """Sit the worker registry next to the model manifest (…/projects/)."""
    return os.path.join(os.path.dirname(settings.manifest_path), "workers.json")


# A worker that hasn't checked in within this window is considered offline.
HEARTBEAT_TIMEOUT_SECONDS = 45.0


def _now() -> float:
    return time.time()


def _is_online(worker: Dict[str, Any]) -> bool:
    last = worker.get("last_seen") or 0
    return (_now() - last) <= HEARTBEAT_TIMEOUT_SECONDS


def _public_view(worker: Dict[str, Any]) -> Dict[str, Any]:
    """The shape returned to API callers — derived ``status`` included."""
    return {**worker, "status": "online" if _is_online(worker) else "offline"}


class WorkerStore:
    """Thread-safe, file-backed registry of GPU workers."""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or _default_workers_path()
        self._lock = threading.RLock()
        self._workers: Dict[str, Dict[str, Any]] = {}
        self._load()

    # -- persistence --------------------------------------------------------
    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    self._workers = {w["id"]: w for w in data.get("workers", []) if w.get("id")}
        except (OSError, ValueError, KeyError):
            # A corrupt registry should never take the API down; start empty.
            self._workers = {}

    def _save(self) -> None:
        try:
            parent = os.path.dirname(self._path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = f"{self._path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"workers": list(self._workers.values())}, fh, indent=2)
            os.replace(tmp, self._path)
        except OSError:
            # Persistence is best-effort; the in-memory pool keeps working.
            pass

    # -- registration / lifecycle ------------------------------------------
    def register(
        self,
        *,
        name: str,
        url: str,
        gpus: Optional[List[Dict[str, Any]]] = None,
        role: str = "worker",
        models: Optional[List[str]] = None,
        worker_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a worker (or re-register an existing one by id/url).

        Re-registration is keyed first on the supplied ``worker_id``, then on
        ``url`` — so an agent that restarts and advertises the same URL keeps
        its assignments instead of creating a duplicate row.
        """
        url = (url or "").rstrip("/")
        with self._lock:
            existing = None
            if worker_id and worker_id in self._workers:
                existing = self._workers[worker_id]
            else:
                for w in self._workers.values():
                    if w.get("url") == url:
                        existing = w
                        break

            if existing is not None:
                existing.update(
                    name=name or existing.get("name"),
                    url=url or existing.get("url"),
                    gpus=gpus if gpus is not None else existing.get("gpus", []),
                    role=role or existing.get("role", "worker"),
                    last_seen=_now(),
                )
                if models is not None:
                    existing["models"] = sorted(set(models))
                self._save()
                return _public_view(existing)

            wid = worker_id or uuid.uuid4().hex
            worker = {
                "id": wid,
                "name": name or wid,
                "url": url,
                "role": role or "worker",
                "gpus": gpus or [],
                "models": sorted(set(models or [])),
                "created_at": _now(),
                "last_seen": _now(),
            }
            self._workers[wid] = worker
            self._save()
            return _public_view(worker)

    def heartbeat(
        self,
        worker_id: str,
        *,
        gpus: Optional[List[Dict[str, Any]]] = None,
        loaded_models: Optional[List[str]] = None,
        spill: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark a worker alive and refresh its live GPU / loaded-model stats."""
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is None:
                return None
            worker["last_seen"] = _now()
            if gpus is not None:
                worker["gpus"] = gpus
            if loaded_models is not None:
                worker["loaded_models"] = loaded_models
            if spill is not None:
                worker["spill"] = spill
            self._save()
            return _public_view(worker)

    def remove(self, worker_id: str) -> bool:
        with self._lock:
            existed = self._workers.pop(worker_id, None) is not None
            if existed:
                self._save()
            return existed

    # -- model assignment ---------------------------------------------------
    def assign_model(
        self,
        worker_id: str,
        model_key: str,
        spill: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Assign a model to a worker, with optional per-assignment spill config.

        ``spill`` is an opaque dict of GPU/CPU knobs (e.g. n_gpu_layers,
        gpu_mem_gib, cpu_mem_gib) the worker applies when it loads the model.
        Omitted / None means "use the worker's autofit default."
        """
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is None:
                return None
            models = set(worker.get("models", []))
            models.add(model_key)
            worker["models"] = sorted(models)
            if spill is not None:
                by_model = worker.setdefault("spill_by_model", {})
                # An empty dict clears any override back to autofit.
                if spill:
                    by_model[model_key] = spill
                else:
                    by_model.pop(model_key, None)
            self._save()
            return _public_view(worker)

    def unassign_model(self, worker_id: str, model_key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is None:
                return None
            worker["models"] = sorted(set(worker.get("models", [])) - {model_key})
            worker.get("spill_by_model", {}).pop(model_key, None)
            self._save()
            return _public_view(worker)

    def spill_for(self, worker_id: str, model_key: str) -> Dict[str, Any]:
        """Per-assignment spill override for (worker, model), or {} for autofit."""
        with self._lock:
            worker = self._workers.get(worker_id)
            if worker is None:
                return {}
            return dict(worker.get("spill_by_model", {}).get(model_key, {}))

    # -- queries ------------------------------------------------------------
    def get(self, worker_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            worker = self._workers.get(worker_id)
            return _public_view(worker) if worker else None

    def all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [_public_view(w) for w in self._workers.values()]

    def workers_for_model(self, model_key: str, *, online_only: bool = True) -> List[Dict[str, Any]]:
        out = []
        for w in self.all():
            if model_key not in w.get("models", []):
                continue
            if online_only and w["status"] != "online":
                continue
            out.append(w)
        return out

    def pick_for_model(self, model_key: str) -> Optional[Dict[str, Any]]:
        """Choose an online worker to serve ``model_key``.

        Preference order:
            1. workers that already report the model as loaded (warm),
            2. otherwise the least-recently-picked online assignee.

        Returns ``None`` when no online worker is assigned to the model, which
        signals the caller to fall back to local execution.
        """
        candidates = self.workers_for_model(model_key, online_only=True)
        if not candidates:
            return None

        warm = [w for w in candidates if model_key in (w.get("loaded_models") or [])]
        pool = warm or candidates
        # Spread load: prefer the assignee touched longest ago.
        pool.sort(key=lambda w: w.get("last_picked", 0))
        chosen = pool[0]

        with self._lock:
            stored = self._workers.get(chosen["id"])
            if stored is not None:
                stored["last_picked"] = _now()
        return chosen


worker_store = WorkerStore()


# Module-level convenience wrappers (mirrors the manifest.py / peers.py style of
# exposing plain functions for routes to import).
def register_worker(**kwargs) -> Dict[str, Any]:
    return worker_store.register(**kwargs)


def heartbeat_worker(worker_id: str, **kwargs) -> Optional[Dict[str, Any]]:
    # kwargs: gpus, loaded_models, spill — all optional, passed straight through.
    return worker_store.heartbeat(worker_id, **kwargs)


def remove_worker(worker_id: str) -> bool:
    return worker_store.remove(worker_id)


def assign_model(worker_id: str, model_key: str,
                 spill: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    return worker_store.assign_model(worker_id, model_key, spill=spill)


def unassign_model(worker_id: str, model_key: str) -> Optional[Dict[str, Any]]:
    return worker_store.unassign_model(worker_id, model_key)


def spill_for(worker_id: str, model_key: str) -> Dict[str, Any]:
    return worker_store.spill_for(worker_id, model_key)


def list_workers() -> List[Dict[str, Any]]:
    return worker_store.all()


def get_worker(worker_id: str) -> Optional[Dict[str, Any]]:
    return worker_store.get(worker_id)


def pick_worker_for_model(model_key: str) -> Optional[Dict[str, Any]]:
    return worker_store.pick_for_model(model_key)
