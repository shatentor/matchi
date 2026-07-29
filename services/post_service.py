import logging
from typing import Any, Dict, List, Optional, Tuple

from config.settings import settings
from db.repositories.post_repo import PostRepository
from db.repositories.user_repo import UserRepository
from models.post import EMOJI_COLUMN_LENGTH, FeedItem, Post, PostComment
from services.outbox import Outbox
from utils.text import escape

logger = logging.getLogger(__name__)

# Сколько символов поста показать в уведомлении. Уведомление — это приглашение
# открыть ленту, а не сам пост: фотографии в него всё равно не попадают.
NOTIFY_PREVIEW_LENGTH = 160


class PostService:
    """Посты и лента: публикация, показ по одному посту, реакции, комментарии.

    Веер уведомлений о новом посте идёт ТОЛЬКО через Outbox: Telegram не даёт
    боту больше ~30 сообщений в секунду суммарно, и за превышение флуд-контроль
    накрывает весь бот, а не одну рассылку. Прямой цикл bot.send_message здесь
    недопустим — так же, как в RoomService.broadcast.

    Репозиторий принимает tg_chat_id строкой, сервис — числом (как его отдаёт
    Telegram), приведение делается здесь.
    """

    def __init__(self, post_repo: PostRepository, user_repo: UserRepository,
                 outbox: Optional[Outbox] = None):
        self.post_repo = post_repo
        self.user_repo = user_repo
        self.outbox = outbox

    # ---------- публикация ----------

    async def publish(self, author_id: int, text: Optional[str],
                      media: List[Tuple[str, str]],
                      interest_id: Optional[int] = None) -> Tuple[Optional[Post], str]:
        """Публикует пост. При отказе возвращает (None, причина для пользователя).

        media — список (file_id, media_type) в том порядке, в котором его
        показывать. Лишние вложения и лишний текст отрезаются, а не приводят к
        отказу: человек уже потратил время на сбор поста.
        """
        author = str(author_id)

        clean_text = (text or "").strip()[:settings.POST_MAX_TEXT_LENGTH] or None
        clean_media = list(media or [])[:settings.POST_MAX_MEDIA]

        if not clean_text and not clean_media:
            return None, "Пустой пост опубликовать нельзя: пришлите текст или фотографию."

        posts_today = await self.post_repo.count_today(author)
        if posts_today >= settings.POSTS_PER_DAY:
            return None, (f"На сегодня лимит постов исчерпан ({settings.POSTS_PER_DAY} за сутки). "
                          f"Попробуйте позже.")

        post = await self.post_repo.create(author, clean_text, interest_id)
        if post.id is None:
            logger.error(f"Пост пользователя {author_id} не создался")
            return None, "Не получилось опубликовать пост. Попробуйте ещё раз."

        if clean_media:
            await self.post_repo.add_media(post.id, clean_media)

        return post, "Пост опубликован."

    async def notify_new_post(self, post: Post, author_name: str) -> int:
        """Ставит в очередь уведомления о новом посте. Возвращает число адресатов.

        Отправка идёт исключительно через Outbox: цикл bot.send_message по всем
        участникам упирается в лимиты Telegram и заканчивается флуд-контролем на
        весь бот. Отписавшихся и самого автора отсекает repo.notify_targets.
        """
        if post.id is None:
            return 0

        targets = await self.post_repo.notify_targets(post.author_chat_id)
        if not targets:
            return 0

        if self.outbox is None:
            logger.error(f"Outbox не передан в PostService, уведомления о посте {post.id} "
                         f"не разосланы")
            return 0

        preview = (post.text or "").strip()[:NOTIFY_PREVIEW_LENGTH]
        payload = f"🆕 Новый пост от <b>{escape(author_name)}</b>"
        if preview:
            payload += f":\n{escape(preview)}"
        payload += "\n\nОткрыть ленту: /feed"

        queued = 0
        for chat_id in targets:
            try:
                await self.outbox.enqueue(int(chat_id), payload)
                queued += 1
            except (TypeError, ValueError):
                logger.warning(f"Некорректный tg_chat_id получателя уведомления: {chat_id!r}")

        return queued

    # ---------- чтение ленты ----------

    async def feed_page(self, viewer_id: int, before_id: Optional[int] = None,
                        limit: int = 1) -> List[FeedItem]:
        """Страница ленты: свежие сверху, before_id — листание вглубь.

        В боте нет скролла, поэтому по умолчанию отдаётся один пост.
        """
        return await self.post_repo.feed_page(str(viewer_id), before_id, max(1, limit))

    async def feed_item(self, post_id: int, viewer_id: int) -> Optional[FeedItem]:
        return await self.post_repo.get_feed_item(post_id, str(viewer_id))

    async def my_posts(self, author_id: int, limit: int = 10) -> List[FeedItem]:
        return await self.post_repo.author_posts(str(author_id), max(1, limit))

    async def latest_id(self) -> int:
        return await self.post_repo.latest_id()

    # ---------- реакции ----------

    async def react(self, post_id: int, tg_chat_id: int,
                    emoji: str) -> Tuple[Optional[str], Optional[FeedItem]]:
        """Переключает реакцию и возвращает (действие, обновлённый пост).

        Действие — 'set', 'changed' или 'removed'; None означает отказ (поста
        нет или эмодзи не подходит). Обновлённый FeedItem нужен, чтобы
        перерисовать клавиатуру со счётчиками на месте, без нового сообщения.
        """
        clean = (emoji or "").strip()
        # post_reactions.emoji — VARCHAR(8), более длинное значение PostgreSQL
        # обрежет молча, и снять такую реакцию повторным нажатием уже не выйдет
        if not clean or len(clean) > EMOJI_COLUMN_LENGTH:
            logger.warning(f"Реакция {emoji!r} не подходит под колонку emoji")
            return None, None

        post = await self.post_repo.get(post_id)
        if post is None or post.is_deleted:
            return None, None

        action = await self.post_repo.set_reaction(post_id, str(tg_chat_id), clean)
        return action, await self.post_repo.get_feed_item(post_id, str(tg_chat_id))

    # ---------- комментарии ----------

    async def comment(self, post_id: int, author_id: int,
                      text: str) -> Tuple[Optional[PostComment], str]:
        """Добавляет комментарий. При отказе возвращает (None, причина)."""
        clean = (text or "").strip()[:settings.POST_MAX_COMMENT_LENGTH]
        if not clean:
            return None, "Комментарий не может быть пустым."

        post = await self.post_repo.get(post_id)
        if post is None or post.is_deleted:
            return None, "Этот пост уже удалён."

        created = await self.post_repo.add_comment(post_id, str(author_id), clean)
        return created, "Комментарий добавлен."

    async def comments(self, post_id: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Последние комментарии поста в хронологическом порядке, с именем автора."""
        return await self.post_repo.comments(post_id, limit or settings.FEED_COMMENTS_PREVIEW)

    # ---------- «что нового» ----------

    async def mark_seen(self, tg_chat_id: int, post_id: int) -> None:
        """Отмечает, докуда человек долистал. Отметка только двигается вперёд."""
        if post_id <= 0:
            return
        await self.post_repo.set_feed_view(str(tg_chat_id), post_id)

    async def unseen_count(self, tg_chat_id: int) -> int:
        """Сколько чужих постов появилось с прошлого захода в ленту."""
        chat_id = str(tg_chat_id)
        last_seen = await self.post_repo.feed_view(chat_id)
        return await self.post_repo.newer_count(chat_id, last_seen)

    # ---------- удаление и уведомления ----------

    async def delete(self, post_id: int, requester_id: int,
                     is_admin: bool = False) -> Tuple[bool, str]:
        """Мягко удаляет пост. Удалять может автор или админ."""
        post = await self.post_repo.get(post_id)
        if post is None:
            return False, "Такого поста нет."
        if post.is_deleted:
            return False, "Пост уже удалён."
        if post.author_chat_id != str(requester_id) and not is_admin:
            return False, "Удалить пост может только его автор."

        await self.post_repo.soft_delete(post_id)
        return True, "Пост удалён."

    async def toggle_notify(self, tg_chat_id: int) -> bool:
        """Включает или выключает уведомления о новых постах. Возвращает новое состояние."""
        return await self.post_repo.toggle_notify(str(tg_chat_id))

    async def notify_enabled(self, tg_chat_id: int) -> bool:
        return await self.post_repo.notify_enabled(str(tg_chat_id))
