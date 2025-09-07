import asyncio
import logging
from aiogram import Bot, Dispatcher, Router, F 
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.types.bot_command import BotCommand
import asyncpg

from config.settings import settings
from db.connection import init_db_pool, close_db_pool, get_db_pool
from db.repositories.user_repo import UserRepository
from db.repositories.like_repo import LikeRepository
from db.repositories.message_repo import MessageRepository
from db.repositories.complain_repo import ComplainRepository
from db.repositories.sticker_repo import StickerRepository

from services.user_service import UserService
from services.matching_service import MatchingService
from services.admin_service import AdminService
from services.support_service import SupportService

from handlers.registration import RegistrationHandlers
from handlers.commands import CommandHandlers
from handlers.profile_management import ProfileManagementHandlers
from handlers.profile_search import ProfileSearchHandlers
from handlers.admin import AdminHandlers

from filters.custom_filters import IsRegistered, IsAdmin, IsFeedbackForCurrentProfile

# Настройка логирования
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

async def set_commands(bot: Bot):
    """Устанавливает стандартные команды для бота."""
    commands = [
        BotCommand(command="/show_my_profile", description="Мой профиль"),
        BotCommand(command="/change_my_profile", description="Изменить мой профиль"),
        BotCommand(command="/searchi", description="Поиск профилей"),
        BotCommand(command="/show_mutual_likes", description="Мои взаимные лайки"),
        BotCommand(command="/support", description="Сообщение администратору"),
        BotCommand(command="/help", description="Помощь :)")
        # BotCommand(command="/admin", description="Админ-панель") # Для админов
    ]
    await bot.set_my_commands(commands)

async def main():
    logger.info("Запуск бота Matchi...")

    # Инициализация пула БД
    await init_db_pool()
    pool = await get_db_pool()

    # --- Создание экземпляров репозиториев ---
    user_repo = UserRepository(pool)
    like_repo = LikeRepository(pool)
    message_repo = MessageRepository(pool)
    complain_repo = ComplainRepository(pool)
    sticker_repo = StickerRepository(pool)

    # --- Создание экземпляров сервисов ---
    user_service = UserService(user_repo=user_repo)
    matching_service = MatchingService(user_repo=user_repo, like_repo=like_repo, sticker_repo=sticker_repo)
    admin_service = AdminService(user_repo=user_repo, complain_repo=complain_repo)
    support_service = SupportService(user_repo=user_repo, complain_repo=complain_repo, message_repo=message_repo)

    # Инициализация хранилища FSM (Redis)
    # Используем RedisStorage для aiogram v3
    storage = RedisStorage.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}")

    # --- Инициализация бота и диспетчера ---
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=storage)

    # --- Инициализация кастомных фильтров ---
    is_registered_filter = IsRegistered(user_service, expected_status="yes")
    is_not_registered_filter = IsRegistered(user_service, expected_status="no")
    is_in_progress_filter = IsRegistered(user_service, expected_status="in_progress")
    is_admin_filter = IsAdmin(admin_service)
    is_feedback_for_current_profile_filter = IsFeedbackForCurrentProfile(user_service)


    # --- Создание экземпляров хендлеров и получение их роутеров ---
    registration_router = RegistrationHandlers(user_service).get_router(
        is_registered_filter=is_registered_filter,
        is_not_registered_filter=is_not_registered_filter,
        is_in_progress_filter=is_in_progress_filter
    )
    command_router = CommandHandlers(user_service, matching_service, support_service).get_router(
        is_registered_filter=is_registered_filter
    )
    profile_management_router = ProfileManagementHandlers(user_service).get_router(
        is_registered_filter=is_registered_filter
    )
    profile_search_handlers_instance = ProfileSearchHandlers(user_service, matching_service, support_service)
    profile_search_handlers_instance.set_bot_instance(bot)
    profile_search_router = profile_search_handlers_instance.get_router(
        is_registered_filter=is_registered_filter,
        is_feedback_for_current_profile_filter=is_feedback_for_current_profile_filter
    )
    admin_handlers_instance = AdminHandlers(admin_service, user_service)
    admin_handlers_instance.set_bot_instance(bot)
    admin_router = admin_handlers_instance.get_router(is_admin_filter=is_admin_filter)


    # --- Регистрация роутеров в диспетчере ---
    dp.include_router(registration_router)
    dp.include_router(command_router)
    dp.include_router(profile_management_router)
    dp.include_router(profile_search_router)
    dp.include_router(admin_router)

    # --- Установка команд бота ---
    await set_commands(bot)

    # --- Запуск поллинга ---
    try:
        await dp.start_polling(bot)
    finally:
        await close_db_pool()
        logger.info("Бот Matchi остановлен.")
        await dp.storage.close()
        # await dp.storage.wait_closed() # wait_closed() не нужен для RedisStorage
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())