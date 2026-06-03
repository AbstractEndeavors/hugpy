# Model slots (root-free, GPU-filling, swap overflow)

Instead of one always-on systemd unit per model (needs root per change, doesn't
scale to dozens of models), serving uses a small fixed pool of **generic slot
services**. Each slot runs at most one `llama-server` child; a model is assigned
to a free slot on demand, autofitting GPU layers from the VRAM still free — so
slots fill the card in order. When every slot is busy, new models route through
the **swap** proxy.

```
selected model ──> slot already serving it?  ── yes ─> use it
                   │ no
                   └> a free slot?            ── yes ─> load it there (autofit ngl)
                      │ no
                      └> all busy             ───────> swap proxy (on-demand)
```

No `systemctl`/root at request time: the app drives slots over HTTP.

## Pieces
- `slot_agent.py` — one slot supervisor. Owns a control/proxy port, spawns &
  health-checks its `llama-server` child, proxies `/v1/*` to it. `python -m
  abstract_hugpy.managers.serve.slot_agent`.
- `slots.py` — `SlotPool`: status/scheduling (`endpoint_for(model_key)`), plus
  the systemd template renderer/installer.
- `serve.serve_endpoint()` — prefers the pool for llama.cpp models, swap when full.

## Config (env)
| var | default | meaning |
|-----|---------|---------|
| `SLOT_COUNT` | `2` | number of slots (0 disables; serving falls back to swap/systemd) |
| `SLOT_PORT_BASE` | `8101` | slot N listens on `BASE + (N-1)`; child on `port + 1000` |
| `SLOT_ADVERTISE` | `127.0.0.1` | host the scheduler reaches slots on |
| `MAIN_GPU` | — | pin slot children to a GPU (`CUDA_VISIBLE_DEVICES`) |
| `LLAMA_SERVER_BIN` | `…/llama.cpp/build/bin/llama-server` | the CUDA-built server |

## One-time install (the only step that needs sudo)
```bash
# preview
curl -s http://127.0.0.1:6092/api/llm/slots/install | python -m json.tool
# it returns: write abstract-hugpy-slot@.service, then
sudo systemctl daemon-reload
sudo systemctl enable --now abstract-hugpy-slot@1
sudo systemctl enable --now abstract-hugpy-slot@2
```
After that, models load/unload over HTTP — no further root needed.

## Live control / status
```
GET  /api/llm/slots                 # what each slot serves + free VRAM
POST /api/llm/slots/load   {model_key}
POST /api/llm/slots/unload {control}
```
`llama-server` must be built with CUDA (`-DGGML_CUDA=on`) for the GPU to be used.
