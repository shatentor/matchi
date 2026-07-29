import logging
from typing import Any, Dict, List, Optional, Tuple

from config.settings import settings
from db.repositories.interest_repo import InterestRepository
from db.repositories.invite_repo import InviteRepository
from db.repositories.user_repo import UserRepository
from models.interest import Interest
from models.user import UserProfileData

logger = logging.getLogger(__name__)


class DirectoryService:
    """Каталог участников: постраничный список, фильтры и карточка участника.

    В отличие от колоды (`MatchingService`), каталог не смотрит на лайки и
    дизлайки: дизлайк в колоде вечен, а каталог обязан показывать всю сеть,
    иначе найти знакомого по имени станет невозможно.

    invite_repo необязателен: без него в карточке просто не будет строки
    «кто пригласил», остальное работает.
    """

    def __init__(self, user_repo: UserRepository, interest_repo: InterestRepository,
                 invite_repo: Optional[InviteRepository] = None):
        self.user_repo = user_repo
        self.interest_repo = interest_repo
        self.invite_repo = invite_repo

    @staticmethod
    def pages_for(total: int) -> int:
        """Сколько страниц занимает total участников. Ноль результатов — ноль страниц."""
        size = max(1, settings.DIRECTORY_PAGE_SIZE)
        return (total + size - 1) // size

    @staticmethod
    def clamp_page(page: int, pages: int) -> int:
        """Приводит номер страницы к существующему.

        Кнопка «➡️» живёт в старом сообщении, и её можно нажать, когда людей
        стало меньше: без приведения человек получил бы пустую страницу.
        """
        if page < 0:
            return 0
        if pages and page >= pages:
            return pages - 1
        return page if pages else 0

    async def page(self, viewer_id: int, query: Optional[str] = None,
                   interest_id: Optional[int] = None, city: Optional[str] = None,
                   page: int = 0) -> Tuple[List[UserProfileData], int, int]:
        """Страница каталога: (участники, всего найдено, всего страниц).

        Два запроса на страницу независимо от числа участников на ней:
        сама выборка и подсчёт для «стр. N из M».
        """
        viewer = str(viewer_id)
        size = max(1, settings.DIRECTORY_PAGE_SIZE)
        total = await self.user_repo.directory_count(viewer, query, interest_id, city)
        pages = self.pages_for(total)
        if not total:
            return [], 0, 0

        current = self.clamp_page(page, pages)
        items = await self.user_repo.directory_page(viewer, query, interest_id, city,
                                                    offset=current * size, limit=size)
        return items, total, pages

    async def cities(self) -> List[Tuple[str, int]]:
        return await self.user_repo.cities_with_members()

    async def interests(self) -> List[Interest]:
        return await self.interest_repo.get_active()

    async def common_interests(self, tg_chat_id: int, viewer_id: int) -> List[Interest]:
        """Интересы, которые есть у обоих."""
        mine = {interest.id for interest in
                await self.interest_repo.get_user_interests(str(viewer_id))}
        return [interest for interest in
                await self.interest_repo.get_user_interests(str(tg_chat_id))
                if interest.id in mine]

    async def profile_card(self, tg_chat_id: int, viewer_id: int) -> Optional[Dict[str, Any]]:
        """Данные карточки участника или None, если показывать нечего.

        Ключи: profile (UserProfileData), common (список общих интересов),
        inviter_id и inviter_name (кто пригласил, оба могут быть None).

        Граф приглашений уже пишется в invite_uses, но нигде не показан — для
        закрытой сети «пришёл по приглашению N» это половина контекста о человеке.
        """
        chat_id = str(tg_chat_id)
        user = await self.user_repo.get_by_id(chat_id)
        if not user or user.is_registered != "yes":
            return None

        description = await self.user_repo.get_description(chat_id)
        # Тот же обязательный минимум, что и в каталоге: без него анкету нечем
        # отрисовать, и она в списке не появлялась.
        if not all([user.name, user.city, user.role, description]):
            return None

        photo_ids = [pid for pid in (user.photo_link, user.photo_link_two,
                                     user.photo_link_three) if pid]
        profile = UserProfileData(
            tg_chat_id=user.tg_chat_id,
            tg_username=user.tg_username,
            name=user.name,
            city=user.city,
            role=user.role,
            description=description,
            status=user.status,
            links=user.links,
            can_help=user.can_help,
            looking_for=user.looking_for,
            photo_ids=photo_ids,
        )

        inviter_id: Optional[str] = None
        inviter_name: Optional[str] = None
        if self.invite_repo is not None:
            inviter_id = await self.invite_repo.inviter_of(chat_id)
            if inviter_id:
                inviter = await self.user_repo.get_by_id(inviter_id)
                if inviter:
                    inviter_name = inviter.name or (f"@{inviter.tg_username}"
                                                    if inviter.tg_username else None)

        return {
            "profile": profile,
            "common": await self.common_interests(tg_chat_id, viewer_id),
            "inviter_id": inviter_id,
            "inviter_name": inviter_name,
        }
