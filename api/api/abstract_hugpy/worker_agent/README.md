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

## Run as a service (systemd)

To auto-start the agent on boot and restart it on crash, use the unit in
`deploy/`:

```bash
cd deploy
sudo ./install.sh
sudo nano /etc/abstract-hugpy-worker.env   # set WORKER_CENTRAL_URL etc.
sudo systemctl start abstract-hugpy-worker
journalctl -u abstract-hugpy-worker -f
```

`install.sh` creates a `hugpy` service user + state dir, installs the unit, and
enables it. All configuration lives in `/etc/abstract-hugpy-worker.env` (copied
from `deploy/abstract-hugpy-worker.env.example`); re-running the installer never
clobbers your edited env.

Three things to check/adjust in the unit for your box
(`/etc/systemd/system/abstract-hugpy-worker.service`):

1. **Python** — `ExecStart` must use a python that can `import abstract_hugpy`
   *and* has the GPU deps (CUDA `llama-cpp-python` and/or `torch`). For a venv:
   `ExecStart=/opt/abstract_hugpy/venv/bin/python -m abstract_hugpy.worker_agent`.
2. **GPU access** — the `hugpy` user must be in the group that owns the device
   nodes. Run `ls -l /dev/nvidia*`; the unit's `SupplementaryGroups=video render`
   covers the common case — edit if your distro differs.
3. **Storage + hardening** — the `hugpy` user must read/write your model storage
   (`DEFAULT_ROOT`). Hardening (`ProtectSystem`/`ProtectHome`) is shipped
   **commented out** because it commonly blocks `/dev/nvidia*` or model dirs; if
   you enable it, also set `ReadWritePaths=` to your storage root.

To wait for WireGuard, uncomment the `wg-quick@wg0` lines in the unit (change
`wg0` to your interface). Validate after editing with
`systemd-analyze verify abstract-hugpy-worker.service`.

## Endpoints the agent serves

| Method | Path            | Purpose                                  |
|--------|-----------------|------------------------------------------|
| GET    | `/health`       | id, GPUs, loaded models, spill snapshot  |
| POST   | `/infer`        | one-shot `{model_key, messages|prompt}`  |
| POST   | `/infer/stream` | SSE `token`/`done`/`error` events        |

`/infer*` accept an optional `spill` dict that overrides the split for the
model being loaded, and an inlined upload (`file_b64` + `file_name`) which the
agent materializes to a temp file before inference (see below).

## File & image chat offload

Vision/document/audio turns offload to workers too:

- **Images** are already inline base64 in the request, so they ride along to
  the worker untouched.
- **Uploaded files** live only on central (under `UPLOADS_HOME`), so central
  inlines the bytes as base64; the worker rebuilds them to a temp file, runs
  inference, and deletes the temp file. Files larger than 256 MB are kept on
  central (run locally) instead of inlining.

## Notes / limits

- One request runs entirely on one worker. This is whole-model routing with
  single-box GPU+CPU spill — **not** cross-machine layer splitting. See
  `CROSS_MACHINE_SPLIT.md` for the design of that future phase.
- Changing spill for an already-loaded model takes effect on its next load
  (restart the agent, or assign before first use).
