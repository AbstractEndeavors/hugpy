from ..functions import *
from ..functions.chat import *
chat_bp,logger=get_bp("chat_router",__name__)

@chat_bp.route("/chat/stream", methods=["POST"])
async def chat_stream(body: ChatBody):
    return StreamingResponse(
        stream_events(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
