import logging

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from filters.custom_filters import IsRegistered
from keyboards.menu import MenuCB, extra_menu_keyboard, main_menu_keyboard

logger = logging.getLogger(__name__)

MENU_TITLE = "<b>Matchi</b> — выберите раздел:"
EXTRA_TITLE = "<b>Ещё</b> — что можно сделать:"


class MenuHandlers:
    """Единая точка входа вместо длинного списка команд.

    Меню — это хаб: он не дублирует логику разделов, а вызывает готовые
    точки входа существующих хендлеров. Все они читают chat.id, поэтому
    вызов из callback с call.message корректен (в личке chat.id совпадает
    с id пользователя). Команды при этом продолжают работать: из меню
    Telegram убраны только редкие, но набрать их по-прежнему можно.
    """

    def __init__(self, command_handlers, search_handlers, dialog_handlers,
                 room_handlers, interest_handlers):
        self.commands = command_handlers
        self.search = search_handlers
        self.dialogs = dialog_handlers
        self.rooms = room_handlers
        self.interests = interest_handlers
        self.router = Router()

    async def show_menu(self, message: types.Message):
        await message.answer(MENU_TITLE, reply_markup=main_menu_keyboard())

    async def open_section(self, call: types.CallbackQuery, callback_data: MenuCB, state: FSMContext):
        action = callback_data.action
        message = call.message

        # Переключение экранов меню правим на месте, чтобы не плодить сообщения.
        if action == "extra":
            await call.message.edit_text(EXTRA_TITLE, reply_markup=extra_menu_keyboard())
            await call.answer()
            return
        if action == "main":
            await call.message.edit_text(MENU_TITLE, reply_markup=main_menu_keyboard())
            await call.answer()
            return

        await call.answer()

        if action == "search":
            await self.search.start_searching_profiles(message, state)
        elif action == "dialogs":
            await self.dialogs.cmd_dialogs(message)
        elif action == "roulette":
            await self.dialogs.cmd_roulette(message)
        elif action == "rooms":
            await self.rooms.rooms_command(message, state)
        elif action == "profile":
            await self.commands.show_profile_func(message)
        elif action == "interests":
            await self.interests.show_interests(message)
        elif action == "mutual":
            await self.commands.show_mutual_liked(message)
        elif action == "edit_profile":
            await self.commands.change_profile_command(message)
        elif action == "support":
            await self.commands.support_create(message, state)
        elif action == "help":
            await self.commands.help_func(message)
        else:
            logger.warning(f"Неизвестный раздел меню: {action}")
            await message.answer("Такого раздела нет. Откройте меню заново: /menu")

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        self.router.message.register(self.show_menu, Command("menu"), is_registered_filter)
        self.router.callback_query.register(self.open_section, MenuCB.filter(), is_registered_filter)
        return self.router
