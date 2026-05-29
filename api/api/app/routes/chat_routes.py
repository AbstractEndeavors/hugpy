from ..functions import *
from ..functions.chat import *
from flask import request, Response

chat_bp,logger=get_bp("chat_router",__name__)


def _iter_sync(agen):
    """Drive an async generator from Flask's synchronous (WSGI) context."""
    loop = asyncio.new_event_loop()
    try:
        while True:
            try:
                yield loop.run_until_complete(agen.__anext__())
            except StopAsyncIteration:
                break
    finally:
        loop.close()


@chat_bp.route("/chat/stream", methods=["POST"])
def chat_stream():
    body = ChatBody(**(request.get_json(silent=True) or {}))
    return Response(
        _iter_sync(stream_events(body)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
