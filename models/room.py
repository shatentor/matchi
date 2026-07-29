from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from config.settings import settings

# Режимы комнаты. relay — бот сам разносит сообщения участникам через Outbox;
# native — комната это реальная супергруппа Telegram (её id в Room.tg_chat_id),
# доставку берёт на себя Telegram, бот только выдаёт ссылку-приглашение.
ROOM_MODE_RELAY = "relay"
ROOM_MODE_NATIVE = "native"
ROOM_MODES = (ROOM_MODE_RELAY, ROOM_MODE_NATIVE)


class Room(BaseModel):
    """Комната по интересу из таблицы rooms.

    id и created_at проставляет БД, поэтому у них есть значения по умолчанию:
    в Pydantic v2 Optional без default — обязательное поле, и модель нельзя
    было бы собрать до вставки.

    tg_chat_id — id супергруппы (BIGINT) для режима native, а НЕ пользователь;
    у пользователей tg_chat_id хранится строкой, здесь это число.

    member_count заполняется запросами, которые считают участников вместе со
    списком комнат (одним запросом на весь каталог, без N+1). Своей колонки в
    таблице у него нет, поэтому значение по умолчанию — 0.
    """
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    interest_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    mode: str = ROOM_MODE_RELAY
    tg_chat_id: Optional[int] = None
    member_limit: int = settings.ROOM_MEMBER_LIMIT
    is_active: bool = True
    created_at: Optional[datetime] = None
    member_count: int = 0

    @property
    def is_native(self) -> bool:
        return self.mode == ROOM_MODE_NATIVE


class RoomMember(BaseModel):
    """Участник комнаты из таблицы room_members.

    tg_chat_id — пользователь, строкой, как в users.
    """
    model_config = ConfigDict(from_attributes=True)

    room_id: int
    tg_chat_id: str
    joined_at: Optional[datetime] = None
    muted_until: Optional[datetime] = None
