from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# Типы вложений поста. Колонка post_media.media_type — VARCHAR(16), значения
# совпадают с именами методов Telegram (photo/video), чтобы отрисовка ленты
# выбирала InputMediaPhoto или InputMediaVideo по этому полю без словаря.
MEDIA_TYPE_PHOTO = "photo"
MEDIA_TYPE_VIDEO = "video"
MEDIA_TYPES = (MEDIA_TYPE_PHOTO, MEDIA_TYPE_VIDEO)

# Набор реакций один на весь бот: клавиатура рисует ровно эти эмодзи, а
# post_reactions.emoji — VARCHAR(8), поэтому длинные составные эмодзи сюда
# добавлять нельзя (в '❤️' два кодовых символа, в семейных эмодзи их больше).
REACTION_EMOJIS = ("❤️", "🔥", "😂")

# Ограничение той же колонки: значение длиннее молча обрежется при приведении
# к VARCHAR(8), поэтому сервис проверяет длину до вставки.
EMOJI_COLUMN_LENGTH = 8


class Post(BaseModel):
    """Пост из таблицы posts.

    id и created_at проставляет БД, поэтому у них есть значения по умолчанию:
    в Pydantic v2 Optional без default — обязательное поле, и модель нельзя
    было бы собрать до вставки.

    text может быть пустым: пост с одними фотографиями допустим. deleted_at
    заполнено у мягко удалённых постов — они пропадают из ленты, но их
    комментарии и реакции остаются на месте.
    """
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    author_chat_id: str
    interest_id: Optional[int] = None
    text: Optional[str] = None
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class PostMedia(BaseModel):
    """Вложение поста из таблицы post_media.

    position задаёт порядок в медиагруппе: пользователь присылает фотографии
    по одной, и показать их надо в том же порядке.
    """
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    post_id: Optional[int] = None
    file_id: str
    media_type: str = MEDIA_TYPE_PHOTO
    position: int = 0


class PostComment(BaseModel):
    """Комментарий к посту из таблицы post_comments."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    post_id: int
    author_chat_id: str
    text: str
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


class FeedItem(BaseModel):
    """Всё, что нужно для отрисовки одного поста в ленте.

    Собирается ОДНИМ запросом репозитория вместе с автором, вложениями,
    счётчиками реакций и числом комментариев: лента показывает посты по одному,
    и добор данных отдельными запросами дал бы N+1 на каждую страницу.

    reactions — счётчики по эмодзи вида {'❤️': 3, '🔥': 1}; эмодзи без реакций
    в словаре отсутствует, поэтому клавиатура берёт числа через
    reaction_count(). my_reaction — реакция смотрящего или None.

    Своей таблицы у FeedItem нет, поля author_* приходят из users, и любое из
    них может быть пустым: анкету автора могли не заполнить до конца.
    """
    model_config = ConfigDict(from_attributes=True)

    post: Post
    author_name: Optional[str] = None
    author_role: Optional[str] = None
    author_username: Optional[str] = None
    media: List[PostMedia] = Field(default_factory=list)
    reactions: Dict[str, int] = Field(default_factory=dict)
    comment_count: int = 0
    my_reaction: Optional[str] = None

    @property
    def id(self) -> Optional[int]:
        return self.post.id

    @property
    def text(self) -> Optional[str]:
        return self.post.text

    @property
    def author_chat_id(self) -> str:
        return self.post.author_chat_id

    @property
    def interest_id(self) -> Optional[int]:
        return self.post.interest_id

    @property
    def created_at(self) -> Optional[datetime]:
        return self.post.created_at

    @property
    def file_ids(self) -> List[str]:
        return [item.file_id for item in self.media]

    @property
    def media_count(self) -> int:
        return len(self.media)

    def reaction_count(self, emoji: str) -> int:
        return self.reactions.get(emoji, 0)

    @property
    def total_reactions(self) -> int:
        return sum(self.reactions.values())
