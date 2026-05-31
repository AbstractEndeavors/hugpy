"""Standalone GPU worker agent for the abstract_hugpy LLM pool.

Run this on any box with a GPU and a working ``abstract_hugpy`` install to
donate that GPU's compute to the central console. The agent:

    1. Detects local GPUs.
    2. Registers with the central node (``/api/llm/workers/register``) and keeps
       a persistent worker id in a local state file so restarts reuse the row.
    3. Serves inference over HTTP for the models the central node assigns to it:
           GET  /health
           POST /infer          {model_key, messages|prompt, ...} -> {text, finish_reason}
           POST /infer/stream   -> SSE token/done/error events
       Inference runs through ``abstract_hugpy.managers.dispatch`` exactly like
       the central node, so the worker loads/serves the model on its own GPU.
    4. Heartbeats every ``--heartbeat`` seconds, reporting live GPU stats and
       which models are currently loaded.

The central node's chat route picks an online, assigned worker for the chosen
model and relays this agent's ``/infer/stream`` back to the browser. If no
worker is assigned (or all are offline) the central node runs the model
locally, so adding workers is purely additive.

Usage
-----
    python -m abstract_hugpy.worker_agent \
        --central https://abstractgpt.ai \
        --name gpu-box-1 \
        --host 10.0.0.5 --port 9100 \
        --models Qwen_Qwen2.5-7B-Instruct,meta-llama_Llama-3.1-8B-Instruct

Every flag also has an env fallback (WORKER_CENTRAL_URL, WORKER_NAME,
WORKER_HOST, WORKER_PORT, WORKER_MODELS, WORKER_ID_FILE, WORKER_HEARTBEAT).
"""
from __future__ import annotations

import os
import sys
import json
import time
import socket
import logging
import argparse
import asyncio
import threading
import subprocess
import urllib.request
import urllib.error

from flask import Flask, request, jsonify, Response, stream_with_context

logger = logging.getLogger("abstract_hugpy.worker_agent")


# ---------------------------------------------------------------------------
# GPU discovery
# ---------------------------------------------------------------------------
def detect_gpus() -> list[dict]:
    """Best-effort GPU inventory.

    Tries ``nvidia-smi`` first (no Python deps), then ``torch.cuda``. Returns
    an empty list on a CPU-only box — the worker still registers and serves,
    it just won't be fast.
    """
    gpus = _detect_gpus_nvidia_smi()
    if gpus:
        return gpus
    return _detect_gpus_torch()


def _detect_gpus_nvidia_smi() -> list[dict]:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            timeout=10,
        ).decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []

    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        idx, name, mem_total, mem_free = parts[:4]
        gpus.append(
            {
                "index": _safe_int(idx),
                "name": name,
                # nvidia-smi reports MiB; normalize to bytes.
                "memory_total": _safe_int(mem_total) * 1024 * 1024 if _safe_int(mem_total) else None,
                "memory_free": _safe_int(mem_free) * 1024 * 1024 if _safe_int(mem_free) else None,
            }
        )
    return gpus


def _detect_gpus_torch() -> list[dict]:
    try:
        import torch  # noqa: WPS433 (optional, lazy)

        if not torch.cuda.is_available():
            return []
        gpus = []
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            free, total = (None, getattr(props, "total_memory", None))
            try:
                free, total = torch.cuda.mem_get_info(i)
            except Exception:
                pass
            gpus.append(
                {
                    "index": i,
                    "name": props.name,
                    "memory_total": total,
                    "memory_free": free,
                }
            )
        return gpus
    except Exception:
        return []


def _safe_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Central node client (registration + heartbeat)
# ---------------------------------------------------------------------------
class CentralClient:
    def __init__(self, central_url: str):
        # Endpoints live under /api on the central Flask app.
        self.base = central_url.rstrip("/") + "/api/llm/workers"

    def _post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def register(self, payload: dict) -> dict:
        return self._post("/register", payload)

    def heartbeat(self, worker_id: str, payload: dict) -> dict:
        return self._post(f"/{worker_id}/heartbeat", payload)


# ---------------------------------------------------------------------------
# Local inference (reuses the same dispatch the central node uses)
# ---------------------------------------------------------------------------
def _ensure_present(payload: dict, central_url: str | None) -> None:
    """Provision the requested model before inference (central-first, HF fallback)."""
    model_key = payload.get("model_key")
    if not model_key:
        return
    try:
        from .provision import ensure_model_present

        ensure_model_present(model_key, central_url)
    except Exception as exc:
        logger.warning("provisioning check for %s failed: %s", model_key, exc)


def _materialize_file(payload: dict) -> str | None:
    """Rebuild an inlined upload (file_b64/file_name) into a local temp file.

    Central ships uploaded files as base64 since the worker can't see central's
    UPLOADS_HOME. We write the bytes to a temp file, point ``payload["file"]``
    at it, and return the temp path so the caller can delete it afterwards.
    Returns None when there's nothing to materialize.
    """
    b64 = payload.pop("file_b64", None)
    name = payload.pop("file_name", None)
    if not b64:
        return None
    import base64
    import tempfile

    suffix = ""
    if name and "." in name:
        suffix = "." + name.rsplit(".", 1)[-1]
    fd, tmp_path = tempfile.mkstemp(prefix="hugpy_worker_", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(base64.b64decode(b64))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    payload["file"] = tmp_path
    return tmp_path


def _cleanup_file(path: str | None) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def _run_once(payload: dict) -> dict:
    from abstract_hugpy.managers.dispatch import execute_prompt

    tmp = _materialize_file(payload)
    try:
        result = execute_prompt(**payload)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)

        if getattr(result, "ok", True):
            return {
                "ok": True,
                "text": getattr(result, "text", None) or str(result),
                "finish_reason": getattr(result, "finish_reason", None) or "stop",
            }
        return {"ok": False, "error": getattr(result, "error", None) or "run failed"}
    finally:
        _cleanup_file(tmp)


_SPILL_ENV = {
    "n_gpu_layers": "HUGPY_N_GPU_LAYERS",
    "gpu_mem_gib": "HUGPY_GPU_MEM_GIB",
    "cpu_mem_gib": "HUGPY_CPU_MEM_GIB",
    "tensor_split": "HUGPY_TENSOR_SPLIT",
    "main_gpu": "HUGPY_MAIN_GPU",
    "n_gpu": "HUGPY_N_GPU",
}


def _apply_spill(spill: dict | None) -> None:
    """Translate a per-request spill override dict into the env vars the spill
    module reads. Only set keys that were provided; the model loads lazily, so
    setting these before the first request for a model takes effect on load.

    NOTE: changing spill for an ALREADY-loaded model has no effect until it's
    evicted/reloaded — central can force that via a fresh worker process or by
    reassigning before first use. For the common case (assign, then chat) the
    override lands before the model is built.
    """
    if not spill:
        return
    for key, env_name in _SPILL_ENV.items():
        if key not in spill or spill[key] is None:
            continue
        val = spill[key]
        if isinstance(val, (list, tuple)):
            val = ",".join(str(x) for x in val)
        os.environ[env_name] = str(val)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_sync(payload: dict):
    """Drive dispatch.execute_prompt_stream (async gen) from Flask's sync ctx."""
    from abstract_hugpy.managers.dispatch import execute_prompt_stream

    tmp = _materialize_file(payload)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    agen = execute_prompt_stream(**payload)
    try:
        while True:
            try:
                event = loop.run_until_complete(agen.__anext__())
            except StopAsyncIteration:
                break
            etype = getattr(event, "type", None)
            if etype == "token":
                yield _sse({"type": "token", "text": getattr(event, "text", "")})
            elif etype == "done":
                yield _sse(
                    {
                        "type": "done",
                        "finish_reason": getattr(event, "finish_reason", None) or "stop",
                    }
                )
                return
            elif etype == "error":
                yield _sse({"type": "error", "message": getattr(event, "message", "run failed")})
                return
        # Stream ended without an explicit done — synthesize one.
        yield _sse({"type": "done", "finish_reason": "stop"})
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
        _cleanup_file(tmp)


def loaded_model_keys() -> list[str]:
    try:
        from abstract_hugpy.managers.dispatch import loaded_model_keys as _loaded

        return sorted({mk for (mk, _task) in _loaded()})
    except Exception:
        return []


def _spill_describe() -> dict:
    try:
        from abstract_hugpy.managers.spill import describe

        return describe()
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------
def build_app(state: "WorkerState") -> Flask:
    app = Flask("abstract_hugpy_worker")

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify(
            {
                "ok": True,
                "worker_id": state.worker_id,
                "name": state.name,
                "gpus": detect_gpus(),
                "loaded_models": loaded_model_keys(),
                "spill": _spill_describe(),
            }
        )

    @app.route("/infer", methods=["POST"])
    def infer():
        payload = request.get_json(silent=True) or {}
        _apply_spill(payload.pop("spill", None))
        _ensure_present(payload, state.central_url)
        return jsonify(_run_once(payload))

    @app.route("/infer/stream", methods=["POST"])
    def infer_stream():
        payload = request.get_json(silent=True) or {}
        _apply_spill(payload.pop("spill", None))
        _ensure_present(payload, state.central_url)
        return Response(
            stream_with_context(_stream_sync(payload)),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
            direct_passthrough=True,
        )

    return app


# ---------------------------------------------------------------------------
# Agent lifecycle
# ---------------------------------------------------------------------------
class WorkerState:
    def __init__(self, name: str, url: str, worker_id: str | None,
                 central_url: str | None = None):
        self.name = name
        self.url = url
        self.worker_id = worker_id
        self.central_url = central_url


def _load_worker_id(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("worker_id")
    except (OSError, ValueError):
        return None


def _save_worker_id(path: str, worker_id: str) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"worker_id": worker_id}, fh)
    except OSError:
        logger.warning("could not persist worker id to %s", path)


def _heartbeat_loop(client: CentralClient, state: WorkerState, args) -> None:
    while True:
        time.sleep(args.heartbeat)
        try:
            client.heartbeat(
                state.worker_id,
                {
                    "gpus": detect_gpus(),
                    "loaded_models": loaded_model_keys(),
                    "spill": _spill_describe(),
                },
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 410:
                # Central forgot us (restart / cleared registry) — re-register.
                logger.warning("central returned 410; re-registering")
                _register(client, state, args)
            else:
                logger.warning("heartbeat HTTP %s", exc.code)
        except Exception as exc:
            logger.warning("heartbeat failed: %s", exc)


def _register(client: CentralClient, state: WorkerState, args) -> None:
    models = [m.strip() for m in (args.models or "").split(",") if m.strip()]
    payload = {
        "name": state.name,
        "url": state.url,
        "gpus": detect_gpus(),
        "role": "worker",
        "models": models or None,
        "worker_id": state.worker_id,
    }
    worker = client.register(payload)
    state.worker_id = worker.get("id", state.worker_id)
    if state.worker_id:
        _save_worker_id(args.id_file, state.worker_id)
    logger.info("registered as worker id=%s serving models=%s", state.worker_id, worker.get("models"))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="abstract_hugpy.worker_agent")
    p.add_argument("--central", default=os.environ.get("WORKER_CENTRAL_URL"),
                   help="Central console base URL, e.g. https://abstractgpt.ai")
    p.add_argument("--name", default=os.environ.get("WORKER_NAME", socket.gethostname()))
    p.add_argument("--host", default=os.environ.get("WORKER_HOST", "0.0.0.0"),
                   help="Bind address for the worker's inference server")
    p.add_argument("--port", type=int, default=int(os.environ.get("WORKER_PORT", "9100")))
    p.add_argument("--advertise", default=os.environ.get("WORKER_URL"),
                   help="URL the central node should call back on "
                        "(defaults to http://<host>:<port>)")
    p.add_argument("--models", default=os.environ.get("WORKER_MODELS", ""),
                   help="Comma-separated model_keys to self-assign on registration")
    p.add_argument("--heartbeat", type=float, default=float(os.environ.get("WORKER_HEARTBEAT", "15")))
    p.add_argument("--id-file", default=os.environ.get(
        "WORKER_ID_FILE", os.path.expanduser("~/.abstract_hugpy_worker.json")))

    # GPU/CPU spill defaults for this worker. These seed the spill env the
    # inference path reads; per-request overrides from central still win.
    spill = p.add_argument_group("spill (GPU/CPU split)")
    spill.add_argument("--spill", choices=["auto", "off"],
                       default=os.environ.get("WORKER_SPILL", "auto"),
                       help="auto = fit as many layers on GPU as VRAM allows "
                            "(spill rest to CPU); off = CPU only")
    spill.add_argument("--n-gpu-layers", type=int, default=_safe_int(os.environ.get("WORKER_N_GPU_LAYERS")),
                       help="llama.cpp: force N layers on GPU (overrides --spill)")
    spill.add_argument("--gpu-mem", type=float, default=_safe_float(os.environ.get("WORKER_GPU_MEM_GIB")),
                       help="transformers: per-GPU memory budget in GiB")
    spill.add_argument("--cpu-mem", type=float, default=_safe_float(os.environ.get("WORKER_CPU_MEM_GIB")),
                       help="transformers: CPU/RAM budget in GiB for offloaded layers")
    spill.add_argument("--tensor-split", default=os.environ.get("WORKER_TENSOR_SPLIT"),
                       help="multi-GPU split, comma-separated e.g. 0.7,0.3")
    spill.add_argument("--main-gpu", type=int, default=_safe_int(os.environ.get("WORKER_MAIN_GPU")),
                       help="primary GPU index")
    return p


def _safe_float(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _apply_cli_spill(args) -> None:
    """Seed the spill env from CLI flags (per-request overrides still win)."""
    if args.n_gpu_layers is not None:
        os.environ["HUGPY_N_GPU_LAYERS"] = str(args.n_gpu_layers)
    elif args.spill == "off":
        os.environ["HUGPY_N_GPU_LAYERS"] = "off"
    else:
        os.environ.setdefault("HUGPY_N_GPU_LAYERS", "auto")
    if args.gpu_mem is not None:
        os.environ["HUGPY_GPU_MEM_GIB"] = str(args.gpu_mem)
    if args.cpu_mem is not None:
        os.environ["HUGPY_CPU_MEM_GIB"] = str(args.cpu_mem)
    if args.tensor_split:
        os.environ["HUGPY_TENSOR_SPLIT"] = args.tensor_split
    if args.main_gpu is not None:
        os.environ["HUGPY_MAIN_GPU"] = str(args.main_gpu)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)

    if not args.central:
        print("error: --central (or WORKER_CENTRAL_URL) is required", file=sys.stderr)
        return 2

    _apply_cli_spill(args)

    advertise = args.advertise
    if not advertise:
        host = args.host if args.host not in ("0.0.0.0", "::") else socket.gethostbyname(socket.gethostname())
        advertise = f"http://{host}:{args.port}"

    state = WorkerState(name=args.name, url=advertise,
                        worker_id=_load_worker_id(args.id_file),
                        central_url=args.central)
    client = CentralClient(args.central)

    try:
        _register(client, state, args)
    except Exception as exc:
        logger.error("initial registration failed: %s", exc)
        # Keep going — the heartbeat loop will retry, and the server can still
        # serve a worker the operator registers manually.

    hb = threading.Thread(target=_heartbeat_loop, args=(client, state, args), daemon=True)
    hb.start()

    logger.info("worker inference server listening on %s (advertising %s)",
                f"{args.host}:{args.port}", state.url)
    build_app(state).run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
