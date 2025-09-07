import asyncpg
from typing import List, Optional
from db.repositories.base import BaseRepository

# У нас нет Pydantic модели для Sticker, так как это просто строка.
# Но мы все равно можем использовать репозиторий для доступа к ним.
class StickerRepository:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def add_sticker(self, sticker_id: str) -> None:
        query = "INSERT INTO stickers (lovely) VALUES ($1);"
        async with self.pool.acquire() as conn:
            await conn.execute(query, sticker_id)

    async def get_random_sticker_id(self) -> Optional[str]:
        query = "SELECT lovely FROM stickers ORDER BY RANDOM() LIMIT 1;"
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query)
            return record['lovely'] if record else None