import asyncio
import logging
import time
from aiogram import Dispatcher, types, Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from config.settings import settings

from services.user_service import UserService
from services.matching_service import MatchingService
from services.support_service import SupportService
from keyboards.inline import start_keyboard, change_profile_keyboard, yes_or_no_keyboard
from models.user import UserProfileData
from filters.custom_filters import IsRegistered
from utils.text import escape
from utils.telegram import safe_send_message, safe_send_media_group
from aiogram.types import InputMediaPhoto

logger = logging.getLogger(__name__)


def _optional_profile_lines(profile: UserProfileData, bold: bool = False) -> list:
    """Строки необязательных полей анкеты; незаполненные поля не печатаются."""
    lines = []
    for label, value in (("Статус", profile.status),
                         ("Ссылки", profile.links),
                         ("Чем могу помочь", profile.can_help),
                         ("Что ищу", profile.looking_for)):
        if value:
            title = f"<b>{label}</b>" if bold else label
            lines.append(f"{title}: {escape(value)}")
    return lines


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
            await message.answer('Привет🙋! Это <b>Matchi</b> — закрытая сеть для своих. \n\n'
                                 'Здесь вы можете найти интересных людей. \n'
                                 'Вход только по приглашению: понадобится код от того, кто вас позвал.',
                                 reply_markup=start_keyboard())
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

        lines = [f'<b>Ваш профиль</b>:',
                 '',
                 f' <b>Имя</b>: {escape(user_profile_data.name)}',
                 f' <b>Роль</b>: {escape(user_profile_data.role)}',
                 f' <b>Город</b>: {escape(user_profile_data.city)}']
        lines += [f' {line}' for line in _optional_profile_lines(user_profile_data, bold=True)]
        lines += ['', '<b>Описание</b>:', f'  {escape(user_profile_data.description)}']

        await message.answer("\n".join(lines))

        media_group_photos = await self.user_service.get_user_media_group(tg_chat_id)
        if media_group_photos:
            await message.answer_media_group(media=media_group_photos)
        else:
            await message.answer("У вас пока нет фотографий в профиле.")

    async def change_profile_command(self, message: types.Message):
        await message.answer("Выберите параметр, который хотите <b>изменить:</b> ",
                             reply_markup=change_profile_keyboard())

    async def support_create(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id

        # TODO: check_support_cooldown обновляет время последнего обращения уже здесь,
        # поэтому кулдаун тратится даже если пользователь так и не напишет сообщение.
        # Время стоит фиксировать в support_send, после фактической отправки.
        remaining_time = await self.support_service.check_support_cooldown(tg_chat_id)

        if remaining_time == 0:
            await message.answer("<b>Напишите сообщение:</b>")
            await state.set_state(CommandsStates.support_message)
        else:
            await message.answer(f"Вы можете связаться с администратором через:\n"
                                 f"{remaining_time} секунд")

    async def support_send(self, message: types.Message, state: FSMContext):
        admin_ids = settings.ADMIN_IDS
        username = message.from_user.username if message.from_user else None
        sender_info = f"@{escape(username)}" if username else f"ID: {message.chat.id}"

        # html_text сохраняет форматирование пользователя и уже экранирован
        text = f"Запрос в поддержку от {sender_info}:\n{message.html_text}"

        delivered = 0
        for admin_id in admin_ids:
            if await safe_send_message(message.bot, admin_id, text):
                delivered += 1

        if delivered:
            await message.answer("Сообщение отправлено и будет обработано.")
        else:
            logger.error(f"Запрос в поддержку от {message.chat.id} не доставлен ни одному админу.")
            await message.answer("Не удалось отправить сообщение администратору. "
                                 "Попробуйте, пожалуйста, позже.")
        await state.clear()

    async def support_send_invalid(self, message: types.Message, state: FSMContext):
        # Админам пересылается html_text, у нетекстового сообщения он пуст
        await message.answer("Вы сейчас пишете обращение в поддержку. Пожалуйста, пришлите его текстом:")

    async def show_profile_without_keyboard(self, bot: Bot, shown_profile_id: str, current_message: types.Message):
        user_profile_data = await self.user_service.get_user_profile_data(int(shown_profile_id))

        if not user_profile_data:
            # Анкета неполная (например, нет описания) — показывать нечего
            logger.warning(f"Профиль {shown_profile_id} пропущен: нет полных данных.")
            await current_message.answer("Не удалось получить информацию о профиле.")
            return

        media_group_photos = await self.user_service.get_user_media_group(int(shown_profile_id))
        await safe_send_media_group(bot, current_message.chat.id, media_group_photos)

        contact = f"@{escape(user_profile_data.tg_username)}" if user_profile_data.tg_username \
            else "скрыто"

        lines = [f"Имя: {escape(user_profile_data.name)}",
                 f"Роль: {escape(user_profile_data.role)}",
                 f"Город: {escape(user_profile_data.city)}"]
        lines += _optional_profile_lines(user_profile_data)
        lines += ['', f"О себе:\n {escape(user_profile_data.description)}",
                  '', f"Имя пользователя: {contact}"]

        await current_message.answer("\n".join(lines))

    async def show_mutual_liked(self, message: types.Message):
        tg_chat_id = message.chat.id

        mutual_likes_ids = await self.matching_service.get_mutual_likes(tg_chat_id)

        if not mutual_likes_ids:
            await message.answer("У вас пока нет взаимных лайков.")
            return

        await message.answer("Ваши взаимные лайки:")

        for liked_cid in mutual_likes_ids:
            await self.show_profile_without_keyboard(message.bot, liked_cid, message)

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        # not_command нужен, чтобы команды не съедались хендлером состояния,
        # а доходили до командных хендлеров — иначе "/show_mutual_likes" во время
        # ввода обращения уехал бы админам как текст обращения (support_send
        # зарегистрирован раньше show_mutual_liked в этом же роутере).
        # Fallback ловит только нетекстовые сообщения и регистрируется после основного:
        # в aiogram 3 порядок регистрации задаёт приоритет
        not_command = ~F.text.startswith("/")

        self.router.message.register(self.start_func, Command("start"))
        self.router.message.register(self.help_func, Command("help"))
        self.router.message.register(self.show_profile_func, Command("show_my_profile"), is_registered_filter)
        self.router.message.register(self.change_profile_command, Command("change_my_profile"), is_registered_filter)
        self.router.message.register(self.support_create, Command("support"), is_registered_filter)
        self.router.message.register(self.support_send, StateFilter(CommandsStates.support_message), F.text,
                                     not_command)
        self.router.message.register(self.support_send_invalid, StateFilter(CommandsStates.support_message),
                                     not_command)
        self.router.message.register(self.show_mutual_liked, Command("show_mutual_likes"), is_registered_filter)
        return self.router