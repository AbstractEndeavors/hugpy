from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Manifest root must be a JSON object.")

    return data
