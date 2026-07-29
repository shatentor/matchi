import json
from typing import Any, Dict, List, Optional, Tuple

import asyncpg

from db.repositories.base import BaseRepository
from models.post import FeedItem, Post, PostComment, PostMedia

# Результаты set_reaction. Реакция одна на человека на пост (PRIMARY KEY
# (post_id, tg_chat_id)), поэтому нажатие либо ставит новую, либо заменяет
# прежнюю, либо снимает её, если нажали то же самое эмодзи.
REACTION_SET = "set"
REACTION_CHANGED = "changed"
REACTION_REMOVED = "removed"

# Одна выборка на все три способа читать ленту: один пост, страница ленты и
# посты одного автора. Всё, что нужно для отрисовки, собирается здесь же —
# автор, вложения, счётчики реакций по эмодзи, число комментариев и реакция
# смотрящего. Отдельные доборы дали бы N+1: страница ленты стоила бы
# 1 + 4 * limit запросов вместо одного.
#
# Вложений на пост немного (settings.POST_MAX_MEDIA = 10), поэтому они
# сворачиваются в jsonb_agg с сортировкой по position прямо в этом запросе:
# добор по WHERE post_id = ANY($1) стоил бы второго round-trip и сборки
# соответствий в Python при тех же данных.
#
# NULL-параметры работают как «без фильтра» (приём из RoomRepository.list_active):
# приведение $N::TYPE обязательно, иначе PostgreSQL не выведет тип параметра.
FEED_QUERY = """
SELECT p.id, p.author_chat_id, p.interest_id, p.text, p.created_at, p.deleted_at,
       u.name AS author_name, u.role AS author_role, u.tg_username AS author_username,
       (SELECT COALESCE(jsonb_object_agg(counts.emoji, counts.cnt), jsonb_build_object())
          FROM (SELECT pr.emoji, COUNT(*) AS cnt
                  FROM post_reactions pr
                 WHERE pr.post_id = p.id
                 GROUP BY pr.emoji) counts) AS reactions,
       (SELECT COUNT(*)
          FROM post_comments pc
         WHERE pc.post_id = p.id AND pc.deleted_at IS NULL) AS comment_count,
       (SELECT mine.emoji
          FROM post_reactions mine
         WHERE mine.post_id = p.id AND mine.tg_chat_id = $1) AS my_reaction,
       (SELECT COALESCE(jsonb_agg(jsonb_build_object('id', pm.id,
                                                     'post_id', pm.post_id,
                                                     'file_id', pm.file_id,
                                                     'media_type', pm.media_type,
                                                     'position', pm.position)
                                  ORDER BY pm.position, pm.id), '[]'::jsonb)
          FROM post_media pm
         WHERE pm.post_id = p.id) AS media
  FROM posts p
  LEFT JOIN users u ON u.tg_chat_id = p.author_chat_id
 WHERE p.deleted_at IS NULL
   AND ($2::INTEGER IS NULL OR p.id = $2::INTEGER)
   AND ($3::INTEGER IS NULL OR p.id < $3::INTEGER)
   AND ($4::VARCHAR IS NULL OR p.author_chat_id = $4::VARCHAR)
 ORDER BY p.id DESC
 LIMIT $5;
"""


def _load_json(value: Any, empty: Any) -> Any:
    """Разбирает значение jsonb из asyncpg.

    Без зарегистрированного кодека asyncpg отдаёт json и jsonb СТРОКОЙ, поэтому
    полагаться на готовый dict нельзя. Функция терпит оба варианта: кодек может
    появиться позже в настройке пула.
    """
    if value is None:
        return empty
    if isinstance(value, (str, bytes)):
        return json.loads(value)
    return value


class PostRepository(BaseRepository):
    """Весь SQL постов: сами посты, вложения, реакции, комментарии и отметки чтения.

    tg_chat_id пользователя принимается и возвращается строкой, как в users.
    Лента отдаётся готовыми FeedItem: страница собирается одним запросом
    (FEED_QUERY), потому что бот показывает посты по одному и добор данных на
    каждый пост превратился бы в N+1.
    """

    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool, Post, "posts")

    # ---------- посты ----------

    async def create(self, author_chat_id: str, text: Optional[str],
                     interest_id: Optional[int]) -> Post:
        query = """
        INSERT INTO posts (author_chat_id, text, interest_id)
        VALUES ($1, $2, $3)
        RETURNING id, author_chat_id, interest_id, text, created_at, deleted_at;
        """
        record = await self._fetch_one(query, author_chat_id, text, interest_id)
        return record if record else Post(author_chat_id=author_chat_id, text=text,
                                         interest_id=interest_id)

    async def get(self, post_id: int) -> Optional[Post]:
        """Сам пост без окружения — для проверки прав на удаление.

        Мягко удалённый пост тоже возвращается: иначе повторное удаление
        выглядело бы как «поста не существует».
        """
        query = """
        SELECT id, author_chat_id, interest_id, text, created_at, deleted_at
        FROM posts
        WHERE id = $1;
        """
        return await self._fetch_one(query, post_id)

    async def add_media(self, post_id: int, items: List[Tuple[str, str]]) -> None:
        """Добавляет вложения поста в переданном порядке — одним запросом.

        Порядок хранится в position, потому что медиагруппа Telegram
        отправляется списком и должна повторять порядок загрузки.
        """
        if not items:
            return

        file_ids = [file_id for file_id, _ in items]
        media_types = [media_type for _, media_type in items]
        positions = list(range(len(items)))

        query = """
        INSERT INTO post_media (post_id, file_id, media_type, position)
        SELECT $1, m.file_id, m.media_type, m.position
        FROM UNNEST($2::VARCHAR[], $3::VARCHAR[], $4::INTEGER[])
             AS m(file_id, media_type, position);
        """
        await self._execute_query(query, post_id, file_ids, media_types, positions)

    async def soft_delete(self, post_id: int) -> None:
        """Убирает пост из ленты, не удаляя строку.

        Физическое удаление увело бы за собой комментарии и реакции по
        ON DELETE CASCADE, а они — чужие данные.
        """
        query = "UPDATE posts SET deleted_at = NOW() WHERE id = $1 AND deleted_at IS NULL;"
        await self._execute_query(query, post_id)

    async def latest_id(self) -> int:
        query = "SELECT COALESCE(MAX(id), 0) AS latest FROM posts WHERE deleted_at IS NULL;"
        record = await self.pool.fetchrow(query)
        return record['latest'] if record else 0

    async def count_today(self, author_chat_id: str) -> int:
        """Сколько постов автор опубликовал за последние сутки.

        Скользящее окно, а не календарный день: таймзона пользователя нигде не
        хранится, а на календарных сутках сервера лимит обходится десятью
        постами в 23:59 и ещё десятью в 00:01. Мягко удалённые посты тоже
        считаются, иначе лимит снимался бы удалением своих же постов.
        """
        query = """
        SELECT COUNT(*) AS posts_today
        FROM posts
        WHERE author_chat_id = $1 AND created_at >= NOW() - INTERVAL '1 day';
        """
        record = await self.pool.fetchrow(query, author_chat_id)
        return record['posts_today'] if record else 0

    # ---------- лента ----------

    async def get_feed_item(self, post_id: int, viewer_chat_id: str) -> Optional[FeedItem]:
        record = await self.pool.fetchrow(FEED_QUERY, viewer_chat_id, post_id, None, None, 1)
        return self._to_feed_item(record) if record else None

    async def feed_page(self, viewer_chat_id: str, before_id: Optional[int],
                        limit: int) -> List[FeedItem]:
        """Страница ленты: свежие сверху, before_id — листание вглубь.

        Порядок и курсор идут по id, а не по created_at: id — SERIAL, поэтому
        порядок тот же, зато курсор before_id однозначен и не спотыкается на
        постах с одинаковым временем.
        """
        records = await self.pool.fetch(FEED_QUERY, viewer_chat_id, None, before_id, None, limit)
        return [self._to_feed_item(record) for record in records]

    async def author_posts(self, author_chat_id: str, limit: int) -> List[FeedItem]:
        """Посты одного автора. Смотрящий — он сам, поэтому видит свои реакции."""
        records = await self.pool.fetch(FEED_QUERY, author_chat_id, None, None,
                                        author_chat_id, limit)
        return [self._to_feed_item(record) for record in records]

    async def newer_count(self, viewer_chat_id: str, last_seen_post_id: int) -> int:
        """Сколько чужих постов появилось после последнего просмотренного.

        Свои посты не считаются новыми: человек их только что и написал.
        """
        query = """
        SELECT COUNT(*) AS newer
        FROM posts
        WHERE deleted_at IS NULL AND id > $2 AND author_chat_id <> $1;
        """
        record = await self.pool.fetchrow(query, viewer_chat_id, last_seen_post_id)
        return record['newer'] if record else 0

    @staticmethod
    def _to_feed_item(record: asyncpg.Record) -> FeedItem:
        """Собирает FeedItem из строки FEED_QUERY."""
        media_rows = _load_json(record['media'], [])
        reactions = _load_json(record['reactions'], {})

        post = Post(
            id=record['id'],
            author_chat_id=record['author_chat_id'],
            interest_id=record['interest_id'],
            text=record['text'],
            created_at=record['created_at'],
            deleted_at=record['deleted_at'],
        )
        return FeedItem(
            post=post,
            author_name=record['author_name'],
            author_role=record['author_role'],
            author_username=record['author_username'],
            media=[PostMedia.model_validate(row) for row in media_rows],
            reactions={emoji: int(count) for emoji, count in reactions.items()},
            comment_count=record['comment_count'],
            my_reaction=record['my_reaction'],
        )

    # ---------- реакции ----------

    async def set_reaction(self, post_id: int, tg_chat_id: str, emoji: str) -> str:
        """Ставит, заменяет или снимает реакцию. Возвращает 'set'|'changed'|'removed'.

        Всё делается ОДНИМ запросом: между чтением прежней реакции и записью
        новой не должно быть окна, иначе два быстрых нажатия (или два устройства
        одного человека) оставят реакцию в состоянии, которого пользователь не
        просил. Порядок внутри запроса задан ссылкой на CTE removed: сначала
        снимаем ту же реакцию, и только если снимать было нечего — вставляем
        или заменяем. Обе ветки взаимно исключают друг друга, поэтому одна
        строка дважды не изменяется.

        xmax = 0 отличает вставку от замены: у строки, обновлённой через
        ON CONFLICT DO UPDATE, xmax уже проставлен.
        """
        query = """
        WITH removed AS (
            DELETE FROM post_reactions
            WHERE post_id = $1 AND tg_chat_id = $2 AND emoji = $3
            RETURNING emoji
        ), upserted AS (
            INSERT INTO post_reactions (post_id, tg_chat_id, emoji)
            SELECT $1::INTEGER, $2::VARCHAR, $3::VARCHAR
            WHERE NOT EXISTS (SELECT 1 FROM removed)
            ON CONFLICT (post_id, tg_chat_id) DO UPDATE
                SET emoji = EXCLUDED.emoji, created_at = NOW()
            RETURNING (xmax = 0) AS inserted
        )
        SELECT CASE
                   WHEN EXISTS (SELECT 1 FROM removed) THEN 'removed'
                   WHEN COALESCE((SELECT inserted FROM upserted), TRUE) THEN 'set'
                   ELSE 'changed'
               END AS result;
        """
        record = await self.pool.fetchrow(query, post_id, tg_chat_id, emoji)
        return record['result'] if record else REACTION_SET

    async def reaction_of(self, post_id: int, tg_chat_id: str) -> Optional[str]:
        query = "SELECT emoji FROM post_reactions WHERE post_id = $1 AND tg_chat_id = $2;"
        record = await self.pool.fetchrow(query, post_id, tg_chat_id)
        return record['emoji'] if record else None

    async def first_reaction_of(self, post_id: int, tg_chat_id: str) -> bool:
        """Ставит ли человек реакцию на этот пост впервые (и не уведомляли ли уже).

        Спрашивать это надо ДО set_reaction: после него строка в post_reactions
        уже есть, и отличить первое нажатие от смены эмодзи нельзя.

        Одного условия недостаточно: наличие строки в post_reactions
        отвечает только на «реакция стоит прямо сейчас», а снятие реакции строку
        удаляет. Без отметки в post_reaction_notices цикл «поставил — снял —
        поставил» каждый раз выглядел бы как первая реакция и заваливал автора.

        При отсутствии ответа от БД возвращается False: лучше не уведомить, чем
        уведомить лишний раз.
        """
        query = """
        SELECT NOT EXISTS (SELECT 1 FROM post_reactions
                            WHERE post_id = $1 AND tg_chat_id = $2)
           AND NOT EXISTS (SELECT 1 FROM post_reaction_notices
                            WHERE post_id = $1 AND tg_chat_id = $2) AS first_time;
        """
        record = await self.pool.fetchrow(query, post_id, tg_chat_id)
        return bool(record['first_time']) if record else False

    async def mark_reaction_notified(self, post_id: int, tg_chat_id: str) -> None:
        """Запоминает, что автора об этой реакции уже уведомили.

        DO NOTHING, а не проверка перед вставкой: два быстрых нажатия могут
        дойти одновременно, и вторая вставка не должна ронять сценарий.
        """
        query = """
        INSERT INTO post_reaction_notices (post_id, tg_chat_id)
        VALUES ($1, $2)
        ON CONFLICT (post_id, tg_chat_id) DO NOTHING;
        """
        await self._execute_query(query, post_id, tg_chat_id)

    # ---------- комментарии ----------

    async def add_comment(self, post_id: int, author_chat_id: str, text: str) -> PostComment:
        query = """
        INSERT INTO post_comments (post_id, author_chat_id, text)
        VALUES ($1, $2, $3)
        RETURNING id, post_id, author_chat_id, text, created_at, deleted_at;
        """
        record = await self.pool.fetchrow(query, post_id, author_chat_id, text)
        return PostComment.model_validate(dict(record))

    async def comments(self, post_id: int, limit: int) -> List[Dict[str, Any]]:
        """Последние комментарии поста в хронологическом порядке, с именем автора.

        Имя берётся LEFT JOIN на users: автор мог не дозаполнить анкету, и
        комментарий всё равно должен показаться.
        """
        query = """
        SELECT pc.id, pc.post_id, pc.author_chat_id, pc.text, pc.created_at,
               u.name AS author_name, u.tg_username AS author_username
        FROM post_comments pc
        LEFT JOIN users u ON u.tg_chat_id = pc.author_chat_id
        WHERE pc.post_id = $1 AND pc.deleted_at IS NULL
        ORDER BY pc.created_at DESC, pc.id DESC
        LIMIT $2;
        """
        records = await self.pool.fetch(query, post_id, limit)
        # Запрос отбирает свежие (DESC), а читать переписку надо снизу вверх
        return [dict(record) for record in reversed(records)]

    # ---------- отметка «докуда долистал» ----------

    async def feed_view(self, tg_chat_id: str) -> int:
        query = "SELECT last_seen_post_id FROM feed_views WHERE tg_chat_id = $1;"
        record = await self.pool.fetchrow(query, tg_chat_id)
        return record['last_seen_post_id'] if record else 0

    async def set_feed_view(self, tg_chat_id: str, post_id: int) -> None:
        """Двигает отметку прочитанного вперёд.

        GREATEST обязателен: листая ленту вглубь, пользователь показывает посты
        с меньшими id, и без него отметка уехала бы назад, а все посты между
        снова стали бы «новыми».
        """
        query = """
        INSERT INTO feed_views (tg_chat_id, last_seen_post_id)
        VALUES ($1, $2)
        ON CONFLICT (tg_chat_id) DO UPDATE
            SET last_seen_post_id = GREATEST(feed_views.last_seen_post_id,
                                             EXCLUDED.last_seen_post_id),
                updated_at = NOW();
        """
        await self._execute_query(query, tg_chat_id, post_id)

    # ---------- уведомления ----------

    async def notify_targets(self, exclude_chat_id: str) -> List[str]:
        """Кому уходит уведомление о новом посте: все зарегистрированные, кроме автора.

        Отписавшиеся (feed_notify = FALSE) отсекаются здесь, а не в сервисе:
        иначе они всё равно попадали бы в очередь рассылки.
        """
        query = """
        SELECT tg_chat_id
        FROM users
        WHERE is_registered = 'yes' AND feed_notify = TRUE AND tg_chat_id <> $1;
        """
        records = await self.pool.fetch(query, exclude_chat_id)
        return [record['tg_chat_id'] for record in records]

    async def notify_enabled(self, tg_chat_id: str) -> bool:
        query = "SELECT feed_notify FROM users WHERE tg_chat_id = $1;"
        record = await self.pool.fetchrow(query, tg_chat_id)
        return bool(record['feed_notify']) if record else False

    async def reply_notify_enabled(self, tg_chat_id: str) -> bool:
        """Хочет ли человек знать об отзывах на свои посты.

        Флаг отдельный от feed_notify: «новые посты в сети» и «отзывы на мои
        посты» выключают по разным причинам.
        """
        query = "SELECT reply_notify FROM users WHERE tg_chat_id = $1;"
        record = await self.pool.fetchrow(query, tg_chat_id)
        return bool(record['reply_notify']) if record else False

    async def toggle_reply_notify(self, tg_chat_id: str) -> bool:
        """Переключает уведомления об отзывах и возвращает новое состояние."""
        query = """
        UPDATE users
        SET reply_notify = NOT reply_notify
        WHERE tg_chat_id = $1
        RETURNING reply_notify;
        """
        record = await self.pool.fetchrow(query, tg_chat_id)
        return bool(record['reply_notify']) if record else False

    async def toggle_notify(self, tg_chat_id: str) -> bool:
        """Переключает уведомления о новых постах и возвращает новое состояние.

        Одним запросом, а не парой «прочитать — записать»: иначе два быстрых
        нажатия могли бы записать одно и то же значение дважды.
        """
        query = """
        UPDATE users
        SET feed_notify = NOT feed_notify
        WHERE tg_chat_id = $1
        RETURNING feed_notify;
        """
        record = await self.pool.fetchrow(query, tg_chat_id)
        return bool(record['feed_notify']) if record else False
