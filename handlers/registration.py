import logging
from aiogram import Dispatcher, types, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter

from services.user_service import UserService
from keyboards.inline import start_keyboard, gender_keyboard, preferred_gender_keyboard, city_keyboard, \
    start_show_profiles
from utils.cities_functions import full_coincidence, get_relevant_cities
from filters.custom_filters import IsRegistered  # Этот импорт все еще нужен для `main.py`

logger = logging.getLogger(__name__)


class Register(StatesGroup):
    name = State()
    city = State()
    city_to_db = State()
    age = State()
    gender = State()
    description = State()
    preferred_gender = State()
    preferred_age_lower = State()
    preferred_age_upper = State()
    photo = State()


class RegistrationHandlers:
    def __init__(self, user_service: UserService):
        self.user_service = user_service
        self.router = Router()

    async def start_registration_callback(self, call: types.CallbackQuery, state: FSMContext):
        message = call.message
        tg_chat_id = call.from_user.id
        username = call.from_user.username

        # ГАРАНТИРУЕМ СОЗДАНИЕ ИЛИ ПОЛУЧЕНИЕ ПОЛЬЗОВАТЕЛЯ ПЕРЕД ВСЕМ ОСТАЛЬНЫМ
        user = await self.user_service.get_or_create_user(tg_chat_id, username)

        if user.is_registered == "yes":
            await message.answer('Вы уже зарегистрированы.')
            await state.clear()
            return
        elif user.is_registered == "in_progress":
            await message.answer("Пожалуйста, завершите регистрацию.")
            await message.answer('Начнем регистрацию заново. Как вас зовут?')
            await state.set_state(Register.name)
        else:  # user.is_registered == "no"
            await message.answer('Как вас зовут?')
            await state.set_state(Register.name)
            # Обновляем статус в объекте user и сохраняем его
            user.is_registered = "in_progress"
            await self.user_service.user_repo.update(user)  # Используем user_repo для обновления
        await call.answer()

    async def process_name(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        if len(message.text) > 30:
            await message.answer("Слишком длинное имя. Попробуйте еще раз:")
            return
        # Здесь user_service.update_user_profile_field() уже найдет пользователя,
        # так как он был создан в start_registration_callback
        await self.user_service.update_user_profile_field(tg_chat_id, "name", message.text)
        await message.answer('Введите ваш город:')
        await state.set_state(Register.city)

    async def process_city(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        user_input_city = message.text.strip()

        found_city = full_coincidence(user_input_city)

        if found_city:
            await self.user_service.update_user_profile_field(tg_chat_id, "city", found_city)
            await message.answer("Сколько вам лет?")
            await state.set_state(Register.age)
        else:
            relevant_cities = get_relevant_cities(user_input_city)
            if relevant_cities:
                await message.answer('Возможно, вы имели в виду:', reply_markup=city_keyboard(relevant_cities))
                await state.set_state(Register.city_to_db)
            else:
                await message.answer("В нашем боте нет города с таким названием! Попробуйте еще раз:")
                await state.set_state(Register.city)

    async def process_city_from_keyboard(self, call: types.CallbackQuery, state: FSMContext):
        message = call.message
        tg_chat_id = call.from_user.id

        if call.data == "city_no":
            await message.answer("Попробуйте ввести ваш город еще раз:")
            await state.set_state(Register.city)
        else:
            city_from_keyboard = call.data.replace("city_", "")
            await self.user_service.update_user_profile_field(tg_chat_id, "city", city_from_keyboard)
            await message.answer("Сколько вам лет?")
            await state.set_state(Register.age)
        await call.answer()

    async def process_age(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        try:
            age = int(message.text)
            if 10 < age < 100:
                await self.user_service.update_user_profile_field(tg_chat_id, "age", age)
                await message.answer('Выберите ваш пол:', reply_markup=gender_keyboard())
                await state.set_state(Register.gender)
            else:
                await message.answer("Укажите ваш возраст (от 10 до 100):")
                await state.set_state(Register.age)
        except ValueError:
            await message.answer("Ошибка: попробуйте ввести целое число.")
            await state.set_state(Register.age)

    async def process_gender(self, call: types.CallbackQuery, state: FSMContext):
        message = call.message
        tg_chat_id = call.from_user.id
        gender = call.data
        await self.user_service.update_user_profile_field(tg_chat_id, "gender", gender)

        await message.answer("Напишите описание вашего профиля (Лимит - 1000 символов):")
        await state.set_state(Register.description)
        await call.answer()

    async def process_description(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        if len(message.text) > 1000:
            await message.answer("Лимит превышен.\nПопробуйте еще раз:")
            return await state.set_state(Register.description)

        await self.user_service.update_user_profile_field(tg_chat_id, "description", message.text)
        await message.answer("Выберите предпочитаемый пол:", reply_markup=preferred_gender_keyboard())
        await state.set_state(Register.preferred_gender)

    async def process_preferred_gender(self, call: types.CallbackQuery, state: FSMContext):
        message = call.message
        tg_chat_id = call.from_user.id
        preferred_gender = call.data
        await self.user_service.update_user_profile_field(tg_chat_id, "preferred_gender", preferred_gender)
        await message.answer("Пожалуйста, укажите нижний предел предпочитаемого возраста:")
        await state.set_state(Register.preferred_age_lower)
        await call.answer()

    async def process_preferred_age_lower(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        try:
            lower_point = int(message.text)
            if 10 < lower_point < 100:
                await self.user_service.update_user_profile_field(tg_chat_id, "age_lower_point", lower_point)
                await message.answer("Укажите верхний предел предпочитаемого возраста:")
                await state.set_state(Register.preferred_age_upper)
            else:
                await message.answer("Укажите число от 10 до 100:")
                await state.set_state(Register.preferred_age_lower)
        except ValueError:
            await message.answer("Пожалуйста, введите целое число.")
            await state.set_state(Register.preferred_age_lower)

    async def process_preferred_age_upper(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        user = await self.user_service.get_user_by_id(tg_chat_id)
        lower_point = user.age_lower_point if user else None

        if lower_point is None:
            await message.answer(
                "Произошла ошибка при получении нижнего предела возраста. Пожалуйста, попробуйте начать сначала.")
            await state.clear()
            return

        try:
            high_point = int(message.text)
            if 10 < high_point < 100 and high_point >= lower_point:
                await self.user_service.update_user_profile_field(tg_chat_id, "age_high_point", high_point)
                await message.answer("И последнее...")
                await message.answer("Отправьте до трех фотографий себя (в одном сообщении): ")
                await state.set_state(Register.photo)
            else:
                await message.answer(f"Укажите число от 10 до 100 и больше или равное {lower_point}:")
                await state.set_state(Register.preferred_age_upper)
        except ValueError:
            await message.answer("Пожалуйста, введите целое число:")
            await state.set_state(Register.preferred_age_upper)

    async def process_photo_upload(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        if not message.photo:
            await message.answer("Пожалуйста, отправьте фотографии.")
            return

        user = await self.user_service.get_user_by_id(tg_chat_id)
        current_photo_links = [user.photo_link, user.photo_link_two, user.photo_link_three]

        photos_to_process = []
        for photo_size in message.photo:
            photos_to_process.append(photo_size.file_id)

        slot_counter = 0
        for i, link in enumerate(current_photo_links):
            if link is None and slot_counter < len(photos_to_process):
                if i == 0:
                    await self.user_service.update_user_profile_field(tg_chat_id, "photo_link",
                                                                      photos_to_process[slot_counter])
                elif i == 1:
                    await self.user_service.update_user_profile_field(tg_chat_id, "photo_link_two",
                                                                      photos_to_process[slot_counter])
                elif i == 2:
                    await self.user_service.update_user_profile_field(tg_chat_id, "photo_link_three",
                                                                      photos_to_process[slot_counter])
                slot_counter += 1
            if slot_counter >= 3:
                break

        await message.answer("Спасибо!\nРегистрация завершена", reply_markup=start_show_profiles())
        await self.user_service.update_user_profile_field(tg_chat_id, "is_registered", "yes")
        await state.clear()

    def get_router(self, is_registered_filter: IsRegistered, is_not_registered_filter: IsRegistered,
                   is_in_progress_filter: IsRegistered) -> Router:
        self.router.callback_query.register(self.start_registration_callback, F.data == 'go')

        self.router.message.register(self.process_name, StateFilter(Register.name))
        self.router.message.register(self.process_city, StateFilter(Register.city))
        self.router.callback_query.register(self.process_city_from_keyboard, F.data.startswith("city_"),
                                            StateFilter(Register.city_to_db))
        self.router.message.register(self.process_age, StateFilter(Register.age))
        self.router.callback_query.register(self.process_gender, F.data.in_({'Male', 'Female', 'Other'}),
                                            StateFilter(Register.gender))
        self.router.message.register(self.process_description, StateFilter(Register.description))
        self.router.callback_query.register(self.process_preferred_gender, F.data.in_({'Male', 'Female', 'Any'}),
                                            StateFilter(Register.preferred_gender))
        self.router.message.register(self.process_preferred_age_lower, StateFilter(Register.preferred_age_lower))
        self.router.message.register(self.process_preferred_age_upper, StateFilter(Register.preferred_age_upper))
        self.router.message.register(self.process_photo_upload, F.photo, StateFilter(Register.photo))
        return self.router