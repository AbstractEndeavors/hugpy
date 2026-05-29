from ..functions import *
from ..functions.models import *
models_bp,logger=get_bp("models_bp",__name__)
# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@models_bp.route("/models", methods=["GET"])
def list_models() -> list:
    result = []
    for key, m in MODELS.items():
        result.append({
            "key": key,
            "name": m.get("name", key),
            "framework": m.get("framework", "?"),
            "primary_task": m.get("primary_task", "?"),
            "tasks": m.get("tasks", []),
            "model_max_length": m.get("model_max_length"),
            "hub_id": m.get("hub_id", ""),
            "filename": m.get("filename"),
            "include": m.get("include"),
            "port": m.get("port"),
            "installed": is_installed(m),
            "destination": str(destination_for(m)),
        })
    return result


@models_bp.route("/models/{model_key}", methods=["GET"])
def get_model(model_key: str) -> dict:
    if model_key not in MODELS:
        raise HTTPException(status_code=404, detail="Unknown model key")
    m = MODELS[model_key]
    return {
        "key": model_key,
        **m,
        "installed": is_installed(m),
        "destination": str(destination_for(m)),
    }


@models_bp.route("/models/{model_key}/download", methods=["POST"])
def start_download(model_key: str) -> dict:
    if model_key not in MODELS:
        raise HTTPException(status_code=404, detail="Unknown model key")
    job_id = make_job(model_key)
    t = threading.Thread(target=_run_download, args=(job_id, model_key), daemon=True)
    t.start()
    return {"job_id": job_id}


@models_bp.route("/jobs/{job_id}", methods=["GET"])
def get_job(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job ID")
    return job


@models_bp.route("/jobs", methods=["GET"])
def listjobs() -> list:
    with jobs_lock:
        return list(jobs.values())
