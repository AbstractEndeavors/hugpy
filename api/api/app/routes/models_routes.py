from ..functions import *
from ..functions.models import *
from flask import jsonify, abort

models_bp,logger=get_bp("models_bp",__name__)
# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@models_bp.route("/models", methods=["GET"])
def list_models():
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
    return jsonify(result)


@models_bp.route("/models/<model_key>", methods=["GET"])
def get_model(model_key):
    if model_key not in MODELS:
        abort(404, description="Unknown model key")
    m = MODELS[model_key]
    return jsonify({
        "key": model_key,
        **m,
        "installed": is_installed(m),
        "destination": str(destination_for(m)),
    })


@models_bp.route("/models/<model_key>/download", methods=["POST"])
def start_download(model_key):
    if model_key not in MODELS:
        abort(404, description="Unknown model key")
    job_id = make_job(model_key)
    t = threading.Thread(target=_run_download, args=(job_id, model_key), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@models_bp.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        abort(404, description="Unknown job ID")
    return jsonify(job)


@models_bp.route("/jobs", methods=["GET"])
def listjobs():
    with jobs_lock:
        return jsonify(list(jobs.values()))
