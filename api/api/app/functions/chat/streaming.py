from .imports import *
async def stream_events(body: ChatBody):
    """Yield SSE lines from the runner's stream."""
    try:
        from abstract_hugpy.managers.dispatch import runner_for
        from abstract_hugpy.imports.src.schemas.chat_schemas import ChatRequest

        runner = runner_for(model_key=body.model_key)
        req = ChatRequest(
            model_key=body.model_key,
            messages=[m.model_dump() for m in body.messages],
            max_new_tokens=body.max_new_tokens,
            temperature=body.temperature,
            do_sample=body.do_sample,
        )

        # Try streaming
        try:
            async for event in runner.stream(req):
                t = getattr(event, "type", None)
                if t == "token":
                    yield f"data: {json.dumps({'type': 'token', 'text': event.text})}\n\n"
                elif t == "done":
                    yield f"data: {json.dumps({'type': 'done', 'finish_reason': getattr(event, 'finish_reason', 'stop')})}\n\n"
                    return
                elif t == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': event.message})}\n\n"
                    return
            return
        except NotImplementedError:
            pass

        # Non-streaming fallback
        result = await runner.run(req)
        text = getattr(result, "text", str(result))
        yield f"data: {json.dumps({'type': 'token', 'text': text})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'finish_reason': 'stop'})}\n\n"

    except Exception as exc:
        yield f"data: {json.dumps({'type': 'error', 'message': f'{type(exc).__name__}: {exc}'})}\n\n"
