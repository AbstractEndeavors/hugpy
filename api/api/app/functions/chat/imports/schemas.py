from .init_imports import *
class Message(BaseModel):
    role: str
    content: str


class ChatBody(BaseModel):
    model_key: str
    messages: List[Message]
    max_new_tokens: int = 2048
    temperature: float = 0.1
    do_sample: bool = False
