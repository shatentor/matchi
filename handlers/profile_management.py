import logging
from aiogram import Dispatcher, types, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from typing import Tuple, Optional
from services.user_service import UserService
from keyboards.inline import gender_keyboard, preferred_gender_keyboard, city_keyboard, photo_management_keyboard
from utils.cities_functions import full_coincidence, get_relevant_cities
from models.user import User
from filters.custom_filters import IsRegistered
from aiogram.types import InputMediaPhoto

logger = logging.getLogger(__name__)


class ChangeProfileStates(StatesGroup):
    name_changing = State()
    age_changing = State()
    city_changing = State()
    city_mistake = State()
    gender_changing = State()
    description_changing = State()
    photo_selection = State()
    photo_changing = State()
    preferred_gender_changing = State()
    preferred_age_lower = State()
    preferred_age_upper = State()


class ProfileManagementHandlers:
    def __init__(self, user_service: UserService):
        self.user_service = user_service
        self.router = Router()

    async def change_name_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Введите новое имя:")
        await state.set_state(ChangeProfileStates.name_changing) # ИСПРАВЛЕНО
        await call.answer()

    async def new_name_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        if len(message.text) > 30:
            await message.answer("Слишком длинное имя. Попробуйте еще раз:")
            return await state.set_state(ChangeProfileStates.name_changing) # ИСПРАВЛЕНО

        await self.user_service.update_user_profile_field(tg_chat_id, "name", message.text)
        await message.answer("Имя успешно изменено.")
        await state.clear()

    async def change_age_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Введите ваш возраст:")
        await state.set_state(ChangeProfileStates.age_changing) # ИСПРАВЛЕНО
        await call.answer()

    async def new_age_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        try:
            age = int(message.text)
            if 10 < age < 100:
                await self.user_service.update_user_profile_field(tg_chat_id, "age", age)
                await message.answer("Возраст успешно изменен.")
                await state.clear()
            else:
                await message.answer("Укажите ваш возраст (от 10 до 100):")
                await state.set_state(ChangeProfileStates.age_changing) # ИСПРАВЛЕНО
        except ValueError:
            await message.answer("Пожалуйста, введите целое число.\nПопробуйте еще раз:")
            await state.set_state(ChangeProfileStates.age_changing) # ИСПРАВЛЕНО

    async def change_city_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Введите новый город:")
        await state.set_state(ChangeProfileStates.city_changing) # ИСПРАВЛЕНО
        await call.answer()

    async def new_city_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        user_input_city = message.text.strip()

        found_city = full_coincidence(user_input_city)

        if found_city:
            await self.user_service.update_user_profile_field(tg_chat_id, "city", found_city)
            await message.answer("Город успешно изменен.")
            await state.clear()
        else:
            relevant_cities = get_relevant_cities(user_input_city)
            if relevant_cities:
                await message.answer('Возможно, вы имели в виду:', reply_markup=city_keyboard(relevant_cities))
                await state.set_state(ChangeProfileStates.city_mistake) # ИСПРАВЛЕНО
            else:
                await message.answer("В нашем боте нет города с таким названием! Попробуйте еще раз:")
                await state.set_state(ChangeProfileStates.city_changing) # ИСПРАВЛЕНО

    async def city_mistake_button(self, call: types.CallbackQuery, state: FSMContext):
        message = call.message
        tg_chat_id = call.from_user.id
        if call.data == "city_no":
            await message.answer("Попробуйте ввести ваш город еще раз:")
            await state.set_state(ChangeProfileStates.city_changing) # ИСПРАВЛЕНО
        else:
            city_from_keyboard = call.data.replace("city_", "")
            await self.user_service.update_user_profile_field(tg_chat_id, "city", city_from_keyboard)
            await message.answer("Город успешно изменен.")
            await state.clear()
        await call.answer()

    async def change_gender_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Выберите ваш пол:", reply_markup=gender_keyboard())
        await state.set_state(ChangeProfileStates.gender_changing) # ИСПРАВЛЕНО
        await call.answer()

    async def new_gender_to_db(self, call: types.CallbackQuery, state: FSMContext):
        tg_chat_id = call.from_user.id
        gender = call.data
        await self.user_service.update_user_profile_field(tg_chat_id, "gender", gender)
        await call.message.answer("Пол успешно изменен.")
        await state.clear()
        await call.answer()

    async def change_description_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Введите новое описание профиля:")
        await state.set_state(ChangeProfileStates.description_changing) # ИСПРАВЛЕНО
        await call.answer()

    async def new_description_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        if len(message.text) > 1000:
            await message.answer("Лимит превышен.\nПопробуйте еще раз:")
            return await state.set_state(ChangeProfileStates.description_changing) # ИСПРАВЛЕНО

        await self.user_service.update_user_profile_field(tg_chat_id, "description", message.text)
        await message.answer("Описание успешно изменено.")
        await state.clear()

    async def change_photo_button(self, call: types.CallbackQuery, state: FSMContext):
        tg_chat_id = call.from_user.id
        message = call.message
        user = await self.user_service.get_user_by_id(tg_chat_id)
        if not user:
            await message.answer("Ошибка: пользователь не найден.")
            await call.answer()
            return

        media_group_photos = await self.user_service.get_user_media_group(tg_chat_id)
        if media_group_photos:
            await message.answer_media_group(media=media_group_photos)
        else:
            await message.answer("У вас пока нет фотографий в профиле.")

        await message.answer("Управление фотографиями:", reply_markup=photo_management_keyboard(user))
        await state.set_state(ChangeProfileStates.photo_selection) # ИСПРАВЛЕНО
        await call.answer()

    async def photo_selected_action(self, call: types.CallbackQuery, state: FSMContext):
        tg_chat_id = call.from_user.id
        message = call.message

        request_from_user = call.data
        await state.update_data(request_from_user=request_from_user)

        if request_from_user.startswith("add_photo") or request_from_user.startswith("change_photo"):
            await message.answer("Отправьте фото:")
            await state.set_state(ChangeProfileStates.photo_changing) # ИСПРАВЛЕНО
        elif request_from_user == "delete_photo_one":
            await self.user_service.update_user_profile_field(tg_chat_id, "photo_link", None)
            await message.answer("Фото 1 удалено.")
            await state.clear()
        elif request_from_user == "delete_photo_two":
            await self.user_service.update_user_profile_field(tg_chat_id, "photo_link_two", None)
            await message.answer("Фото 2 удалено.")
            await state.clear()
        elif request_from_user == "delete_photo_three":
            await self.user_service.update_user_profile_field(tg_chat_id, "photo_link_three", None)
            await message.answer("Фото 3 удалено.")
            await state.clear()
        else:
            await message.answer("Неизвестное действие. Пожалуйста, попробуйте еще раз.")
            await state.clear()
        await call.answer()

    async def new_photo_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        if not message.photo:
            await message.answer("Пожалуйста, отправьте фотографию.")
            return

        file_id = message.photo[-1].file_id
        data = await state.get_data()
        request_from_user = data.get('request_from_user')

        field_map = {
            "change_photo_one": "photo_link",
            "change_photo_two": "photo_link_two",
            "change_photo_three": "photo_link_three",
            "add_photo_one": "photo_link",
            "add_photo_two": "photo_link_two",
            "add_photo_three": "photo_link_three",
        }
        field_to_update = field_map.get(request_from_user)

        if field_to_update:
            await self.user_service.update_user_profile_field(tg_chat_id, field_to_update, file_id)
            if request_from_user.startswith('change'):
                await message.answer("Фото успешно изменено.")
            else:
                await message.answer("Фото успешно добавлено.")
        else:
            await message.answer("Произошла ошибка при обновлении фото. Пожалуйста, попробуйте еще раз.")

        await state.clear()

    async def change_preferred_gender_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Выберите предпочитаемый пол:", reply_markup=preferred_gender_keyboard())
        await state.set_state(ChangeProfileStates.preferred_gender_changing) # ИСПРАВЛЕНО
        await call.answer()

    async def new_preferred_gender_to_db(self, call: types.CallbackQuery, state: FSMContext):
        tg_chat_id = call.from_user.id
        preferred_gender = call.data
        await self.user_service.update_user_profile_field(tg_chat_id, "preferred_gender", preferred_gender)
        await call.message.answer("Предпочитаемый пол успешно изменен.")
        await state.clear()
        await call.answer()

    async def change_preferred_age_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Введите нижний предел вашего предпочитаемого возраста:")
        await state.set_state(ChangeProfileStates.preferred_age_lower) # ИСПРАВЛЕНО
        await call.answer()

    async def lower_age_point_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        try:
            lower_point = int(message.text)
            if 10 < lower_point < 100:
                await self.user_service.update_user_profile_field(tg_chat_id, "age_lower_point", lower_point)
                await message.answer("Введите верхний предел вашего предпочитаемого возраста:")
                await state.set_state(ChangeProfileStates.preferred_age_upper) # ИСПРАВЛЕНО
            else:
                await message.answer("Введите число от 10 до 100:")
                await state.set_state(ChangeProfileStates.preferred_age_lower) # ИСПРАВЛЕНО
        except ValueError:
            await message.answer("Пожалуйста, введите целое число.\nПопробуйте еще раз:")
            await state.set_state(ChangeProfileStates.preferred_age_lower) # ИСПРАВЛЕНО

    async def high_age_point_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        user = await self.user_service.get_user_by_id(tg_chat_id)
        lower_age_point = user.age_lower_point if user else None

        if lower_age_point is None:
            await message.answer("Произошла ошибка при получении нижнего предела возраста. Попробуйте начать сначала.")
            await state.clear()
            return

        try:
            high_point = int(message.text)
            if 10 < high_point < 100 and high_point >= lower_age_point:
                await self.user_service.update_user_profile_field(tg_chat_id, "age_high_point", high_point)
                await message.answer("Предпочитаемый возраст успешно изменен.")
                await state.clear()
            else:
                await message.answer(f"Введите число от 10 до 100 и больше или равное {lower_age_point}:")
                await state.set_state(ChangeProfileStates.preferred_age_upper) # ИСПРАВЛЕНО
        except ValueError:
            await message.answer("Пожалуйста, введите целое число.\nПопробуйте еще раз:")
            await state.set_state(ChangeProfileStates.preferred_age_upper) # ИСПРАВЛЕНО

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        self.router.callback_query.register(self.change_name_button, F.data == "change_name",
                                            is_registered_filter)  # Убрал state="*"
        self.router.message.register(self.new_name_to_db, StateFilter(ChangeProfileStates.name_changing), F.text)

        self.router.callback_query.register(self.change_age_button, F.data == "change_age",
                                            is_registered_filter)  # Убрал state="*"
        self.router.message.register(self.new_age_to_db, StateFilter(ChangeProfileStates.age_changing), F.text)

        self.router.callback_query.register(self.change_city_button, F.data == "change_city",
                                            is_registered_filter)  # Убрал state="*"
        self.router.message.register(self.new_city_to_db, StateFilter(ChangeProfileStates.city_changing), F.text)
        self.router.callback_query.register(self.city_mistake_button, F.data.startswith("city_"),
                                            StateFilter(ChangeProfileStates.city_mistake))

        self.router.callback_query.register(self.change_gender_button, F.data == "change_gender",
                                            is_registered_filter)  # Убрал state="*"
        self.router.callback_query.register(self.new_gender_to_db, F.data.in_({'Male', 'Female', 'Other'}),
                                            StateFilter(ChangeProfileStates.gender_changing))

        self.router.callback_query.register(self.change_description_button, F.data == "change_description",
                                            is_registered_filter)  # Убрал state="*"
        self.router.message.register(self.new_description_to_db, StateFilter(ChangeProfileStates.description_changing),
                                     F.text)

        self.router.callback_query.register(self.change_photo_button, F.data == "change_photo",
                                            is_registered_filter)  # Убрал state="*"
        self.router.callback_query.register(self.photo_selected_action,
                                            F.data.startswith("change_photo") | F.data.startswith(
                                                "delete_photo") | F.data.startswith("add_photo"),
                                            StateFilter(ChangeProfileStates.photo_selection))
        self.router.message.register(self.new_photo_to_db, StateFilter(ChangeProfileStates.photo_changing), F.photo)

        self.router.callback_query.register(self.change_preferred_gender_button, F.data == 'change_preferred_gender',
                                            is_registered_filter)  # Убрал state="*"
        self.router.callback_query.register(self.new_preferred_gender_to_db, F.data.in_({'Male', 'Female', 'Any'}),
                                            StateFilter(ChangeProfileStates.preferred_gender_changing))

        self.router.callback_query.register(self.change_preferred_age_button, F.data == "change_preferred_age",
                                            is_registered_filter)  # Убрал state="*"
        self.router.message.register(self.lower_age_point_to_db, StateFilter(ChangeProfileStates.preferred_age_lower),
                                     F.text)
        self.router.message.register(self.high_age_point_to_db, StateFilter(ChangeProfileStates.preferred_age_upper),
                                     F.text)
        return self.router