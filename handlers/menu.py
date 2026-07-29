import logging
from contextlib import suppress

from aiogram import Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from filters.custom_filters import IsRegistered
from handlers.dialogs import DialogStates
from handlers.rooms import RoomStates
from keyboards.menu import MenuCB, extra_menu_keyboard, main_menu_keyboard
from keyboards.reply import remove_dialog_keyboard

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
                 room_handlers, interest_handlers, invite_handlers=None,
                 post_handlers=None, feed_handlers=None, directory_handlers=None,
                 dialog_service=None):
        self.commands = command_handlers
        self.search = search_handlers
        self.dialogs = dialog_handlers
        self.rooms = room_handlers
        self.interests = interest_handlers
        self.invites = invite_handlers
        self.posts = post_handlers
        self.feed = feed_handlers
        self.directory = directory_handlers
        # Нужен, чтобы при уходе в раздел корректно закрыть активный диалог
        # и уведомить собеседника, а не бросить переписку в подвешенном виде.
        self.dialog_service = dialog_service
        self.router = Router()

    async def show_menu(self, message: types.Message):
        await message.answer(MENU_TITLE, reply_markup=main_menu_keyboard())

    async def _open_feed_section(self, action: str, message: types.Message, state: FSMContext) -> None:
        """Разделы ленты и постов. Хендлеры необязательные: если их не передали,
        честно говорим об этом вместо молчания."""
        # Свои посты и переключатель уведомлений живут в FeedHandlers,
        # создание поста — в PostHandlers.
        owner = self.posts if action == "new_post" else self.feed
        if owner is None:
            await message.answer("Этот раздел пока недоступен.")
            return

        if action == "feed":
            await owner.feed_command(message, state)
        elif action == "new_post":
            await owner.post_command(message, state)
        elif action == "my_posts":
            await owner.my_posts_command(message)
        else:
            await owner.feed_notify_command(message)

    async def _leave_relay_modes(self, message: types.Message, state: FSMContext) -> None:
        """Выводит из режимов, где реплики уходят не боту, а людям.

        Без этого переход в раздел одним тапом оставлял бы пользователя
        в активном диалоге или в чате комнаты: он отвечает боту, а сообщение
        уезжает собеседнику или всем участникам.
        """
        current = await state.get_state()
        me = message.chat.id

        if current == DialogStates.active.state:
            dialog = await self.dialog_service.get_active(me) if self.dialog_service else None
            if dialog is not None:
                await self.dialog_service.close(dialog, me, bot=message.bot)
            await state.clear()
            await message.answer("Диалог завершён.", reply_markup=remove_dialog_keyboard())
        elif current == RoomStates.chatting.state:
            await state.clear()
            await message.answer("Вы вышли из чата комнаты.")

    async def open_section(self, call: types.CallbackQuery, callback_data: MenuCB, state: FSMContext):
        action = callback_data.action
        message = call.message

        # Сообщение с меню остаётся в истории навсегда, а Telegram отдаёт для
        # старых кнопок InaccessibleMessage — у него нет ни edit_text, ни текста.
        if not isinstance(message, types.Message):
            await call.answer("Меню устарело, откройте заново: /menu", show_alert=True)
            return

        # Переключение экранов меню правим на месте, чтобы не плодить сообщения.
        if action in ("extra", "main"):
            # Сначала гасим крутилку: повторный тап по той же кнопке даёт
            # "message is not modified", и ответ на callback тогда не дошёл бы.
            await call.answer()
            title, keyboard = ((EXTRA_TITLE, extra_menu_keyboard()) if action == "extra"
                               else (MENU_TITLE, main_menu_keyboard()))
            with suppress(TelegramBadRequest):
                await message.edit_text(title, reply_markup=keyboard)
            return

        await call.answer()
        await self._leave_relay_modes(message, state)

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
        elif action == "people":
            if self.directory is None:
                await message.answer("Каталог участников пока недоступен.")
            else:
                await self.directory.people_command(message, state)
        elif action == "invite":
            await self.invites.invite_command(message)
        elif action == "community":
            await self.rooms.community_command(message)
        elif action in ("feed", "new_post", "my_posts", "feed_notify"):
            await self._open_feed_section(action, message, state)
        else:
            logger.warning(f"Неизвестный раздел меню: {action}")
            await message.answer("Такого раздела нет. Откройте меню заново: /menu")

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        self.router.message.register(self.show_menu, Command("menu"), is_registered_filter)
        self.router.callback_query.register(self.open_section, MenuCB.filter(), is_registered_filter)
        return self.router
