from typing import Dict, Optional, Sequence, Tuple

from aiogram import types
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder

from models.interest import Interest
from models.post import REACTION_EMOJIS

# Темы поста показываем парами: заголовки интересов короткие, а в один столбец
# список из десятка тем не влезает на экран без прокрутки.
INTERESTS_PER_ROW = 2


class PostCB(CallbackData, prefix="pst"):
    """callback_data создания поста.

    Фабрика вместо склейки префиксов: склейка в этом проекте уже дала коллизию
    ("message" внутри "message_to_all"), и для новых кнопок так больше не делаем.

    action: done | drop_last | cancel | topic | publish
    interest_id: 0 означает «без темы».
    """
    action: str
    interest_id: int = 0


class FeedCB(CallbackData, prefix="fd"):
    """callback_data ленты.

    action: react | comments | write | older | newer | author | open
            | del_ask | del_yes | back | cancel
    emoji заполнено только у react и обязано быть одним из REACTION_EMOJIS.
    """
    action: str
    post_id: int = 0
    emoji: str = ""


def _post_button(text: str, action: str, interest_id: int = 0) -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text=text,
        callback_data=PostCB(action=action, interest_id=interest_id).pack()
    )


def _feed_button(text: str, action: str, post_id: int = 0,
                 emoji: str = "") -> types.InlineKeyboardButton:
    return types.InlineKeyboardButton(
        text=text,
        callback_data=FeedCB(action=action, post_id=post_id, emoji=emoji).pack()
    )


def post_content_keyboard(media_count: int) -> types.InlineKeyboardMarkup:
    """Сбор поста: закончить, убрать последнее фото, отменить.

    Только row(): adjust() переразбивает все ряды и утащил бы «Отмена»
    в один ряд с «Готово».
    """
    builder = InlineKeyboardBuilder()
    builder.row(_post_button("✅ Готово", "done"))
    if media_count:
        builder.row(_post_button(f"↩️ Убрать последнее фото ({media_count})", "drop_last"))
    builder.row(_post_button("✖️ Отмена", "cancel"))
    return builder.as_markup()


def post_topic_keyboard(interests: Sequence[Interest]) -> types.InlineKeyboardMarkup:
    """Тема поста: активные интересы по два в ряд плюс «Без темы»."""
    builder = InlineKeyboardBuilder()

    row = []
    for interest in interests:
        row.append(_post_button(interest.title, "topic", interest.id or 0))
        if len(row) == INTERESTS_PER_ROW:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)

    builder.row(_post_button("Без темы", "topic", 0))
    builder.row(_post_button("✖️ Отмена", "cancel"))
    return builder.as_markup()


def post_confirm_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_post_button("🚀 Опубликовать", "publish"))
    builder.row(_post_button("✖️ Отмена", "cancel"))
    return builder.as_markup()


def reaction_button_text(emoji: str, count: int, mine: bool) -> str:
    text = f"{emoji} {count}" if count else emoji
    return f"✅ {text}" if mine else text


def feed_post_keyboard(post_id: int, reactions: Dict[str, int],
                       my_reaction: Optional[str], comment_count: int,
                       can_delete: bool) -> types.InlineKeyboardMarkup:
    """Клавиатура одного поста в ленте.

    Кнопки «Раньше»/«Свежее» стоят всегда: есть ли сосед, выясняется уже при
    нажатии — иначе на каждую отрисовку поста пришлось бы по два лишних запроса.
    """
    builder = InlineKeyboardBuilder()

    builder.row(*[
        _feed_button(
            reaction_button_text(emoji, reactions.get(emoji, 0), my_reaction == emoji),
            "react", post_id, emoji
        )
        for emoji in REACTION_EMOJIS
    ])

    comments_text = f"💬 Комментарии ({comment_count})" if comment_count else "💬 Комментарии"
    builder.row(_feed_button(comments_text, "comments", post_id))

    builder.row(
        _feed_button("⬅️ Раньше", "older", post_id),
        _feed_button("Свежее ➡️", "newer", post_id),
    )

    last_row = [_feed_button("👤 Автор", "author", post_id)]
    if can_delete:
        last_row.append(_feed_button("🗑 Удалить", "del_ask", post_id))
    builder.row(*last_row)

    return builder.as_markup()


def feed_comments_keyboard(post_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_feed_button("✍️ Написать комментарий", "write", post_id))
    builder.row(_feed_button("⬅️ К посту", "open", post_id))
    return builder.as_markup()


def comment_cancel_keyboard(post_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_feed_button("✖️ Не писать", "cancel", post_id))
    return builder.as_markup()


def delete_confirm_keyboard(post_id: int) -> types.InlineKeyboardMarkup:
    """Удаление постов подтверждается: отменить его пользователь уже не сможет."""
    builder = InlineKeyboardBuilder()
    builder.row(_feed_button("🗑 Да, удалить", "del_yes", post_id))
    builder.row(_feed_button("⬅️ Оставить", "back", post_id))
    return builder.as_markup()


def my_posts_keyboard(entries: Sequence[Tuple[int, str]]) -> Optional[types.InlineKeyboardMarkup]:
    """Свои посты: по кнопке удаления на каждый. None означает «клавиатура не нужна».

    Принимает уже готовые подписи, а не FeedItem: клавиатуре незачем знать,
    как устроен пост.
    """
    if not entries:
        return None

    builder = InlineKeyboardBuilder()
    for post_id, label in entries:
        builder.row(_feed_button(f"🗑 {label}", "del_ask", post_id))
    return builder.as_markup()
