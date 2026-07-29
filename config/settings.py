import os
from dotenv import load_dotenv
from pathlib import Path
from typing import List

load_dotenv()


class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    DB_USER: str = os.getenv("DB_USER", "user")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "password")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", 5432))
    DB_NAME: str = os.getenv("DB_NAME", "match_bot")

    # Redis settings for FSM storage
    REDIS_HOST: str = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", 6379))
    REDIS_DB: int = int(os.getenv("REDIS_DB", 0))

    # Парсим ADMIN_IDS как список целых чисел
    _admin_ids_str = os.getenv("ADMIN_IDS", "")
    ADMIN_IDS: List[int] = [int(x.strip()) for x in _admin_ids_str.split(',') if x.strip().isdigit()]

    # Ограничения профиля. Возраста и пола здесь нет намеренно: закрытая сеть
    # для знакомых не фильтрует людей по этим признакам.
    MAX_NAME_LENGTH: int = 30
    MAX_DESCRIPTION_LENGTH: int = 1000
    MAX_PHOTOS: int = 3
    MAX_ROLE_LENGTH: int = 60
    MAX_STATUS_LENGTH: int = 140
    MAX_LINKS_LENGTH: int = 300
    MAX_OFFER_LENGTH: int = 500

    # Посты и лента
    POST_MAX_TEXT_LENGTH: int = int(os.getenv("POST_MAX_TEXT_LENGTH", 1500))
    POST_MAX_MEDIA: int = int(os.getenv("POST_MAX_MEDIA", 10))
    POST_MAX_COMMENT_LENGTH: int = int(os.getenv("POST_MAX_COMMENT_LENGTH", 700))
    POSTS_PER_DAY: int = int(os.getenv("POSTS_PER_DAY", 10))
    FEED_COMMENTS_PREVIEW: int = int(os.getenv("FEED_COMMENTS_PREVIEW", 5))
    # Значение по умолчанию для уведомлений о постах задаёт схема
    # (users.feed_notify DEFAULT TRUE), настройки для него нет намеренно:
    # мёртвый параметр в конфиге хуже отсутствующего.

    # Каталог участников и поиск
    DIRECTORY_PAGE_SIZE: int = int(os.getenv("DIRECTORY_PAGE_SIZE", 8))
    SEARCH_MIN_QUERY: int = int(os.getenv("SEARCH_MIN_QUERY", 2))

    # Резервные копии базы
    BACKUP_DIR: str = os.getenv("BACKUP_DIR", str(Path.home() / ".local/share/matchi-backups"))
    BACKUP_KEEP: int = int(os.getenv("BACKUP_KEEP", 14))
    PG_BIN_DIR: str = os.getenv("PG_BIN_DIR", "/usr/lib/postgresql/16/bin")

    # Инвайты: закрытая сеть, вход только по коду
    INVITE_CODE_LENGTH: int = int(os.getenv("INVITE_CODE_LENGTH", 8))
    INVITE_TTL_DAYS: int = int(os.getenv("INVITE_TTL_DAYS", 14))
    INVITE_MAX_USES: int = int(os.getenv("INVITE_MAX_USES", 3))
    INVITES_PER_USER: int = int(os.getenv("INVITES_PER_USER", 5))

    # Поиск и антиспам
    CANDIDATES_LIMIT: int = int(os.getenv("CANDIDATES_LIMIT", 50))
    SUPPORT_COOLDOWN: int = int(os.getenv("SUPPORT_COOLDOWN", 120))
    BROADCAST_DELAY: float = float(os.getenv("BROADCAST_DELAY", 0.05))

    # Интересы
    MAX_USER_INTERESTS: int = int(os.getenv("MAX_USER_INTERESTS", 5))

    # Исходящая очередь (веерная рассылка в комнатах)
    # Telegram допускает порядка 30 сообщений в секунду суммарно, поэтому
    # держим запас, и не быстрее одного сообщения в секунду в один и тот же чат.
    OUTBOX_RATE: float = float(os.getenv("OUTBOX_RATE", 25))
    OUTBOX_PER_CHAT_INTERVAL: float = float(os.getenv("OUTBOX_PER_CHAT_INTERVAL", 1.0))
    SEND_RETRY_ATTEMPTS: int = int(os.getenv("SEND_RETRY_ATTEMPTS", 3))

    # Троттлинг входящих апдейтов
    THROTTLE_LIMIT: int = int(os.getenv("THROTTLE_LIMIT", 12))
    THROTTLE_WINDOW: int = int(os.getenv("THROTTLE_WINDOW", 10))

    # Комнаты по интересам
    ROOM_MEMBER_LIMIT: int = int(os.getenv("ROOM_MEMBER_LIMIT", 30))
    ROOM_MAX_MESSAGE_LENGTH: int = int(os.getenv("ROOM_MAX_MESSAGE_LENGTH", 700))
    ROOM_HISTORY_SIZE: int = int(os.getenv("ROOM_HISTORY_SIZE", 15))
    ROOM_INVITE_TTL: int = int(os.getenv("ROOM_INVITE_TTL", 3600))

    # Рулетка по интересам
    ROULETTE_WAIT_TTL: int = int(os.getenv("ROULETTE_WAIT_TTL", 600))

    # Личные диалоги
    DIALOG_HISTORY_SIZE: int = int(os.getenv("DIALOG_HISTORY_SIZE", 20))


settings = Settings()

if not settings.BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in the .env file")
if not settings.ADMIN_IDS:
    print("Warning: ADMIN_IDS are not set in the .env file. Admin functions may not work.")