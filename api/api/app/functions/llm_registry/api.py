from __future__ import annotations

import shutil
import threading

from fastapi import FastAPI, HTTPException

from .config import settings
from .downloader import download_model, model_status
from .jobs import job_store
from .manifest import load_manifest
from .paths import model_destination


app = FastAPI(title="Local LLM Registry API")


def get_manifest() -> dict:
    try:
        return load_manifest(settings.manifest_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "storage_root": str(settings.storage_root),
        "manifest_path": str(settings.manifest_path),
    }


@app.get("/models")
def list_models() -> list[dict]:
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

    return output


@app.get("/models/{model_key}")
def get_model(model_key: str) -> dict:
    manifest = get_manifest()

    if model_key not in manifest:
        raise HTTPException(status_code=404, detail="Unknown model key.")

    model = manifest[model_key]

    return {
        "key": model_key,
        **model,
        **model_status(model),
    }


@app.post("/models/{model_key}/download")
def start_download(model_key: str) -> dict:
    manifest = get_manifest()

    if model_key not in manifest:
        raise HTTPException(status_code=404, detail="Unknown model key.")

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

    return job.to_dict()


@app.get("/jobs")
def list_jobs() -> list[dict]:
    return [job.to_dict() for job in job_store.all()]


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = job_store.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Unknown job ID.")

    return job.to_dict()


@app.delete("/models/{model_key}")
def delete_model(model_key: str) -> dict:
    manifest = get_manifest()

    if model_key not in manifest:
        raise HTTPException(status_code=404, detail="Unknown model key.")

    destination = model_destination(settings.storage_root, manifest[model_key])

    if not destination.exists():
        return {
            "deleted": False,
            "message": "Model is not installed.",
            "destination": str(destination),
        }

    shutil.rmtree(destination)

    return {
        "deleted": True,
        "destination": str(destination),
    }
