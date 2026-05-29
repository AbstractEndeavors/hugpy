import os
from pydantic import BaseModel


class Settings(BaseModel):
    storage_root: str = "/mnt/llm_storage"
    manifest_path: str = "/mnt/llm_storage/projects/model_manifest.json"

    @property
    def hf_home(self) -> str:
        return os.path.join(self.storage_root, "cache", "huggingface")

    @property
    def hf_hub_cache(self) -> str:
        return os.path.join(self.hf_home, "hub")

    @property
    def torch_home(self) -> str:
        return os.path.join(self.storage_root, "cache", "torch")

    @property
    def pip_cache_dir(self) -> str:
        return os.path.join(self.storage_root, "cache", "pip")


settings = Settings()
