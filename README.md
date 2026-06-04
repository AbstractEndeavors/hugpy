# abstractgpt

> **Self-hosted, GPU-pooling inference for open-source LLMs and vision models.**
> abstractgpt turns the hardware you already own — a workstation, a gaming
> laptop, GPUs on another network, even a rack of Android phones — into one
> managed inference cluster behind a single web console. Central distributes the
> models, fills each GPU on demand, and degrades gracefully (CPU spill,
> on-demand model swapping, parallel/resumable transfer) so you get private,
> OpenAI-style inference on hardware you control. No third-party API keys, no
> per-token bill — your models, your machines.

---

## Why

Renting GPU inference is expensive and sends your prompts to someone else's
servers. Meanwhile most teams already have idle GPUs scattered around. The hard
parts of using them are operational, not theoretical:

- getting the *same* (often multi-GB, sometimes gated) model onto every box,
- fitting models into limited VRAM without OOMing,
- standing up model servers without hand-editing systemd units as root,
- keeping a long conversation from blowing past a model's context window.

abstractgpt solves these so a heterogeneous pile of hardware behaves like one
inference endpoint.

---

## Architecture

```
        ┌──────────────────────────────┐
        │   Web console (React)        │   models · GPU workers · chat
        └───────────────┬──────────────┘
                        │  HTTP / SSE
        ┌───────────────┴──────────────┐
        │   Central (Flask API)        │   registry · model storage · router
        └───┬───────────────┬──────────┘
            │ register/HB    │ pull model files (parallel, resumable)
   ┌────────┴───────┐  ┌─────┴────────────┐
   │ GPU worker(s)  │  │ Model slots      │   on-demand llama-server
   │ (donate a GPU) │  │ (root-free pool) │   children, GPU-filling
   └────────────────┘  └──────────────────┘
```

Inference is whole-model routing with single-box GPU+CPU spill — the right
model runs on the right GPU; overflow layers fall to CPU/RAM.

---

## Features

**Model distribution (central is the source of truth)**
- Workers pull a model's **entire directory** from central over HTTP —
  **parallel + byte-range-segmented** (a multi-GB weights file isn't stuck on
  one connection), **resumable**, and **verified** (complete-or-raise, never a
  silent partial), with a single-stream **tar archive** fallback.
- Works for **gated models** that can't be pulled from Hugging Face without
  auth: if central has it, workers get it.
- Workers learn models they weren't built with — they fetch the model's config
  from central and register it locally.

**GPU packing & serving**
- **Model slots** — a small, fixed pool of *generic*, **root-free** services.
  Selecting a model loads it into a free slot, autofitting GPU layers from the
  VRAM still free, so slots fill the card in order. When all are busy, overflow
  routes to an on-demand **swap** proxy. No `systemctl`/sudo at request time.
- **GPU/CPU spill (autofit)** — an 8 GB card can serve a model larger than 8 GB.
- **Per-model serving control from the console** — mode · GPU layers · CPU
  threads · context — persisted and applied.
- Backends: **llama.cpp** (GGUF, native `llama-server` or in-process),
  **transformers** (`device_map="auto"` with memory budgets), **Qwen-VL** vision.

**Robust inference**
- **Context fitting** — long conversations are trimmed token-accurately to the
  model's real `n_ctx` (using the model's own tokenizer) instead of erroring,
  with auto-continuation for long *outputs*.
- Streaming (SSE), cancellation, continuation.

**Distributed computer vision — "phone brick"**
- ONNX YOLO PPE detection across a fleet of cheap Android phones (Termux): fan
  one image across the chain and collate verdicts by **plurality consensus**,
  with annotated output. One consolidated worker, one coordinator-free
  orchestrator.

**Operability**
- `/health` surfaces real GPU usability — `torch.cuda.is_available()` **and**
  llama.cpp GPU-offload support — so "the GPU is idle" is diagnosable.

---

## Repository layout

```
api/api/abstract_hugpy/
  flask_app/            central Flask API (registry, storage, routes)
  worker_agent/         GPU worker: register/heartbeat, /infer, provisioning
  managers/
    serve/              serving: slots, llama-server units, swap, per-model config
      slot_agent.py     one root-free model slot (spawns a llama-server child)
      slots.py          slot scheduler/pool + one-time install helpers
      slots_launch.py   run the slot pool WITHOUT systemd (detached processes)
      serve.py          serving modes + endpoint resolution
      overrides.py      persisted per-model serving overrides (UI-writable)
    llama/ generate/ vision/ embed/ whisper_model/   inference backends
    dispatch/ resolvers/ chat_context/ spill.py      routing, context, GPU/CPU spill
  model_sync.py         pull whole model directories from central (CLI + lib)
  phone_brick/          distributed PPE detection across phones + orchestrator
app/                    React console (models, GPU workers, chat)
scripts/                helper scripts (deploy, gen_install_requires, …)
docs/                   project docs (incl. socialDescription.md)
```

---

## Quickstart

**Central** — run the Flask API (behind gunicorn) and the console; point storage
at a disk with room for your models.

**Donate a GPU (worker)** — on any box with a GPU and `abstract_hugpy` installed:
```bash
python -m abstract_hugpy.worker_agent --central https://your-central --name laptop-4060
```
Open the console → **GPU Workers** → assign a model. The worker pulls it from
central (parallel/resumable) if it doesn't have it.

**Run GPU slots without systemd:**
```bash
export SLOT_COUNT=2 MAIN_GPU=0 \
       LLAMA_SERVER_BIN=/path/to/llama.cpp/build/bin/llama-server
python -m abstract_hugpy.managers.serve.slots_launch start   # status | stop | restart
```
Selecting a GGUF model loads it into a free slot, filling the GPU in order; when
full, overflow goes through swap. See `api/api/abstract_hugpy/managers/serve/SLOTS.md`.

**Sync models to a box:**
```bash
python -m abstract_hugpy.model_sync --central https://your-central --all
```

**Distributed PPE detection (optional):**
```bash
# on each phone (Termux):
python -m abstract_hugpy.phone_brick worker
# on a control box:
python -m abstract_hugpy.phone_brick orchestrate --image img.jpg \
    --file-server http://192.168.0.26:8088/chain-outputs/ \
    --phones red:192.168.0.32:5002,blue:192.168.0.70:5003
```

---

## Configuration (selected env)

| Variable | Purpose |
|---|---|
| `WORKER_CENTRAL_URL` | central URL a worker registers with |
| `HUGPY_PULL_CONCURRENCY` | parallel connections per model transfer (default 8) |
| `SLOT_COUNT` / `SLOT_PORT_BASE` | model-slot pool size / base port |
| `MAIN_GPU` | pin slot children to a GPU |
| `LLAMA_SERVER_BIN` | path to a CUDA-built `llama-server` |
| `DEFAULT_SERVE_MODE` | `systemd` \| `swap` \| `off` |

---

## Requirements

- **Central:** Python 3.11+, Flask/gunicorn, disk for model storage.
- **GPU worker / slots:** a CUDA build of `llama-cpp-python` (GGUF) and/or
  `torch`+`transformers`; `llama-server` built with `-DGGML_CUDA=on` for the
  slot pool.
- **Phone brick:** Termux + `onnxruntime`, `numpy`, `Pillow`, `flask`.

---

## License

See [`LICENSE`](./LICENSE).
