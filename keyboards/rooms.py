from typing import List, Optional, Sequence

from aiogram import types
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder

from models.interest import Interest
from models.room import Room


class RoomCB(CallbackData, prefix="room"):
    """callback_data комнат.

    Фабрика вместо склейки префиксов: склейка в этом проекте уже дала коллизию
    ("message" внутри "message_to_all"), и для новых кнопок так больше не делаем.

    action: list | open | join | leave | history | complain | filter | pick | exit
    """
    action: str
    room_id: int = 0
    interest_id: int = 0


def _room_button_text(room: Room) -> str:
    limit = room.member_limit
    mark = "🧵" if room.is_topic else ("🏛" if room.is_native else "💬")
    return f"{mark} {room.title} · {room.member_count}/{limit}"


def rooms_keyboard(rooms: Sequence[Room], with_filter: bool = True,
                   filtered: bool = False) -> types.InlineKeyboardMarkup:
    """Каталог комнат: по одной в ряд, с числом участников.

    Только row(): adjust() пересобирает разметку из плоского списка кнопок и
    утащил бы «Фильтр» в общий ряд с комнатами.
    """
    builder = InlineKeyboardBuilder()

    for room in rooms:
        builder.row(types.InlineKeyboardButton(
            text=_room_button_text(room),
            callback_data=RoomCB(action="open", room_id=room.id or 0).pack()
        ))

    controls: List[types.InlineKeyboardButton] = []
    if with_filter:
        controls.append(types.InlineKeyboardButton(
            text="Фильтр по интересу",
            callback_data=RoomCB(action="filter").pack()
        ))
    if filtered:
        controls.append(types.InlineKeyboardButton(
            text="Все комнаты",
            callback_data=RoomCB(action="list").pack()
        ))
    if controls:
        builder.row(*controls)

    return builder.as_markup()


def room_card_keyboard(room: Room, is_member: bool) -> types.InlineKeyboardMarkup:
    """Карточка комнаты: вход/выход, история, жалоба."""
    builder = InlineKeyboardBuilder()
    room_id = room.id or 0

    if is_member:
        first_row = [types.InlineKeyboardButton(
            text="Открыть" if room.is_native else "Войти в чат",
            callback_data=RoomCB(action="join", room_id=room_id).pack()
        ), types.InlineKeyboardButton(
            text="Выйти",
            callback_data=RoomCB(action="leave", room_id=room_id).pack()
        )]
    else:
        first_row = [types.InlineKeyboardButton(
            text="Войти",
            callback_data=RoomCB(action="join", room_id=room_id).pack()
        )]
    builder.row(*first_row)

    second_row = []
    if not room.is_native:
        # История хранится в room_messages только для режима relay
        second_row.append(types.InlineKeyboardButton(
            text="История",
            callback_data=RoomCB(action="history", room_id=room_id).pack()
        ))
    second_row.append(types.InlineKeyboardButton(
        text="Пожаловаться",
        callback_data=RoomCB(action="complain", room_id=room_id).pack()
    ))
    builder.row(*second_row)

    builder.row(types.InlineKeyboardButton(
        text="К списку комнат",
        callback_data=RoomCB(action="list").pack()
    ))
    return builder.as_markup()


def room_interests_keyboard(interests: Sequence[Interest]) -> types.InlineKeyboardMarkup:
    """Интересы как фильтр каталога, по 2 в ряд."""
    builder = InlineKeyboardBuilder()

    row: List[types.InlineKeyboardButton] = []
    for interest in interests:
        row.append(types.InlineKeyboardButton(
            text=interest.title,
            callback_data=RoomCB(action="pick", interest_id=interest.id or 0).pack()
        ))
        if len(row) == 2:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)

    builder.row(types.InlineKeyboardButton(
        text="Все комнаты",
        callback_data=RoomCB(action="list").pack()
    ))
    return builder.as_markup()


def room_chat_keyboard(room_id: int) -> types.InlineKeyboardMarkup:
    """Клавиатура режима relay-комнаты: выход из чата."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="Выйти из чата комнаты",
        callback_data=RoomCB(action="exit", room_id=room_id).pack()
    ))
    return builder.as_markup()


def native_invite_keyboard(invite_link: Optional[str], room_id: int,
                           topic_url: Optional[str] = None) -> types.InlineKeyboardMarkup:
    """Вход в native-комнату: топик и ссылка-приглашение в супергруппу.

    Режима чата у native-комнаты нет: сообщения разносит сам Telegram,
    бот только открывает доступ.

    Ссылка на топик (t.me/c/...) работает лишь у тех, кто уже состоит в
    закрытой супергруппе, поэтому рядом идёт одноразовое приглашение.
    Любая из двух ссылок может отсутствовать: топика нет у комнаты, привязанной
    к группе целиком, а приглашение не выдаётся, если у бота нет прав.
    """
    builder = InlineKeyboardBuilder()

    if topic_url:
        builder.row(types.InlineKeyboardButton(text="Открыть топик", url=topic_url))
    if invite_link:
        builder.row(types.InlineKeyboardButton(
            text="Войти в супергруппу" if topic_url else "Перейти в комнату",
            url=invite_link
        ))

    builder.row(types.InlineKeyboardButton(
        text="К списку комнат",
        callback_data=RoomCB(action="list", room_id=room_id).pack()
    ))
    return builder.as_markup()


def community_invite_keyboard(invite_link: str) -> types.InlineKeyboardMarkup:
    """Одноразовое приглашение в закрытую супергруппу сообщества."""
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="Войти в сообщество", url=invite_link))
    return builder.as_markup()
