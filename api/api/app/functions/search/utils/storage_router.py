from .imports import *

def safe_path_part(value: str) -> str:
    value = value.strip().replace("\\", "/")
    value = re.sub(r"[^A-Za-z0-9._/\-]+", "_", value)
    value = re.sub(r"/+", "/", value)
    return value.strip("/")


def runtime_folder(framework: str, hub_id: str, include: Any = None, filename: str | None = None) -> str:
    framework = framework.lower().strip()

    if framework == "llama_cpp":
        return "gguf"

    if filename and filename.lower().endswith(".gguf"):
        return "gguf"

    if include:
        patterns = include if isinstance(include, list) else [include]
        if any("gguf" in pattern.lower() for pattern in patterns):
            return "gguf"

    if framework == "transformers":
        return "transformers"

    return "misc"


def destination_for_model(
    *,
    hub_id: str,
    framework: str,
    task: str,
    include: Any = None,
    filename: str | None = None,
    repo_type: str = "model",
) -> str:
    hub_path = safe_path_part(hub_id)
    task_path = safe_path_part(task or "misc")

    if repo_type == "dataset" or task == "dataset":
        return os.path.join(DATASETS_DIR,hub_path)

    runtime = runtime_folder(framework, hub_id, include=include, filename=filename)
    return os.path.join(MODELS_DIR,runtime,task_path,hub_path)
