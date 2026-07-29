import logging
from typing import Optional, Union

from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message

from models.user import User
from services.admin_service import AdminService
from services.user_service import UserService

logger = logging.getLogger(__name__)


class IsRegistered(Filter):
    """Пропускает апдейт, если статус регистрации совпадает с ожидаемым.

    Модель пользователя приходит из UserContextMiddleware в аргументе `user`;
    запрос к БД остаётся резервным путём, если middleware не сработал.
    """

    def __init__(self, user_service: UserService, expected_status: str = "yes"):
        self.user_service = user_service
        self.expected_status = expected_status

    async def __call__(self, event: Union[Message, CallbackQuery], user: Optional[User] = None) -> bool:
        if user is not None:
            return user.is_registered == self.expected_status

        status = await self.user_service.get_registration_status(event.from_user.id)
        return status == self.expected_status


class IsAdmin(Filter):
    def __init__(self, admin_service: AdminService):
        self.admin_service = admin_service

    async def __call__(self, event: Union[Message, CallbackQuery]) -> bool:
        return await self.admin_service.is_admin(event.from_user.id)


class IsFeedbackForCurrentProfile(Filter):
    """Отсекает лайк/дизлайк по анкете, которая уже пролистана.

    Иначе кнопкой под старым сообщением можно оценить профиль,
    показанный несколько шагов назад.
    """

    def __init__(self, user_service: UserService):
        self.user_service = user_service

    async def __call__(self, call: CallbackQuery, user: Optional[User] = None) -> bool:
        if user is not None:
            last_shown_profile_id = user.last_shown_profile
        else:
            last_shown_profile_id = await self.user_service.user_repo.get_last_shown_profile(str(call.from_user.id))

        if not last_shown_profile_id:
            return False

        data = call.data or ""
        # "like" — суффикс "dislike", поэтому длинный префикс проверяем первым:
        # со startswith порядок пока не влияет, но станет критичным, если
        # проверка сменится на вхождение подстроки или на removeprefix без startswith.
        for feedback_type in ("dislike", "like"):
            if data.startswith(feedback_type):
                return data.removeprefix(feedback_type) == last_shown_profile_id
        return False
