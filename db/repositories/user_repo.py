import asyncpg
from typing import Optional, List, Any, Tuple
from models.user import User, UserProfileData
from db.repositories.base import BaseRepository

# Каталог участников. Отбор и ранжирование целиком в SQL — одним запросом на
# страницу, без добора данных на каждого участника (в подборе анкет такой добор
# уже приводил к N+1).
#
# Лайки и дизлайки здесь не учитываются намеренно: в колоде дизлайк исключает
# человека навсегда, а каталог показывает всех участников сети.
#
# NULL-параметр означает «без фильтра» (приём из RoomRepository.list_active и
# PostRepository.FEED_QUERY): приведение $N::TYPE обязательно, иначе PostgreSQL
# не выведет тип параметра при NULL.
#
# Общие интересы считаются подзапросом и на отбор не влияют — это ранжирование:
# участник без совпадений обязан остаться в выдаче.
DIRECTORY_QUERY = """
SELECT u.tg_chat_id, u.tg_username, u.name, u.city, u.role, u.status, u.links,
       u.can_help, u.looking_for,
       ARRAY_REMOVE(ARRAY[u.photo_link, u.photo_link_two, u.photo_link_three], NULL) AS photo_ids,
       d.descr AS description,
       (SELECT COUNT(*)
          FROM user_interests mine
          INNER JOIN user_interests theirs ON theirs.interest_id = mine.interest_id
         WHERE mine.tg_chat_id = $1 AND theirs.tg_chat_id = u.tg_chat_id) AS common
  FROM users u
  INNER JOIN descriptions d ON d.tg_chat_id = u.tg_chat_id
 WHERE u.is_registered = 'yes'
   AND u.tg_chat_id <> $1
   AND u.name IS NOT NULL AND u.city IS NOT NULL AND u.role IS NOT NULL
   AND d.descr IS NOT NULL AND d.descr <> ''
   AND ($2::VARCHAR IS NULL OR u.name ILIKE $2::VARCHAR
                            OR u.role ILIKE $2::VARCHAR
                            OR u.city ILIKE $2::VARCHAR
                            OR u.status ILIKE $2::VARCHAR)
   AND ($3::INTEGER IS NULL OR EXISTS (SELECT 1 FROM user_interests f
                                        WHERE f.tg_chat_id = u.tg_chat_id
                                          AND f.interest_id = $3::INTEGER))
   AND ($4::VARCHAR IS NULL OR u.city ILIKE $4::VARCHAR)
 ORDER BY common DESC, u.name, u.tg_chat_id
 LIMIT $5 OFFSET $6;
"""

# Тот же отбор, что в DIRECTORY_QUERY, но без ранжирования и без данных профиля:
# нужен для «стр. N из M». Условия выписаны второй раз намеренно — склейка
# запроса из куска f-строкой прячет его от проверки sqlglot в smoke_check.
DIRECTORY_COUNT_QUERY = """
SELECT COUNT(*) AS total
  FROM users u
  INNER JOIN descriptions d ON d.tg_chat_id = u.tg_chat_id
 WHERE u.is_registered = 'yes'
   AND u.tg_chat_id <> $1
   AND u.name IS NOT NULL AND u.city IS NOT NULL AND u.role IS NOT NULL
   AND d.descr IS NOT NULL AND d.descr <> ''
   AND ($2::VARCHAR IS NULL OR u.name ILIKE $2::VARCHAR
                            OR u.role ILIKE $2::VARCHAR
                            OR u.city ILIKE $2::VARCHAR
                            OR u.status ILIKE $2::VARCHAR)
   AND ($3::INTEGER IS NULL OR EXISTS (SELECT 1 FROM user_interests f
                                        WHERE f.tg_chat_id = u.tg_chat_id
                                          AND f.interest_id = $3::INTEGER))
   AND ($4::VARCHAR IS NULL OR u.city ILIKE $4::VARCHAR);
"""


def _escape_like(value: str) -> str:
    """Обезвреживает шаблонные символы ILIKE в тексте от пользователя.

    Без этого запрос «%» совпал бы со всеми участниками, а «_» — с любым
    символом: для человека, который просто ищет подстроку, это выглядит
    как сломанный поиск. Экранирующий символ по умолчанию в PostgreSQL —
    обратный слэш, поэтому его тоже приходится удваивать.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class UserRepository(BaseRepository):
    def __init__(self, pool: asyncpg.Pool):
        # Пользовательская таблица 'users' использует 'tg_chat_id' как PK,
        # поэтому метод get_by_id из BaseRepository не будет работать корректно
        # для UserRepository без его переопределения.
        # В BaseRepository get_by_id ищет по "id", но в users нет колонки "id".
        super().__init__(pool, User, "users")

    async def create(self, user: User) -> User:
        query = """
        INSERT INTO users (tg_chat_id, tg_username, name, city, role, status, links,
                           can_help, looking_for, photo_link, photo_link_two,
                           photo_link_three, last_shown_profile, support_time, is_registered)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
        RETURNING *;
        """
        record = await self._fetch_one(query,
            user.tg_chat_id, user.tg_username, user.name, user.city, user.role,
            user.status, user.links, user.can_help, user.looking_for, user.photo_link,
            user.photo_link_two, user.photo_link_three, user.last_shown_profile,
            user.support_time, user.is_registered
        )
        return record if record else user

    async def get_by_id(self, tg_chat_id: str) -> Optional[User]:
        # Переопределяем get_by_id для User, чтобы использовать tg_chat_id
        query = "SELECT * FROM users WHERE tg_chat_id = $1;"
        return await self._fetch_one(query, tg_chat_id)

    async def update(self, user: User) -> User:
        query = """
        UPDATE users
        SET tg_username = $2, name = $3, city = $4, role = $5, status = $6, links = $7,
            can_help = $8, looking_for = $9, photo_link = $10, photo_link_two = $11,
            photo_link_three = $12, last_shown_profile = $13, support_time = $14,
            is_registered = $15
        WHERE tg_chat_id = $1
        RETURNING *;
        """
        record = await self._fetch_one(query,
            user.tg_chat_id, user.tg_username, user.name, user.city, user.role,
            user.status, user.links, user.can_help, user.looking_for, user.photo_link,
            user.photo_link_two, user.photo_link_three, user.last_shown_profile,
            user.support_time, user.is_registered
        )
        return record if record else user

    async def get_all_chat_ids(self) -> List[str]:
        query = "SELECT tg_chat_id FROM users;"
        records = await self.pool.fetch(query)
        return [r['tg_chat_id'] for r in records]

    async def get_candidate_ids(self, tg_chat_id: str, limit: int) -> List[str]:
        """Возвращает список ID анкет, подходящих пользователю.

        Отбор целиком выполняется в БД: одним запросом вместо выборки всех
        пользователей и двух запросов на каждого из них. Анкеты без описания
        исключаются, потому что отрисовать их всё равно невозможно.

        Сортировка: сначала анкеты с большим числом общих интересов, при равенстве
        — случайный порядок. Общие интересы считаются подзапросом и на отбор не
        влияют: кандидат без совпадений остаётся в выдаче, иначе при незаполненных
        интересах (сид справочника может быть не применён) поиск вернул бы ноль анкет.
        """
        query = """
        SELECT u.tg_chat_id,
               (SELECT COUNT(*)
                FROM user_interests mine
                INNER JOIN user_interests theirs ON theirs.interest_id = mine.interest_id
                WHERE mine.tg_chat_id = $1 AND theirs.tg_chat_id = u.tg_chat_id) AS common
        FROM users u
        WHERE u.is_registered = 'yes'
          AND u.tg_chat_id <> $1
          AND EXISTS (SELECT 1 FROM descriptions d WHERE d.tg_chat_id = u.tg_chat_id
                      AND d.descr IS NOT NULL AND d.descr <> '')
          AND NOT EXISTS (SELECT 1 FROM likes l
                          WHERE l.liker_chat_id = $1 AND l.liked_chat_id = u.tg_chat_id)
          AND NOT EXISTS (SELECT 1 FROM dislikes dl
                          WHERE dl.disliker_chat_id = $1 AND dl.disliked_chat_id = u.tg_chat_id)
        ORDER BY common DESC, RANDOM()
        LIMIT $2;
        """
        records = await self.pool.fetch(query, tg_chat_id, limit)
        return [r['tg_chat_id'] for r in records]

    async def directory_page(self, viewer_chat_id: str, query: Optional[str],
                             interest_id: Optional[int], city: Optional[str],
                             offset: int, limit: int) -> List[UserProfileData]:
        """Страница каталога участников — одним запросом.

        Возвращает готовые UserProfileData: без описания участника отрисовать
        нечем, поэтому descriptions присоединяется INNER JOIN, а не добирается
        отдельным запросом на каждого.

        query — подстрока, ищется регистронезависимо сразу по имени, роли,
        городу и статусу; None или пустая строка означают «без фильтра».
        city сравнивается целиком (ILIKE без шаблонных символов).
        """
        pattern = f"%{_escape_like(query.strip())}%" if query and query.strip() else None
        city_pattern = _escape_like(city.strip()) if city and city.strip() else None
        records = await self.pool.fetch(DIRECTORY_QUERY, viewer_chat_id, pattern, interest_id,
                                        city_pattern, max(1, limit), max(0, offset))
        return [UserProfileData.model_validate(dict(record)) for record in records]

    async def directory_count(self, viewer_chat_id: str, query: Optional[str] = None,
                              interest_id: Optional[int] = None,
                              city: Optional[str] = None) -> int:
        """Сколько всего участников попадает в те же фильтры — для «стр. N из M»."""
        pattern = f"%{_escape_like(query.strip())}%" if query and query.strip() else None
        city_pattern = _escape_like(city.strip()) if city and city.strip() else None
        record = await self.pool.fetchrow(DIRECTORY_COUNT_QUERY, viewer_chat_id, pattern,
                                          interest_id, city_pattern)
        return record['total'] if record else 0

    async def cities_with_members(self) -> List[Tuple[str, int]]:
        """Города и число участников в каждом — для кнопок «кто рядом».

        Считаются только те, кого каталог действительно покажет: со статусом
        'yes' и непустым описанием.
        """
        query = """
        SELECT u.city, COUNT(*) AS members
          FROM users u
          INNER JOIN descriptions d ON d.tg_chat_id = u.tg_chat_id
         WHERE u.is_registered = 'yes'
           AND u.city IS NOT NULL AND u.city <> ''
           AND d.descr IS NOT NULL AND d.descr <> ''
         GROUP BY u.city
         ORDER BY members DESC, u.city;
        """
        records = await self.pool.fetch(query)
        return [(r['city'], r['members']) for r in records]

    async def update_username(self, tg_chat_id: str, username: Optional[str]) -> None:
        await self._execute_query("UPDATE users SET tg_username = $1 WHERE tg_chat_id = $2", username, tg_chat_id)

    async def update_register_status(self, tg_chat_id: str, status: str) -> None:
        await self._execute_query("UPDATE users SET is_registered = $1 WHERE tg_chat_id = $2", status, tg_chat_id)

    async def update_photo_link(self, tg_chat_id: str, photo_num: int, file_id: Optional[str]) -> None:
        column_map = {1: "photo_link", 2: "photo_link_two", 3: "photo_link_three"}
        if photo_num not in column_map:
            raise ValueError("Invalid photo number")
        query = f"UPDATE users SET {column_map[photo_num]} = $1 WHERE tg_chat_id = $2"
        await self._execute_query(query, file_id, tg_chat_id)

    async def get_description(self, tg_chat_id: str) -> Optional[str]:
        query = "SELECT descr FROM descriptions WHERE tg_chat_id = $1"
        record = await self.pool.fetchrow(query, tg_chat_id)
        return record['descr'] if record else None

    async def update_description(self, tg_chat_id: str, description: str) -> None:
        query = """
        INSERT INTO descriptions (tg_chat_id, descr)
        VALUES ($1, $2)
        ON CONFLICT (tg_chat_id) DO UPDATE SET descr = $2;
        """
        await self._execute_query(query, tg_chat_id, description)

    async def update_last_shown_profile(self, tg_chat_id: str, shown_profile_id: str) -> None:
        await self._execute_query("UPDATE users SET last_shown_profile = $1 WHERE tg_chat_id = $2", shown_profile_id, tg_chat_id)

    async def get_last_shown_profile(self, tg_chat_id: str) -> Optional[str]:
        query = "SELECT last_shown_profile FROM users WHERE tg_chat_id = $1;"
        record = await self.pool.fetchrow(query, tg_chat_id)
        return record['last_shown_profile'] if record else None

    async def update_support_time(self, tg_chat_id: str, timestamp: int) -> None:
        await self._execute_query("UPDATE users SET support_time = $1 WHERE tg_chat_id = $2", timestamp, tg_chat_id)

    async def get_support_time(self, tg_chat_id: str) -> Optional[int]:
        query = "SELECT support_time FROM users WHERE tg_chat_id = $1;"
        record = await self.pool.fetchrow(query, tg_chat_id)
        return record['support_time'] if record and record['support_time'] is not None else 0