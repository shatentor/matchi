import asyncpg
from typing import List

from models.interest import Interest
from db.repositories.base import BaseRepository


class InterestRepository(BaseRepository):
    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool, Interest, "interests")

    async def get_active(self) -> List[Interest]:
        query = "SELECT id, slug, title, is_active FROM interests WHERE is_active = TRUE ORDER BY id;"
        return await self._fetch_all(query)

    async def get_user_interest_ids(self, tg_chat_id: str) -> List[int]:
        query = "SELECT interest_id FROM user_interests WHERE tg_chat_id = $1 ORDER BY interest_id;"
        records = await self.pool.fetch(query, tg_chat_id)
        return [r['interest_id'] for r in records]

    async def get_user_interests(self, tg_chat_id: str) -> List[Interest]:
        query = """
        SELECT i.id, i.slug, i.title, i.is_active
        FROM user_interests ui
        INNER JOIN interests i ON i.id = ui.interest_id
        WHERE ui.tg_chat_id = $1
        ORDER BY i.id;
        """
        return await self._fetch_all(query, tg_chat_id)

    async def add_user_interest(self, tg_chat_id: str, interest_id: int) -> None:
        # PRIMARY KEY (tg_chat_id, interest_id) в схеме, повторное нажатие кнопки
        # не должно приводить к UniqueViolation
        query = """
        INSERT INTO user_interests (tg_chat_id, interest_id)
        VALUES ($1, $2)
        ON CONFLICT (tg_chat_id, interest_id) DO NOTHING;
        """
        await self._execute_query(query, tg_chat_id, interest_id)

    async def remove_user_interest(self, tg_chat_id: str, interest_id: int) -> None:
        query = "DELETE FROM user_interests WHERE tg_chat_id = $1 AND interest_id = $2;"
        await self._execute_query(query, tg_chat_id, interest_id)

    async def count_user_interests(self, tg_chat_id: str) -> int:
        query = "SELECT COUNT(*) FROM user_interests WHERE tg_chat_id = $1;"
        record = await self.pool.fetchrow(query, tg_chat_id)
        return record[0] if record else 0
