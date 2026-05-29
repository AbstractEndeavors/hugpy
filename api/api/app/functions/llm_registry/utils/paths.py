from __future__ import annotations

import os
import re
from typing import Any


def safe_path_part(value: str) -> str:
    value = value.strip().replace("\\", "/")
    value = re.sub(r"[^A-Za-z0-9._/\-]+", "_", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_/")


def split_hub_id(hub_id: str) -> tuple[str, str | None]:
    """
    Handles normal repo IDs:

        Qwen/Qwen2.5-Coder-3B-Instruct-GGUF

    and accidental repo+subfolder IDs:

        Qwen/Qwen3-Coder-Next-GGUF/Qwen3-Coder-Next-Q4_K_M
    """
    parts = hub_id.strip("/").split("/")

    if len(parts) <= 2:
        return hub_id, None

    repo_id = "/".join(parts[:2])
    subfolder = "/".join(parts[2:])
    return repo_id, subfolder


def framework_family(model: dict[str, Any]) -> str:
    framework = model.get("framework", "")
    task = model.get("task", "")

    if task == "dataset":
        return "datasets"

    if framework == "llama_cpp":
        return "gguf"

    if framework == "transformers":
        return "transformers"

    return "misc"


def model_destination(storage_root: str, model: dict[str, Any]) -> str:
    hub_id = model.get("hub_id") or model.get("folder") or model.get("name")

    if not hub_id:
        raise ValueError("Model entry is missing hub_id/folder/name.")

    task = safe_path_part(model.get("task", "misc"))
    hub_path = safe_path_part(hub_id)
    family = framework_family(model)

    if family == "datasets":
        return os.path.join(storage_root, "datasets", hub_path)

    return os.path.join(storage_root, "models", family, task, hub_path)


def install_marker(destination: str) -> str:
    return os.path.join(destination, ".llm_registry_installed.json")
