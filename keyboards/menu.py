from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class MenuCB(CallbackData, prefix="menu"):
    """Кнопки главного меню. Фабрика, а не склейка префиксов: в проекте
    склейка уже приводила к коллизии ("message" внутри "message_to_all")."""

    action: str


def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # Только row(): adjust() переразбивает все ряды и ломает явную разметку.
    builder.row(
        _button("🔍 Искать людей", "search"),
        _button("💬 Переписки", "dialogs"),
    )
    builder.row(
        _button("🎲 Рулетка", "roulette"),
        _button("🏠 Комнаты", "rooms"),
    )
    builder.row(
        _button("👤 Мой профиль", "profile"),
        _button("🎯 Интересы", "interests"),
    )
    builder.row(_button("⚙️ Ещё", "extra"))
    return builder.as_markup()


def extra_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("💞 Взаимные лайки", "mutual"),
        _button("✏️ Изменить профиль", "edit_profile"),
    )
    builder.row(
        _button("✉️ Написать админу", "support"),
        _button("❓ Помощь", "help"),
    )
    builder.row(_button("⬅️ Назад", "main"))
    return builder.as_markup()


def _button(text: str, action: str):
    from aiogram.types import InlineKeyboardButton

    return InlineKeyboardButton(text=text, callback_data=MenuCB(action=action).pack())
