import asyncpg
from typing import TypeVar, Type, Optional, List , Any
from pydantic import BaseModel

ModelType = TypeVar("ModelType", bound=BaseModel)

class BaseRepository:
    def __init__(self, pool: asyncpg.Pool, model: Type[ModelType], table_name: str):
        self.pool = pool
        self.model = model
        self.table_name = table_name

    async def _execute_query(self, query: str, *args: Any) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)

    async def _fetch_one(self, query: str, *args: Any) -> Optional[ModelType]:
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, *args)
            # ИСПРАВЛЕНО: Преобразуем record в словарь перед передачей в Pydantic
            return self.model.model_validate(dict(record)) if record else None # Использование model_validate для Pydantic v2
            # Старый код: return self.model.from_orm(record) if record else None


    async def _fetch_all(self, query: str, *args: Any) -> List[ModelType]:
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, *args)
            # ИСПРАВЛЕНО: Преобразуем каждый record в словарь
            return [self.model.model_validate(dict(record)) for record in records] # Использование model_validate для Pydantic v2
            # Старый код: return [self.model.from_orm(record) for record in records]


    async def get_by_id(self, id_value: Any) -> Optional[ModelType]:
        # В вашем коде `get_by_id` в BaseRepository ищет по 'id',
        # но в UserRepository используется `tg_chat_id` как PRIMARY KEY.
        # Для универсальности, если таблица использует 'id' как PK:
        query = f"SELECT * FROM {self.table_name} WHERE id = $1;"
        # Если PK всегда 'tg_chat_id' (как для users), то лучше в каждом репозитории переопределять get_by_id
        # Но для BaseRepository оставим универсальный 'id', а UserRepo будет свой
        return await self._fetch_one(query, id_value)