import secrets
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict

from config.settings import settings

# Алфавит кода приглашения. Из него убраны символы, которые невозможно
# различить при пересылке текстом и при чтении с чужого экрана: 0 и O, 1 и l и I.
# Регистр только верхний — иначе к путанице цифр добавилась бы путаница
# l/L и o/O, а вводит код человек руками.
INVITE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# Ширина колонки invites.code в схеме. Более длинную строку PostgreSQL приводит
# к VARCHAR(16) молчаливым обрезанием, поэтому длину введённого кода проверяет
# сервис, а не БД.
CODE_COLUMN_LENGTH = 16


def generate_code(length: int = settings.INVITE_CODE_LENGTH) -> str:
    """Случайный код приглашения.

    secrets, а не random: код — это единственный пропуск в закрытую сеть,
    а генератор random предсказуем по нескольким выданным значениям.
    """
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(length))


def normalize_code(raw: Optional[str]) -> str:
    """Приводит введённый человеком код к виду, в котором он лежит в БД.

    Код доходит до получателя пересылкой или копипастой, поэтому по краям
    бывают пробелы и переводы строки, а регистр — какой угодно.
    """
    return (raw or "").strip().upper()


class Invite(BaseModel):
    """Код приглашения из таблицы invites.

    created_at проставляет БД, expires_at может быть NULL («без срока»),
    поэтому у обоих есть значения по умолчанию: в Pydantic v2 Optional без
    default — обязательное поле, и модель нельзя было бы собрать до вставки.

    created_by — tg_chat_id автора кода строкой, как в users (ON DELETE SET NULL
    в схеме, поэтому у старого кода автора может уже не быть).
    """
    model_config = ConfigDict(from_attributes=True)

    code: str
    created_by: Optional[str] = None
    max_uses: int = settings.INVITE_MAX_USES
    used_count: int = 0
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    revoked: bool = False

    @property
    def uses_left(self) -> int:
        return max(0, self.max_uses - self.used_count)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        # TIMESTAMPTZ приходит из asyncpg с таймзоной, но модель могли собрать
        # и в коде: наивное значение считаем UTC, иначе сравнение упадёт.
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc)

    @property
    def is_active(self) -> bool:
        """Код ещё можно погасить: не отозван, не истёк, есть свободные использования."""
        return not self.revoked and not self.is_expired and self.uses_left > 0
