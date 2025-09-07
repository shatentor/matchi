import os
from dotenv import load_dotenv
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


settings = Settings()

if not settings.BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set in the .env file")
if not settings.ADMIN_IDS:
    print("Warning: ADMIN_IDS are not set in the .env file. Admin functions may not work.")