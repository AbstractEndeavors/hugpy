"""Model provisioning for the worker — central-first, Hugging Face fallback.

When the worker is asked to serve a model it doesn't have on disk, it tries to
fetch the files in this order:

    1. From the CENTRAL node, over WireGuard, using the read-only endpoints
       /api/llm/models/<key>/manifest and /api/llm/models/<key>/file. This needs
       no Hugging Face token on the worker and reuses whatever central already
       downloaded.
    2. If central doesn't have it (409) or is unreachable, fall back to the
       normal Hugging Face download via abstract_hugpy.ensure_model — which the
       inference path would call anyway.

Files are placed under the worker's OWN storage root using the same
route_destination() layout central uses, so the existing loader/`ensure_model`
finds them with no further config.
"""
from __future__ import annotations

import os
import logging
import urllib.parse
import urllib.request
import urllib.error

logger = logging.getLogger("abstract_hugpy.worker_agent.provision")

_CHUNK = 8 * 1024 * 1024  # 8 MiB streaming chunks


def model_is_local(model_key: str) -> bool:
    """True if the model already looks downloaded under the worker's storage."""
    try:
        from abstract_hugpy.imports.config.main import (
            get_model_config, model_looks_downloaded, get_model_path,
        )
        cfg = get_model_config(model_key)
        return bool(model_looks_downloaded(get_model_path(model_key), cfg))
    except Exception:
        return False


def _local_destination(meta: dict) -> str:
    """Where this file-set should live on the worker (same layout as central)."""
    from abstract_hugpy.imports.src.constants.paths import route_destination

    return route_destination({
        "hub_id": meta.get("hub_id"),
        "name": meta.get("name"),
        "framework": meta.get("framework"),
        "task": meta.get("task"),
        "primary_task": meta.get("task"),
        "filename": meta.get("filename"),
        "include": meta.get("include"),
    })


def _get_json(url: str, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        import json
        return json.loads(resp.read().decode("utf-8"))


def _download_file(url: str, dest_path: str, expected_size: int | None,
                   on_bytes=None) -> None:
    """Stream one file to dest_path, resuming if a partial is already present.

    ``on_bytes(n)`` is called with the number of newly-written bytes per chunk
    so the caller can report download progress.
    """
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)

    have = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
    if expected_size is not None and have == expected_size:
        if on_bytes:
            on_bytes(have)   # count the already-present bytes toward progress
        return  # already complete

    req = urllib.request.Request(url)
    if have and expected_size and have < expected_size:
        req.add_header("Range", f"bytes={have}-")
        mode = "ab"
        if on_bytes:
            on_bytes(have)   # resumed: pre-existing bytes already on disk
    else:
        have = 0
        mode = "wb"

    with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, mode) as fh:
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            fh.write(chunk)
            if on_bytes:
                on_bytes(len(chunk))


def fetch_from_central(central_url: str, model_key: str, progress=None) -> bool:
    """Pull a model's files from central into the worker's storage.

    ``progress(done_bytes, total_bytes, filename)`` is called as bytes arrive.
    Returns True on success, False if central doesn't have the model (so the
    caller can fall back to Hugging Face). Raises on hard network errors only
    when central was reachable but failed mid-transfer.
    """
    base = central_url.rstrip("/") + "/api/llm/models/" + urllib.parse.quote(model_key)
    try:
        manifest = _get_json(base + "/manifest")
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 409):
            logger.info("central has no copy of %s (HTTP %s); will try HF", model_key, exc.code)
            return False
        raise
    except urllib.error.URLError as exc:
        logger.warning("central unreachable for %s (%s); will try HF", model_key, exc)
        return False

    dest = _local_destination(manifest)
    files = manifest.get("files") or []
    total = manifest.get("total_bytes") or sum((e.get("size") or 0) for e in files)
    logger.info("provisioning %s from central: %d files (%s) -> %s",
                model_key, len(files), _human(total), dest)

    done = 0

    def _emit(fname):
        if progress:
            progress(done, total, fname)

    _emit("")
    for entry in files:
        rel = entry["path"]
        size = entry.get("size")
        url = base + "/file?path=" + urllib.parse.quote(rel)
        target = os.path.join(dest, rel)

        def _on_bytes(n, _rel=rel):
            nonlocal done
            done += n
            _emit(_rel)

        _download_file(url, target, size, on_bytes=_on_bytes)

    logger.info("provisioned %s from central", model_key)
    return True


def _human(n) -> str:
    if not n:
        return "?"
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(n)
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return f"{v:.1f} {units[i]}"


def fetch_from_hf(model_key: str) -> str:
    """Last-resort: pull from Hugging Face via the normal code path."""
    from abstract_hugpy.imports.apis.download_models import ensure_model

    logger.info("provisioning %s from Hugging Face", model_key)
    return ensure_model(model_key)


def ensure_model_present(model_key: str, central_url: str | None, progress=None) -> bool:
    """Make sure model_key is on local disk. Central-first, then HF fallback.

    ``progress(done_bytes, total_bytes, filename)`` is forwarded to the central
    download so callers can stream provisioning status. Returns True if the
    model is present (or already was), False if it could not be provisioned.
    """
    if model_is_local(model_key):
        return True

    if central_url:
        try:
            if fetch_from_central(central_url, model_key, progress=progress):
                return True
        except Exception as exc:
            logger.warning("central provisioning of %s failed: %s; trying HF", model_key, exc)

    try:
        if progress:
            progress(0, 0, "huggingface")
        fetch_from_hf(model_key)
        return True
    except Exception as exc:
        logger.error("could not provision %s from HF: %s", model_key, exc)
        return False

