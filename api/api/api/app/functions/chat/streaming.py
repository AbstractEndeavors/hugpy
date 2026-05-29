from .imports import *


def _last_user_message(messages):
    for msg in reversed(messages):
        role = getattr(msg, "role", None)
        if role == "user":
            return msg
    return None


def _images_from(msg):
    if msg is None:
        return None
    images = getattr(msg, "images", None)
    if not images:
        return None
    return [s for s in images if s]


async def stream_events(body: ChatBody):
    """Yield SSE lines from the runner's stream.

    Vision branch: if the last user message has images and the resolved runner
    is a VisionRunner, build a VisionRequest and emit a single one-shot token
    + done event. TODO: VisionRequest takes a single image today; multi-image
    support requires extending VisionRequest. TODO: vision_runner doesn't
    expose .stream() yet; when it does, plumb token streaming here.
    """
    try:
        from abstract_hugpy.managers.dispatch import runner_for
        from abstract_hugpy.imports.src.schemas.chat_schemas import ChatRequest

        runner = runner_for(model_key=body.model_key)

        last_user = _last_user_message(body.messages)
        pending_images = _images_from(last_user)

        if pending_images:
            from abstract_hugpy.managers.vision import VisionRunner
            from abstract_hugpy.managers.vision.schemas import VisionRequest

            if not isinstance(runner, VisionRunner):
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "error",
                            "message": "This model does not accept images.",
                        }
                    )
                    + "\n\n"
                )
                return

            vreq = VisionRequest(
                prompt=last_user.content or "Describe this image.",
                image_b64=pending_images[0],
            )

            result = runner.run(req=vreq)
            if inspect.isawaitable(result):
                result = await result

            text = getattr(result, "text", None) or str(result)
            yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'finish_reason': 'stop'})}\n\n"
            return

        req = ChatRequest(
            model_key=body.model_key,
            messages=[m.model_dump(exclude_none=True) for m in body.messages],
            max_new_tokens=body.max_new_tokens,
            temperature=body.temperature,
            do_sample=body.do_sample,
        )

        # Try streaming
        try:
            saw_token = False
            async for event in runner.stream(req):
                t = getattr(event, "type", None)
                if t == "token":
                    saw_token = True
                    yield f"data: {json.dumps({'type': 'token', 'text': event.text})}\n\n"
                elif t == "done":
                    yield f"data: {json.dumps({'type': 'done', 'finish_reason': getattr(event, 'finish_reason', 'stop')})}\n\n"
                    return
                elif t == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': event.message})}\n\n"
                    return
            # Stream exited without an explicit done. If we saw tokens, emit a
            # synthetic done so the client clears its placeholder; if not, fall
            # through to the non-streaming runner.run path.
            if saw_token:
                yield f"data: {json.dumps({'type': 'done', 'finish_reason': 'stop'})}\n\n"
                return
        except NotImplementedError:
            pass

        # Non-streaming fallback
        result = runner.run(req)
        if inspect.isawaitable(result):
            result = await result
        text = getattr(result, "text", str(result))
        yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'finish_reason': 'stop'})}\n\n"

    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'message': f'{type(exc).__name__}: {exc}'})}\n\n"
