import asyncio
import logging
from aiogram import Dispatcher, types, Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter

from services.admin_service import AdminService
from services.user_service import UserService
from keyboards.inline import admin_keyboard
from config.settings import settings
from filters.custom_filters import IsAdmin

logger = logging.getLogger(__name__)


class AdminStates(StatesGroup):
    choose_action = State()
    send_message_to_all = State()


class AdminHandlers:
    def __init__(self, admin_service: AdminService, user_service: UserService):
        self.admin_service = admin_service
        self.user_service = user_service
        self.bot: Bot = None
        self.router = Router()

    def set_bot_instance(self, bot_instance: Bot):
        self.bot = bot_instance

    async def admin_command(self, message: types.Message, state: FSMContext):
        await message.answer("Выберите действие", parse_mode="MARKDOWN",
                             reply_markup=admin_keyboard())
        await state.set_state(AdminStates.choose_action) # ИСПРАВЛЕНО

    async def message_to_all_users_callback(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Напишите ваше сообщение для всех пользователей:")
        await state.set_state(AdminStates.send_message_to_all) # ИСПРАВЛЕНО
        await call.answer()

    async def send_message_to_all_users(self, message: types.Message, state: FSMContext):
        all_user_chat_ids = await self.admin_service.get_all_user_chat_ids()

        if not all_user_chat_ids:
            await message.answer("В базе данных нет пользователей для отправки сообщения.")
            await state.clear()
            return

        sent_count = 0
        failed_count = 0
        for cid_str in all_user_chat_ids:
            try:
                if self.bot:
                    await self.bot.send_message(int(cid_str), f"{message.text}")
                    sent_count += 1
                    await asyncio.sleep(0.05)
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение пользователю {cid_str}: {e}")
                failed_count += 1

        await message.answer(f"Сообщение отправлено {sent_count} пользователям. "
                             f"Не удалось отправить {failed_count} пользователям.")
        await state.clear()

    async def show_all_complains_command(self, message: types.Message):
        complains = await self.admin_service.get_all_complains()
        if not complains:
            await message.answer("Активных жалоб нет.")
            return

        response_text = "Список жалоб:\n"
        for complain_record in complains:
            reporter_user = await self.user_service.get_user_by_id(int(complain_record['reporter_chat_id']))
            reported_user = await self.user_service.get_user_by_id(int(complain_record['reported_chat_id']))

            reporter_info = f"@{reporter_user.tg_username}" if reporter_user and reporter_user.tg_username else f"ID: {complain_record['reporter_chat_id']}"
            reported_info = f"@{reported_user.tg_username}" if reported_user and reported_user.tg_username else f"ID: {complain_record['reported_chat_id']}"

            response_text += (
                f"--- Жалоба #{complain_record['id']} ---\n"
                f"От: {reporter_info}\n"
                f"На: {reported_info}\n"
                f"Причина: {complain_record['reason']}\n"
                f"Время: {complain_record['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            )
        await message.answer(response_text)

    def get_router(self, is_admin_filter: IsAdmin) -> Router:
        self.router.message.register(self.admin_command, Command("admin"), is_admin_filter)
        self.router.callback_query.register(self.message_to_all_users_callback, F.data == "message_to_all", StateFilter(AdminStates.choose_action))
        self.router.message.register(self.send_message_to_all_users, StateFilter(AdminStates.send_message_to_all), F.text)
        return self.router