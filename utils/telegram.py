import asyncio
import logging
from typing import Any, List, Optional

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import InputMediaPhoto

from config.settings import settings

logger = logging.getLogger(__name__)

# Telegram продолжает отвечать флуд-контролем, если начать ровно в указанную
# секунду, поэтому к retry_after добавляем небольшой запас.
RETRY_AFTER_MARGIN = 0.5
# Пауза перед повтором после сетевой ошибки или 5xx.
NETWORK_RETRY_DELAY = 1.0


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


async def send_with_retry(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    attempts: int = settings.SEND_RETRY_ATTEMPTS,
    **kwargs: Any,
) -> bool:
    """Отправляет сообщение с повторами и сообщает, дошло ли оно.

    В отличие от safe_send_message предназначена для веерной рассылки и релея
    сообщений между пользователями, где молча потерять сообщение нельзя.
    Восстановимые ошибки повторяются: флуд-контроль (TelegramRetryAfter) —
    после ожидания указанного Telegram времени, сетевые сбои и 5xx — после
    короткой паузы. Блокировка бота (TelegramForbiddenError) и некорректный
    запрос (TelegramBadRequest, TelegramNotFound: чат не найден, текст не
    парсится) повтора не переживут, поэтому False возвращается сразу.
    """
    total = max(1, attempts)

    for attempt in range(1, total + 1):
        try:
            await bot.send_message(chat_id, text, **kwargs)
            return True
        except TelegramRetryAfter as e:
            delay = e.retry_after + RETRY_AFTER_MARGIN
            if attempt >= total:
                logger.error(
                    f"Флуд-контроль на чате {chat_id}: попытки исчерпаны ({total}), сообщение не доставлено"
                )
                return False
            logger.warning(
                f"Флуд-контроль на чате {chat_id}: ждём {delay} с, "
                f"попытка {attempt} из {total}"
            )
            await asyncio.sleep(delay)
        except (TelegramForbiddenError, TelegramBadRequest, TelegramNotFound) as e:
            logger.warning(f"Сообщение в чат {chat_id} не доставлено, повтор бессмыслен: {e}")
            return False
        except (TelegramNetworkError, TelegramServerError) as e:
            if attempt >= total:
                logger.error(
                    f"Сообщение в чат {chat_id} не доставлено за {total} попыток: {e}"
                )
                return False
            logger.warning(
                f"Сбой отправки в чат {chat_id} ({type(e).__name__}: {e}), "
                f"повтор через {NETWORK_RETRY_DELAY} с, попытка {attempt} из {total}"
            )
            await asyncio.sleep(NETWORK_RETRY_DELAY)
        except TelegramAPIError as e:
            logger.error(f"Сообщение в чат {chat_id} не доставлено ({type(e).__name__}): {e}")
            return False

    return False
