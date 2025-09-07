import logging
import numpy as np
from aiogram.fsm.context import FSMContext
from aiogram import Dispatcher, types, Router, F, Bot
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from config import settings
from services.user_service import UserService
from services.matching_service import MatchingService
from services.support_service import SupportService
from keyboards.inline import searching_profiles_keyboard, yes_or_no_keyboard
from models.user import UserProfileData
from filters.custom_filters import IsRegistered, IsFeedbackForCurrentProfile
from aiogram.types import InputMediaPhoto

logger = logging.getLogger(__name__)


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

    async def _show_profile(self, tg_chat_id: int, message: types.Message):
        """Отображает профиль пользователя с кнопками взаимодействия."""
        profile_data = await self.user_service.get_user_profile_data(tg_chat_id)
        if not profile_data:
            await message.answer("Не удалось получить информацию о профиле.")
            return

        media_group_photos = await self.user_service.get_user_media_group(tg_chat_id)
        if media_group_photos:
            await message.answer_media_group(media=media_group_photos)
        else:
            await message.answer("Профиль без фотографий.")

        text = (f"Имя: {profile_data.name}\n"
                f"Возраст: {profile_data.age}\n"
                f"Город: {profile_data.city}\n\n"
                f"О себе:\n {profile_data.description}")

        await message.answer(text, reply_markup=searching_profiles_keyboard(str(tg_chat_id)))

    async def _get_next_profile_and_show(self, message: types.Message, state: FSMContext, current_user_id: int):
        """Вспомогательная функция для получения следующего профиля и его отображения."""
        profile_ids_np = await self.matching_service.get_profiles_for_user(current_user_id)
        profile_ids = profile_ids_np.tolist()

        if not profile_ids:
            await message.answer("Профили закончились. Заходите завтра!")
            await state.clear()
            return

        shown_profile_id = profile_ids[0]
        await self._show_profile(int(shown_profile_id), message)
        await self.user_service.update_user_profile_field(current_user_id, "last_shown_profile", shown_profile_id)
        await state.update_data(shown_profile_id=shown_profile_id)
        await state.set_state(ProfileSearchStates.people_searching) # ИСПРАВЛЕНО

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
                        await message.answer(f"У вас взаимный лайк с этим пользователем!\n"
                                             f"Вот его имя пользователя: @{profile_data_liked.tg_username}")

                        if self.bot:
                            await self.bot.send_message(int(shown_profile_id), f"У вас взаимный лайк с пользователем:\n"
                                                                               f"@{current_user_data.tg_username}!")
                            media_group_current = await self.user_service.get_user_media_group(current_user_id)
                            if media_group_current:
                                await self.bot.send_media_group(int(shown_profile_id), media_group_current)

                if sticker_id and self.bot:
                    await self.bot.send_sticker(current_user_id, sticker_id)
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
        tg_chat_id = call.from_user.id
        message = call.message
        data = await state.get_data()
        shown_profile_id = data.get("shown_profile_id")

        if not shown_profile_id:
            await message.answer("Произошла ошибка, ID профиля не найден. Пожалуйста, попробуйте еще раз.")
            await state.clear()
            await call.answer()
            return

        profile_data = await self.user_service.get_user_profile_data(int(shown_profile_id))
        target_name = profile_data.name if profile_data else "пользователю"

        if call.data.startswith('message'):
            await message.answer(f"Напишите сообщение для {target_name}:")
            await state.set_state(ProfileSearchStates.message_to_profile) # ИСПРАВЛЕНО
        elif call.data.startswith("complain"):
            await message.answer(f"Опишите проблему с профилем {target_name}:")
            await state.set_state(ProfileSearchStates.complain_about_profile) # ИСПРАВЛЕНО
        await call.answer()

    async def send_message_to_profile(self, message: types.Message, state: FSMContext):
        sender_id = message.chat.id
        data = await state.get_data()
        receiver_id = data.get("shown_profile_id")

        if not receiver_id:
            await message.answer("Произошла ошибка, ID профиля не найден. Пожалуйста, попробуйте еще раз.")
            await state.clear()
            return

        await self.support_service.send_user_message(sender_id, int(receiver_id), message.text)
        await message.answer("Сообщение отправлено!")

        if self.bot:
            sender_user = await self.user_service.get_user_by_id(sender_id)
            sender_username = sender_user.tg_username if sender_user else f"ID: {sender_id}"
            receiver_chat_id = int(receiver_id)

            await self.bot.send_message(receiver_chat_id, "Вы получили сообщение:\n"
                                                          f"От @{sender_username}:\n"
                                                          f"{message.text}")
            await self.bot.send_message(receiver_chat_id,
                                        "Хотите посмотреть профиль этого пользователя?",
                                        reply_markup=yes_or_no_keyboard(str(sender_id)))

        await state.clear()

    async def handle_complain_submission(self, message: types.Message, state: FSMContext):
        reporter_id = message.chat.id
        data = await state.get_data()
        reported_id = data.get("shown_profile_id")

        if not reported_id:
            await message.answer("Произошла ошибка, ID профиля не найден. Пожалуйста, попробуйте еще раз.")
            await state.clear()
            return

        complain = await self.support_service.create_user_complain(reporter_id, int(reported_id), message.text)

        admin_ids = settings.Settings.ADMIN_IDS
        reporter_user = await self.user_service.get_user_by_id(reporter_id)
        reported_user = await self.user_service.get_user_by_id(int(reported_id))

        reporter_username = reporter_user.tg_username if reporter_user else f"ID: {reporter_id}"
        reported_username = reported_user.tg_username if reported_user else f"ID: {reported_id}"


        for admin_id in admin_ids:
            try:
                if self.bot:
                    await self.bot.send_message(admin_id, f"Жалоба от @{reporter_username} ({reporter_id}) "
                                                          f"на @{reported_username} ({reported_id}):\n"
                                                          f"Причина: {message.text}\n"
                                                          f"ID жалобы: {complain.id}")
            except Exception as e:
                logger.error(f"Не удалось отправить жалобу админу {admin_id}: {e}")

        await message.answer("Ваша жалоба отправлена администратору и будет рассмотрена.")
        await state.clear()

    async def handle_yes_or_no_callback(self, call: types.CallbackQuery, state: FSMContext):
        current_user_id = call.from_user.id
        message = call.message

        if call.data.startswith('yes'):
            profile_to_view_id = call.data[3:]

            await self.user_service.update_user_profile_field(current_user_id, "last_shown_profile", profile_to_view_id)
            await state.update_data(shown_profile_id=profile_to_view_id)

            await self._show_profile(int(profile_to_view_id), message)
            await state.set_state(ProfileSearchStates.people_searching) # ИСПРАВЛЕНО
        else:
            await message.answer("Хорошо.")
            await state.clear()
        await call.answer()

    def get_router(self, is_registered_filter: IsRegistered, is_feedback_for_current_profile_filter: IsFeedbackForCurrentProfile) -> Router:
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

        self.router.message.register(self.send_message_to_profile, StateFilter(ProfileSearchStates.message_to_profile), F.text)
        self.router.message.register(self.handle_complain_submission, StateFilter(ProfileSearchStates.complain_about_profile), F.text)

        self.router.callback_query.register(self.handle_yes_or_no_callback, F.data.startswith("yes") | F.data.startswith("no"), is_registered_filter)
        return self.router