from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime, timezone
from typing import Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Message(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    sender_chat_id: str
    receiver_chat_id: str
    message_text: str
    timestamp: datetime = Field(default_factory=_utc_now)
