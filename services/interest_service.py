import logging
from typing import List, Tuple

from config.settings import settings
from db.repositories.interest_repo import InterestRepository
from models.interest import Interest

logger = logging.getLogger(__name__)


class InterestService:
    def __init__(self, interest_repo: InterestRepository):
        self.interest_repo = interest_repo

    async def list_active(self) -> List[Interest]:
        return await self.interest_repo.get_active()

    async def get_user_interests(self, tg_chat_id: int) -> List[Interest]:
        return await self.interest_repo.get_user_interests(str(tg_chat_id))

    async def toggle(self, tg_chat_id: int, interest_id: int) -> Tuple[bool, str]:
        """Переключает интерес пользователя.

        Возвращает (изменилось ли состояние, текст для пользователя).
        Отказ возможен, если интерес больше не активен или уже выбрано
        settings.MAX_USER_INTERESTS интересов.
        """
        chat_id_str = str(tg_chat_id)
        selected_ids = await self.interest_repo.get_user_interest_ids(chat_id_str)

        if interest_id in selected_ids:
            await self.interest_repo.remove_user_interest(chat_id_str, interest_id)
            return True, "Интерес убран."

        active_ids = {interest.id for interest in await self.interest_repo.get_active()}
        if interest_id not in active_ids:
            return False, "Этот интерес больше недоступен."

        if len(selected_ids) >= settings.MAX_USER_INTERESTS:
            return False, (f"Можно выбрать не больше {settings.MAX_USER_INTERESTS} интересов. "
                           f"Сначала снимите какой-нибудь из уже выбранных.")

        await self.interest_repo.add_user_interest(chat_id_str, interest_id)
        return True, "Интерес добавлен."
