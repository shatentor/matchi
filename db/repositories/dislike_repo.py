import asyncpg
from typing import List, Optional
from models.dislike import Dislike # Импортируем новую модель Dislike
from db.repositories.base import BaseRepository

class DislikeRepository(BaseRepository):
    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool, Dislike, "dislikes") # Передаем модель Dislike и имя таблицы

    async def add_dislike(self, disliker_chat_id: str, disliked_chat_id: str) -> None:
        query = "INSERT INTO dislikes (disliker_chat_id, disliked_chat_id) VALUES ($1, $2) ON CONFLICT (disliker_chat_id, disliked_chat_id) DO NOTHING;"
        await self._execute_query(query, disliker_chat_id, disliked_chat_id)

    async def has_disliked(self, disliker_chat_id: str, disliked_chat_id: str) -> bool:
        query = "SELECT COUNT(*) FROM dislikes WHERE disliker_chat_id = $1 AND disliked_chat_id = $2;"
        record = await self.pool.fetchrow(query, disliker_chat_id, disliked_chat_id)
        return record[0] > 0