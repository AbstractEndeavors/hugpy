from __future__ import annotations

import os
import shutil
import socket
from typing import Any

from .schemas import settings


def _disk(path: str) -> dict[str, int | None]:
    try:
        usage = shutil.disk_usage(path if os.path.exists(path) else "/")
        return {"total": usage.total, "used": usage.used, "free": usage.free}
    except OSError:
        return {"total": None, "used": None, "free": None}


def describe_self() -> dict[str, Any]:
    """Describe this node as a peer entry — the central registry/storage box."""
    hostname = socket.gethostname()
    role = os.environ.get("LLM_PEER_ROLE", "central")
    name = os.environ.get("LLM_PEER_NAME", hostname)

    return {
        "name": name,
        "host": hostname,
        "role": role,
        "storage_root": str(settings.storage_root),
        "manifest_path": str(settings.manifest_path),
        "storage_mounted": os.path.exists(settings.storage_root),
        "disk": _disk(settings.storage_root),
        "status": "online",
    }


def _worker_as_peer(worker: dict[str, Any]) -> dict[str, Any]:
    """Project a registered GPU worker into the peer shape PeersBar renders."""
    return {
        "name": worker.get("name") or worker.get("id"),
        "host": worker.get("url"),
        "role": worker.get("role", "worker"),
        "storage_root": worker.get("url", ""),
        "manifest_path": "",
        "storage_mounted": worker.get("status") == "online",
        "disk": None,
        "status": worker.get("status", "offline"),
        "gpus": worker.get("gpus") or [],
        "models": worker.get("models", []),
        "loaded_models": worker.get("loaded_models", []),
        "worker_id": worker.get("id"),
    }


def list_peers() -> list[dict[str, Any]]:
    # Central node first, then every GPU worker that has joined the pool.
    from .workers import list_workers

    peers = [describe_self()]
    peers.extend(_worker_as_peer(w) for w in list_workers())
    return peers

def execute(**kwargs):
    """Delegated module execution. Pure **kwargs so prune_inputs passes
    every field straight through — no positional reshaping of 'file'."""
    from abstract_hugpy.managers.dispatch import execute_prompt
    delegated = kwargs.pop("delegated", False)
    if delegated:
        kwargs["_force_local"] = True      # loop guard, consumed by resolve()
    result = execute_prompt(**kwargs)
    return result.model_dump() if hasattr(result, "model_dump") else result
