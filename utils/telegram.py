import logging
from typing import Any, List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InputMediaPhoto

logger = logging.getLogger(__name__)


async def safe_send_message(bot: Bot, chat_id: int, text: str, **kwargs: Any) -> bool:
    """Отправляет сообщение, не роняя хендлер, если получатель недоступен.

    Пользователь мог заблокировать бота или удалить чат — в этом случае
    Telegram отвечает ошибкой, и без перехвата падает весь сценарий
    (например, взаимный лайк не доходит даже до того, кто его поставил).
    """
    try:
        await bot.send_message(chat_id, text, **kwargs)
        return True
    except TelegramAPIError as e:
        logger.warning(f"Не удалось отправить сообщение в чат {chat_id}: {e}")
        return False


async def safe_send_media_group(bot: Bot, chat_id: int, media: List[InputMediaPhoto]) -> bool:
    if not media:
        return False
    try:
        await bot.send_media_group(chat_id, media=media)
        return True
    except TelegramAPIError as e:
        logger.warning(f"Не удалось отправить медиагруппу в чат {chat_id}: {e}")
        return False


async def safe_send_sticker(bot: Bot, chat_id: int, sticker_id: Optional[str]) -> bool:
    if not sticker_id:
        return False
    try:
        await bot.send_sticker(chat_id, sticker_id)
        return True
    except TelegramAPIError as e:
        logger.warning(f"Не удалось отправить стикер в чат {chat_id}: {e}")
        return False
