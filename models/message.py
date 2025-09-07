from pydantic import BaseModel , Field
from datetime import datetime
from typing import Optional

class Message(BaseModel):
    id: Optional[int]
    sender_chat_id: str
    receiver_chat_id: str
    message_text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        # orm_mode = True # УДАЛЕНО
        from_attributes = True # ИСПРАВЛЕНО