from pydantic import BaseModel
from typing import Optional

class Dislike(BaseModel):
    disliker_chat_id: str
    disliked_chat_id: str

    class Config:
        orm_mode = True