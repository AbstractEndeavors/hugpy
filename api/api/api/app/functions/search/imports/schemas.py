from .init_imports import *
from .settings import *


class Runtime(str, Enum):
    transformers = "transformers"
    llama_cpp = "llama_cpp"
    dataset = "dataset"
    unknown = "unknown"


class DownloadStatus(str, Enum):
    queued = "queued"
    running = "running"
    complete = "complete"
    failed = "failed"


class ModelSearchResult(BaseModel):
    hub_id: str
    author: str | None = None
    downloads: int | None = None
    likes: int | None = None
    tags: list[str] = Field(default_factory=list)
    pipeline_tag: str | None = None
    library_name: str | None = None
    private: bool | None = None


class DownloadRequest(BaseModel):
    hub_id: str = Field(..., examples=["Qwen/Qwen2.5-Coder-3B-Instruct-GGUF"])
    framework: Runtime | str = Field(default="transformers")
    task: str = Field(default="text-generation")
    filename: str | None = None
    include: str | list[str] | None = None
    repo_type: Literal["model", "dataset"] = "model"


class DownloadJob(BaseModel):
    job_id: str
    hub_id: str
    framework: str
    task: str
    destination: str
    status: DownloadStatus
    error: str | None = None
