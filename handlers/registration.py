import logging
from aiogram import Dispatcher, types, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter

from config.settings import settings
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
    # Поля профиля, в которые складываются фотографии (по порядку слотов)
    PHOTO_FIELDS = ("photo_link", "photo_link_two", "photo_link_three")

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
        if len(message.text) > settings.MAX_NAME_LENGTH:
            await message.answer(
                f"Слишком длинное имя (лимит - {settings.MAX_NAME_LENGTH} символов). Попробуйте еще раз:")
            return
        # Здесь user_service.update_user_profile_field() уже найдет пользователя,
        # так как он был создан в start_registration_callback
        await self.user_service.update_user_profile_field(tg_chat_id, "name", message.text)
        await message.answer('Введите ваш город:')
        await state.set_state(Register.city)

    async def process_name_invalid(self, message: types.Message, state: FSMContext):
        # Пользователь прислал не текст (стикер, фото и т.п.) — просим текст
        await message.answer("Пожалуйста, напишите ваше имя текстом:")

    async def _handle_city_input(self, message: types.Message, state: FSMContext):
        # Общая логика разбора введенного города: используется и на шаге ввода,
        # и когда пользователь вместо кнопки с подсказкой пишет город заново
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

    async def process_city(self, message: types.Message, state: FSMContext):
        await self._handle_city_input(message, state)

    async def process_city_invalid(self, message: types.Message, state: FSMContext):
        # Название города должно быть текстом, иначе .strip() упадет на None
        await message.answer("Пожалуйста, напишите название вашего города текстом:")

    async def process_city_to_db_text(self, message: types.Message, state: FSMContext):
        # Пользователь не нажал кнопку с подсказкой, а написал город заново —
        # обрабатываем это как новую попытку ввода
        await self._handle_city_input(message, state)

    async def process_city_to_db_invalid(self, message: types.Message, state: FSMContext):
        await message.answer("Выберите город из списка выше или напишите его название текстом:")

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
            if settings.MIN_AGE <= age <= settings.MAX_AGE:
                await self.user_service.update_user_profile_field(tg_chat_id, "age", age)
                await message.answer('Выберите ваш пол:', reply_markup=gender_keyboard())
                await state.set_state(Register.gender)
            else:
                await message.answer(f"Укажите ваш возраст (от {settings.MIN_AGE} до {settings.MAX_AGE}):")
                await state.set_state(Register.age)
        except ValueError:
            await message.answer("Ошибка: попробуйте ввести целое число.")
            await state.set_state(Register.age)

    async def process_age_invalid(self, message: types.Message, state: FSMContext):
        # Нетекстовое сообщение: int(None) дал бы TypeError, который не ловится выше
        await message.answer(f"Пожалуйста, напишите ваш возраст числом "
                             f"(от {settings.MIN_AGE} до {settings.MAX_AGE}):")

    async def process_gender(self, call: types.CallbackQuery, state: FSMContext):
        message = call.message
        tg_chat_id = call.from_user.id
        gender = call.data
        await self.user_service.update_user_profile_field(tg_chat_id, "gender", gender)

        await message.answer(
            f"Напишите описание вашего профиля (Лимит - {settings.MAX_DESCRIPTION_LENGTH} символов):")
        await state.set_state(Register.description)
        await call.answer()

    async def process_gender_invalid(self, message: types.Message, state: FSMContext):
        # На этом шаге ждем нажатие инлайн-кнопки, а не текст
        await message.answer('Пожалуйста, выберите ваш пол кнопкой ниже:', reply_markup=gender_keyboard())

    async def process_description(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        if len(message.text) > settings.MAX_DESCRIPTION_LENGTH:
            await message.answer(
                f"Лимит превышен (максимум {settings.MAX_DESCRIPTION_LENGTH} символов).\nПопробуйте еще раз:")
            return await state.set_state(Register.description)

        await self.user_service.update_user_profile_field(tg_chat_id, "description", message.text)
        await message.answer("Выберите предпочитаемый пол:", reply_markup=preferred_gender_keyboard())
        await state.set_state(Register.preferred_gender)

    async def process_description_invalid(self, message: types.Message, state: FSMContext):
        # Описание должно быть текстом, иначе len(None) упадет
        await message.answer(
            f"Пожалуйста, пришлите описание текстом (Лимит - {settings.MAX_DESCRIPTION_LENGTH} символов):")

    async def process_preferred_gender(self, call: types.CallbackQuery, state: FSMContext):
        message = call.message
        tg_chat_id = call.from_user.id
        preferred_gender = call.data
        await self.user_service.update_user_profile_field(tg_chat_id, "preferred_gender", preferred_gender)
        await message.answer("Пожалуйста, укажите нижний предел предпочитаемого возраста:")
        await state.set_state(Register.preferred_age_lower)
        await call.answer()

    async def process_preferred_gender_invalid(self, message: types.Message, state: FSMContext):
        # На этом шаге ждем нажатие инлайн-кнопки, а не текст
        await message.answer("Пожалуйста, выберите предпочитаемый пол кнопкой ниже:",
                             reply_markup=preferred_gender_keyboard())

    async def process_preferred_age_lower(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        try:
            lower_point = int(message.text)
            if settings.MIN_AGE <= lower_point <= settings.MAX_AGE:
                await self.user_service.update_user_profile_field(tg_chat_id, "age_lower_point", lower_point)
                await message.answer("Укажите верхний предел предпочитаемого возраста:")
                await state.set_state(Register.preferred_age_upper)
            else:
                await message.answer(f"Укажите число от {settings.MIN_AGE} до {settings.MAX_AGE}:")
                await state.set_state(Register.preferred_age_lower)
        except ValueError:
            await message.answer("Пожалуйста, введите целое число.")
            await state.set_state(Register.preferred_age_lower)

    async def process_preferred_age_lower_invalid(self, message: types.Message, state: FSMContext):
        await message.answer(f"Пожалуйста, напишите числом нижний предел предпочитаемого возраста "
                             f"(от {settings.MIN_AGE} до {settings.MAX_AGE}):")

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
            if settings.MIN_AGE <= high_point <= settings.MAX_AGE and high_point >= lower_point:
                await self.user_service.update_user_profile_field(tg_chat_id, "age_high_point", high_point)
                await message.answer("И последнее...")
                await message.answer(f"Отправьте до {settings.MAX_PHOTOS} фотографий себя: ")
                await state.set_state(Register.photo)
            else:
                await message.answer(
                    f"Укажите число от {settings.MIN_AGE} до {settings.MAX_AGE} "
                    f"и больше или равное {lower_point}:")
                await state.set_state(Register.preferred_age_upper)
        except ValueError:
            await message.answer("Пожалуйста, введите целое число:")
            await state.set_state(Register.preferred_age_upper)

    async def process_preferred_age_upper_invalid(self, message: types.Message, state: FSMContext):
        await message.answer(f"Пожалуйста, напишите числом верхний предел предпочитаемого возраста "
                             f"(от {settings.MIN_AGE} до {settings.MAX_AGE}):")

    async def process_photo_upload(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        if not message.photo:
            await message.answer("Пожалуйста, отправьте фотографию.")
            return

        user = await self.user_service.get_user_by_id(tg_chat_id)
        if user is None:
            await message.answer("Не удалось найти ваш профиль. Пожалуйста, начните регистрацию заново: /start")
            await state.clear()
            return

        slots = self.PHOTO_FIELDS[:settings.MAX_PHOTOS]
        # Ищем первый свободный слот: альбом из нескольких фото приходит
        # отдельными сообщениями, каждое из них занимает свой слот
        free_field = next((field for field in slots if getattr(user, field, None) is None), None)

        if free_field is None:
            await message.answer(
                f"Все {settings.MAX_PHOTOS} слотов для фото заняты, "
                f"изменить их можно через /change_my_profile")
            await state.clear()
            return

        # message.photo — это одно и то же изображение в разных разрешениях,
        # берем самое качественное
        file_id = message.photo[-1].file_id
        await self.user_service.update_user_profile_field(tg_chat_id, free_field, file_id)

        # Регистрацию завершаем на первой сохраненной фотографии и только один раз,
        # чтобы не поздравлять пользователя на каждое фото из альбома
        data = await state.get_data()
        if not data.get("registration_completed"):
            await self.user_service.update_user_profile_field(tg_chat_id, "is_registered", "yes")
            await state.update_data(registration_completed=True)
            await message.answer("Спасибо!\nРегистрация завершена", reply_markup=start_show_profiles())

        if free_field == slots[-1]:
            # Слоты закончились — только теперь выходим из состояния
            await message.answer(
                f"Загружено максимальное количество фотографий ({settings.MAX_PHOTOS}). "
                f"Изменить их можно через /change_my_profile")
            await state.clear()

    async def process_photo_invalid(self, message: types.Message, state: FSMContext):
        # На этом шаге ждем именно фотографию, а не текст или другой тип вложения
        await message.answer(f"Пожалуйста, отправьте фотографию (до {settings.MAX_PHOTOS} штук).")

    def get_router(self) -> Router:
        # Статус регистрации здесь не фильтруется: start_registration_callback
        # сам разбирает все три состояния ('no', 'in_progress', 'yes'),
        # а остальные хендлеры ограничены StateFilter'ами анкеты.
        self.router.callback_query.register(self.start_registration_callback, F.data == 'go')

        # Порядок регистрации важен: fallback-хендлеры идут после основных,
        # иначе они будут перехватывать корректные сообщения.
        # not_command нужен, чтобы команды (/start, /change_my_profile и т.д.)
        # не съедались хендлерами состояний, а доходили до роутера команд —
        # иначе из начатой регистрации нельзя выйти, а "/start" на шаге города
        # был бы записан как название города
        not_command = ~F.text.startswith("/")

        self.router.message.register(self.process_name, F.text, not_command, StateFilter(Register.name))
        self.router.message.register(self.process_name_invalid, not_command, StateFilter(Register.name))
        self.router.message.register(self.process_city, F.text, not_command, StateFilter(Register.city))
        self.router.message.register(self.process_city_invalid, not_command, StateFilter(Register.city))
        self.router.callback_query.register(self.process_city_from_keyboard, F.data.startswith("city_"),
                                            StateFilter(Register.city_to_db))
        self.router.message.register(self.process_city_to_db_text, F.text, not_command,
                                     StateFilter(Register.city_to_db))
        self.router.message.register(self.process_city_to_db_invalid, not_command, StateFilter(Register.city_to_db))
        self.router.message.register(self.process_age, F.text, not_command, StateFilter(Register.age))
        self.router.message.register(self.process_age_invalid, not_command, StateFilter(Register.age))
        self.router.callback_query.register(self.process_gender, F.data.in_({'Male', 'Female', 'Other'}),
                                            StateFilter(Register.gender))
        self.router.message.register(self.process_gender_invalid, not_command, StateFilter(Register.gender))
        self.router.message.register(self.process_description, F.text, not_command,
                                     StateFilter(Register.description))
        self.router.message.register(self.process_description_invalid, not_command, StateFilter(Register.description))
        self.router.callback_query.register(self.process_preferred_gender, F.data.in_({'Male', 'Female', 'Any'}),
                                            StateFilter(Register.preferred_gender))
        self.router.message.register(self.process_preferred_gender_invalid, not_command,
                                     StateFilter(Register.preferred_gender))
        self.router.message.register(self.process_preferred_age_lower, F.text, not_command,
                                     StateFilter(Register.preferred_age_lower))
        self.router.message.register(self.process_preferred_age_lower_invalid, not_command,
                                     StateFilter(Register.preferred_age_lower))
        self.router.message.register(self.process_preferred_age_upper, F.text, not_command,
                                     StateFilter(Register.preferred_age_upper))
        self.router.message.register(self.process_preferred_age_upper_invalid, not_command,
                                     StateFilter(Register.preferred_age_upper))
        self.router.message.register(self.process_photo_upload, F.photo, StateFilter(Register.photo))
        self.router.message.register(self.process_photo_invalid, not_command, StateFilter(Register.photo))
        return self.router