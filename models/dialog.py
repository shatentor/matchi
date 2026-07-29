from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime, timezone
from typing import Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Dialog(BaseModel):
    """Личный диалог двух пользователей из таблицы dialogs.

    Пара хранится упорядоченной: в схеме есть CHECK (user_one < user_two),
    поэтому user_one — это не инициатор, а меньший из двух tg_chat_id
    (сравнение строковое, колонки VARCHAR(20)). Кто начал диалог, хранится
    только косвенно в source.

    id проставляет БД (SERIAL), closed_at заполняется при закрытии, поэтому
    у обоих есть значение по умолчанию: в Pydantic v2 Optional без default —
    обязательное поле, и модель нельзя было бы собрать до вставки.
    """
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    user_one: str
    user_two: str
    source: str = "profile"
    created_at: datetime = Field(default_factory=_utc_now)
    closed_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return self.closed_at is None
