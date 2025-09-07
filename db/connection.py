import asyncpg
import logging
from typing import Optional, Any, List

from config.settings import settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None

async def init_db_pool():
    """Инициализирует пул подключений к базе данных PostgreSQL."""
    global _pool
    if _pool is None:
        try:
            _pool = await asyncpg.create_pool(
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                database=settings.DB_NAME,
                min_size=1,
                max_size=10
            )
            logger.info("Пул подключений к PostgreSQL успешно создан.")
        except asyncpg.exceptions.PostgresError as e:
            logger.error(f"Ошибка при создании пула подключений к PostgreSQL: {e}")
            raise

async def close_db_pool():
    """Закрывает пул подключений к базе данных."""
    global _pool
    if _pool:
        await _pool.close()
        logger.info("Пул подключений к PostgreSQL успешно закрыт.")
        _pool = None

async def get_db_pool() -> asyncpg.Pool:
    """Возвращает текущий пул подключений."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call init_db_pool() first.")
    return _pool

# Низкоуровневые функции для выполнения запросов, которые будут использоваться репозиториями
async def execute_query(query: str, *args: Any) -> None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(query, *args)

async def fetch_one(query: str, *args: Any) -> Optional[asyncpg.Record]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)

async def fetch_all(query: str, *args: Any) -> List[asyncpg.Record]:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)