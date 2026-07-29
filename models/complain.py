from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime, timezone
from typing import Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Complain(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    reporter_chat_id: str
    reported_chat_id: str
    reason: str
    timestamp: datetime = Field(default_factory=_utc_now)
