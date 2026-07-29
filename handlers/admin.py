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
from utils.text import escape
from utils.telegram import safe_send_message

logger = logging.getLogger(__name__)

# Лимит текста сообщения Telegram — 4096 символов, поэтому длинный список жалоб
# приходится разбивать на части, а причину — обрезать. Бюджет с запасом:
# escape() может увеличить длину (например, '&' превращается в '&amp;').
COMPLAINS_PER_MESSAGE = 10
MAX_REASON_LENGTH = 300
MAX_MESSAGE_LENGTH = 3500


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
        await message.answer("Выберите действие", reply_markup=admin_keyboard())
        await state.set_state(AdminStates.choose_action)

    async def message_to_all_users_callback(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Напишите ваше сообщение для всех пользователей:")
        await state.set_state(AdminStates.send_message_to_all)
        await call.answer()

    async def send_message_to_all_users(self, message: types.Message, state: FSMContext):
        if not self.bot:
            logger.error("Экземпляр бота не задан (set_bot_instance), рассылка невозможна.")
            await message.answer("Рассылка недоступна: бот не инициализирован.")
            await state.clear()
            return

        all_user_chat_ids = await self.admin_service.get_all_user_chat_ids()

        if not all_user_chat_ids:
            await message.answer("В базе данных нет пользователей для отправки сообщения.")
            await state.clear()
            return

        # html_text сохраняет форматирование админа и экранирует служебные символы
        broadcast_text = message.html_text

        sent_count = 0
        failed_count = 0
        for cid_str in all_user_chat_ids:
            if await safe_send_message(self.bot, int(cid_str), broadcast_text):
                sent_count += 1
            else:
                failed_count += 1
            # Троттлинг нужен независимо от результата: лимиты Telegram считают все запросы
            await asyncio.sleep(settings.BROADCAST_DELAY)

        await message.answer(f"Сообщение отправлено {sent_count} пользователям. "
                             f"Не удалось отправить {failed_count} пользователям.")
        await state.clear()

    async def send_message_to_all_users_invalid(self, message: types.Message, state: FSMContext):
        # Рассылается html_text, у нетекстового сообщения он пуст
        await message.answer("Вы сейчас составляете сообщение для рассылки. Пожалуйста, пришлите его текстом:")

    async def _user_label(self, chat_id: str) -> str:
        """Юзернейм жалующегося/обвиняемого, либо его ID, если юзернейма нет."""
        try:
            user = await self.user_service.get_user_by_id(int(chat_id))
        except (TypeError, ValueError):
            user = None

        if user and user.tg_username:
            return f"@{escape(user.tg_username)}"
        return f"ID: {escape(chat_id)}"

    async def show_all_complains_command(self, message: types.Message):
        complains = await self.admin_service.get_all_complains()
        if not complains:
            await message.answer("Активных жалоб нет.")
            return

        blocks = []
        for complain in complains:
            # Обрезаем до escape(), иначе можно разрезать HTML-сущность вроде '&amp;'
            reason = complain.reason or ""
            if len(reason) > MAX_REASON_LENGTH:
                reason = reason[:MAX_REASON_LENGTH] + "…"

            block = (
                f"--- Жалоба #{complain.id} ---\n"
                f"От: {await self._user_label(complain.reporter_chat_id)}\n"
                f"На: {await self._user_label(complain.reported_chat_id)}\n"
                f"Причина: {escape(reason)}\n"
                f"Время: {complain.timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
            )
            blocks.append(block)

        # Отправляем порциями: и по количеству жалоб, и по длине текста
        chunk = []
        chunk_length = 0
        first = True

        async def flush():
            nonlocal chunk, chunk_length, first
            if not chunk:
                return
            header = "<b>Список жалоб:</b>\n\n" if first else ""
            await message.answer(header + "\n".join(chunk))
            chunk, chunk_length, first = [], 0, False

        for block in blocks:
            if chunk and (len(chunk) >= COMPLAINS_PER_MESSAGE
                          or chunk_length + len(block) > MAX_MESSAGE_LENGTH):
                await flush()
            chunk.append(block)
            chunk_length += len(block) + 1

        await flush()

    async def show_all_complains_callback(self, call: types.CallbackQuery):
        await self.show_all_complains_command(call.message)
        await call.answer()

    def get_router(self, is_admin_filter: IsAdmin) -> Router:
        # not_command нужен, чтобы команды не съедались хендлером состояния:
        # иначе любая команда, набранная в состоянии рассылки, ушла бы её текстом
        # всем пользователям бота. Fallback ловит только нетекстовые сообщения
        # и регистрируется после основного: в aiogram 3 порядок регистрации задаёт приоритет
        not_command = ~F.text.startswith("/")

        self.router.message.register(self.admin_command, Command("admin"), is_admin_filter)
        self.router.message.register(self.show_all_complains_command, Command("complains"), is_admin_filter)
        self.router.callback_query.register(self.show_all_complains_callback, F.data == "show_complains", is_admin_filter)
        self.router.callback_query.register(self.message_to_all_users_callback, F.data == "message_to_all", StateFilter(AdminStates.choose_action))
        self.router.message.register(self.send_message_to_all_users, StateFilter(AdminStates.send_message_to_all),
                                     F.text, not_command)
        self.router.message.register(self.send_message_to_all_users_invalid,
                                     StateFilter(AdminStates.send_message_to_all), not_command)
        return self.router