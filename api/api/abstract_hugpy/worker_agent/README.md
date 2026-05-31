# GPU Worker Agent

Donate a remote GPU's compute to the central abstractgpt console. The agent
registers with central, heartbeats, and serves inference for the models central
assigns to it — loading each model on its own GPU, spilling overflow layers to
CPU/RAM when a model is bigger than VRAM.

## Quick start

On the GPU box (must have `abstract_hugpy` importable + its inference deps —
`llama-cpp-python` built with CUDA for GGUF, and/or `torch`+`transformers`):

```bash
python -m abstract_hugpy.worker_agent \
    --central https://abstractgpt.ai \
    --name laptop-4060 \
    --port 9100
```

Then open the console → **GPU Workers** panel → find the worker → attach any
model from the table to it. Chats with that model now route to this GPU.

Over WireGuard, point `--central` at central's WG address and let `--advertise`
default to the worker's own WG IP (or set it explicitly):

```bash
python -m abstract_hugpy.worker_agent \
    --central http://10.6.0.1 \
    --advertise http://10.6.0.2:9100 \
    --name laptop-4060
```

## GPU/CPU spill (hybrid compute)

By default the worker runs in **autofit**: it detects free VRAM, estimates the
model size, and puts as many layers on the GPU as will fit — the rest run on
CPU/RAM. An 8 GB card can therefore serve a model larger than 8 GB (slower, but
it runs).

- `--spill auto` (default) — autofit.
- `--spill off` — CPU only.
- `--n-gpu-layers N` — llama.cpp: force N transformer layers onto the GPU.
- `--gpu-mem GiB` / `--cpu-mem GiB` — transformers: per-GPU and CPU memory
  budgets handed to `device_map="auto"`.
- `--tensor-split 0.7,0.3` / `--main-gpu I` — multi-GPU on one box.

These set process-wide defaults. The console can also attach a **per-model**
override when you assign a model (the "▸ split" control in the Workers panel);
that override is sent with each inference request and wins over the defaults.

## Model provisioning (central-first)

If the worker doesn't have a model's files, it fetches them before loading:

1. **From central** over HTTP (`/api/llm/models/<key>/manifest` + `/file`) —
   no Hugging Face token needed on the worker; reuses what central already has.
   Transfers are chunked and resumable (HTTP Range).
2. **From Hugging Face** as a fallback (the normal `ensure_model` path) if
   central doesn't have the model or is unreachable.

Files land under the worker's own storage root using the same on-disk layout as
central, so the loader finds them with no extra config.

## Endpoints the agent serves

| Method | Path            | Purpose                                  |
|--------|-----------------|------------------------------------------|
| GET    | `/health`       | id, GPUs, loaded models, spill snapshot  |
| POST   | `/infer`        | one-shot `{model_key, messages|prompt}`  |
| POST   | `/infer/stream` | SSE `token`/`done`/`error` events        |

`/infer*` accept an optional `spill` dict that overrides the split for the
model being loaded.

## Notes / limits

- One request runs entirely on one worker. This is whole-model routing with
  single-box GPU+CPU spill — **not** cross-machine layer splitting. See
  `CROSS_MACHINE_SPLIT.md` for the design of that future phase.
- Changing spill for an already-loaded model takes effect on its next load
  (restart the agent, or assign before first use).
- File/image chat turns currently stay on central (the upload lives there).
