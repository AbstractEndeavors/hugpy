from .imports import *

from flask import Response, stream_with_context
from pydantic import BaseModel
from typing import Optional, List


def sse_event(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


# An uploaded file is shipped to the worker inline (base64) so vision/doc/audio
# chat can offload too. Above this size we keep the turn local rather than load
# a huge file into memory + JSON.
_MAX_WORKER_FILE_BYTES = 256 * 1024 * 1024


def _inline_file_for_worker(worker_kwargs: dict) -> bool:
    """Replace a local upload path with inline bytes the worker can rebuild.

    Central's ``file`` is a path under UPLOADS_HOME that only exists here. Read
    it, base64 it into ``file_b64`` + ``file_name``, and drop ``file`` so the
    worker materializes it to its own temp path. Returns False (→ run locally)
    if the file is missing or too big to inline.
    """
    import os
    import base64

    path = worker_kwargs.get("file")
    if not path:
        return True  # nothing to inline; images (if any) go as-is
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > _MAX_WORKER_FILE_BYTES:
            return False
        with open(path, "rb") as fh:
            worker_kwargs["file_b64"] = base64.b64encode(fh.read()).decode("ascii")
        worker_kwargs["file_name"] = os.path.basename(path)
        worker_kwargs.pop("file", None)
        return True
    except OSError:
        return False


async def _proxy_worker_stream(worker: dict, prompt_kwargs: dict):
    """Relay an assigned GPU worker's SSE inference stream.

    The worker agent exposes ``POST {url}/infer/stream`` and emits the same
    ``token`` / ``done`` / ``error`` SSE events the browser already understands,
    so we forward its lines through unchanged. Raising before the first byte
    lets the caller fall back to local execution.
    """
    import httpx

    url = worker["url"].rstrip("/") + "/infer/stream"
    timeout = httpx.Timeout(600.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=prompt_kwargs) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    yield (line + "\n\n").encode("utf-8")


def chat_iter_sync(agen):
    """Drive an async generator from Flask's synchronous WSGI context."""
    loop = asyncio.new_event_loop()

    try:
        asyncio.set_event_loop(loop)

        while True:
            try:
                item = loop.run_until_complete(agen.__anext__())

                if isinstance(item, str):
                    item = item.encode("utf-8")

                yield item

            except StopAsyncIteration:
                break

    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass

        asyncio.set_event_loop(None)
        loop.close()


async def stream_events(body: ChatBody):
    from abstract_hugpy.managers.dispatch import execute_prompt

    prompt_kwargs = {
        "max_new_tokens": body.max_new_tokens,
    }


    if body.model_key:
        prompt_kwargs["model_key"] = body.model_key

    if body.temperature is not None:
        prompt_kwargs["temperature"] = body.temperature

    if body.do_sample is not None:
        prompt_kwargs["do_sample"] = body.do_sample

    if body.messages:
        prompt_kwargs["messages"] = messages_to_dicts(body.messages)
    else:
        prompt_kwargs["prompt"] = body.prompt

    if body.file:
        prompt_kwargs["file"] = body.file
    if body.images:
        prompt_kwargs["images"] = body.images

    logger.info("prompt_kwargs == %s", prompt_kwargs)

    # ── GPU worker offload ────────────────────────────────────────────────
    # If an online worker is assigned to this model, hand the whole request to
    # its GPU and relay the stream. Images ride along inline (already base64);
    # an uploaded file is inlined as bytes the worker rebuilds. Any failure
    # before the worker emits a token falls through to local execution below.
    offloadable = bool(body.model_key)
    worker = None
    if offloadable:
        try:
            from ..imports.utils.workers import pick_worker_for_model
            worker = pick_worker_for_model(body.model_key)
        except Exception:
            worker = None

    if worker:
        # Attach this worker's per-assignment spill override (if any) so the
        # worker loads the model with the operator's chosen GPU/CPU split.
        worker_kwargs = dict(prompt_kwargs)
        try:
            from ..imports.utils.workers import spill_for
            spill = spill_for(worker.get("id"), body.model_key)
            if spill:
                worker_kwargs["spill"] = spill
        except Exception:
            pass

        # Ship any uploaded file to the worker; if it can't be inlined
        # (missing / too large), skip offload and run this turn locally.
        if not _inline_file_for_worker(worker_kwargs):
            logger.info("file too large/absent to offload; running %s locally", body.model_key)
            worker = None

    if worker:
        produced_any = False
        try:
            async for chunk in _proxy_worker_stream(worker, worker_kwargs):
                produced_any = True
                yield chunk
            if produced_any:
                return
            logger.warning("worker %s produced no output; falling back to local", worker.get("id"))
        except Exception as exc:
            logger.warning("worker offload failed (%s); falling back to local", exc)
            if produced_any:
                # Stream already started — don't replay it locally.
                yield sse_event({"type": "error", "message": f"worker stream interrupted: {exc}"})
                return

    try:
        result = execute_prompt(**prompt_kwargs)

        if inspect.isawaitable(result):
            result = await result

        if getattr(result, "ok", True):
            text = getattr(result, "text", None) or str(result)

            yield sse_event({
                "type": "token",
                "text": text,
            })

            yield sse_event({
                "type": "done",
                "finish_reason": getattr(result, "finish_reason", None) or "stop",
            })

        else:
            yield sse_event({
                "type": "error",
                "message": getattr(result, "error", None) or "run failed",
            })

    except Exception as exc:
        logger.exception("stream_events failed")

        yield sse_event({
            "type": "error",
            "message": str(exc),
        })


def chat_stream(mimetype=None, headers=None, **kwargs):
    logger.info(kwargs)
    body = ChatBody(**kwargs)

    return Response(
        stream_with_context(chat_iter_sync(stream_events(body))),
        mimetype=mimetype or "text/event-stream",
        headers=headers or {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
        direct_passthrough=True,
    )
