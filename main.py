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
from db.repositories.dislike_repo import DislikeRepository
from db.repositories.message_repo import MessageRepository
from db.repositories.complain_repo import ComplainRepository
from db.repositories.sticker_repo import StickerRepository
from db.repositories.interest_repo import InterestRepository
from db.repositories.dialog_repo import DialogRepository
from db.repositories.room_repo import RoomRepository

from services.user_service import UserService
from services.matching_service import MatchingService
from services.admin_service import AdminService
from services.support_service import SupportService
from services.interest_service import InterestService
from services.dialog_service import DialogService
from services.roulette_service import RouletteService
from services.room_service import RoomService
from services.outbox import Outbox

from handlers.registration import RegistrationHandlers
from handlers.commands import CommandHandlers
from handlers.profile_management import ProfileManagementHandlers
from handlers.profile_search import ProfileSearchHandlers
from handlers.admin import AdminHandlers
from handlers.interests import InterestHandlers
from handlers.dialogs import DialogHandlers
from handlers.rooms import RoomHandlers
from handlers.errors import build_errors_router

from filters.custom_filters import IsRegistered, IsAdmin, IsFeedbackForCurrentProfile
from middlewares.user_context import UserContextMiddleware
from middlewares.throttling import ThrottlingMiddleware

# Настройка логирования
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

async def set_commands(bot: Bot):
    """Устанавливает стандартные команды для бота."""
    commands = [
        BotCommand(command="/start", description="Начать"),
        BotCommand(command="/show_my_profile", description="Мой профиль"),
        BotCommand(command="/change_my_profile", description="Изменить мой профиль"),
        BotCommand(command="/searchi", description="Поиск профилей"),
        BotCommand(command="/show_mutual_likes", description="Мои взаимные лайки"),
        BotCommand(command="/interests", description="Мои интересы"),
        BotCommand(command="/dialogs", description="Мои переписки"),
        BotCommand(command="/roulette", description="Случайный собеседник по интересу"),
        BotCommand(command="/rooms", description="Комнаты по интересам"),
        BotCommand(command="/support", description="Сообщение администратору"),
        BotCommand(command="/help", description="Помощь :)")
        # /admin и /complains намеренно не публикуются в меню — они только для админов
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
    dislike_repo = DislikeRepository(pool)
    message_repo = MessageRepository(pool)
    complain_repo = ComplainRepository(pool)
    sticker_repo = StickerRepository(pool)
    interest_repo = InterestRepository(pool)
    dialog_repo = DialogRepository(pool)
    room_repo = RoomRepository(pool)

    # --- Создание экземпляров сервисов ---
    user_service = UserService(user_repo=user_repo)
    matching_service = MatchingService(user_repo=user_repo, like_repo=like_repo,
                                       dislike_repo=dislike_repo, sticker_repo=sticker_repo)
    admin_service = AdminService(user_repo=user_repo, complain_repo=complain_repo)
    support_service = SupportService(user_repo=user_repo, complain_repo=complain_repo, message_repo=message_repo)
    interest_service = InterestService(interest_repo=interest_repo)
    dialog_service = DialogService(dialog_repo=dialog_repo, message_repo=message_repo, user_repo=user_repo)
    room_service = RoomService(room_repo=room_repo, user_repo=user_repo)

    # Инициализация хранилища FSM (Redis)
    # Используем RedisStorage для aiogram v3
    storage = RedisStorage.from_url(f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}")

    # --- Инициализация бота и диспетчера ---
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=storage)

    # Хендлеры передают bot из апдейта, но диалогам нужно уметь уведомлять
    # брошенного собеседника и из вызовов без апдейта.
    dialog_service.set_bot_instance(bot)

    # Рулетка держит очередь ожидания в Redis — переиспользуем клиент FSM-хранилища.
    roulette_service = RouletteService(redis_client=storage.redis, dialog_service=dialog_service)

    # Веерная рассылка в комнатах идёт через очередь с троттлингом: Telegram не даёт
    # боту отправлять больше ~20 сообщений в минуту в один групповой чат.
    # Зависимость взаимная (Outbox сообщает комнатам о недоставленных сообщениях,
    # чтобы исключить участника), поэтому очередь досоздаётся после сервиса.
    outbox = Outbox(bot, on_undeliverable=room_service.handle_undeliverable)
    room_service.outbox = outbox

    # --- Регистрация middleware ---
    # Порядок важен: троттлинг идёт первым, чтобы отброшенный апдейт не стоил
    # запроса к БД. Оба именно outer_middleware — данные должны попасть в
    # контекст до фильтров, чтобы IsRegistered брал готовую модель, а не SELECT.
    # Redis-клиент переиспользуем из FSM-хранилища, второй пул не нужен.
    throttling_middleware = ThrottlingMiddleware(storage.redis)
    dp.message.outer_middleware(throttling_middleware)
    dp.callback_query.outer_middleware(throttling_middleware)

    user_context_middleware = UserContextMiddleware(user_service)
    dp.message.outer_middleware(user_context_middleware)
    dp.callback_query.outer_middleware(user_context_middleware)

    # --- Инициализация кастомных фильтров ---
    is_registered_filter = IsRegistered(user_service, expected_status="yes")
    is_admin_filter = IsAdmin(admin_service)
    is_feedback_for_current_profile_filter = IsFeedbackForCurrentProfile(user_service)


    # --- Создание экземпляров хендлеров и получение их роутеров ---
    registration_router = RegistrationHandlers(user_service).get_router()
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
    interests_router = InterestHandlers(interest_service).get_router(
        is_registered_filter=is_registered_filter
    )
    dialogs_router = DialogHandlers(
        dialog_service=dialog_service,
        user_service=user_service,
        support_service=support_service,
        interest_service=interest_service,
        roulette_service=roulette_service,
    ).get_router(is_registered_filter=is_registered_filter)
    rooms_router = RoomHandlers(
        room_service=room_service,
        interest_service=interest_service,
        user_service=user_service,
    ).get_router(is_registered_filter=is_registered_filter, is_admin_filter=is_admin_filter)
    admin_handlers_instance = AdminHandlers(admin_service, user_service)
    admin_handlers_instance.set_bot_instance(bot)
    admin_router = admin_handlers_instance.get_router(is_admin_filter=is_admin_filter)


    # --- Регистрация роутеров в диспетчере ---
    # Порядок значим: роутер регистрации первым (его состояния перехватывают
    # ввод анкеты), админский последним. Роутер ошибок подключается в конце,
    # чтобы ловить исключения из всех остальных.
    dp.include_router(registration_router)
    dp.include_router(command_router)
    dp.include_router(profile_management_router)
    dp.include_router(profile_search_router)
    dp.include_router(interests_router)
    dp.include_router(dialogs_router)
    dp.include_router(rooms_router)
    dp.include_router(admin_router)
    dp.include_router(build_errors_router())

    # --- Установка команд бота ---
    await set_commands(bot)

    # --- Запуск поллинга ---
    await outbox.start()
    try:
        await dp.start_polling(bot)
    finally:
        # Очередь останавливаем первой: она дописывает остаток сообщений,
        # а для этого ей нужны живые сессия бота и пул БД.
        await outbox.stop()
        await close_db_pool()
        logger.info("Бот Matchi остановлен.")
        await dp.storage.close()
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())