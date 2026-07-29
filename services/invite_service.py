import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from config.settings import settings
from db.repositories.invite_repo import (ADD_USE_ALREADY, ADD_USE_OK, InviteRepository)
from models.invite import CODE_COLUMN_LENGTH, Invite, generate_code, normalize_code

logger = logging.getLogger(__name__)

# Сколько раз пытаться сгенерировать незанятый код. Алфавит без похожих
# символов даёт 31^8 вариантов, поэтому совпадение — событие уровня «никогда»,
# и цикл нужен только чтобы не отдавать пользователю ошибку из-за него.
CODE_ATTEMPTS = 5


def format_deadline(value: Optional[datetime]) -> str:
    """Срок действия кода для показа человеку.

    Только дата, без времени: срок измеряется днями, а время из TIMESTAMPTZ
    пришлось бы объяснять таймзоной, которой у пользователя мы не знаем.
    """
    if value is None:
        return "без срока"
    return value.strftime('%d.%m.%Y')


class InviteService:
    """Приглашения: вход в сеть только по коду от того, кто уже внутри.

    Выдача ограничена settings.INVITES_PER_USER действующими кодами на человека —
    иначе один участник смог бы наштамповать сколько угодно пропусков, и сеть
    перестала бы быть закрытой.
    """

    def __init__(self, invite_repo: InviteRepository):
        self.invite_repo = invite_repo

    async def issue(self, tg_chat_id: int) -> Tuple[Optional[Invite], str]:
        """Выдаёт новый код приглашения. При отказе возвращает (None, причина)."""
        owner = str(tg_chat_id)

        active = await self.invite_repo.count_active_by(owner)
        if active >= settings.INVITES_PER_USER:
            return None, (f"У вас уже {active} действующих кодов, это максимум "
                          f"({settings.INVITES_PER_USER}). Отзовите ненужный "
                          f"в /my_invites или дождитесь, когда истечёт срок.")

        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.INVITE_TTL_DAYS)
        for _ in range(CODE_ATTEMPTS):
            invite = Invite(
                code=generate_code(settings.INVITE_CODE_LENGTH),
                created_by=owner,
                max_uses=settings.INVITE_MAX_USES,
                expires_at=expires_at,
            )
            created = await self.invite_repo.create(invite)
            if created is not None:
                return created, "Код приглашения готов."

        logger.error(f"Не удалось подобрать свободный код приглашения за {CODE_ATTEMPTS} "
                     f"попыток для пользователя {tg_chat_id}")
        return None, "Не получилось выдать код. Попробуйте ещё раз через минуту."

    async def redeem(self, code: str, tg_chat_id: int) -> Tuple[bool, str]:
        """Принимает код при регистрации: (успех, текст для пользователя).

        Причины отказа различаются по-настоящему, а не одним «код не подошёл»:
        человек на входе в закрытую сеть должен понимать, просить ему новый код
        или искать опечатку в этом.

        Сам факт использования пишется в invite_uses в той же транзакции, что и
        инкремент счётчика (см. InviteRepository.add_use), поэтому две
        одновременные регистрации по одному коду не израсходуют его дважды.
        """
        clean = normalize_code(code)
        if not clean:
            return False, "Пришлите код приглашения текстом."
        # Колонка invites.code — VARCHAR(16), и приведение более длинной строки
        # к этому типу PostgreSQL делает молчаливым обрезанием: без проверки
        # длинный мусор совпал бы с настоящим кодом по первым 16 символам.
        if len(clean) > CODE_COLUMN_LENGTH:
            return False, "Это слишком длинно для кода приглашения. Проверьте, что скопировали только код."

        invite = await self.invite_repo.get(clean)
        if invite is None:
            return False, ("Такого кода нет. Проверьте, что он скопирован целиком "
                           "и без лишних символов.")
        if invite.revoked:
            return False, ("Этот код отозвали. Попросите новый у того, кто вас приглашает.")
        if invite.is_expired:
            return False, (f"Срок действия кода истёк {format_deadline(invite.expires_at)}. "
                           f"Попросите новый у того, кто вас приглашает.")
        if invite.uses_left <= 0:
            return False, (f"Этот код уже использовали максимальное число раз "
                           f"({invite.max_uses}). Попросите новый у того, кто вас приглашает.")

        status, _ = await self.invite_repo.add_use(clean, str(tg_chat_id))
        if status == ADD_USE_ALREADY:
            return False, ("Вы уже входили по этому коду — второй раз он не сработает. "
                           "Попросите новый у того, кто вас приглашает.")
        if status != ADD_USE_OK:
            # Проверки выше прошли, а UPDATE строку не отдал: код разобрали
            # или отозвали прямо между двумя запросами.
            return False, ("Этот код только что разобрали до конца. Попросите новый "
                           "у того, кто вас приглашает.")

        return True, "Код принят. Добро пожаловать, продолжаем регистрацию."

    async def my_invites(self, tg_chat_id: int) -> List[Invite]:
        """Коды человека: сначала действующие, внутри группы — свежие сверху."""
        invites = await self.invite_repo.list_by(str(tg_chat_id))
        # created_at заполняет БД, но у собранной в коде модели его может не быть
        return sorted(
            invites,
            key=lambda inv: (not inv.is_active,
                             -(inv.created_at.timestamp() if inv.created_at else 0.0))
        )

    async def revoke(self, tg_chat_id: int, code: str) -> Tuple[bool, str]:
        """Отзывает свой код. Чужой код отозвать нельзя."""
        clean = normalize_code(code)
        if not clean or len(clean) > CODE_COLUMN_LENGTH:
            return False, "Не понял, какой код отозвать."

        invite = await self.invite_repo.get(clean)
        if invite is None:
            return False, "Такого кода нет."
        if invite.created_by != str(tg_chat_id):
            return False, "Это не ваш код."
        if invite.revoked:
            return True, f"Код {clean} и так был отозван."

        revoked = await self.invite_repo.revoke(clean)
        if not revoked:
            return True, f"Код {clean} и так был отозван."
        return True, f"Код {clean} отозван, войти по нему больше нельзя."

    async def inviter_of(self, tg_chat_id: int) -> Optional[str]:
        """Кто привёл человека в сеть: tg_chat_id строкой или None."""
        return await self.invite_repo.inviter_of(str(tg_chat_id))

    async def is_invited(self, tg_chat_id: int) -> bool:
        """Гасил ли человек уже чей-то код.

        Нужно на входе в регистрацию: тот, кто код уже погасил, а анкету не
        дозаполнил, не должен требовать второй код — по своему прежнему он
        пройти уже не сможет.
        """
        return await self.invite_repo.used_any(str(tg_chat_id))
