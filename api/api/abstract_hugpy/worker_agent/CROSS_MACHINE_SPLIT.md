# Phase 2 (design only): cross-machine layer split

> Status: **not implemented.** This documents how we'd split ONE model across
> several machines' GPUs over the network — e.g. run a 70B across the server +
> the laptop + a GPU on another network — vs. today's whole-model routing with
> single-box GPU+CPU spill.

## Why it's a separate phase

Today each request runs entirely on one worker (`pick_worker_for_model` →
`/infer/stream`). Splitting a single model's layers across machines is a
fundamentally different execution model: every token's forward pass crosses the
network between layer groups, so it needs a real distributed-inference engine
and is dominated by interconnect latency.

## Realistic approaches

1. **llama.cpp RPC backend** (best fit for our GGUF path)
   - `llama.cpp` ships `rpc-server`: each GPU box runs one, exposing its device
     over TCP. The driver lists `--rpc host1:port,host2:port` and llama.cpp
     shards layers across them (local + remote).
   - Maps cleanly onto what we have: the worker agent gains a `--rpc-server`
     mode (just runs `rpc-server`), and central (or a designated lead worker)
     builds the `Llama(..., rpc_servers=...)` with a `tensor_split` across the
     pool. The registry already tracks each box's URL + free VRAM, which is
     exactly the input the split planner needs.
   - Over WireGuard this is feasible on a LAN-ish link; cross-Internet hops
     will be slow per token but functional.

2. **Petals / distributed transformers** (for the HF/transformers path)
   - Petals-style: each node hosts a contiguous block of transformer layers and
     forwards activations. Heavier to operate; better for very large models with
     many participants. Likely overkill for a handful of personal GPUs.

## What we'd add on top of the current code

- **Registry**: a `rpc_endpoint` field per worker (already have `url`, `gpus`,
  free VRAM via heartbeat).
- **Roles**: extend the existing `role` field — `worker` (whole-model, today),
  `rpc` (contributes its GPU to a shard pool), `lead` (drives a split model).
- **A split planner**: given a model's size + each pool member's free VRAM,
  produce the `tensor_split` / layer assignment. The autofit math in
  `managers/spill.py` is the single-box version of this and would generalize.
- **Selection**: `pick_for_model` gains a branch — if a model is flagged
  "sharded", gather the rpc pool and route to the lead instead of one worker.
- **Provisioning**: every rpc node needs the weights locally; the central-first
  provisioning built in Phase 1 already covers that.

## Why we didn't default to this

For the actual hardware in play (an 8 GB 4060, plus GPUs on other networks),
**modular whole-model routing + single-box spill wins almost every time**:
a model that fits on one card runs fastest there, and splitting a small/mid
model across a WAN only adds latency. Cross-machine split earns its keep only
for models too big for any single available GPU — at which point the
llama.cpp RPC backend is the path of least resistance.
