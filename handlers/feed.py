import logging
from contextlib import suppress
from datetime import datetime
from typing import Any, Dict, List, Optional

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config.settings import settings
from filters.custom_filters import IsRegistered
from handlers.posts import PostStates, fit_escaped, render_feed_item, send_post
from keyboards.feed import (FeedCB, comment_cancel_keyboard, delete_confirm_keyboard,
                            feed_comments_keyboard, feed_post_keyboard, my_posts_keyboard)
from models.post import REACTION_EMOJIS, FeedItem
from models.user import User
from services.admin_service import AdminService
from services.interest_service import InterestService
from services.post_service import PostService
from services.user_service import UserService
from utils.text import escape

logger = logging.getLogger(__name__)

# Сообщение Telegram ограничено 4096 символами; списки комментариев и своих
# постов собираются из пользовательских текстов, поэтому режем с запасом на escape().
MAX_MESSAGE_LENGTH = 3500
# Размер страницы при поиске соседнего поста. Репозиторий листает только вглубь
# (before_id), поэтому «ближайший более свежий» ищется проходом от начала ленты.
FEED_PAGE = 50
# Ограничение прохода: без него испорченный post_id заставил бы перебрать всю ленту.
SCAN_PAGES = 10
# Сколько символов поста показывать в подписи кнопки и в списке своих постов
PREVIEW_LENGTH = 40

REACTION_NOTE = {
    "set": "Реакция поставлена.",
    "changed": "Реакция изменена.",
    "removed": "Реакция снята.",
}

POST_DRAFT_STATES = (PostStates.content.state, PostStates.topic.state,
                     PostStates.confirm.state)


class FeedStates(StatesGroup):
    comment = State()


class FeedHandlers:
    """Лента по одному посту: навигация, реакции, комментарии, свои посты.

    interest_service необязателен: без него у постов просто не показывается
    тема — остальное работает.
    """

    def __init__(self, post_service: PostService, user_service: UserService,
                 admin_service: AdminService,
                 interest_service: Optional[InterestService] = None):
        self.post_service = post_service
        self.user_service = user_service
        self.admin_service = admin_service
        self.interest_service = interest_service
        self.router = Router()

    # ---------- вспомогательное ----------

    @staticmethod
    def _accessible(call: types.CallbackQuery) -> Optional[types.Message]:
        """Сообщение под кнопкой или None, если Telegram отдал InaccessibleMessage.

        Пост остаётся в истории чата навсегда, а для сообщений старше ~48 часов
        Telegram присылает InaccessibleMessage — у него нет ни answer, ни edit_text.
        """
        return call.message if isinstance(call.message, types.Message) else None

    async def _interest_title(self, interest_id: Optional[int]) -> Optional[str]:
        if not interest_id or self.interest_service is None:
            return None
        for interest in await self.interest_service.list_active():
            if interest.id == interest_id:
                return interest.title
        return None

    @staticmethod
    def _preview(item: FeedItem) -> str:
        """Короткая подпись поста для кнопки и списка.

        Текст кнопки Telegram передаёт как есть, без разбора HTML, поэтому
        экранировать его не нужно и нельзя — иначе в кнопке появится '&amp;'.
        """
        text = (item.text or "").replace("\n", " ").strip()
        if text:
            return text[:PREVIEW_LENGTH] + ("…" if len(text) > PREVIEW_LENGTH else "")
        return f"{item.media_count} фото" if item.media_count else "без текста"

    async def _keyboard(self, item: FeedItem, viewer_id: int) -> types.InlineKeyboardMarkup:
        is_admin = await self.admin_service.is_admin(viewer_id)
        can_delete = item.author_chat_id == str(viewer_id) or is_admin
        return feed_post_keyboard(
            post_id=item.id or 0,
            reactions=item.reactions,
            my_reaction=item.my_reaction,
            comment_count=item.comment_count,
            can_delete=can_delete,
        )

    async def _show(self, target: types.Message, viewer_id: int, post_id: int,
                    header: Optional[str] = None) -> bool:
        item = await self.post_service.feed_item(post_id, viewer_id)
        if item is None or item.post.is_deleted:
            await target.answer("Этого поста больше нет. Открыть ленту заново: /feed")
            return False

        if header:
            await target.answer(header)

        body = render_feed_item(item, interest_title=await self._interest_title(item.interest_id))
        media = [(media_item.file_id, media_item.media_type) for media_item in item.media]
        await send_post(target, body, media, await self._keyboard(item, viewer_id))

        # Отметка «докуда долистал» двигается только вперёд, поэтому её можно
        # ставить на каждый показанный пост, в том числе при листании назад.
        await self.post_service.mark_seen(viewer_id, post_id)
        return True

    async def _older_id(self, viewer_id: int, post_id: int) -> Optional[int]:
        page = await self.post_service.feed_page(viewer_id, post_id, 1)
        return page[0].id if page else None

    async def _newer_id(self, viewer_id: int, post_id: int) -> Optional[int]:
        """Ближайший более свежий пост или None, если этот пост самый свежий.

        Курсор репозитория (before_id) листает только вглубь, поэтому идём
        страницами от начала ленты и запоминаем предыдущий id.
        """
        before: Optional[int] = None
        previous: Optional[int] = None
        for _ in range(SCAN_PAGES):
            page = await self.post_service.feed_page(viewer_id, before, FEED_PAGE)
            if not page:
                return None
            for item in page:
                if item.id == post_id:
                    return previous
                previous = item.id
            before = page[-1].id
        return None

    async def _oldest_unseen_id(self, viewer_id: int, unseen: int) -> Optional[int]:
        """Самый ранний из непрочитанных постов — с него человек читает по порядку.

        unseen считается по ЧУЖИМ постам (свои автор только что и написал),
        поэтому при проходе по ленте свои посты не учитываются.
        """
        me = str(viewer_id)
        counted = 0
        before: Optional[int] = None
        for _ in range(SCAN_PAGES):
            page = await self.post_service.feed_page(viewer_id, before, FEED_PAGE)
            if not page:
                return None
            for item in page:
                if item.author_chat_id == me:
                    continue
                counted += 1
                if counted >= unseen:
                    return item.id
            before = page[-1].id
        return None

    def _comments_text(self, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "Комментариев пока нет — можно быть первым."

        blocks = [f"<b>Последние комментарии</b> (до {settings.FEED_COMMENTS_PREVIEW})"]
        length = len(blocks[0])
        for row in rows:
            author = row.get("author_name") or "Кто-то из своих"
            created = row.get("created_at")
            stamp = created.strftime('%d.%m %H:%M') if isinstance(created, datetime) else ""
            block = (f"<b>{escape(str(author))}</b> {stamp}\n"
                     f"{fit_escaped(row.get('text') or '', MAX_MESSAGE_LENGTH)}")
            if length + len(block) > MAX_MESSAGE_LENGTH:
                blocks.append("…")
                break
            blocks.append(block)
            length += len(block) + 2
        return "\n\n".join(blocks)

    @staticmethod
    def _author_card(user: Optional[User], author_chat_id: str) -> str:
        if user is None:
            return "Автор не нашёлся: возможно, он больше не в сети друзей."

        lines = [f"👤 <b>{escape(user.name) if user.name else 'Без имени'}</b>"]
        if user.role:
            lines.append(f"Занимается: {escape(user.role)}")
        if user.city:
            lines.append(f"Город: {escape(user.city)}")
        if user.status:
            lines.append(f"Сейчас: {escape(user.status)}")
        if user.links:
            lines.append(f"Ссылки: {escape(user.links)}")
        if user.tg_username:
            lines.append(f"Написать: @{escape(user.tg_username)}")
        else:
            lines.append(f"ID: {escape(author_chat_id)}")
        return "\n".join(lines)

    # ---------- вход в ленту ----------

    async def feed_command(self, message: types.Message, state: FSMContext) -> None:
        viewer_id = message.chat.id

        current = await state.get_state()
        if current == FeedStates.comment.state:
            # Иначе следующая реплика человека ушла бы комментарием к посту,
            # который он уже пролистал.
            await state.set_state(None)
            await message.answer("Незаконченный комментарий отменён.")
        elif current in POST_DRAFT_STATES:
            await message.answer("Незаконченный пост никуда не делся: текст и фотографии "
                                 "по-прежнему уходят в него. Начать заново — /post")

        unseen = await self.post_service.unseen_count(viewer_id)
        post_id: Optional[int] = None
        header: Optional[str] = None

        if unseen:
            post_id = await self._oldest_unseen_id(viewer_id, unseen)
            if post_id:
                header = (f"Новых постов: {unseen}. Начинаю с самого раннего непрочитанного, "
                          f"дальше — «Свежее ➡️».")

        if post_id is None:
            page = await self.post_service.feed_page(viewer_id, None, 1)
            if not page:
                await message.answer("Лента пока пуста. Первый пост за вами: /post")
                return
            post_id = page[0].id
            header = header or "Нового с прошлого раза нет — вот самый свежий пост."

        await self._show(message, viewer_id, post_id, header=header)

    async def my_posts_command(self, message: types.Message) -> None:
        viewer_id = message.chat.id
        items = await self.post_service.my_posts(viewer_id, settings.POSTS_PER_DAY)
        if not items:
            await message.answer("Вы ещё ничего не публиковали. Первый пост — /post")
            return

        lines = ["<b>Ваши посты</b>"]
        entries = []
        length = len(lines[0])
        for item in items:
            created = item.created_at
            stamp = created.strftime('%d.%m %H:%M') if isinstance(created, datetime) else ""
            line = (f"{stamp} · 📷 {item.media_count} · ❤️ {item.total_reactions} · "
                    f"💬 {item.comment_count}\n"
                    f"{fit_escaped(item.text or '', PREVIEW_LENGTH * 4)}")
            if length + len(line) > MAX_MESSAGE_LENGTH:
                lines.append("…")
                break
            lines.append(line)
            length += len(line) + 2
            entries.append((item.id or 0, f"{stamp} {self._preview(item)}"))

        await message.answer("\n\n".join(lines), reply_markup=my_posts_keyboard(entries))

    async def feed_notify_command(self, message: types.Message) -> None:
        enabled = await self.post_service.toggle_notify(message.chat.id)
        if enabled:
            await message.answer("Уведомления о новых постах включены.")
        else:
            await message.answer("Уведомления о новых постах выключены. "
                                 "Лента всё равно доступна: /feed")

    # ---------- навигация и реакции ----------

    async def nav_callback(self, call: types.CallbackQuery, callback_data: FeedCB) -> None:
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте ленту заново: /feed",
                              show_alert=True)
            return

        viewer_id = call.from_user.id
        if callback_data.action == "older":
            target = await self._older_id(viewer_id, callback_data.post_id)
            miss = "Это самый ранний пост в ленте."
        else:
            target = await self._newer_id(viewer_id, callback_data.post_id)
            miss = "Это самый свежий пост, новее пока ничего нет."

        if target is None:
            await call.answer(miss, show_alert=True)
            return

        await call.answer()
        await self._show(message, viewer_id, target)

    async def open_callback(self, call: types.CallbackQuery, callback_data: FeedCB) -> None:
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте ленту заново: /feed",
                              show_alert=True)
            return
        await call.answer()
        await self._show(message, call.from_user.id, callback_data.post_id)

    async def react_callback(self, call: types.CallbackQuery, callback_data: FeedCB) -> None:
        if callback_data.emoji not in REACTION_EMOJIS:
            await call.answer("Такой реакции нет.", show_alert=True)
            return

        action, item = await self.post_service.react(callback_data.post_id, call.from_user.id,
                                                     callback_data.emoji)
        if action is None or item is None:
            await call.answer("Этого поста больше нет. Откройте ленту заново: /feed",
                              show_alert=True)
            return

        # Крутилку гасим ДО правки сообщения: если Telegram ответит
        # "message is not modified", ответ на callback уже не дошёл бы.
        await call.answer(REACTION_NOTE.get(action, ""))

        message = self._accessible(call)
        if message is None:
            return
        # Реакция переключается на месте: новое сообщение на каждый тап
        # засыпало бы чат копиями поста.
        with suppress(TelegramBadRequest):
            await message.edit_reply_markup(
                reply_markup=await self._keyboard(item, call.from_user.id)
            )

    async def author_callback(self, call: types.CallbackQuery, callback_data: FeedCB) -> None:
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте ленту заново: /feed",
                              show_alert=True)
            return

        item = await self.post_service.feed_item(callback_data.post_id, call.from_user.id)
        if item is None:
            await call.answer("Этого поста больше нет.", show_alert=True)
            return

        await call.answer()
        author = await self.user_service.get_user_by_id(int(item.author_chat_id))
        await message.answer(self._author_card(author, item.author_chat_id))

    # ---------- комментарии ----------

    async def comments_callback(self, call: types.CallbackQuery, callback_data: FeedCB) -> None:
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте ленту заново: /feed",
                              show_alert=True)
            return

        await call.answer()
        rows = await self.post_service.comments(callback_data.post_id)
        await message.answer(self._comments_text(rows),
                            reply_markup=feed_comments_keyboard(callback_data.post_id))

    async def write_callback(self, call: types.CallbackQuery, callback_data: FeedCB,
                             state: FSMContext) -> None:
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте ленту заново: /feed",
                              show_alert=True)
            return

        await call.answer()
        dropped = await state.get_state() in POST_DRAFT_STATES
        await state.set_state(FeedStates.comment)
        await state.update_data(comment_post_id=callback_data.post_id)

        note = "Черновик поста при этом закрыт.\n" if dropped else ""
        await message.answer(
            f"{note}Напишите комментарий одним сообщением "
            f"(до {settings.POST_MAX_COMMENT_LENGTH} символов).",
            reply_markup=comment_cancel_keyboard(callback_data.post_id)
        )

    async def process_comment(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        post_id = data.get("comment_post_id")
        if not post_id:
            await state.set_state(None)
            await message.answer("Пост потерялся. Откройте ленту заново: /feed")
            return

        raw = message.text or ""
        note = ""
        if len(raw.strip()) > settings.POST_MAX_COMMENT_LENGTH:
            note = (f"\nКомментарий был длиннее {settings.POST_MAX_COMMENT_LENGTH} символов — "
                    f"сохранил начало.")

        comment, reason = await self.post_service.comment(post_id, message.chat.id, raw)
        if comment is None:
            # Остаёмся в состоянии: человек может исправить и прислать заново.
            await message.answer(escape(reason))
            return

        await state.set_state(None)
        await message.answer(escape(reason) + note)
        rows = await self.post_service.comments(post_id)
        await message.answer(self._comments_text(rows),
                             reply_markup=feed_comments_keyboard(post_id))

    async def process_comment_invalid(self, message: types.Message, state: FSMContext) -> None:
        await message.answer("Комментарий должен быть текстом. Пришлите текст или отмените "
                             "кнопкой под сообщением выше.")

    async def cancel_callback(self, call: types.CallbackQuery, callback_data: FeedCB,
                              state: FSMContext) -> None:
        await call.answer()
        if await state.get_state() == FeedStates.comment.state:
            await state.set_state(None)
        message = self._accessible(call)
        if message is not None:
            await message.answer("Комментарий отменён.")

    # ---------- удаление ----------

    async def delete_ask_callback(self, call: types.CallbackQuery, callback_data: FeedCB) -> None:
        await call.answer()
        message = self._accessible(call)
        if message is None:
            return
        with suppress(TelegramBadRequest):
            await message.edit_reply_markup(
                reply_markup=delete_confirm_keyboard(callback_data.post_id)
            )

    async def back_callback(self, call: types.CallbackQuery, callback_data: FeedCB) -> None:
        item = await self.post_service.feed_item(callback_data.post_id, call.from_user.id)
        await call.answer()
        message = self._accessible(call)
        if message is None or item is None:
            return
        with suppress(TelegramBadRequest):
            await message.edit_reply_markup(
                reply_markup=await self._keyboard(item, call.from_user.id)
            )

    async def delete_yes_callback(self, call: types.CallbackQuery, callback_data: FeedCB) -> None:
        is_admin = await self.admin_service.is_admin(call.from_user.id)
        deleted, reason = await self.post_service.delete(callback_data.post_id,
                                                         call.from_user.id, is_admin)
        await call.answer(reason, show_alert=not deleted)

        message = self._accessible(call)
        if message is None or not deleted:
            return

        # У поста с фотографией текст лежит в подписи, а у медиагруппы его нет
        # вовсе, поэтому от удалённого поста снимаем кнопки, а не правим текст.
        with suppress(TelegramBadRequest):
            await message.edit_reply_markup(reply_markup=None)
        await message.answer("Пост удалён. Лента: /feed")

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        # not_command обязателен на текстовом хендлере состояния: иначе "/feed"
        # или "/menu" уехали бы текстом в комментарий вместо своих хендлеров.
        not_command = ~F.text.startswith("/")
        # Фильтр Command читает message.text ИЛИ message.caption, поэтому
        # команда в подписи к фотографии тоже обязана дойти до своего хендлера.
        not_caption_command = ~F.caption.startswith("/")

        self.router.message.register(self.feed_command, Command("feed"), is_registered_filter)
        self.router.message.register(self.my_posts_command, Command("my_posts"),
                                     is_registered_filter)
        self.router.message.register(self.feed_notify_command, Command("feed_notify"),
                                     is_registered_filter)

        self.router.callback_query.register(self.react_callback, FeedCB.filter(F.action == "react"),
                                            is_registered_filter)
        self.router.callback_query.register(self.comments_callback,
                                            FeedCB.filter(F.action == "comments"),
                                            is_registered_filter)
        self.router.callback_query.register(self.write_callback, FeedCB.filter(F.action == "write"),
                                            is_registered_filter)
        self.router.callback_query.register(self.nav_callback,
                                            FeedCB.filter(F.action.in_({"older", "newer"})),
                                            is_registered_filter)
        self.router.callback_query.register(self.open_callback, FeedCB.filter(F.action == "open"),
                                            is_registered_filter)
        self.router.callback_query.register(self.author_callback,
                                            FeedCB.filter(F.action == "author"),
                                            is_registered_filter)
        self.router.callback_query.register(self.delete_ask_callback,
                                            FeedCB.filter(F.action == "del_ask"),
                                            is_registered_filter)
        self.router.callback_query.register(self.delete_yes_callback,
                                            FeedCB.filter(F.action == "del_yes"),
                                            is_registered_filter)
        self.router.callback_query.register(self.back_callback, FeedCB.filter(F.action == "back"),
                                            is_registered_filter)
        self.router.callback_query.register(self.cancel_callback, FeedCB.filter(F.action == "cancel"),
                                            is_registered_filter)

        # Fallback идёт после основного хендлера состояния, иначе перехватывал бы
        # корректный текст комментария.
        self.router.message.register(self.process_comment, StateFilter(FeedStates.comment),
                                     F.text, not_command)
        self.router.message.register(self.process_comment_invalid,
                                     StateFilter(FeedStates.comment),
                                     not_command, not_caption_command)
        return self.router
