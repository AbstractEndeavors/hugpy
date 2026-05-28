from .init_imports import *
LLM_STORAGE = os.getenv("LLM_STORAGE", "/mnt/llm_storage")
MODELS_DIR = os.path.join(LLM_STORAGE,"models")
DATASETS_DIR = os.path.join(LLM_STORAGE,"datasets")
HF_HOME = os.path.join(LLM_STORAGE,"cache","huggingface")
HF_HUB_CACHE = os.path.join(HF_HOME,"hub")
TORCH_HOME = os.path.join(LLM_STORAGE,"cache","torch")
PIP_CACHE_DIR = os.path.join(LLM_STORAGE,"cache","pip")
PATHS = [
    MODELS_DIR,
    DATASETS_DIR,
    HF_HOME,
    HF_HUB_CACHE,
    TORCH_HOME,
    PIP_CACHE_DIR,
]
[os.makedirs(path, exist_ok=True) for path in PATHS]

os.environ.setdefault("HF_HOME", HF_HOME)
os.environ.setdefault("HF_HUB_CACHE", HF_HUB_CACHE)
os.environ.setdefault("TORCH_HOME", TORCH_HOME)
os.environ.setdefault("PIP_CACHE_DIR", PIP_CACHE_DIR)
