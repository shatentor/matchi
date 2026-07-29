import logging
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config.settings import settings
from filters.custom_filters import IsRegistered
from keyboards.feed import (PostCB, post_confirm_keyboard, post_content_keyboard,
                            post_topic_keyboard)
from models.post import MEDIA_TYPE_PHOTO, MEDIA_TYPE_VIDEO, FeedItem
from services.interest_service import InterestService
from services.post_service import PostService
from services.user_service import UserService
from utils.text import escape

logger = logging.getLogger(__name__)

# Подпись к фотографии в Telegram ограничена 1024 символами, а текст поста
# допускает settings.POST_MAX_TEXT_LENGTH (1500) — длинный текст уходит
# отдельным сообщением, вместе с кнопками.
CAPTION_LIMIT = 1024
# Сообщение Telegram ограничено 4096 символами, а escape() раздувает текст с
# '<' и '&' в четыре-пять раз, поэтому тело поста режем с запасом.
BODY_TEXT_LIMIT = 3000
# Сколько раз подбирать длину исходного текста, чтобы экранированный влез в лимит
FIT_ATTEMPTS = 5

# Ключи FSM-данных черновика. RedisStorage сериализует данные в JSON, поэтому
# кортежи (file_id, media_type) хранятся списками и приводятся обратно перед
# передачей в сервис.
DRAFT_MEDIA = "post_media"
DRAFT_TEXT = "post_text"
DRAFT_INTEREST = "post_interest_id"
DRAFT_GROUP = "post_group_id"

CONTENT_HINT = (
    "<b>Новый пост</b>\n"
    "Пришлите текст и фотографии: можно альбомом, можно по одной, "
    "можно фото с подписью.\n"
    f"Лимиты: текст до {settings.POST_MAX_TEXT_LENGTH} символов, "
    f"фотографий до {settings.POST_MAX_MEDIA}.\n"
    "Когда всё готово — «Готово»."
)


class PostStates(StatesGroup):
    content = State()
    topic = State()
    confirm = State()


def fit_escaped(text: Optional[str], limit: int = BODY_TEXT_LIMIT) -> str:
    """Экранирует текст пользователя и подгоняет результат под лимит сообщения.

    Обрезать уже экранированную строку нельзя: разрез посередине '&amp;' даёт
    ломаную разметку, и Telegram отвечает "can't parse entities". Поэтому
    укорачивается исходный текст, а экранирование делается заново.
    """
    raw = text or ""
    escaped = escape(raw)
    for _ in range(FIT_ATTEMPTS):
        if len(escaped) <= limit:
            break
        shrink = max(1, int(len(raw) * limit / len(escaped)) - 1)
        raw = raw[:shrink]
        escaped = escape(raw)
    if len(raw) < len(text or ""):
        return escaped + "…"
    return escaped


def author_line(name: Optional[str], role: Optional[str], username: Optional[str]) -> str:
    parts = [f"👤 <b>{escape(name) if name else 'Без имени'}</b>"]
    if role:
        parts.append(escape(role))
    if username:
        parts.append(f"@{escape(username)}")
    return " · ".join(parts)


def render_post_body(author_name: Optional[str], author_role: Optional[str],
                     author_username: Optional[str], text: Optional[str],
                     created_at: Optional[datetime] = None,
                     interest_title: Optional[str] = None,
                     comment_count: int = 0) -> str:
    """Текст поста ровно в том виде, в котором его увидят другие."""
    head = [author_line(author_name, author_role, author_username)]
    if interest_title:
        head.append(f"🏷 {escape(interest_title)}")

    body = fit_escaped(text) if text else "<i>без текста</i>"

    footer = []
    if created_at is not None:
        footer.append(f"🕒 {created_at.strftime('%d.%m %H:%M')}")
    if comment_count:
        footer.append(f"💬 {comment_count}")

    blocks = ["\n".join(head), body]
    if footer:
        blocks.append(" · ".join(footer))
    return "\n\n".join(blocks)


def render_feed_item(item: FeedItem, interest_title: Optional[str] = None) -> str:
    return render_post_body(
        author_name=item.author_name,
        author_role=item.author_role,
        author_username=item.author_username,
        text=item.text,
        created_at=item.created_at,
        interest_title=interest_title,
        comment_count=item.comment_count,
    )


def _input_media(file_id: str, media_type: str):
    if media_type == MEDIA_TYPE_VIDEO:
        return types.InputMediaVideo(media=file_id)
    return types.InputMediaPhoto(media=file_id)


async def send_post(target: types.Message, body: str,
                    media: Sequence[Tuple[str, str]],
                    reply_markup: Optional[types.InlineKeyboardMarkup] = None) -> None:
    """Отправляет пост, обходя три ограничения Telegram.

    Без медиа — одно текстовое сообщение с кнопками. Одно вложение — одно
    сообщение с подписью и кнопками. Несколько вложений — медиагруппа, а текст
    и кнопки отдельным сообщением: к медиагруппе инлайн-клавиатуру прикрепить
    нельзя, это ограничение Bot API, а не выбор вёрстки.

    Подпись длиннее CAPTION_LIMIT Telegram не принимает, поэтому такой текст
    тоже уезжает отдельным сообщением — вместе с кнопками, иначе они остались
    бы под пустой фотографией.
    """
    items = list(media)

    if not items:
        await target.answer(body, reply_markup=reply_markup)
        return

    if len(items) == 1:
        file_id, media_type = items[0]
        caption = body if len(body) <= CAPTION_LIMIT else None
        markup = reply_markup if caption is not None else None
        if media_type == MEDIA_TYPE_VIDEO:
            await target.answer_video(file_id, caption=caption, reply_markup=markup)
        else:
            await target.answer_photo(file_id, caption=caption, reply_markup=markup)
        if caption is None:
            await target.answer(body, reply_markup=reply_markup)
        return

    await target.answer_media_group(
        media=[_input_media(file_id, media_type) for file_id, media_type in items]
    )
    await target.answer(body, reply_markup=reply_markup)


class PostHandlers:
    """Создание поста: сбор текста и фотографий, тема, предпросмотр, публикация."""

    def __init__(self, post_service: PostService, interest_service: InterestService,
                 user_service: UserService):
        self.post_service = post_service
        self.interest_service = interest_service
        self.user_service = user_service
        self.router = Router()

    # ---------- вспомогательное ----------

    @staticmethod
    def _accessible(call: types.CallbackQuery) -> Optional[types.Message]:
        """Сообщение под кнопкой или None, если Telegram отдал InaccessibleMessage.

        Кнопки живут в истории чата вечно, а сообщения старше ~48 часов
        приходят как InaccessibleMessage — у него нет ни answer, ни edit_text.
        """
        return call.message if isinstance(call.message, types.Message) else None

    @staticmethod
    async def _draft(state: FSMContext) -> Tuple[List[List[str]], Optional[str]]:
        data = await state.get_data()
        media = [list(pair) for pair in (data.get(DRAFT_MEDIA) or [])]
        return media, data.get(DRAFT_TEXT)

    async def _interest_title(self, interest_id: Optional[int]) -> Optional[str]:
        if not interest_id:
            return None
        for interest in await self.interest_service.list_active():
            if interest.id == interest_id:
                return interest.title
        return None

    # ---------- сбор контента ----------

    async def post_command(self, message: types.Message, state: FSMContext) -> None:
        # set_state сам выводит из другого текстового состояния, если человек
        # начал пост, не закончив комментарий.
        await state.set_state(PostStates.content)
        await state.update_data(**{DRAFT_MEDIA: [], DRAFT_TEXT: None,
                                   DRAFT_INTEREST: 0, DRAFT_GROUP: None})
        await message.answer(CONTENT_HINT, reply_markup=post_content_keyboard(0))

    async def add_text(self, message: types.Message, state: FSMContext) -> None:
        raw = (message.text or "").strip()
        if not raw:
            await message.answer("Текст пустой. Пришлите текст или фотографию.")
            return

        note = ""
        if len(raw) > settings.POST_MAX_TEXT_LENGTH:
            raw = raw[:settings.POST_MAX_TEXT_LENGTH]
            note = (f"\nТекст был длиннее {settings.POST_MAX_TEXT_LENGTH} символов — "
                    f"оставил начало.")

        media, previous = await self._draft(state)
        await state.update_data(**{DRAFT_TEXT: raw})
        action = "Текст поста заменён." if previous else "Текст поста сохранён."
        await message.answer(action + note, reply_markup=post_content_keyboard(len(media)))

    async def add_photo(self, message: types.Message, state: FSMContext) -> None:
        """Добавляет одну фотографию к черновику.

        Альбом Telegram присылает НЕСКОЛЬКИМИ апдейтами с общим media_group_id,
        собрать его одним апдейтом нельзя — фотографии накапливаются в данных
        состояния. Ответ шлём только на первый элемент альбома: иначе на альбом
        из десяти фото человек получит десять сообщений подряд.
        """
        if not message.photo:
            await message.answer("Фотография не распознана, попробуйте ещё раз.")
            return

        data = await state.get_data()
        media = [list(pair) for pair in (data.get(DRAFT_MEDIA) or [])]
        group_id = message.media_group_id
        continuation = group_id is not None and group_id == data.get(DRAFT_GROUP)

        if len(media) >= settings.POST_MAX_MEDIA:
            await state.update_data(**{DRAFT_GROUP: group_id})
            if not continuation:
                await message.answer(
                    f"В пост влезает не больше {settings.POST_MAX_MEDIA} фотографий, "
                    f"остальные не добавляю.",
                    reply_markup=post_content_keyboard(len(media))
                )
            return

        # message.photo — это РАЗНЫЕ РАЗМЕРЫ ОДНОЙ фотографии, а не разные фото;
        # нужен самый большой размер.
        media.append([message.photo[-1].file_id, MEDIA_TYPE_PHOTO])

        text = data.get(DRAFT_TEXT)
        # Подпись к альбому Telegram присылает только с ПЕРВЫМ элементом,
        # поэтому её нельзя ждать от последнего апдейта группы.
        caption = (message.caption or "").strip()
        if caption and not text:
            text = caption[:settings.POST_MAX_TEXT_LENGTH]

        await state.update_data(**{DRAFT_MEDIA: media, DRAFT_TEXT: text,
                                   DRAFT_GROUP: group_id})

        if continuation:
            return

        if group_id is None:
            answer = (f"Фотография добавлена. Всего: {len(media)} из "
                      f"{settings.POST_MAX_MEDIA}.")
        else:
            answer = ("Принимаю альбом — остальные фотографии добавятся сами. "
                      "Сколько получилось, будет видно в предпросмотре.")
        await message.answer(answer, reply_markup=post_content_keyboard(len(media)))

    async def content_invalid(self, message: types.Message, state: FSMContext) -> None:
        media, _ = await self._draft(state)
        await message.answer(
            "В пост идут только текст и фотографии. Пришлите их или нажмите «Готово».",
            reply_markup=post_content_keyboard(len(media))
        )

    async def waiting_button(self, message: types.Message, state: FSMContext) -> None:
        await message.answer("Осталось нажать кнопку под сообщением выше. "
                             "Бросить пост — /post заново.")

    # ---------- тема и публикация ----------

    async def drop_last_callback(self, call: types.CallbackQuery, state: FSMContext) -> None:
        await call.answer()
        message = self._accessible(call)
        if message is None:
            return

        media, _ = await self._draft(state)
        if not media:
            await message.answer("Фотографий в черновике нет.",
                                reply_markup=post_content_keyboard(0))
            return

        media.pop()
        await state.update_data(**{DRAFT_MEDIA: media, DRAFT_GROUP: None})
        await message.answer(f"Последняя фотография убрана. Осталось: {len(media)}.",
                            reply_markup=post_content_keyboard(len(media)))

    async def done_callback(self, call: types.CallbackQuery, state: FSMContext) -> None:
        media, text = await self._draft(state)
        if not media and not text:
            await call.answer("Пост пустой: пришлите текст или фотографию.", show_alert=True)
            return

        await call.answer()
        message = self._accessible(call)
        if message is None:
            return

        await state.set_state(PostStates.topic)
        interests = await self.interest_service.list_active()
        await message.answer("Тема поста — необязательна. Выберите или «Без темы»:",
                            reply_markup=post_topic_keyboard(interests))

    async def topic_callback(self, call: types.CallbackQuery, callback_data: PostCB,
                             state: FSMContext) -> None:
        await call.answer()
        message = self._accessible(call)
        if message is None:
            return

        interest_id = callback_data.interest_id or 0
        await state.update_data(**{DRAFT_INTEREST: interest_id})
        await state.set_state(PostStates.confirm)

        media, text = await self._draft(state)
        user = await self.user_service.get_user_by_id(call.from_user.id)
        body = render_post_body(
            author_name=user.name if user else None,
            author_role=user.role if user else None,
            author_username=user.tg_username if user else None,
            text=text,
            created_at=datetime.now(timezone.utc),
            interest_title=await self._interest_title(interest_id),
        )

        await message.answer("Предпросмотр — так пост увидят другие:")
        await send_post(message, body, [(pair[0], pair[1]) for pair in media])
        await message.answer(
            f"Фотографий: {len(media)}. Кнопки реакций появятся после публикации.",
            reply_markup=post_confirm_keyboard()
        )

    async def publish_callback(self, call: types.CallbackQuery, state: FSMContext) -> None:
        media, text = await self._draft(state)
        data = await state.get_data()
        interest_id = data.get(DRAFT_INTEREST) or None

        post, reason = await self.post_service.publish(
            author_id=call.from_user.id,
            text=text,
            media=[(pair[0], pair[1]) for pair in media],
            interest_id=interest_id,
        )

        if post is None:
            await call.answer(reason, show_alert=True)
            return

        await call.answer()
        await state.clear()

        message = self._accessible(call)
        if message is not None:
            await message.answer(f"{escape(reason)} Лента: /feed")

        await self._notify(call.from_user.id, post)

    async def cancel_callback(self, call: types.CallbackQuery, state: FSMContext) -> None:
        await call.answer()
        await state.clear()
        message = self._accessible(call)
        if message is not None:
            await message.answer("Создание поста отменено. Начать заново — /post")

    async def _notify(self, author_id: int, post) -> None:
        """Веер уведомлений о новом посте — целиком забота сервиса (Outbox).

        Сбой рассылки не должен выглядеть для автора как неудачная публикация:
        пост уже в базе.
        """
        user = await self.user_service.get_user_by_id(author_id)
        author_name = user.name if user and user.name else "Кто-то из своих"
        try:
            await self.post_service.notify_new_post(post, author_name)
        except Exception as e:
            logger.error(f"Уведомления о посте {post.id} не поставлены в очередь: {e}")

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        # not_command обязателен на каждом текстовом хендлере состояния: иначе
        # "/feed" или "/menu" уехали бы текстом в пост вместо своих хендлеров.
        not_command = ~F.text.startswith("/")
        # Фильтр Command читает message.text ИЛИ message.caption, поэтому
        # команда в подписи к фотографии тоже обязана дойти до своего хендлера,
        # а не превратиться в текст поста.
        not_caption_command = ~F.caption.startswith("/")

        self.router.message.register(self.post_command, Command("post"), is_registered_filter)

        self.router.callback_query.register(self.done_callback, PostCB.filter(F.action == "done"),
                                            is_registered_filter)
        self.router.callback_query.register(self.drop_last_callback,
                                            PostCB.filter(F.action == "drop_last"),
                                            is_registered_filter)
        self.router.callback_query.register(self.topic_callback, PostCB.filter(F.action == "topic"),
                                            is_registered_filter)
        self.router.callback_query.register(self.publish_callback,
                                            PostCB.filter(F.action == "publish"),
                                            is_registered_filter)
        self.router.callback_query.register(self.cancel_callback, PostCB.filter(F.action == "cancel"),
                                            is_registered_filter)

        # Fallback-хендлеры идут после основных, иначе перехватывают корректный
        # ввод; не_текст они ловят тоже, поэтому состояние не запирается.
        self.router.message.register(self.add_text, StateFilter(PostStates.content),
                                     F.text, not_command)
        self.router.message.register(self.add_photo, StateFilter(PostStates.content),
                                     F.photo, not_caption_command)
        self.router.message.register(self.content_invalid, StateFilter(PostStates.content),
                                     not_command, not_caption_command)
        self.router.message.register(self.waiting_button,
                                     StateFilter(PostStates.topic, PostStates.confirm),
                                     not_command, not_caption_command)
        return self.router
