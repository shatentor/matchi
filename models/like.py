from pydantic import BaseModel
from typing import Optional

class Like(BaseModel):
    liker_chat_id: str
    liked_chat_id: str

    class Config:
        # orm_mode = True # УДАЛЕНО
        from_attributes = True # ИСПРАВЛЕНО