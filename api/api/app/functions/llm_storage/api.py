from __future__ import annotations

import os
import shutil
import threading

from flask import Flask, request, jsonify, abort

from pydantic import BaseModel, Field

from .config import settings
from .downloader import download_model, model_status
from .jobs import job_store
from .manifest import load_manifest, upsert_model, key_for_hub_id
from .paths import model_destination
from .peers import list_peers


app = Flask("Local LLM Registry API")


class HFRepoDownloadRequest(BaseModel):
    hub_id: str = Field(..., examples=["Qwen/Qwen2.5-VL-7B-Instruct"])
    framework: str = Field(default="transformers")
    task: str = Field(default="text-generation")
    filename: str | None = None
    include: str | list[str] | None = None
    name: str | None = None
    register: bool = True


@app.route("/peers", methods=["GET"])
def peers():
    return jsonify(list_peers())


@app.route("/repos/download", methods=["POST"])
def download_repo():
    body = HFRepoDownloadRequest(**(request.get_json(silent=True) or {}))
    model = {
        "name": body.name or body.hub_id.split("/")[-1],
        "hub_id": body.hub_id,
        "framework": body.framework,
        "task": body.task,
        "filename": body.filename,
        "include": body.include,
    }

    if body.register:
        model_key, _ = upsert_model(settings.manifest_path, model)
    else:
        model_key = key_for_hub_id(body.hub_id)

    job = job_store.create(model_key)

    def runner() -> None:
        try:
            job_store.update(job.id, status="running", message=f"Pulling {body.hub_id}…")
            destination = download_model(model_key, model)
            job_store.update(
                job.id,
                status="completed",
                message=f"Installed at {destination}",
            )
        except Exception as exc:
            job_store.update(
                job.id,
                status="failed",
                message="Download failed.",
                error=str(exc),
            )

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()

    return jsonify({**job.to_dict(), "model_key": model_key})


def get_manifest() -> dict:
    try:
        return load_manifest(settings.manifest_path)
    except Exception as exc:
        abort(500, description=str(exc))


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "storage_root": str(settings.storage_root),
        "manifest_path": str(settings.manifest_path),
    })


@app.route("/models", methods=["GET"])
def list_models():
    manifest = get_manifest()
    output = []

    for key, model in manifest.items():
        status = model_status(model)

        output.append(
            {
                "key": key,
                "name": model.get("name"),
                "hub_id": model.get("hub_id"),
                "framework": model.get("framework"),
                "task": model.get("task"),
                "filename": model.get("filename"),
                "include": model.get("include"),
                **status,
            }
        )

    return jsonify(output)


@app.route("/models/<model_key>", methods=["GET"])
def get_model(model_key):
    manifest = get_manifest()

    if model_key not in manifest:
        abort(404, description="Unknown model key.")

    model = manifest[model_key]

    return jsonify({
        "key": model_key,
        **model,
        **model_status(model),
    })


@app.route("/models/<model_key>/download", methods=["POST"])
def start_download(model_key):
    manifest = get_manifest()

    if model_key not in manifest:
        abort(404, description="Unknown model key.")

    model = manifest[model_key]
    job = job_store.create(model_key)

    def runner() -> None:
        try:
            job_store.update(job.id, status="running", message="Download started.")
            destination = download_model(model_key, model)
            job_store.update(
                job.id,
                status="completed",
                message=f"Installed at {destination}",
            )
        except Exception as exc:
            job_store.update(
                job.id,
                status="failed",
                message="Download failed.",
                error=str(exc),
            )

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()

    return jsonify(job.to_dict())


@app.route("/jobs", methods=["GET"])
def list_jobs():
    return jsonify([job.to_dict() for job in job_store.all()])


@app.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    job = job_store.get(job_id)

    if not job:
        abort(404, description="Unknown job ID.")

    return jsonify(job.to_dict())


@app.route("/models/<model_key>", methods=["DELETE"])
def delete_model(model_key):
    manifest = get_manifest()

    if model_key not in manifest:
        abort(404, description="Unknown model key.")

    destination = model_destination(settings.storage_root, manifest[model_key])

    if not os.path.exists(destination):
        return jsonify({
            "deleted": False,
            "message": "Model is not installed.",
            "destination": str(destination),
        })

    shutil.rmtree(destination)

    return jsonify({
        "deleted": True,
        "destination": str(destination),
    })
