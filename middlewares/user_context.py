import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User as TgUser

from models.user import User
from services.user_service import UserService

logger = logging.getLogger(__name__)


class UserContextMiddleware(BaseMiddleware):
    """Один раз за апдейт достаёт пользователя из БД и кладёт его в data['user'].

    Регистрируется как outer middleware, поэтому данные доступны уже фильтрам:
    IsRegistered и IsFeedbackForCurrentProfile берут готовую модель вместо
    собственного SELECT (IsAdmin в БД не ходит вообще — сверяет ID со списком
    из настроек). До этого каждый апдейт стоил несколько одинаковых запросов
    к users. Заодно синхронизирует сменившийся @username.

    Связь с фильтрами держится на имени ключа: aiogram передаёт значение из
    data в параметр фильтра с тем же именем. Переименуешь 'user' — фильтры
    молча уйдут в резервную ветку с запросом к БД.
    """

    def __init__(self, user_service: UserService):
        self.user_service = user_service

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        tg_user: Optional[TgUser] = data.get("event_from_user")
        user: Optional[User] = None

        if tg_user is not None and not tg_user.is_bot:
            try:
                user = await self.user_service.get_user_by_id(tg_user.id)
            except Exception as e:
                # Недоступность БД не должна ронять обработку апдейта целиком:
                # фильтры в этом случае сходят в БД сами и обработают ошибку там.
                logger.error(f"Не удалось загрузить пользователя {tg_user.id}: {e}")
                user = None

            if user is not None:
                try:
                    user = await self.user_service.sync_username(user, tg_user.username)
                except Exception as e:
                    # tg_username объявлен UNIQUE: занятый кем-то юзернейм даст
                    # UniqueViolation. Это не причина терять загруженный профиль.
                    logger.warning(f"Не удалось обновить username пользователя {tg_user.id}: {e}")

        data["user"] = user
        return await handler(event, data)
