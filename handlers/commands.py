import asyncio
import logging
import time
from aiogram import Dispatcher, types, Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from config import settings

from services.user_service import UserService
from services.matching_service import MatchingService
from services.support_service import SupportService
from keyboards.inline import start_keyboard, change_profile_keyboard, yes_or_no_keyboard
from models.user import UserProfileData
from filters.custom_filters import IsRegistered
from aiogram.types import InputMediaPhoto

logger = logging.getLogger(__name__)


class CommandsStates(StatesGroup):
    support_message = State()


class CommandHandlers:
    def __init__(self, user_service: UserService, matching_service: MatchingService, support_service: SupportService):
        self.user_service = user_service
        self.matching_service = matching_service
        self.support_service = support_service
        self.router = Router()

    async def start_func(self, message: types.Message):
        tg_chat_id = message.chat.id
        user_status = await self.user_service.get_registration_status(tg_chat_id)

        if user_status is None or user_status == "no":
            await message.answer('Привет🙋! Это *Matchi* - бот для знакомств. \n\n'
                                 'Здесь вы можете найти интересных людей. \n'
                                 'Сначала вам нужно ответить на несколько вопросов.', reply_markup=start_keyboard(),
                                 parse_mode="MARKDOWN")
        elif user_status == "yes":
            await message.answer('Вы уже зарегистрированы.')
        elif user_status == "in_progress":
            await message.answer("Пожалуйста, завершите регистрацию.")

    async def help_func(self, message: types.Message):
        await message.answer('Используйте меню или напишите "/"'
                             " для поиска команд \n\n "
                             " По любому вопросу вы можете написать администратору: /support\n\n"
                             " Здесь я рассказываю о своих проектах:\n"
                             " https://t.me/Mister_Senna_channel")

    async def show_profile_func(self, message: types.Message):
        tg_chat_id = message.chat.id
        user_profile_data = await self.user_service.get_user_profile_data(tg_chat_id)

        if not user_profile_data:
            await message.answer("Ваш профиль еще не полностью заполнен или не существует.")
            return

        text = (f'*Ваш профиль*:\n\n'
                f' *Имя*: {user_profile_data.name}\n'
                f' *Возраст*: {user_profile_data.age}\n'
                f' *Город*: {user_profile_data.city}\n'
                f' *Пол*: {user_profile_data.gender}\n'
                f' *Предпочитаемый пол*: {user_profile_data.preferred_gender}\n'
                f' *Предпочитаемый возраст*: [{user_profile_data.age_range}]\n\n'
                f'*Описание*:\n'
                f'  {user_profile_data.description}')

        await message.answer(text, parse_mode='MARKDOWN')

        media_group_photos = await self.user_service.get_user_media_group(tg_chat_id)
        if media_group_photos:
            await message.answer_media_group(media=media_group_photos)
        else:
            await message.answer("У вас пока нет фотографий в профиле.")

    async def change_profile_command(self, message: types.Message):
        await message.answer("Выберите параметр, который хотите *изменить:* ", parse_mode="MARKDOWN",
                             reply_markup=change_profile_keyboard())

    async def support_create(self, message: types.Message, state: FSMContext): # Добавлен state
        tg_chat_id = message.chat.id

        remaining_time = await self.support_service.check_support_cooldown(tg_chat_id)

        if remaining_time == 0:
            await message.answer("*Напишите сообщение:*", parse_mode="MARKDOWN")
            await state.set_state(CommandsStates.support_message) # ИСПРАВЛЕНО
        else:
            await message.answer(f"Вы можете связаться с администратором через:\n"
                                 f"{remaining_time} секунд")

    async def support_send(self, message: types.Message, state: FSMContext):
        admin_ids = settings.Settings.ADMIN_IDS
        sender_username = message.from_user.username if message.from_user.username else f"ID: {message.chat.id}"

        for admin_id in admin_ids:
            try:
                await message.bot.send_message(admin_id, f"Запрос в поддержку от @{sender_username}:\n"
                                                         f"{message.text}")
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение админу {admin_id}: {e}")

        await message.answer("Сообщение отправлено и будет обработано.")
        await state.clear()

    async def show_profile_without_keyboard(self, bot: Bot, shown_profile_id: str, current_message: types.Message):
        user_profile_data = await self.user_service.get_user_profile_data(int(shown_profile_id))

        if not user_profile_data:
            await current_message.answer("Не удалось получить информацию о профиле.")
            return

        media_group_photos = await self.user_service.get_user_media_group(int(shown_profile_id))
        if media_group_photos:
            await bot.send_media_group(current_message.chat.id, media=media_group_photos)

        text = (f"Имя: {user_profile_data.name}\n"
                f"Возраст: {user_profile_data.age}\n"
                f"Город: {user_profile_data.city}\n\n"
                f"О себе:\n {user_profile_data.description}\n\n"
                f"Имя пользователя: @{user_profile_data.tg_username}")

        await current_message.answer(text)

    async def show_mutual_liked(self, message: types.Message):
        tg_chat_id = message.chat.id
        await message.answer("Ваши взаимные лайки:")

        mutual_likes_ids = await self.matching_service.get_mutual_likes(tg_chat_id)

        if not mutual_likes_ids:
            await message.answer("У вас пока нет взаимных лайков.")
            return

        for liked_cid in mutual_likes_ids:
            await self.show_profile_without_keyboard(message.bot, liked_cid, message)

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        self.router.message.register(self.start_func, Command("start"))
        self.router.message.register(self.help_func, Command("help"))
        self.router.message.register(self.show_profile_func, Command("show_my_profile"), is_registered_filter)
        self.router.message.register(self.change_profile_command, Command("change_my_profile"), is_registered_filter)
        self.router.message.register(self.support_create, Command("support"), is_registered_filter) # Здесь добавил state
        self.router.message.register(self.support_send, StateFilter(CommandsStates.support_message), F.text)
        self.router.message.register(self.show_mutual_liked, Command("show_mutual_likes"), is_registered_filter)
        return self.router