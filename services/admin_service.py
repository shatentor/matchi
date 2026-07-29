from typing import List
from config.settings import settings
from db.repositories.user_repo import UserRepository
from db.repositories.complain_repo import ComplainRepository
from models.complain import Complain

class AdminService:
    def __init__(self, user_repo: UserRepository, complain_repo: ComplainRepository):
        self.user_repo = user_repo
        self.complain_repo = complain_repo

    async def is_admin(self, tg_chat_id: int) -> bool:
        return tg_chat_id in settings.ADMIN_IDS

    async def get_all_user_chat_ids(self) -> List[str]:
        return await self.user_repo.get_all_chat_ids()

    async def get_all_complains(self, limit: int = 50) -> List[Complain]:
        return await self.complain_repo.get_all(limit)