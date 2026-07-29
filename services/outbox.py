import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import Bot

from config.settings import settings
from utils.telegram import send_with_retry

logger = logging.getLogger(__name__)

# Словарь времён последней отправки нужен только для недавних чатов, иначе он
# растёт вместе с числом получателей. Чистим его, когда записей стало много.
CHAT_STATE_SOFT_LIMIT = 1000
CHAT_STATE_TTL = 60.0


class Outbox:
    """Очередь исходящих сообщений с соблюдением лимитов Telegram.

    Веерная рассылка (сообщение комнаты всем участникам) не может отправляться
    в цикле без паузы: Telegram допускает порядка 30 сообщений в секунду
    суммарно и примерно одно в секунду в один и тот же чат, а за превышение
    отвечает флуд-контролем на весь бот. Поэтому все сообщения проходят через
    один воркер, который выдерживает settings.OUTBOX_RATE в секунду суммарно и
    settings.OUTBOX_PER_CHAT_INTERVAL секунд между сообщениями в один чат.

    Если доставка невозможна (бот заблокирован, чат удалён), вызывается
    on_undeliverable(chat_id) — по этому колбэку комнаты исключают участника.
    """

    def __init__(self, bot: Bot, on_undeliverable: Optional[Callable[[int], Awaitable[None]]] = None):
        self._bot = bot
        self._on_undeliverable = on_undeliverable
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None

        rate = settings.OUTBOX_RATE if settings.OUTBOX_RATE > 0 else 1.0
        self._global_interval = 1.0 / rate
        self._per_chat_interval = max(0.0, settings.OUTBOX_PER_CHAT_INTERVAL)

        self._next_global_slot = 0.0
        self._chat_sent_at: Dict[int, float] = {}
        self._chat_state_purged_at = 0.0

    async def start(self) -> None:
        """Поднимает воркер. Повторный вызов ничего не делает."""
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._worker_task = asyncio.create_task(self._worker(), name="outbox-worker")
        logger.info(
            f"Outbox запущен: не быстрее {1 / self._global_interval:.0f} сообщений/с суммарно "
            f"и одного раз в {self._per_chat_interval} с на чат"
        )

    async def stop(self) -> None:
        """Дожидается опустошения очереди и останавливает воркер."""
        task, self._worker_task = self._worker_task, None
        if task is None:
            return

        if not task.done():
            # Ждём и опустошения очереди, и самого воркера: если воркер всё-таки
            # умер, join() никогда не завершится, и stop() повис бы навсегда.
            join_task = asyncio.create_task(self._queue.join())
            try:
                await asyncio.wait({join_task, task}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                if not join_task.done():
                    join_task.cancel()
                    try:
                        await join_task
                    except asyncio.CancelledError:
                        pass

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info(f"Outbox остановлен, в очереди осталось {self.pending()} сообщений")

    async def enqueue(self, chat_id: int, text: str, **kwargs: Any) -> None:
        """Ставит сообщение в очередь. Не ждёт отправки."""
        if self._worker_task is None or self._worker_task.done():
            logger.warning("Outbox: воркер не запущен, сообщения будут ждать start()")
        await self._queue.put((chat_id, text, kwargs))

    def pending(self) -> int:
        """Сколько сообщений ждёт отправки."""
        return self._queue.qsize()

    async def _worker(self) -> None:
        while True:
            chat_id, text, kwargs = await self._queue.get()
            try:
                await self._wait_for_slot(chat_id)
                delivered = await send_with_retry(self._bot, chat_id, text, **kwargs)
                if not delivered:
                    await self._report_undeliverable(chat_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Умерший воркер означает тихо застрявшую очередь, поэтому любая
                # ошибка на одном сообщении не должна прекращать обработку.
                logger.exception(f"Outbox: ошибка при отправке в чат {chat_id}: {e}")
            finally:
                self._queue.task_done()

    async def _wait_for_slot(self, chat_id: int) -> None:
        """Выжидает общий лимит скорости и интервал по конкретному чату."""
        loop = asyncio.get_running_loop()
        now = loop.time()

        wait_global = self._next_global_slot - now
        chat_sent_at = self._chat_sent_at.get(chat_id)
        wait_chat = 0.0 if chat_sent_at is None else chat_sent_at + self._per_chat_interval - now

        delay = max(wait_global, wait_chat, 0.0)
        if delay > 0:
            await asyncio.sleep(delay)
            now = loop.time()

        self._next_global_slot = now + self._global_interval
        self._chat_sent_at[chat_id] = now
        self._purge_chat_state(now)

    def _purge_chat_state(self, now: float) -> None:
        ttl = max(CHAT_STATE_TTL, self._per_chat_interval * 10)
        if len(self._chat_sent_at) <= CHAT_STATE_SOFT_LIMIT or now - self._chat_state_purged_at < ttl:
            return
        self._chat_sent_at = {
            chat: sent_at for chat, sent_at in self._chat_sent_at.items() if now - sent_at < ttl
        }
        self._chat_state_purged_at = now

    async def _report_undeliverable(self, chat_id: int) -> None:
        logger.warning(f"Outbox: сообщение в чат {chat_id} доставить не удалось")
        if self._on_undeliverable is None:
            return
        try:
            await self._on_undeliverable(chat_id)
        except Exception as e:
            logger.exception(f"Outbox: колбэк on_undeliverable упал на чате {chat_id}: {e}")
