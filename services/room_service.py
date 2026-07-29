import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from config.settings import settings
from db.repositories.room_repo import RoomRepository
from db.repositories.user_repo import UserRepository
from models.room import ROOM_MODE_NATIVE, ROOM_MODE_RELAY, ROOM_MODES, Room
from services.outbox import Outbox
from utils.text import escape

logger = logging.getLogger(__name__)


class RoomService:
    """Групповые комнаты по интересам.

    В режиме relay бот сам разносит сообщение всем участникам, и делает это
    ТОЛЬКО через Outbox: Telegram допускает порядка 30 сообщений в секунду
    суммарно и примерно одно в секунду в один и тот же чат, поэтому отправка
    в цикле по участникам приводит к флуд-контролю на весь бот. Из тех же
    ограничений растёт settings.ROOM_MEMBER_LIMIT — relay пригоден только для
    небольших комнат. Для больших комнат режим native: комната это реальная
    супергруппа Telegram, и доставку берёт на себя сам Telegram.
    """

    def __init__(self, room_repo: RoomRepository, user_repo: UserRepository,
                 outbox: Optional[Outbox] = None):
        self.room_repo = room_repo
        self.user_repo = user_repo
        self.outbox = outbox

    # ---------- каталог ----------

    async def list_rooms(self, interest_id: Optional[int] = None) -> List[Room]:
        return await self.room_repo.list_active(interest_id)

    async def get_room(self, room_id: int) -> Optional[Room]:
        return await self.room_repo.get(room_id)

    async def my_rooms(self, tg_chat_id: int) -> List[Room]:
        return await self.room_repo.rooms_of_user(str(tg_chat_id))

    async def is_member(self, tg_chat_id: int, room_id: int) -> bool:
        return await self.room_repo.is_member(room_id, str(tg_chat_id))

    # ---------- вход и выход ----------

    async def join(self, tg_chat_id: int, room_id: int) -> Tuple[bool, str]:
        """Добавляет пользователя в комнату.

        Проверки идут по порядку: комната есть и активна, пользователь не забанен,
        лимит участников не превышен, пользователь ещё не участник.
        """
        chat_id_str = str(tg_chat_id)
        room = await self.room_repo.get(room_id)

        if room is None or not room.is_active:
            return False, "Такой комнаты нет или она закрыта."

        if await self.room_repo.is_banned(room_id, chat_id_str):
            return False, "Вход в эту комнату для вас закрыт."

        if await self.room_repo.is_member(room_id, chat_id_str):
            return False, "Вы уже участник этой комнаты."

        limit = room.member_limit or settings.ROOM_MEMBER_LIMIT
        if await self.room_repo.member_count(room_id) >= limit:
            return False, f"В комнате уже максимум участников ({limit}). Попробуйте позже."

        await self.room_repo.add_member(room_id, chat_id_str)
        return True, f"Вы вошли в комнату «{room.title}»."

    async def leave(self, tg_chat_id: int, room_id: int) -> Tuple[bool, str]:
        chat_id_str = str(tg_chat_id)
        if not await self.room_repo.is_member(room_id, chat_id_str):
            return False, "Вы не участник этой комнаты."

        await self.room_repo.remove_member(room_id, chat_id_str)
        room = await self.room_repo.get(room_id)
        title = room.title if room else str(room_id)
        return True, f"Вы вышли из комнаты «{title}»."

    async def can_write(self, tg_chat_id: int, room_id: int) -> Tuple[bool, str]:
        """Проверяет право писать в комнату: участие, бан, мьют, режим комнаты."""
        chat_id_str = str(tg_chat_id)
        room = await self.room_repo.get(room_id)

        if room is None or not room.is_active:
            return False, "Комната закрыта."

        if room.mode != ROOM_MODE_RELAY:
            return False, "Это комната-супергруппа, пишите прямо в ней."

        if await self.room_repo.is_banned(room_id, chat_id_str):
            return False, "Вы забанены в этой комнате."

        if not await self.room_repo.is_member(room_id, chat_id_str):
            return False, "Вы не участник этой комнаты."

        if await self.room_repo.is_muted(room_id, chat_id_str):
            until = await self.room_repo.muted_until(room_id, chat_id_str)
            when = until.strftime('%d.%m %H:%M') if until else "неизвестно"
            return False, f"Вам временно запрещено писать в этой комнате (до {when})."

        return True, ""

    # ---------- сообщения ----------

    async def broadcast(self, room_id: int, author_id: int, text: str) -> int:
        """Разносит сообщение всем участникам комнаты, кроме автора.

        Возвращает число адресатов. Отправка идёт исключительно через Outbox:
        прямой bot.send_message в цикле по участникам упирается в лимиты
        Telegram и заканчивается флуд-баном бота.
        """
        room = await self.room_repo.get(room_id)
        if room is None or not room.is_active:
            return 0

        if room.mode != ROOM_MODE_RELAY:
            # В нативной супергруппе сообщения разносит Telegram, релеить нечего
            logger.warning(f"broadcast вызван для комнаты {room_id} в режиме {room.mode}")
            return 0

        author_str = str(author_id)
        # Право писать проверяется и здесь, а не только в хендлере: иначе мьют и
        # бан держались бы на дисциплине вызывающего кода
        if not await self.room_repo.is_member(room_id, author_str):
            logger.warning(f"Попытка написать в комнату {room_id} от неучастника {author_id}")
            return 0
        if await self.room_repo.is_banned(room_id, author_str):
            return 0
        if await self.room_repo.is_muted(room_id, author_str):
            return 0

        # Обрезаем до escape(), иначе можно разрезать HTML-сущность вроде '&amp;'
        clean_text = (text or "").strip()[:settings.ROOM_MAX_MESSAGE_LENGTH]
        if not clean_text:
            return 0

        await self.room_repo.save_message(room_id, author_str, clean_text)

        recipients = [cid for cid in await self.room_repo.member_ids(room_id) if cid != author_str]
        if not recipients:
            return 0

        author = await self.user_repo.get_by_id(author_str)
        author_name = (author.name if author and author.name else author_str)
        payload = (f"<b>{escape(author_name)}</b> в «{escape(room.title)}»:\n"
                   f"{escape(clean_text)}")

        if self.outbox is None:
            logger.error(f"Outbox не передан в RoomService, сообщение в комнату {room_id} не разослано")
            return 0

        for chat_id in recipients:
            try:
                await self.outbox.enqueue(int(chat_id), payload)
            except (TypeError, ValueError):
                logger.warning(f"Некорректный tg_chat_id участника комнаты {room_id}: {chat_id!r}")

        return len(recipients)

    async def history(self, room_id: int, limit: int = settings.ROOM_HISTORY_SIZE) -> List[Dict[str, Any]]:
        return await self.room_repo.last_messages(room_id, limit)

    async def handle_undeliverable(self, chat_id: int) -> None:
        """Колбэк для Outbox: участник недоступен, исключаем его из всех комнат.

        Пользователь заблокировал бота или удалил чат, поэтому дальше он будет
        только копить неудачные отправки в каждой рассылке.
        """
        chat_id_str = str(chat_id)
        rooms = await self.room_repo.rooms_of_user(chat_id_str)
        if not rooms:
            return

        for room in rooms:
            await self.room_repo.remove_member(room.id, chat_id_str)

        logger.warning(f"Пользователь {chat_id} недоступен для бота и исключён из комнат: "
                       f"{[room.id for room in rooms]}")

    # ---------- админские операции ----------

    async def create_room(self, title: str, interest_id: Optional[int] = None,
                          description: Optional[str] = None, mode: str = ROOM_MODE_RELAY,
                          member_limit: Optional[int] = None) -> Tuple[Optional[Room], str]:
        title = (title or "").strip()
        if not title:
            return None, "Название комнаты не может быть пустым."

        if mode not in ROOM_MODES:
            return None, f"Неизвестный режим комнаты: {mode}. Допустимо: {', '.join(ROOM_MODES)}."

        room = Room(
            title=title,
            interest_id=interest_id,
            description=(description or "").strip() or None,
            mode=mode,
            member_limit=member_limit or settings.ROOM_MEMBER_LIMIT,
        )
        created = await self.room_repo.create(room)
        return created, f"Комната «{created.title}» создана (id {created.id}, режим {created.mode})."

    async def bind_native(self, room_id: int, chat_id: int) -> Tuple[bool, str]:
        """Привязывает существующую супергруппу к комнате.

        Бот не может создать группу сам — её создаёт человек, добавляет бота
        администратором и вызывает привязку прямо в этой группе, чтобы id чата
        пришёл из апдейта, а не набирался руками.
        """
        room = await self.room_repo.get(room_id)
        if room is None:
            return False, f"Комнаты с id {room_id} нет."

        occupied = await self.room_repo.get_by_native_chat(chat_id)
        if occupied is not None and occupied.id != room_id:
            return False, f"Эта группа уже привязана к комнате «{occupied.title}» (id {occupied.id})."

        await self.room_repo.bind_native(room_id, chat_id)
        return True, (f"Комната «{room.title}» (id {room_id}) привязана к этой группе "
                      f"и переведена в режим {ROOM_MODE_NATIVE}.")

    async def mute(self, room_id: int, tg_chat_id: int, minutes: int) -> Tuple[bool, str]:
        chat_id_str = str(tg_chat_id)
        if not await self.room_repo.is_member(room_id, chat_id_str):
            return False, "Этот пользователь не участник комнаты."

        if minutes <= 0:
            await self.room_repo.mute(room_id, chat_id_str, None)
            return True, f"Мьют с пользователя {tg_chat_id} снят."

        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await self.room_repo.mute(room_id, chat_id_str, until)
        return True, f"Пользователь {tg_chat_id} не может писать в комнате {room_id} {minutes} мин."

    async def ban(self, room_id: int, tg_chat_id: int, reason: Optional[str] = None) -> Tuple[bool, str]:
        room = await self.room_repo.get(room_id)
        if room is None:
            return False, f"Комнаты с id {room_id} нет."

        chat_id_str = str(tg_chat_id)
        await self.room_repo.ban(room_id, chat_id_str, reason)
        # Бан без исключения из комнаты оставил бы пользователя в рассылке
        await self.room_repo.remove_member(room_id, chat_id_str)
        return True, f"Пользователь {tg_chat_id} забанен в комнате «{room.title}»."

    async def unban(self, room_id: int, tg_chat_id: int) -> Tuple[bool, str]:
        chat_id_str = str(tg_chat_id)
        if not await self.room_repo.is_banned(room_id, chat_id_str):
            return False, "Этот пользователь не забанен в комнате."

        await self.room_repo.unban(room_id, chat_id_str)
        return True, f"Бан пользователя {tg_chat_id} в комнате {room_id} снят."
