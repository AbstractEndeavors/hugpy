from pydantic import BaseModel, Field

from ..functions import *
from ..functions.llm_registry import *
from ..functions.llm_registry.utils.manifest import upsert_model
from ..functions.llm_registry.utils.peers import list_peers
llm_bp,logger=get_bp("llm_bp",__name__)


class HFRepoDownloadRequest(BaseModel):
    hub_id: str = Field(..., examples=["Qwen/Qwen2.5-VL-7B-Instruct"])
    framework: str = Field(default="transformers")
    task: str = Field(default="text-generation")
    filename: str | None = None
    include: str | list[str] | None = None
    name: str | None = None
    register: bool = True

@llm_bp.route("/health", methods=["GET"])
def health() -> dict:
    return {
        "ok": True,
        "storage_root": str(settings.storage_root),
        "manifest_path": str(settings.manifest_path),
    }


@llm_bp.route("/llm/peers", methods=["GET"])
def peers() -> list[dict]:
    return list_peers()


@llm_bp.route("/models", methods=["GET"])
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


@llm_bp.route("/models/{model_key}", methods=["GET"])
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


@llm_bp.route("/models/{model_key}/download", methods=["POST"])
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


@llm_bp.route("/jobs", methods=["GET"])
def list_jobs() -> list[dict]:
    return [job.to_dict() for job in job_store.all()]


@llm_bp.route("/jobs/{job_id}", methods=["GET"])
def get_job(job_id: str) -> dict:
    job = job_store.get(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Unknown job ID.")

    return job.to_dict()


@llm_bp.route("/llm/repos/download", methods=["GET"])
def download_repo(body: HFRepoDownloadRequest) -> dict:
    """Acquire any Hugging Face repo by hub_id without a pre-registered manifest entry.

    If register=True, the model is added to the manifest so it appears in the
    registry browser on the next refresh.
    """
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
        from ..functions.llm_registry.utils.manifest import key_for_hub_id
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

    return {**job.to_dict(), "model_key": model_key}


@llm_bp.route("/models/{model_key}", methods=["DELETE"])
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
