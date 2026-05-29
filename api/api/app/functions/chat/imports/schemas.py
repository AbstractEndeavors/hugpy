from __future__ import annotations

from .init_imports import *
class Message(BaseModel):
    role: str
    content: str
    images: List[str] | None = None


class ChatBody(BaseModel):
    model_key: str
    messages: List[Message]
    max_new_tokens: int = 2048
    temperature: float = 0.1
    do_sample: bool = False
