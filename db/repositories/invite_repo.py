import asyncpg
from typing import List, Optional, Tuple

from db.repositories.base import BaseRepository
from models.invite import Invite

# Результат попытки погасить код (InviteRepository.add_use).
# Разделять «недоступен» и «этот человек уже входил по нему» приходится здесь:
# оба случая видны только внутри той транзакции, которая меняет счётчик.
ADD_USE_OK = "ok"
ADD_USE_ALREADY = "already"
ADD_USE_UNAVAILABLE = "unavailable"


class InviteRepository(BaseRepository):
    """Весь SQL приглашений: сами коды (invites) и факты их использования (invite_uses).

    tg_chat_id принимается и возвращается строкой, как в users.
    Колонки в запросах перечислены явно, без SELECT *: модель Invite ждёт
    ровно этот набор, и новая колонка в схеме не должна её ломать.
    """

    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool, Invite, "invites")

    async def create(self, invite: Invite) -> Optional[Invite]:
        """Сохраняет новый код.

        Возвращает None, если такой код уже занят: ON CONFLICT DO NOTHING вместо
        исключения нужен, чтобы сервис просто перегенерировал код, а слой
        сервисов не разбирал ошибки asyncpg.
        """
        query = """
        INSERT INTO invites (code, created_by, max_uses, used_count, expires_at, revoked)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (code) DO NOTHING
        RETURNING code, created_by, max_uses, used_count, expires_at, created_at, revoked;
        """
        return await self._fetch_one(
            query,
            invite.code, invite.created_by, invite.max_uses, invite.used_count,
            invite.expires_at, invite.revoked,
        )

    async def get(self, code: str) -> Optional[Invite]:
        query = """
        SELECT code, created_by, max_uses, used_count, expires_at, created_at, revoked
        FROM invites
        WHERE code = $1;
        """
        return await self._fetch_one(query, code)

    async def count_active_by(self, tg_chat_id: str) -> int:
        """Сколько у человека кодов, которыми ещё можно воспользоваться."""
        query = """
        SELECT COUNT(*) FROM invites
        WHERE created_by = $1
          AND revoked = FALSE
          AND used_count < max_uses
          AND (expires_at IS NULL OR expires_at > NOW());
        """
        record = await self.pool.fetchrow(query, tg_chat_id)
        return record[0] if record else 0

    async def list_by(self, tg_chat_id: str) -> List[Invite]:
        query = """
        SELECT code, created_by, max_uses, used_count, expires_at, created_at, revoked
        FROM invites
        WHERE created_by = $1
        ORDER BY created_at DESC;
        """
        return await self._fetch_all(query, tg_chat_id)

    async def add_use(self, code: str, tg_chat_id: str) -> Tuple[str, Optional[Invite]]:
        """Погашает код: увеличивает used_count и записывает, кто им воспользовался.

        Возвращает (ADD_USE_*, обновлённый код): на успехе — код с новым
        счётчиком, на отказе — None.

        Обе операции идут в ОДНОЙ транзакции на одном соединении. Иначе при двух
        одновременных регистрациях по одному коду проверка «использования ещё
        остались» и инкремент разъезжаются, и код уходит лишний раз.

        Сама проверка живёт в WHERE того же UPDATE, а не в отдельном SELECT:
        PostgreSQL держит строку под блокировкой до конца UPDATE, поэтому второй
        конкурент перепроверяет условие уже на новом значении used_count и
        честно не получает ни одной строки. NOT EXISTS по invite_uses в том же
        WHERE не даёт человеку истратить использование повторно, а составной
        PRIMARY KEY (code, tg_chat_id) страхует это на уровне схемы.
        """
        claim_query = """
        UPDATE invites
        SET used_count = used_count + 1
        WHERE code = $1
          AND revoked = FALSE
          AND used_count < max_uses
          AND (expires_at IS NULL OR expires_at > NOW())
          AND NOT EXISTS (
              SELECT 1 FROM invite_uses u WHERE u.code = $1 AND u.tg_chat_id = $2
          )
        RETURNING code, created_by, max_uses, used_count, expires_at, created_at, revoked;
        """
        used_query = "SELECT 1 FROM invite_uses WHERE code = $1 AND tg_chat_id = $2;"
        insert_query = "INSERT INTO invite_uses (code, tg_chat_id) VALUES ($1, $2);"

        async with self.pool.acquire() as conn:
            try:
                async with conn.transaction():
                    record = await conn.fetchrow(claim_query, code, tg_chat_id)
                    if record is None:
                        # Код мог быть недоступен, а мог быть уже использован этим
                        # человеком — различает это только invite_uses.
                        already = await conn.fetchrow(used_query, code, tg_chat_id)
                        return (ADD_USE_ALREADY if already else ADD_USE_UNAVAILABLE), None

                    await conn.execute(insert_query, code, tg_chat_id)
                    return ADD_USE_OK, Invite.model_validate(dict(record))
            except asyncpg.UniqueViolationError:
                # Тот же человек погасил код параллельно и успел первым: инкремент
                # откатился вместе с транзакцией, лишнее использование не списано.
                return ADD_USE_ALREADY, None

    async def revoke(self, code: str) -> bool:
        """Отзывает код. False означает «кода нет или он уже был отозван»."""
        query = """
        UPDATE invites SET revoked = TRUE
        WHERE code = $1 AND revoked = FALSE
        RETURNING code;
        """
        record = await self.pool.fetchrow(query, code)
        return record is not None

    async def used_any(self, tg_chat_id: str) -> bool:
        """Гасил ли человек хоть какой-нибудь код.

        Отдельно от inviter_of: created_by у старого кода может быть NULL
        (ON DELETE SET NULL в схеме), и «нет пригласившего» это не то же самое,
        что «не входил по коду».
        """
        query = "SELECT 1 FROM invite_uses WHERE tg_chat_id = $1 LIMIT 1;"
        record = await self.pool.fetchrow(query, tg_chat_id)
        return record is not None

    async def inviter_of(self, tg_chat_id: str) -> Optional[str]:
        """tg_chat_id того, чьим кодом человек вошёл в сеть (социальный граф).

        Берётся самое первое использование: привёл человека тот, чей код он
        погасил первым, даже если позже он засветился в других приглашениях.
        """
        query = """
        SELECT i.created_by FROM invite_uses u
        INNER JOIN invites i ON i.code = u.code
        WHERE u.tg_chat_id = $1
        ORDER BY u.used_at
        LIMIT 1;
        """
        record = await self.pool.fetchrow(query, tg_chat_id)
        return record['created_by'] if record else None
