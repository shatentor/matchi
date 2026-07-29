import logging
from typing import Optional

from aiogram import Router
from aiogram.types import CallbackQuery, ErrorEvent, Message, Update

logger = logging.getLogger(__name__)

ERROR_TEXT = "Что-то сломалось, попробуйте позже."


def _describe_update(update: Optional[Update]) -> str:
    if update is None:
        return "неизвестный апдейт"
    try:
        return update.event_type
    except Exception:
        # event_type кидает UpdateTypeLookupError на незнакомом типе апдейта.
        return "неизвестный тип"


def _extract_event(update: Optional[Update]):
    """Достаёт сам объект события: у апдейта может не быть ни message, ни callback."""
    if update is None:
        return None
    try:
        return update.event
    except Exception:
        return None


async def _notify_user(event) -> None:
    """Пробует сообщить пользователю о сбое. Сам упасть не имеет права."""
    try:
        if isinstance(event, CallbackQuery):
            # Всплывающее уведомление: нового сообщения в чате не появится,
            # а «часики» на кнопке погаснут.
            await event.answer(ERROR_TEXT, show_alert=True)
        elif isinstance(event, Message):
            await event.answer(ERROR_TEXT)
    except Exception as e:
        logger.warning(f"Не удалось сообщить пользователю о сбое: {type(e).__name__}: {e}")


async def handle_error(event: ErrorEvent) -> bool:
    """Ловит всё, что не поймали хендлеры.

    Без этого обработчика необработанное исключение уходило только в лог,
    а пользователь оставался без ответа и не понимал, что произошло.
    """
    update = getattr(event, "update", None)
    source = _extract_event(update)
    user_id = getattr(getattr(source, "from_user", None), "id", None)

    logger.error(
        f"Необработанная ошибка в апдейте {_describe_update(update)} "
        f"(user_id={user_id}): {type(event.exception).__name__}: {event.exception}",
        exc_info=event.exception,
    )

    await _notify_user(source)
    # True — aiogram считает ошибку обработанной и не поднимает её выше.
    return True


def build_errors_router() -> Router:
    router = Router(name="errors")
    router.errors.register(handle_error)
    return router
