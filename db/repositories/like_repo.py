import asyncpg
from typing import List, Optional
from models.like import Like
from db.repositories.base import BaseRepository

class LikeRepository(BaseRepository):
    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool, Like, "likes")

    async def add_like(self, liker_chat_id: str, liked_chat_id: str) -> None:
        query = "INSERT INTO likes (liker_chat_id, liked_chat_id) VALUES ($1, $2) ON CONFLICT (liker_chat_id, liked_chat_id) DO NOTHING;"
        await self._execute_query(query, liker_chat_id, liked_chat_id)

    async def has_liked(self, liker_chat_id: str, liked_chat_id: str) -> bool:
        query = "SELECT COUNT(*) FROM likes WHERE liker_chat_id = $1 AND liked_chat_id = $2;"
        record = await self.pool.fetchrow(query, liker_chat_id, liked_chat_id)
        return record[0] > 0

    async def get_mutual_likes_for_user(self, tg_chat_id: str) -> List[str]:
        query = """
            SELECT l1.liked_chat_id FROM likes l1
            INNER JOIN likes l2 ON l1.liked_chat_id = l2.liker_chat_id
            WHERE l1.liker_chat_id = $1 AND l2.liked_chat_id = $1;
        """
        records = await self.pool.fetch(query, tg_chat_id)
        return [r['liked_chat_id'] for r in records]

    async def is_mutual_like_pair(self, user1_id: str, user2_id: str) -> bool:
        user1_likes_user2 = await self.has_liked(user1_id, user2_id)
        user2_likes_user1 = await self.has_liked(user2_id, user1_id)
        return user1_likes_user2 and user2_likes_user1