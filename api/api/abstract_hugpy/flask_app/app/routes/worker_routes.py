"""HTTP surface for the GPU worker pool.

These endpoints serve two audiences:

  * the worker agent (machine-to-machine):
        POST /llm/workers/register
        POST /llm/workers/<id>/heartbeat
  * the console UI (human-driven):
        GET    /llm/workers
        GET    /llm/workers/<id>
        DELETE /llm/workers/<id>
        POST   /llm/workers/<id>/assign      {"model_key": ..., "spill": {...}?}
        POST   /llm/workers/<id>/unassign    {"model_key": ...}
  * model provisioning (worker pulls files from central over WireGuard):
        GET    /llm/models/<model_key>/manifest      file list + sizes + meta
        GET    /llm/models/<model_key>/file?path=..  stream one file (Range ok)

All registry state lives in functions.imports.utils.workers; this module only
translates HTTP <-> that store. get_bp, the worker_store helpers,
get_models_dict, get_model_config and route_destination are all re-exported
through functions/__init__ (imports → utils), mirroring how
llm_storage_routes.py pulls its registry helpers.
"""
import os

from pydantic import BaseModel, Field
from flask import request, jsonify, abort, send_file

from ..functions import *

worker_bp, logger = get_bp("worker_bp", __name__)


class GpuInfo(BaseModel):
    index: int | None = None
    name: str | None = None
    memory_total: int | None = None
    memory_free: int | None = None


class RegisterRequest(BaseModel):
    name: str
    url: str = Field(..., examples=["http://10.0.0.5:9100"])
    gpus: list[GpuInfo] = Field(default_factory=list)
    role: str = "worker"
    models: list[str] | None = None
    worker_id: str | None = None


class HeartbeatRequest(BaseModel):
    gpus: list[GpuInfo] | None = None
    loaded_models: list[str] | None = None
    spill: dict | None = None


class AssignRequest(BaseModel):
    model_key: str
    # Optional per-assignment GPU/CPU spill override. Empty/omitted = autofit.
    # Recognized keys: n_gpu_layers (int|"auto"|"off"), gpu_mem_gib (float),
    # cpu_mem_gib (float), tensor_split (list[float]).
    spill: dict | None = None


@worker_bp.route("/llm/workers", methods=["GET"])
def workers_list():
    return jsonify(list_workers())


@worker_bp.route("/llm/workers/register", methods=["POST"])
def workers_register():
    body = RegisterRequest(**(request.get_json(silent=True) or {}))
    worker = register_worker(
        name=body.name,
        url=body.url,
        gpus=[g.model_dump() for g in body.gpus],
        role=body.role,
        models=body.models,
        worker_id=body.worker_id,
    )
    return jsonify(worker)


@worker_bp.route("/llm/workers/<worker_id>", methods=["GET"])
def workers_get(worker_id):
    worker = get_worker(worker_id)
    if worker is None:
        abort(404, description="Unknown worker id.")
    return jsonify(worker)


@worker_bp.route("/llm/workers/<worker_id>/heartbeat", methods=["POST"])
def workers_heartbeat(worker_id):
    body = HeartbeatRequest(**(request.get_json(silent=True) or {}))
    worker = heartbeat_worker(
        worker_id,
        gpus=[g.model_dump() for g in body.gpus] if body.gpus is not None else None,
        loaded_models=body.loaded_models,
        spill=body.spill,
    )
    if worker is None:
        # The agent thinks it's registered but central forgot it (restart,
        # cleared registry). 410 tells the agent to re-register.
        abort(410, description="Unknown worker id; please re-register.")
    return jsonify(worker)


@worker_bp.route("/llm/workers/<worker_id>", methods=["DELETE"])
def workers_remove(worker_id):
    if not remove_worker(worker_id):
        abort(404, description="Unknown worker id.")
    return jsonify({"removed": True, "id": worker_id})


@worker_bp.route("/llm/workers/<worker_id>/assign", methods=["POST"])
def workers_assign(worker_id):
    body = AssignRequest(**(request.get_json(silent=True) or {}))
    if body.model_key not in get_models_dict(dict_return=True):
        abort(404, description="Unknown model key.")
    worker = assign_model(worker_id, body.model_key, spill=body.spill)
    if worker is None:
        abort(404, description="Unknown worker id.")
    return jsonify(worker)


@worker_bp.route("/llm/workers/<worker_id>/unassign", methods=["POST"])
def workers_unassign(worker_id):
    body = AssignRequest(**(request.get_json(silent=True) or {}))
    worker = unassign_model(worker_id, body.model_key)
    if worker is None:
        abort(404, description="Unknown worker id.")
    return jsonify(worker)


# ──────────────────────────────────────────────────────────────────────────
# Model provisioning — workers pull missing model files from central.
#
# A worker that lacks a model calls /manifest to learn the file list + the
# routing metadata (framework/task/hub_id) it needs to place the files under
# its OWN storage root, then GETs each file via /file. Streaming with send_file
# means large GGUF/safetensors transfers don't buffer in memory and support
# HTTP Range (resumable). Both routes are read-only and confined to the model's
# own destination directory.
# ──────────────────────────────────────────────────────────────────────────
def _model_dir_or_404(model_key: str):
    manifest = get_models_dict(dict_return=True)
    if model_key not in manifest:
        abort(404, description="Unknown model key.")
    model = manifest[model_key]
    dest = route_destination(model)
    if not os.path.isdir(dest):
        abort(409, description="Model is not installed on central.")
    return model, os.path.realpath(dest)


@worker_bp.route("/llm/models/<model_key>/manifest", methods=["GET"])
def model_file_manifest(model_key):
    model, dest = _model_dir_or_404(model_key)

    files = []
    total = 0
    for root, _dirs, names in os.walk(dest):
        for name in names:
            full = os.path.join(root, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            rel = os.path.relpath(full, dest)
            files.append({"path": rel, "size": size})
            total += size

    return jsonify({
        "model_key": model_key,
        "hub_id": model.get("hub_id"),
        "name": model.get("name"),
        "framework": model.get("framework"),
        "task": model.get("task") or model.get("primary_task"),
        "filename": model.get("filename"),
        "include": model.get("include"),
        "total_bytes": total,
        "files": files,
    })


@worker_bp.route("/llm/models/<model_key>/file", methods=["GET"])
def model_file(model_key):
    _model, dest = _model_dir_or_404(model_key)

    rel = request.args.get("path", "")
    if not rel:
        abort(400, description="Missing ?path=")

    # Resolve and confine: the final real path must stay inside dest.
    target = os.path.realpath(os.path.join(dest, rel))
    if target != dest and not target.startswith(dest + os.sep):
        abort(403, description="Path escapes model directory.")
    if not os.path.isfile(target):
        abort(404, description="No such file.")

    # conditional/Range handling is provided by send_file.
    return send_file(target, as_attachment=True,
                     download_name=os.path.basename(target),
                     conditional=True)
