from typing import Iterable, List, Sequence

from aiogram import types
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder

from models.interest import Interest


class InterestCB(CallbackData, prefix="int"):
    """callback_data интересов.

    Фабрика вместо склейки префиксов: склейка в этом проекте уже дала коллизию
    ("message" внутри "message_to_all"), и для новых кнопок так больше не делаем.
    """
    action: str
    interest_id: int = 0


def interests_keyboard(interests: Sequence[Interest], selected_ids: Iterable[int]) -> types.InlineKeyboardMarkup:
    """Мультиселект интересов: выбранные помечены галочкой, по 2 в ряд."""
    selected = set(selected_ids)
    builder = InlineKeyboardBuilder()

    # Только row(): adjust() пересобрал бы разметку из плоского списка кнопок
    # и утащил бы «Готово» в общий ряд с интересами.
    row: List[types.InlineKeyboardButton] = []
    for interest in interests:
        mark = "✅ " if interest.id in selected else ""
        row.append(types.InlineKeyboardButton(
            text=f"{mark}{interest.title}",
            callback_data=InterestCB(action="toggle", interest_id=interest.id).pack()
        ))
        if len(row) == 2:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)

    builder.row(types.InlineKeyboardButton(
        text="Готово",
        callback_data=InterestCB(action="done").pack()
    ))
    return builder.as_markup()
