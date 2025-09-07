from typing import Union
from aiogram.filters import Filter, Command
from aiogram.types import Message, CallbackQuery

from services.user_service import UserService
from services.admin_service import AdminService
import logging

logger = logging.getLogger(__name__)

class IsRegistered(Filter):
    def __init__(self, user_service: UserService, expected_status: str = "yes"):
        self.user_service = user_service
        self.expected_status = expected_status

    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        user_id = event.from_user.id
        status = await self.user_service.get_registration_status(user_id)
        # logger.debug(f"Filter IsRegistered: user_id={user_id}, status={status}, expected={self.expected_status}, result={status == self.expected_status}")
        return status == self.expected_status

class IsAdmin(Filter):
    def __init__(self, admin_service: AdminService):
        self.admin_service = admin_service

    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        user_id = event.from_user.id
        # logger.debug(f"Filter IsAdmin: user_id={user_id}, is_admin={await self.admin_service.is_admin(user_id)}")
        return await self.admin_service.is_admin(user_id)

class IsFeedbackForCurrentProfile(Filter):
    def __init__(self, user_service: UserService):
        self.user_service = user_service

    async def __call__(self, call: CallbackQuery) -> bool:
        user_id = call.from_user.id
        last_shown_profile_id = await self.user_service.user_repo.get_last_shown_profile(str(user_id))
        if last_shown_profile_id:
            # Например, callback_data: "like123456789"
            # Извлекаем ID из конца callback_data
            try:
                # Находим место, где начинается ID профиля
                feedback_type = ""
                if call.data.startswith("like"):
                    feedback_type = "like"
                elif call.data.startswith("dislike"):
                    feedback_type = "dislike"

                if feedback_type:
                    id_from_callback = call.data[len(feedback_type):]
                    return id_from_callback == last_shown_profile_id
                return False
            except Exception as e:
                logger.error(f"Error parsing profile ID from callback data {call.data}: {e}")
                return False
        return False