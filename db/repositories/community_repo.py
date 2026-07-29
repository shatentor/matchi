from typing import Optional

import asyncpg

from db.repositories.base import BaseRepository
from models.community import Community


class CommunityRepository(BaseRepository):
    """Весь SQL по закрытой супергруппе сообщества.

    В таблице ожидается ровно одна строка, поэтому get() читает её без ключа,
    а bind() перед вставкой убирает прежнюю привязку.

    chat_id здесь BIGINT (id супергруппы), а не строковый tg_chat_id из users.
    """

    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool, Community, "community")

    async def get(self) -> Optional[Community]:
        """Текущая супергруппа сообщества.

        ORDER BY + LIMIT 1 на случай, если в таблице почему-то оказалось
        несколько строк: свежая привязка считается действующей.
        """
        query = """
        SELECT chat_id, title, bound_at
        FROM community
        ORDER BY bound_at DESC
        LIMIT 1;
        """
        return await self._fetch_one(query)

    async def bind(self, chat_id: int, title: Optional[str] = None) -> Community:
        """Привязывает супергруппу, заменяя прежнюю.

        Удаление старых строк и вставка новой идут в одной транзакции: иначе при
        ошибке между запросами сообщество осталось бы без привязки вообще.
        ON CONFLICT нужен для повторного вызова в той же группе — он обновляет
        название и время вместо UniqueViolation по первичному ключу.
        """
        delete_query = "DELETE FROM community WHERE chat_id <> $1;"
        insert_query = """
        INSERT INTO community (chat_id, title)
        VALUES ($1, $2)
        ON CONFLICT (chat_id) DO UPDATE SET title = $2, bound_at = NOW()
        RETURNING chat_id, title, bound_at;
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(delete_query, chat_id)
                record = await conn.fetchrow(insert_query, chat_id, title)
        return Community.model_validate(dict(record))

    async def unbind(self) -> None:
        """Снимает привязку целиком: строка ожидается одна, WHERE не нужен."""
        query = "DELETE FROM community;"
        await self._execute_query(query)
