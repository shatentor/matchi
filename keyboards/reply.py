from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# Тексты кнопок вынесены в константы: по ним же строятся фильтры хендлеров
# в handlers/dialogs.py, и расхождение строк молча увело бы нажатие кнопки
# в релей — собеседник получил бы «✖️ Завершить» текстом.
DIALOG_FINISH = "✖️ Завершить"
DIALOG_PEER_PROFILE = "👤 Профиль собеседника"
DIALOG_COMPLAIN = "⛔ Пожаловаться"

DIALOG_BUTTONS = (DIALOG_FINISH, DIALOG_PEER_PROFILE, DIALOG_COMPLAIN)


def dialog_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура режима диалога.

    Здесь нужна именно reply-клавиатура, а не inline: она должна оставаться
    доступной всё время переписки, а не висеть под одним сообщением.
    """
    builder = ReplyKeyboardBuilder()
    builder.button(text=DIALOG_FINISH)
    builder.button(text=DIALOG_PEER_PROFILE)
    builder.button(text=DIALOG_COMPLAIN)
    builder.adjust(1, 2)
    return builder.as_markup(resize_keyboard=True,
                             input_field_placeholder="Сообщение собеседнику")


def remove_dialog_keyboard() -> ReplyKeyboardRemove:
    """Снимает клавиатуру диалога при выходе из режима переписки.

    Без этого кнопки остаются у пользователя и после закрытия диалога,
    а их нажатие уже никем не обрабатывается.
    """
    return ReplyKeyboardRemove()
