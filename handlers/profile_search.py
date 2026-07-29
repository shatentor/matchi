import logging
from typing import Optional

from aiogram.fsm.context import FSMContext
from aiogram import types, Router, F, Bot
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter

from config.settings import settings
from services.user_service import UserService
from services.matching_service import MatchingService
from services.support_service import SupportService
from keyboards.dialogs import dialog_reply_keyboard
from keyboards.inline import searching_profiles_keyboard, yes_or_no_keyboard
from filters.custom_filters import IsRegistered, IsFeedbackForCurrentProfile
from utils.text import escape
from utils.telegram import safe_send_message, safe_send_media_group, safe_send_sticker

logger = logging.getLogger(__name__)


def _mention(username: Optional[str], tg_chat_id: int) -> str:
    """Готовит безопасное для HTML упоминание пользователя."""
    if username:
        return f"@{escape(username)}"
    return f"ID: {tg_chat_id}"


class ProfileSearchStates(StatesGroup):
    people_searching = State()
    end_of_profiles = State()
    message_to_profile = State()
    complain_about_profile = State()


class ProfileSearchHandlers:
    def __init__(self, user_service: UserService, matching_service: MatchingService, support_service: SupportService):
        self.user_service = user_service
        self.matching_service = matching_service
        self.support_service = support_service
        self.bot: Bot = None
        self.router = Router()

    def set_bot_instance(self, bot_instance: Bot):
        self.bot = bot_instance

    async def _show_profile(self, tg_chat_id: int, message: types.Message) -> bool:
        """Отображает профиль пользователя с кнопками взаимодействия.

        Возвращает True, если анкету удалось отрисовать, и False, если данных
        профиля нет — тогда вызывающий код решает, что делать дальше.
        """
        profile_data = await self.user_service.get_user_profile_data(tg_chat_id)
        if not profile_data:
            return False

        media_group_photos = await self.user_service.get_user_media_group(tg_chat_id)
        if media_group_photos:
            await message.answer_media_group(media=media_group_photos)
        else:
            await message.answer("Профиль без фотографий.")

        text = (f"Имя: <b>{escape(profile_data.name)}</b>\n"
                f"Возраст: {profile_data.age}\n"
                f"Город: {escape(profile_data.city)}\n\n"
                f"О себе:\n {escape(profile_data.description)}")

        await message.answer(text, reply_markup=searching_profiles_keyboard(str(tg_chat_id)))
        return True

    async def _get_next_profile_and_show(self, message: types.Message, state: FSMContext, current_user_id: int):
        """Показывает первого кандидата, чью анкету удалось отрисовать."""
        profile_ids = await self.matching_service.get_profiles_for_user(current_user_id)

        for profile_id in profile_ids:
            if await self._show_profile(int(profile_id), message):
                await self.user_service.update_user_profile_field(current_user_id, "last_shown_profile", profile_id)
                await state.update_data(shown_profile_id=profile_id)
                await state.set_state(ProfileSearchStates.people_searching)
                return
            # Анкета неполная (например, пропало описание) — пропускаем её, а не упираемся в тупик
            logger.warning(f"Пропущена анкета {profile_id}: не удалось получить данные профиля.")

        await message.answer("Профили закончились. Заходите завтра!")
        await state.clear()

    async def start_searching_profiles(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        user_status = await self.user_service.get_registration_status(tg_chat_id)

        if user_status != "yes":
            await message.answer("Вы еще не зарегистрированы или не завершили регистрацию.")
            return

        await self._get_next_profile_and_show(message, state, tg_chat_id)

    async def start_searching_profiles_callback(self, call: types.CallbackQuery, state: FSMContext):
        await self.start_searching_profiles(call.message, state)
        await call.answer()

    async def process_feedback(self, call: types.CallbackQuery, state: FSMContext):
        current_user_id = call.from_user.id
        message = call.message
        data = await state.get_data()
        shown_profile_id = data.get("shown_profile_id")

        if not shown_profile_id:
            await message.answer("Произошла ошибка, ID профиля не найден. Пожалуйста, попробуйте еще раз.")
            await state.clear()
            await call.answer()
            return

        if call.data.startswith("like"):
            success, is_mutual, sticker_id = await self.matching_service.process_like(current_user_id,
                                                                                      int(shown_profile_id))
            if success:
                await message.answer("Вы лайкнули этот профиль! 👍")
                if is_mutual:
                    profile_data_liked = await self.user_service.get_user_profile_data(int(shown_profile_id))
                    current_user_data = await self.user_service.get_user_profile_data(current_user_id)

                    if profile_data_liked and current_user_data:
                        liked_mention = _mention(profile_data_liked.tg_username, int(shown_profile_id))
                        await message.answer(f"У вас взаимный лайк с этим пользователем!\n"
                                             f"Вот его имя пользователя: <b>{liked_mention}</b>")

                        if self.bot:
                            # Партнёр мог заблокировать бота — это не должно ломать сценарий инициатора
                            current_mention = _mention(current_user_data.tg_username, current_user_id)
                            notified = await safe_send_message(
                                self.bot,
                                int(shown_profile_id),
                                f"У вас взаимный лайк с пользователем:\n<b>{current_mention}</b>!"
                            )
                            if notified:
                                media_group_current = await self.user_service.get_user_media_group(current_user_id)
                                if media_group_current:
                                    await safe_send_media_group(self.bot, int(shown_profile_id), media_group_current)

                if sticker_id and self.bot:
                    await safe_send_sticker(self.bot, current_user_id, sticker_id)
            else:
                await message.answer("Вы уже лайкнули этого пользователя.")

        elif call.data.startswith("dislike"):
            success = await self.matching_service.process_dislike(current_user_id, int(shown_profile_id))
            if success:
                await message.answer("Вы дизлайкнули этот профиль. 👎")
            else:
                await message.answer("Вы уже дизлайкнули этого пользователя.")

        await call.answer()
        await self._get_next_profile_and_show(message, state, current_user_id)

    async def message_or_complain_prompt(self, call: types.CallbackQuery, state: FSMContext):
        message = call.message
        data = await state.get_data()
        shown_profile_id = data.get("shown_profile_id")

        if not shown_profile_id:
            await message.answer("Произошла ошибка, ID профиля не найден. Пожалуйста, попробуйте еще раз.")
            await state.clear()
            await call.answer()
            return

        profile_data = await self.user_service.get_user_profile_data(int(shown_profile_id))
        target_name = escape(profile_data.name) if profile_data else "пользователю"

        if call.data.startswith('message'):
            await message.answer(f"Напишите сообщение для {target_name}:")
            await state.set_state(ProfileSearchStates.message_to_profile)
        elif call.data.startswith("complain"):
            await message.answer(f"Опишите проблему с профилем {target_name}:")
            await state.set_state(ProfileSearchStates.complain_about_profile)
        await call.answer()

    async def send_message_to_profile(self, message: types.Message, state: FSMContext):
        sender_id = message.chat.id
        data = await state.get_data()
        receiver_id = data.get("shown_profile_id")

        if not receiver_id:
            await message.answer("Произошла ошибка, ID профиля не найден. Пожалуйста, попробуйте еще раз.")
            await state.clear()
            return

        # Пустой текст (например, одни пробелы) отправлять некуда — просим повторить, состояние сохраняем
        if not (message.text or "").strip():
            await message.answer("Сообщение не может быть пустым. Напишите текст сообщения:")
            return

        # В БД сохраняем plain-текст, а получателю отправляем html_text с сохранением форматирования
        await self.support_service.send_user_message(sender_id, int(receiver_id), message.text)

        if not self.bot:
            logger.error("Экземпляр бота не установлен, сообщение не доставлено.")
            await message.answer("Не удалось доставить сообщение. Попробуйте позже.")
            await state.clear()
            return

        sender_user = await self.user_service.get_user_by_id(sender_id)
        sender_mention = _mention(sender_user.tg_username if sender_user else None, sender_id)
        receiver_chat_id = int(receiver_id)

        # «Ответить» открывает диалог с отправителем сразу, без захода в его
        # профиль и повторного нажатия «Message 💌»
        delivered = await safe_send_message(self.bot, receiver_chat_id,
                                           "Вы получили сообщение:\n"
                                           f"От <b>{sender_mention}</b>:\n"
                                           f"{message.html_text}",
                                           reply_markup=dialog_reply_keyboard(sender_id))

        if delivered:
            await message.answer("Сообщение отправлено!")
            await safe_send_message(self.bot, receiver_chat_id,
                                    "Хотите посмотреть профиль этого пользователя?",
                                    reply_markup=yes_or_no_keyboard(str(sender_id)))
        else:
            await message.answer("Не удалось доставить сообщение: пользователь недоступен для бота.")

        await state.clear()

    async def send_message_to_profile_invalid(self, message: types.Message, state: FSMContext):
        # Переслать можно только текст: html_text у нетекстового сообщения пуст
        await message.answer("Вы сейчас пишете сообщение пользователю. Пожалуйста, пришлите его текстом:")

    async def handle_complain_submission(self, message: types.Message, state: FSMContext):
        reporter_id = message.chat.id
        data = await state.get_data()
        reported_id = data.get("shown_profile_id")

        if not reported_id:
            await message.answer("Произошла ошибка, ID профиля не найден. Пожалуйста, попробуйте еще раз.")
            await state.clear()
            return

        if not (message.text or "").strip():
            await message.answer("Причина жалобы не может быть пустой. Опишите проблему:")
            return

        complain = await self.support_service.create_user_complain(reporter_id, int(reported_id), message.text)

        reporter_user = await self.user_service.get_user_by_id(reporter_id)
        reported_user = await self.user_service.get_user_by_id(int(reported_id))

        reporter_mention = _mention(reporter_user.tg_username if reporter_user else None, reporter_id)
        reported_mention = _mention(reported_user.tg_username if reported_user else None, int(reported_id))

        if self.bot:
            for admin_id in settings.ADMIN_IDS:
                await safe_send_message(self.bot, admin_id,
                                        f"Жалоба от <b>{reporter_mention}</b> ({reporter_id}) "
                                        f"на <b>{reported_mention}</b> ({reported_id}):\n"
                                        f"Причина: {escape(message.text)}\n"
                                        f"ID жалобы: {complain.id}")
        else:
            logger.error("Экземпляр бота не установлен, жалоба не разослана админам.")

        await message.answer("Ваша жалоба отправлена администратору и будет рассмотрена.")
        await state.clear()

    async def handle_complain_invalid(self, message: types.Message, state: FSMContext):
        # Причина жалобы должна быть текстом, иначе админам уйдёт пустое сообщение
        await message.answer("Вы сейчас описываете жалобу. Пожалуйста, опишите проблему текстом:")

    async def handle_yes_or_no_callback(self, call: types.CallbackQuery, state: FSMContext):
        current_user_id = call.from_user.id
        message = call.message
        callback_data = call.data or ""

        # Явно отрезаем префикс и проверяем ID, чтобы не падать на int() от мусора
        is_yes = callback_data.startswith("yes")
        profile_to_view_id = callback_data.removeprefix("yes") if is_yes else callback_data.removeprefix("no")

        if not profile_to_view_id.isdigit():
            logger.warning(f"Некорректный callback_data в yes/no: {callback_data!r}")
            await call.answer("Некорректные данные кнопки, попробуйте еще раз.", show_alert=True)
            return

        if is_yes:
            if not await self._show_profile(int(profile_to_view_id), message):
                await message.answer("Не удалось получить информацию о профиле.")
                await call.answer()
                return

            await self.user_service.update_user_profile_field(current_user_id, "last_shown_profile", profile_to_view_id)
            await state.update_data(shown_profile_id=profile_to_view_id)
            await state.set_state(ProfileSearchStates.people_searching)
        else:
            await message.answer("Хорошо.")
            await state.clear()
        await call.answer()

    def get_router(self, is_registered_filter: IsRegistered, is_feedback_for_current_profile_filter: IsFeedbackForCurrentProfile) -> Router:
        # not_command нужен, чтобы команды не съедались хендлерами состояний,
        # а доходили до роутеров ниже по цепочке (/admin, /complains) — иначе
        # "/admin" ушёл бы текстом в сообщение другому пользователю или в жалобу.
        # Fallback-хендлеры ловят только нетекстовые сообщения и регистрируются
        # после основных: в aiogram 3 порядок регистрации задаёт приоритет
        not_command = ~F.text.startswith("/")

        self.router.message.register(self.start_searching_profiles, Command("searchi"), is_registered_filter)
        self.router.callback_query.register(self.start_searching_profiles_callback, F.data == "searchi", is_registered_filter)

        self.router.callback_query.register(
            self.process_feedback,
            F.data.startswith("like") | F.data.startswith("dislike"),
            is_registered_filter,
            is_feedback_for_current_profile_filter,
            StateFilter(ProfileSearchStates.people_searching)
        )

        self.router.callback_query.register(
            self.message_or_complain_prompt,
            F.data.startswith("message") | F.data.startswith("complain"),
            is_registered_filter,
            StateFilter(ProfileSearchStates.people_searching)
        )

        self.router.message.register(self.send_message_to_profile, StateFilter(ProfileSearchStates.message_to_profile),
                                     F.text, not_command)
        self.router.message.register(self.send_message_to_profile_invalid,
                                     StateFilter(ProfileSearchStates.message_to_profile), not_command)
        self.router.message.register(self.handle_complain_submission,
                                     StateFilter(ProfileSearchStates.complain_about_profile), F.text, not_command)
        self.router.message.register(self.handle_complain_invalid,
                                     StateFilter(ProfileSearchStates.complain_about_profile), not_command)

        self.router.callback_query.register(self.handle_yes_or_no_callback, F.data.startswith("yes") | F.data.startswith("no"), is_registered_filter)
        return self.router
