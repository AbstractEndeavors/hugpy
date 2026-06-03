# Phone Brick — distributed PPE detection

Run ONNX YOLO PPE detection across a fleet of cheap Android phones (Termux) and
collate their verdicts by **plurality consensus**. This is the packaged,
de-duplicated form of the field "phone-brick" scripts: one configurable worker
(replacing five near-identical copies) and one coordinator-free orchestrator.

```
phone_brick/
  detector.py       ONNX YOLO core: load + NMS + infer -> Detection list
  protocol.py       the worker<->orchestrator wire format (single source of truth)
  worker.py         the phone-side HTTP service (Flask)  -> Worker, build_app
  client.py         orchestrator-side HTTP client (push/drain)
  consensus.py      plurality consensus across phones
  rendering.py      draw per-phone boxes (cv2 optional)
  orchestrator.py   chain runner: fan one image across the chain
  schemas.py        typed configs + results (pydantic / dataclasses)
```

## Worker (on each phone)

The worker is **import-light** — it needs only `flask`, `onnxruntime`, `numpy`,
and `Pillow`, not the rest of `abstract_hugpy`. Configure it entirely via env:

```bash
MODEL_PATH=~/phone-brick/ppe-tanishjain-6class.onnx \
PORT=5002 \
python -m abstract_hugpy.phone_brick worker
```

Class names resolve in this order: an explicit list → a JSON sidecar next to the
model (`<model>.json`, `<model>.onnx.json`, or `classes.json`) → the built-in
6-class fallback (`Gloves, Vest, goggles, helmet, mask, safety_shoe`).

| Env var                    | Default                              |
|----------------------------|--------------------------------------|
| `MODEL_PATH`               | `~/phone-brick/ppe-tanishjain-6class.onnx` |
| `PORT` / `HOST`            | `5002` / `0.0.0.0`                    |
| `YOLO_IMGSZ` / `YOLO_CONF` | `640` / `0.25`                       |
| `PHONE_BRICK_ENABLE_SHELL` | unset (the `sh` verb is **disabled**)|

The legacy `sh <command>` verb (arbitrary shell execution) is **off by default**
and only enabled with `PHONE_BRICK_ENABLE_SHELL=1`, on a network you trust.

### Wire protocol

```
POST /queue   {"task": "yolo <image_url>"}  -> {"status": "queued", "id": ...}
GET  /results                                -> [ {id, status, result}, ... ]
GET  /status                                 -> health + model + class info
```

`yolo` output is parsed back by `protocol.parse_detections`; the format lives in
`protocol.py` so the worker and orchestrator can't drift apart.

## Orchestrator (on a control box)

No coordinator required — point it at a chain and an image:

```bash
python -m abstract_hugpy.phone_brick orchestrate \
    --image image100.jpg \
    --file-server http://192.168.0.26:8088/chain-outputs/ \
    --phones red:192.168.0.32:5002:#f85149,blue:192.168.0.70:5003:#58a6ff
```

It seeds the image where the file server serves it, pushes a `yolo` task to each
phone, parses the detections, computes consensus (`AGR`/`DIS`/`NOD` per phone),
and writes an annotated copy with every phone's boxes drawn in its colour. The
result filename encodes each phone's verdict:

```
image100__red__helmet_88_AGR__1716...__blue__helmet_91_AGR__1716....jpg
```

### As a library

```python
from abstract_hugpy.phone_brick import (
    ChainConfig, ChainOrchestrator, PhoneSpec,
)

config = ChainConfig(
    phones=[
        PhoneSpec("red", "192.168.0.32", 5002, "#f85149"),
        PhoneSpec("blue", "192.168.0.70", 5003, "#58a6ff"),
    ],
    file_server="http://192.168.0.26:8088/chain-outputs/",
)
result = ChainOrchestrator(config).run("image100.jpg", "chain-outputs")
for phase in result.phases:
    print(phase.phone, phase.top_cls, phase.consensus)
```
