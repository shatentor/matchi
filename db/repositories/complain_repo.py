import asyncpg
from typing import List, Optional
from models.complain import Complain
from db.repositories.base import BaseRepository

class ComplainRepository(BaseRepository):
    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool, Complain, "complains")

    async def create_complain(self, complain: Complain) -> Complain:
        query = """
        INSERT INTO complains (reporter_chat_id, reported_chat_id, reason)
        VALUES ($1, $2, $3)
        RETURNING *;
        """
        record = await self._fetch_one(query, complain.reporter_chat_id, complain.reported_chat_id, complain.reason)
        return record if record else complain

    async def get_all(self, limit: int = 50) -> List[Complain]:
        query = "SELECT * FROM complains ORDER BY timestamp DESC LIMIT $1;"
        return await self._fetch_all(query, limit)

    async def get_complains_by_reporter(self, reporter_chat_id: str) -> List[Complain]:
        query = "SELECT * FROM complains WHERE reporter_chat_id = $1 ORDER BY timestamp DESC;"
        return await self._fetch_all(query, reporter_chat_id)

    async def get_complains_on_reported_user(self, reported_chat_id: str) -> List[Complain]:
        query = "SELECT * FROM complains WHERE reported_chat_id = $1 ORDER BY timestamp DESC;"
        return await self._fetch_all(query, reported_chat_id)