import asyncpg
from datetime import datetime
from typing import Any, Dict, List, Optional

from db.repositories.base import BaseRepository
from models.room import Room


class RoomRepository(BaseRepository):
    """Весь SQL комнат: сами комнаты, участники, сообщения, мьюты и баны.

    tg_chat_id пользователя принимается и возвращается строкой (как в users),
    а rooms.tg_chat_id — это BIGINT id супергруппы для режима native.
    """

    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool, Room, "rooms")

    async def list_active(self, interest_id: Optional[int] = None) -> List[Room]:
        """Активные комнаты с числом участников — одним запросом, без N+1.

        interest_id = None означает «без фильтра»; приведение $1::INTEGER нужно,
        чтобы PostgreSQL знал тип параметра при NULL.
        """
        query = """
        SELECT r.id, r.interest_id, r.title, r.description, r.mode, r.tg_chat_id, r.thread_id,
               r.member_limit, r.is_active, r.created_at,
               COUNT(m.tg_chat_id) AS member_count
        FROM rooms r
        LEFT JOIN room_members m ON m.room_id = r.id
        WHERE r.is_active = TRUE
          AND ($1::INTEGER IS NULL OR r.interest_id = $1::INTEGER)
        GROUP BY r.id
        ORDER BY r.id;
        """
        return await self._fetch_all(query, interest_id)

    async def member_counts(self, room_ids: List[int]) -> Dict[int, int]:
        """Число участников для нескольких комнат сразу — одним запросом."""
        if not room_ids:
            return {}
        query = """
        SELECT room_id, COUNT(*) AS member_count
        FROM room_members
        WHERE room_id = ANY($1::INTEGER[])
        GROUP BY room_id;
        """
        records = await self.pool.fetch(query, room_ids)
        return {r['room_id']: r['member_count'] for r in records}

    async def get(self, room_id: int) -> Optional[Room]:
        query = """
        SELECT r.id, r.interest_id, r.title, r.description, r.mode, r.tg_chat_id, r.thread_id,
               r.member_limit, r.is_active, r.created_at,
               (SELECT COUNT(*) FROM room_members m WHERE m.room_id = r.id) AS member_count
        FROM rooms r
        WHERE r.id = $1;
        """
        return await self._fetch_one(query, room_id)

    async def get_by_native_chat(self, tg_chat_id: int) -> Optional[Room]:
        """Комната, занимающая эту супергруппу целиком.

        thread_id IS NULL обязателен: в супергруппе сообщества комнат много, у
        каждой свой топик, и все они делят один tg_chat_id. Занятой группа
        считается только если её забрала комната без топика.
        """
        query = """
        SELECT r.id, r.interest_id, r.title, r.description, r.mode, r.tg_chat_id, r.thread_id,
               r.member_limit, r.is_active, r.created_at,
               (SELECT COUNT(*) FROM room_members m WHERE m.room_id = r.id) AS member_count
        FROM rooms r
        WHERE r.tg_chat_id = $1 AND r.thread_id IS NULL
        ORDER BY r.id
        LIMIT 1;
        """
        return await self._fetch_one(query, tg_chat_id)

    async def create(self, room: Room) -> Room:
        query = """
        INSERT INTO rooms (interest_id, title, description, mode, tg_chat_id, thread_id,
                           member_limit, is_active)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, interest_id, title, description, mode, tg_chat_id, thread_id,
                  member_limit, is_active, created_at;
        """
        record = await self._fetch_one(
            query,
            room.interest_id, room.title, room.description, room.mode,
            room.tg_chat_id, room.thread_id, room.member_limit, room.is_active,
        )
        return record if record else room

    async def bind_native(self, room_id: int, tg_chat_id: int,
                          thread_id: Optional[int] = None) -> None:
        """Привязывает существующую супергруппу к комнате и переводит её в native.

        Создать группу бот не может — её создаёт человек и добавляет туда бота
        администратором, поэтому id чата приходит из апдейта, а не из кода.
        thread_id пишется всегда, в том числе NULL: при перепривязке к другому
        чату прежний id топика указывал бы в пустоту.
        """
        query = "UPDATE rooms SET tg_chat_id = $2, thread_id = $3, mode = 'native' WHERE id = $1;"
        await self._execute_query(query, room_id, tg_chat_id, thread_id)

    async def set_thread(self, room_id: int, thread_id: Optional[int]) -> None:
        """Проставляет комнате топик, не меняя режим.

        Нужно, когда топик создан отдельно от комнаты (например, первая попытка
        упёрлась в отсутствие прав у бота и админ повторяет её позже).
        """
        query = "UPDATE rooms SET thread_id = $2 WHERE id = $1;"
        await self._execute_query(query, room_id, thread_id)

    async def set_active(self, room_id: int, is_active: bool) -> None:
        query = "UPDATE rooms SET is_active = $2 WHERE id = $1;"
        await self._execute_query(query, room_id, is_active)

    async def member_ids(self, room_id: int) -> List[str]:
        query = "SELECT tg_chat_id FROM room_members WHERE room_id = $1 ORDER BY joined_at;"
        records = await self.pool.fetch(query, room_id)
        return [r['tg_chat_id'] for r in records]

    async def member_count(self, room_id: int) -> int:
        query = "SELECT COUNT(*) FROM room_members WHERE room_id = $1;"
        record = await self.pool.fetchrow(query, room_id)
        return record[0] if record else 0

    async def is_member(self, room_id: int, tg_chat_id: str) -> bool:
        query = "SELECT 1 FROM room_members WHERE room_id = $1 AND tg_chat_id = $2;"
        record = await self.pool.fetchrow(query, room_id, tg_chat_id)
        return record is not None

    async def add_member(self, room_id: int, tg_chat_id: str) -> None:
        # PRIMARY KEY (room_id, tg_chat_id) в схеме: повторный вход не должен
        # давать UniqueViolation и не должен создавать второго участника
        query = """
        INSERT INTO room_members (room_id, tg_chat_id)
        VALUES ($1, $2)
        ON CONFLICT (room_id, tg_chat_id) DO NOTHING;
        """
        await self._execute_query(query, room_id, tg_chat_id)

    async def remove_member(self, room_id: int, tg_chat_id: str) -> None:
        query = "DELETE FROM room_members WHERE room_id = $1 AND tg_chat_id = $2;"
        await self._execute_query(query, room_id, tg_chat_id)

    async def rooms_of_user(self, tg_chat_id: str) -> List[Room]:
        query = """
        SELECT r.id, r.interest_id, r.title, r.description, r.mode, r.tg_chat_id, r.thread_id,
               r.member_limit, r.is_active, r.created_at,
               (SELECT COUNT(*) FROM room_members m2 WHERE m2.room_id = r.id) AS member_count
        FROM rooms r
        INNER JOIN room_members m ON m.room_id = r.id
        WHERE m.tg_chat_id = $1
        ORDER BY r.id;
        """
        return await self._fetch_all(query, tg_chat_id)

    async def save_message(self, room_id: int, author_chat_id: str, text: str) -> None:
        query = """
        INSERT INTO room_messages (room_id, author_chat_id, text)
        VALUES ($1, $2, $3);
        """
        await self._execute_query(query, room_id, author_chat_id, text)

    async def last_messages(self, room_id: int, limit: int) -> List[Dict[str, Any]]:
        """Последние сообщения комнаты в хронологическом порядке.

        Имя автора берётся LEFT JOIN на users: пользователь мог удалить анкету,
        и сообщение всё равно должно показаться.
        """
        query = """
        SELECT rm.id, rm.author_chat_id, rm.text, rm.created_at, u.name AS author_name
        FROM room_messages rm
        LEFT JOIN users u ON u.tg_chat_id = rm.author_chat_id
        WHERE rm.room_id = $1
        ORDER BY rm.created_at DESC, rm.id DESC
        LIMIT $2;
        """
        records = await self.pool.fetch(query, room_id, limit)
        # Запрос отбирает свежие (DESC), а показывать историю надо снизу вверх
        return [dict(r) for r in reversed(records)]

    async def mute(self, room_id: int, tg_chat_id: str, until: Optional[datetime]) -> None:
        """Отключает участнику право писать до указанного момента.

        UPDATE, а не INSERT: мьют имеет смысл только для участника комнаты,
        и вставка создала бы участника из ниоткуда.
        """
        query = "UPDATE room_members SET muted_until = $3 WHERE room_id = $1 AND tg_chat_id = $2;"
        await self._execute_query(query, room_id, tg_chat_id, until)

    async def is_muted(self, room_id: int, tg_chat_id: str) -> bool:
        query = """
        SELECT 1 FROM room_members
        WHERE room_id = $1 AND tg_chat_id = $2
          AND muted_until IS NOT NULL AND muted_until > NOW();
        """
        record = await self.pool.fetchrow(query, room_id, tg_chat_id)
        return record is not None

    async def muted_until(self, room_id: int, tg_chat_id: str) -> Optional[datetime]:
        query = "SELECT muted_until FROM room_members WHERE room_id = $1 AND tg_chat_id = $2;"
        record = await self.pool.fetchrow(query, room_id, tg_chat_id)
        return record['muted_until'] if record else None

    async def ban(self, room_id: int, tg_chat_id: str, reason: Optional[str]) -> None:
        # PRIMARY KEY (room_id, tg_chat_id): повторный бан обновляет причину
        query = """
        INSERT INTO room_bans (room_id, tg_chat_id, reason)
        VALUES ($1, $2, $3)
        ON CONFLICT (room_id, tg_chat_id) DO UPDATE SET reason = $3, banned_at = NOW();
        """
        await self._execute_query(query, room_id, tg_chat_id, reason)

    async def is_banned(self, room_id: int, tg_chat_id: str) -> bool:
        query = "SELECT 1 FROM room_bans WHERE room_id = $1 AND tg_chat_id = $2;"
        record = await self.pool.fetchrow(query, room_id, tg_chat_id)
        return record is not None

    async def unban(self, room_id: int, tg_chat_id: str) -> None:
        query = "DELETE FROM room_bans WHERE room_id = $1 AND tg_chat_id = $2;"
        await self._execute_query(query, room_id, tg_chat_id)
