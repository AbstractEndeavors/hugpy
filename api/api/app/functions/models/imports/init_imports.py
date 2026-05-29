from __future__ import annotations

import threading
import uuid
from typing import Any, Dict

try:
    from abstract_hugpy.imports.config.models_dict import MODELS
    from abstract_hugpy.console import is_installed, destination_for, download_model
except ImportError:
    MODELS: Dict[str, Any] = {}

    def is_installed(m):
        return False

    def destination_for(m):
        return "/unknown"

    def download_model(key, model):
        raise RuntimeError("abstract_hugpy not installed")
