"""Shared shard queue — a small, persistent prompt queue for the GPU pool.

The console gets a SharedQueuePanel (behind the same login as everything
else) where any signed-in user drops prompts into one shared queue. A
single dispatcher thread feeds them, one at a time, to the deployment's
OpenAI-compatible chat endpoint — so the allocator / shard pool decides
where each job actually runs, exactly as if the prompt had come from the
chat panel or /v1.

Routes (nginx maps /api/* onto this app, matching the other blueprints):

    GET    /shard-queue              newest-first job list (last 100)
    POST   /shard-queue              {"prompt": ..., "model"?: ..., "user"?: ...}
    POST   /shard-queue/<id>/cancel  cancel a still-queued job
    DELETE /shard-queue/<id>         remove a finished job

State is one JSON file (SHARD_QUEUE_STATE, default ~/.hugpy/shard-queue.json)
so the queue survives restarts; jobs caught mid-flight on shutdown are
re-queued on boot. The dispatcher posts to SHARD_QUEUE_V1_URL (default
http://127.0.0.1:7002/v1/chat/completions) — point it wherever this
deployment serves /v1.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

import httpx
from flask import jsonify, request

from ..functions import *

shard_queue_bp, logger = get_bp("shard_queue_bp", __name__)

_STATE_PATH = os.environ.get(
    "SHARD_QUEUE_STATE",
    os.path.join(os.path.expanduser("~"), ".hugpy", "shard-queue.json"))
_V1_URL = os.environ.get(
    "SHARD_QUEUE_V1_URL", "http://127.0.0.1:7002/v1/chat/completions")
_JOB_TIMEOUT_S = float(os.environ.get("SHARD_QUEUE_JOB_TIMEOUT", "600"))

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_loaded = False
_dispatcher_started = False


def _save() -> None:
    parent = os.path.dirname(_STATE_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{_STATE_PATH}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"jobs": _JOBS}, f, indent=1)
    os.replace(tmp, _STATE_PATH)


def _ensure_loaded() -> None:
    global _loaded, _JOBS
    if _loaded:
        return
    _loaded = True
    if not os.path.exists(_STATE_PATH):
        return
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            _JOBS = json.load(f).get("jobs", {})
        for job in _JOBS.values():
            # Mid-flight when the server died → back in line.
            if job.get("status") == "running":
                job["status"] = "queued"
    except (OSError, ValueError):
        logger.warning("shard-queue state unreadable at %s; starting empty",
                       _STATE_PATH)
        _JOBS = {}


def _dispatch_loop() -> None:
    """One job at a time; the allocator/shard pool spreads the load."""
    client = httpx.Client(timeout=_JOB_TIMEOUT_S)
    while True:
        job = None
        with _LOCK:
            queued = [j for j in _JOBS.values() if j["status"] == "queued"]
            if queued:
                job = min(queued, key=lambda j: j["created_at"])
                job["status"] = "running"
                job["started_at"] = time.time()
                _save()
        if job is None:
            time.sleep(2.0)
            continue
        payload = {
            "messages": [{"role": "user", "content": job["prompt"]}],
            "stream": False,
        }
        if job.get("model"):
            payload["model"] = job["model"]
        try:
            r = client.post(_V1_URL, json=payload,
                            headers={"Accept": "application/json"})
            data = r.json()
            if r.status_code == 200:
                text = (data.get("choices") or [{}])[0] \
                    .get("message", {}).get("content", "")
                with _LOCK:
                    job["status"] = "done"
                    job["result"] = text
            else:
                msg = (data.get("error") or {}).get("message") or r.text[:500]
                with _LOCK:
                    job["status"] = "error"
                    job["error"] = f"HTTP {r.status_code}: {msg}"
        except Exception as exc:
            with _LOCK:
                job["status"] = "error"
                job["error"] = f"{type(exc).__name__}: {exc}"
        with _LOCK:
            job["finished_at"] = time.time()
            _save()


def _ensure_dispatcher() -> None:
    """Lazy start so importing the blueprint never spawns threads."""
    global _dispatcher_started
    with _LOCK:
        if _dispatcher_started:
            return
        _dispatcher_started = True
    threading.Thread(target=_dispatch_loop, daemon=True,
                     name="shard-queue-dispatch").start()


@shard_queue_bp.route("/shard-queue", methods=["GET"])
def shard_queue_list():
    with _LOCK:
        _ensure_loaded()
        jobs = sorted(_JOBS.values(), key=lambda j: j["created_at"],
                      reverse=True)[:100]
    _ensure_dispatcher()
    return jsonify({"jobs": jobs})


@shard_queue_bp.route("/shard-queue", methods=["POST"])
def shard_queue_add():
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    job = {
        "id": uuid.uuid4().hex[:12],
        "prompt": prompt,
        "model": (body.get("model") or "").strip() or None,
        # The console passes the signed-in username along; default keeps the
        # endpoint usable from curl during review.
        "user": (body.get("user") or "").strip() or "unknown",
        "status": "queued",
        "result": None,
        "error": None,
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
    }
    with _LOCK:
        _ensure_loaded()
        _JOBS[job["id"]] = job
        _save()
    _ensure_dispatcher()
    return jsonify(job)


@shard_queue_bp.route("/shard-queue/<job_id>/cancel", methods=["POST"])
def shard_queue_cancel(job_id):
    with _LOCK:
        _ensure_loaded()
        job = _JOBS.get(job_id)
        if not job:
            return jsonify({"error": "unknown job"}), 404
        if job["status"] == "queued":
            job["status"] = "cancelled"
            job["finished_at"] = time.time()
            _save()
    return jsonify(job)


@shard_queue_bp.route("/shard-queue/<job_id>", methods=["DELETE"])
def shard_queue_delete(job_id):
    with _LOCK:
        _ensure_loaded()
        job = _JOBS.get(job_id)
        if not job:
            return jsonify({"error": "unknown job"}), 404
        if job["status"] == "running":
            return jsonify({"error": "job is running"}), 409
        _JOBS.pop(job_id, None)
        _save()
    return jsonify({"ok": True})
