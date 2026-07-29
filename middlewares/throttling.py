import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from config.settings import settings

logger = logging.getLogger(__name__)

THROTTLE_WARNING = "Слишком много запросов. Подождите немного, пожалуйста."


class ThrottlingMiddleware(BaseMiddleware):
    """Ограничивает частоту апдейтов от одного пользователя.

    Регистрируется как outer middleware и ДО UserContextMiddleware, чтобы
    отброшенный апдейт не стоил запроса к БД. Счётчик живёт в Redis:
    throttle:<user_id> инкрементируется на каждый апдейт, и при первом
    инкременте на ключ ставится TTL длиной в окно.

    Предупреждение отправляется ровно один раз за окно (отдельный ключ-флаг),
    иначе бот в ответ на флуд устроил бы флуд сам и попал под флуд-контроль
    Telegram.
    """

    def __init__(
        self,
        redis_client: Any,
        limit: int = settings.THROTTLE_LIMIT,
        window: int = settings.THROTTLE_WINDOW,
    ):
        self.redis = redis_client
        self.limit = limit
        self.window = window

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user: Optional[TgUser] = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        counter = await self._hit(tg_user.id)
        if counter is None or counter <= self.limit:
            return await handler(event, data)

        logger.info(f"Троттлинг: пользователь {tg_user.id} превысил {self.limit} апдейтов за {self.window} с")
        if await self._should_warn(tg_user.id):
            await self._warn(event)
        return None

    async def _hit(self, user_id: int) -> Optional[int]:
        """Возвращает номер апдейта в окне или None, если Redis недоступен.

        Молча блокировать пользователей из-за проблем с инфраструктурой хуже,
        чем на время потерять троттлинг, поэтому при ошибке — fail-open.
        """
        key = f"throttle:{user_id}"
        try:
            counter = int(await self.redis.incr(key))
            if counter == 1:
                await self.redis.expire(key, self.window)
            elif counter > self.limit:
                # INCR и EXPIRE — две операции: если EXPIRE когда-то не дошёл,
                # счётчик остался бессрочным и заблокировал бы пользователя
                # навсегда. Проверяем TTL только на превышении и восстанавливаем.
                ttl = await self.redis.ttl(key)
                if ttl is not None and int(ttl) < 0:
                    logger.warning(f"Ключ {key} остался без TTL, ставим окно заново")
                    await self.redis.expire(key, self.window)
            return counter
        except Exception as e:
            logger.error(f"Троттлинг отключён для апдейта: Redis недоступен ({e})")
            return None

    async def _should_warn(self, user_id: int) -> bool:
        """True, если предупреждение в этом окне ещё не отправлялось."""
        key = f"throttle:notified:{user_id}"
        try:
            created = await self.redis.set(key, "1", ex=self.window, nx=True)
        except Exception as e:
            # Не смогли поставить флаг — лучше промолчать, чем задвоить.
            logger.error(f"Не удалось отметить предупреждение о троттлинге для {user_id}: {e}")
            return False
        return bool(created)

    async def _warn(self, event: TelegramObject) -> None:
        try:
            if isinstance(event, CallbackQuery):
                # answer вместо сообщения: всплывающее уведомление не плодит
                # новых сообщений в чате.
                await event.answer(THROTTLE_WARNING, show_alert=False)
            elif isinstance(event, Message):
                await event.answer(THROTTLE_WARNING)
        except Exception as e:
            logger.warning(f"Не удалось предупредить о троттлинге: {type(e).__name__}: {e}")
