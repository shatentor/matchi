import asyncpg
from typing import List, Optional, Tuple

from models.dialog import Dialog
from db.repositories.base import BaseRepository


def ordered_pair(a: str, b: str) -> Tuple[str, str]:
    """Упорядочивает пару так, как её хранит таблица.

    В схеме есть CONSTRAINT dialogs_pair_ordered CHECK (user_one < user_two),
    поэтому вставлять и искать нужно строго в этом порядке, иначе одна и та же
    пара даст либо нарушение CHECK, либо две разные строки. Сравнение
    строковое, а не числовое: tg_chat_id хранится как VARCHAR(20).
    """
    return (a, b) if a < b else (b, a)


class DialogRepository(BaseRepository):
    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool, Dialog, "dialogs")

    async def get_active_for_user(self, tg_chat_id: str) -> Optional[Dialog]:
        """Возвращает открытый диалог пользователя (самый свежий, если их несколько)."""
        query = """
        SELECT id, user_one, user_two, source, created_at, closed_at
        FROM dialogs
        WHERE closed_at IS NULL AND (user_one = $1 OR user_two = $1)
        ORDER BY created_at DESC, id DESC
        LIMIT 1;
        """
        return await self._fetch_one(query, tg_chat_id)

    async def get_active_pair(self, a: str, b: str) -> Optional[Dialog]:
        one, two = ordered_pair(a, b)
        query = """
        SELECT id, user_one, user_two, source, created_at, closed_at
        FROM dialogs
        WHERE user_one = $1 AND user_two = $2 AND closed_at IS NULL
        LIMIT 1;
        """
        return await self._fetch_one(query, one, two)

    async def open_dialog(self, a: str, b: str, source: str) -> Dialog:
        """Открывает диалог или возвращает уже открытый для этой пары.

        Частичный уникальный индекс idx_dialogs_active_pair (user_one, user_two)
        WHERE closed_at IS NULL запрещает второй открытый диалог на пару.
        Конфликт здесь — нормальная ситуация (оба участника могли нажать
        «Ответить» одновременно), поэтому вместо ошибки отдаём существующую
        строку. ON CONFLICT по частичному индексу обязан повторять его предикат.
        """
        one, two = ordered_pair(a, b)
        query = """
        INSERT INTO dialogs (user_one, user_two, source)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_one, user_two) WHERE closed_at IS NULL DO NOTHING
        RETURNING id, user_one, user_two, source, created_at, closed_at;
        """
        # Две попытки: между DO NOTHING и повторным чтением конкурент мог
        # успеть закрыть диалог, тогда вставка проходит со второго раза.
        for _ in range(2):
            created = await self._fetch_one(query, one, two, source)
            if created:
                return created
            existing = await self.get_active_pair(one, two)
            if existing:
                return existing
        raise RuntimeError(f"Не удалось открыть диалог для пары {one}/{two}")

    async def close_dialog(self, dialog_id: int) -> None:
        query = "UPDATE dialogs SET closed_at = NOW() WHERE id = $1 AND closed_at IS NULL;"
        await self._execute_query(query, dialog_id)

    async def close_all_for_user(self, tg_chat_id: str) -> None:
        query = """
        UPDATE dialogs
        SET closed_at = NOW()
        WHERE closed_at IS NULL AND (user_one = $1 OR user_two = $1);
        """
        await self._execute_query(query, tg_chat_id)

    async def get_recent_for_user(self, tg_chat_id: str, limit: int) -> List[Dialog]:
        """Последние диалоги пользователя, по одному на собеседника.

        Нужен для списка переписок: DISTINCT ON оставляет самый свежий диалог
        с каждым собеседником, включая закрытые — история не должна исчезать
        после выхода из диалога.
        """
        query = """
        SELECT id, user_one, user_two, source, created_at, closed_at
        FROM (
            SELECT DISTINCT ON (CASE WHEN user_one = $1 THEN user_two ELSE user_one END)
                   id, user_one, user_two, source, created_at, closed_at
            FROM dialogs
            WHERE user_one = $1 OR user_two = $1
            ORDER BY CASE WHEN user_one = $1 THEN user_two ELSE user_one END,
                     created_at DESC, id DESC
        ) AS latest_per_peer
        ORDER BY created_at DESC
        LIMIT $2;
        """
        return await self._fetch_all(query, tg_chat_id, limit)
