from typing import Iterable, Sequence, Tuple

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from models.interest import Interest


class DialogCB(CallbackData, prefix="dlg"):
    """callback_data личных диалогов.

    Фабрика вместо склейки префиксов: старая схема (`like<id>`, `no<id>`)
    ломается на пересечениях префиксов, а здесь префикс «dlg» отделён
    двоеточием и не может совпасть с чужой кнопкой.

    action: reply — ответить автору входящего сообщения, open — открыть
    переписку из списка /dialogs, close — закрыть диалог,
    accept/decline — принять или отклонить приглашение (рулетка).
    """
    action: str
    peer_id: int


class RouletteCB(CallbackData, prefix="rlt"):
    """callback_data рулетки: pick — выбран интерес, cancel — отмена ожидания."""
    action: str
    interest_id: int


def dialog_reply_keyboard(peer_id: int) -> InlineKeyboardMarkup:
    """Кнопка «Ответить» под входящим сообщением.

    Открывает ввод ответа сразу этому пользователю, без захода в его профиль.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="Ответить 💬", callback_data=DialogCB(action="reply", peer_id=peer_id).pack())
    return builder.as_markup()


def dialog_invite_keyboard(peer_id: int) -> InlineKeyboardMarkup:
    """Приглашение в диалог: принять или отказаться."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Начать общение 💬", callback_data=DialogCB(action="accept", peer_id=peer_id).pack())
    builder.button(text="Не сейчас", callback_data=DialogCB(action="decline", peer_id=peer_id).pack())
    builder.adjust(1)
    return builder.as_markup()


def dialog_close_keyboard(peer_id: int) -> InlineKeyboardMarkup:
    """Завершение диалога кнопкой под сообщением.

    Дублирует «✖️ Завершить» с reply-клавиатуры: та может быть свёрнута,
    и тогда выход из режима диалога не виден.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="Завершить диалог ✖️", callback_data=DialogCB(action="close", peer_id=peer_id).pack())
    return builder.as_markup()


def dialogs_list_keyboard(partners: Sequence[Tuple[int, str]]) -> InlineKeyboardMarkup:
    """Список переписок: по кнопке «Открыть» на каждого собеседника.

    partners — пары (tg_chat_id, отображаемое имя). Имя в тексте кнопки
    экранировать не нужно: подписи кнопок Telegram разбирает как plain text.
    """
    builder = InlineKeyboardBuilder()
    for peer_id, title in partners:
        builder.button(text=f"Открыть: {title}",
                       callback_data=DialogCB(action="open", peer_id=peer_id).pack())
    builder.adjust(1)
    return builder.as_markup()


def roulette_interests_keyboard(interests: Iterable[Interest]) -> InlineKeyboardMarkup:
    """Выбор интереса для рулетки."""
    builder = InlineKeyboardBuilder()
    for interest in interests:
        if interest.id is None:
            continue
        builder.button(text=interest.title,
                       callback_data=RouletteCB(action="pick", interest_id=interest.id).pack())
    builder.adjust(2)
    return builder.as_markup()


def roulette_waiting_keyboard(interest_id: int) -> InlineKeyboardMarkup:
    """Отмена ожидания собеседника."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Отменить поиск ✖️",
                   callback_data=RouletteCB(action="cancel", interest_id=interest_id).pack())
    return builder.as_markup()
