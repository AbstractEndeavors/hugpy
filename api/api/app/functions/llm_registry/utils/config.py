from pathlib import Path
from pydantic import BaseModel


class Settings(BaseModel):
    storage_root: Path = Path("/mnt/llm_registry")
    manifest_path: Path = Path("/mnt/llm_registry/projects/model_manifest.json")

    @property
    def hf_home(self) -> Path:
        return self.storage_root / "cache" / "huggingface"

    @property
    def hf_hub_cache(self) -> Path:
        return self.hf_home / "hub"

    @property
    def torch_home(self) -> Path:
        return self.storage_root / "cache" / "torch"

    @property
    def pip_cache_dir(self) -> Path:
        return self.storage_root / "cache" / "pip"


settings = Settings()
