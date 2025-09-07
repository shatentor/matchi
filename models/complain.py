from pydantic import BaseModel,Field
from datetime import datetime
from typing import Optional

class Complain(BaseModel):
    id: Optional[int]
    reporter_chat_id: str
    reported_chat_id: str
    reason: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        # orm_mode = True # УДАЛЕНО
        from_attributes = True # ИСПРАВЛЕНО