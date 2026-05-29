from __future__ import annotations

import json,os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from huggingface_hub import hf_hub_download, snapshot_download

from .utils.config import settings
from .utils.paths import install_marker, model_destination, split_hub_id


def configure_environment() -> None:
    os.environ.setdefault("HF_HOME", str(settings.hf_home))
    os.environ.setdefault("HF_HUB_CACHE", str(settings.hf_hub_cache))
    os.environ.setdefault("TORCH_HOME", str(settings.torch_home))
    os.environ.setdefault("PIP_CACHE_DIR", str(settings.pip_cache_dir))


def model_status(model: dict[str, Any]) -> dict[str, Any]:
    destination = model_destination(settings.storage_root, model)
    marker = install_marker(destination)

    if marker.exists():
        status = "installed"
    elif destination.exists() and any(destination.iterdir()):
        status = "partial"
    else:
        status = "not_installed"

    return {
        "status": status,
        "destination": str(destination),
        "installed_marker": str(marker),
    }


def write_install_marker(destination: Path, model_key: str, model: dict[str, Any]) -> None:
    marker = install_marker(destination)
    payload = {
        "model_key": model_key,
        "hub_id": model.get("hub_id"),
        "framework": model.get("framework"),
        "task": model.get("task"),
        "filename": model.get("filename"),
        "include": model.get("include"),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }

    marker.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def download_model(model_key: str, model: dict[str, Any]) -> Path:
    configure_environment()

    hub_id = model.get("hub_id")
    if not hub_id:
        raise ValueError(f"{model_key} is missing hub_id.")

    destination = model_destination(settings.storage_root, model)
    destination.mkdir(parents=True, exist_ok=True)

    repo_id, subfolder = split_hub_id(hub_id)

    framework = model.get("framework")
    task = model.get("task")
    filename = model.get("filename")
    include = model.get("include")

    if task == "dataset":
        snapshot_download(
            repo_id=repo_id,
            repo_type="dataset",
            local_dir=destination,
            local_dir_use_symlinks=False,
        )

        write_install_marker(destination, model_key, model)
        return destination

    if framework == "llama_cpp":
        if filename:
            hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                subfolder=subfolder,
                local_dir=destination,
                local_dir_use_symlinks=False,
            )
        elif include:
            snapshot_download(
                repo_id=repo_id,
                allow_patterns=include,
                local_dir=destination,
                local_dir_use_symlinks=False,
            )
        else:
            snapshot_download(
                repo_id=repo_id,
                local_dir=destination,
                local_dir_use_symlinks=False,
            )

        write_install_marker(destination, model_key, model)
        return destination

    allow_patterns = include if include else None

    snapshot_download(
        repo_id=repo_id,
        allow_patterns=allow_patterns,
        local_dir=destination,
        local_dir_use_symlinks=False,
    )

    write_install_marker(destination, model_key, model)
    return destination
