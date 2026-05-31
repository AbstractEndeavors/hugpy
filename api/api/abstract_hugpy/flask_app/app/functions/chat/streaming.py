from .imports import *

from flask import Response, stream_with_context
from pydantic import BaseModel
from typing import Optional, List


def sse_event(payload: dict) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


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
