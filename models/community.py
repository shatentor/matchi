from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

# Telegram отдаёт id супергруппы с постоянным префиксом -100, а во внутренних
# ссылках t.me/c/... используется тот же id уже без него.
SUPERGROUP_ID_PREFIX = "-100"


def chat_internal_id(chat_id: Optional[int]) -> Optional[str]:
    """Внутренний id чата для ссылок вида t.me/c/<internal_id>/... .

    Префикс отрезается как строка, а не вычитается числом: длина внутреннего id
    у Telegram разная (у супергрупп, созданных позже, он длиннее), поэтому
    арифметика вроде `chat_id + 10**12` верна не для всех чатов.

    Обычная группа (id без -100) во внутренних ссылках не адресуется, для неё
    возвращается None.
    """
    if chat_id is None:
        return None

    raw = str(chat_id)
    if not raw.startswith(SUPERGROUP_ID_PREFIX):
        return None

    internal = raw[len(SUPERGROUP_ID_PREFIX):]
    return internal or None


def topic_link(chat_id: Optional[int], thread_id: Optional[int]) -> Optional[str]:
    """Ссылка на форум-топик супергруппы.

    Открывается только у тех, кто уже состоит в супергруппе: у закрытой группы
    публичного адреса нет, и попасть в неё можно лишь по ссылке-приглашению из
    create_chat_invite_link.
    """
    internal = chat_internal_id(chat_id)
    if internal is None or not thread_id:
        return None
    return f"https://t.me/c/{internal}/{thread_id}"


class Community(BaseModel):
    """Закрытая супергруппа сообщества из таблицы community.

    Ожидается ровно одна строка: сообщество одно.

    chat_id — id супергруппы (BIGINT со знаком, с префиксом -100), а не
    пользователь: у пользователей tg_chat_id хранится строкой, здесь это число.
    bound_at проставляет БД, поэтому у него есть значение по умолчанию — в
    Pydantic v2 Optional без default был бы обязательным полем.
    """
    model_config = ConfigDict(from_attributes=True)

    chat_id: int
    title: Optional[str] = None
    bound_at: Optional[datetime] = None

    @property
    def internal_id(self) -> Optional[str]:
        return chat_internal_id(self.chat_id)

    def topic_url(self, thread_id: Optional[int]) -> Optional[str]:
        return topic_link(self.chat_id, thread_id)
