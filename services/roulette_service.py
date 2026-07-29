import logging
from typing import Any, Optional

from config.settings import settings
from services.dialog_service import DialogService

logger = logging.getLogger(__name__)


def queue_key(interest_id: int) -> str:
    return f"roulette:queue:{interest_id}"


def waiting_key(tg_chat_id: int) -> str:
    return f"roulette:waiting:{tg_chat_id}"


def _decode(value: Any) -> Optional[str]:
    """Redis-клиент может быть создан и с decode_responses, и без него."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


class RouletteService:
    """Подбор случайного собеседника по общему интересу.

    Очередь ожидания — список Redis roulette:queue:<interest_id>. Выдача из
    очереди идёт только атомарным LPOP: при схеме «прочитал → проверил →
    удалил» два одновременных join получили бы одного и того же ожидающего и
    его свели бы сразу с двумя.

    У списка нельзя задать TTL отдельным элементам, поэтому на каждого
    ожидающего дополнительно ставится ключ-маркер roulette:waiting:<id> с
    TTL = settings.ROULETTE_WAIT_TTL. Элемент очереди без живого маркера
    считается протухшим и выбрасывается. Маркер один на пользователя, так что
    ждать в двух очередях одновременно нельзя: новый join обесценивает старый.
    """

    def __init__(self, redis_client: Any, dialog_service: DialogService):
        self.redis = redis_client
        self.dialog_service = dialog_service

    async def join(self, tg_chat_id: int, interest_id: int) -> Optional[int]:
        """Ищет собеседника по интересу.

        Возвращает id найденного собеседника (пара сведена и из очереди он
        уже убран) либо None — тогда пользователь сам поставлен в очередь.
        """
        key = queue_key(interest_id)
        me = str(tg_chat_id)

        while True:
            candidate = _decode(await self.redis.lpop(key))
            if candidate is None:
                break
            if candidate == me:
                # Пользователь мог уже стоять в этой очереди. Сам с собой не
                # сводится, и обратно в очередь не возвращается: ниже он
                # встанет в неё заново.
                continue
            if not candidate.lstrip("-").isdigit():
                logger.warning("Мусор в очереди рулетки %s: %r", key, candidate)
                continue
            if not await self._is_still_waiting(int(candidate), interest_id):
                continue
            if await self.dialog_service.get_active(int(candidate)) is not None:
                # За время ожидания ушёл в другой диалог — берём следующего.
                await self._forget(int(candidate))
                continue

            await self._forget(int(candidate))
            await self._forget(tg_chat_id)
            return int(candidate)

        await self._enqueue(tg_chat_id, interest_id)
        return None

    async def leave(self, tg_chat_id: int, interest_id: int) -> None:
        await self.redis.lrem(queue_key(interest_id), 0, str(tg_chat_id))
        await self._forget(tg_chat_id)

    async def waiting_count(self, interest_id: int) -> int:
        """Длина очереди. Это верхняя оценка: протухшие элементы отбрасываются
        только при выдаче, поэтому пока их не достали, они ещё считаются."""
        return int(await self.redis.llen(queue_key(interest_id)))

    async def _enqueue(self, tg_chat_id: int, interest_id: int) -> None:
        key = queue_key(interest_id)
        me = str(tg_chat_id)
        # Страховка от дубля, если пользователь встал в очередь параллельно
        # с этим же вызовом.
        await self.redis.lrem(key, 0, me)
        await self.redis.rpush(key, me)
        await self.redis.expire(key, settings.ROULETTE_WAIT_TTL)
        await self.redis.set(waiting_key(tg_chat_id), str(interest_id), ex=settings.ROULETTE_WAIT_TTL)

    async def _is_still_waiting(self, tg_chat_id: int, interest_id: int) -> bool:
        marker = _decode(await self.redis.get(waiting_key(tg_chat_id)))
        return marker == str(interest_id)

    async def _forget(self, tg_chat_id: int) -> None:
        await self.redis.delete(waiting_key(tg_chat_id))
