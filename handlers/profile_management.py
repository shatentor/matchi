import logging
from aiogram import Dispatcher, types, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter
from typing import Tuple, Optional
from config.settings import settings
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
        await state.set_state(ChangeProfileStates.name_changing)
        await call.answer()

    async def new_name_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        if len(message.text) > settings.MAX_NAME_LENGTH:
            await message.answer(f"Слишком длинное имя (лимит — {settings.MAX_NAME_LENGTH} символов). "
                                 f"Попробуйте еще раз:")
            return await state.set_state(ChangeProfileStates.name_changing)

        await self.user_service.update_user_profile_field(tg_chat_id, "name", message.text)
        await message.answer("Имя успешно изменено.")
        await state.clear()

    async def new_name_invalid(self, message: types.Message, state: FSMContext):
        # Пришло не текстовое сообщение: len(None) упал бы в основном хендлере
        await message.answer("Вы сейчас меняете имя. Пожалуйста, пришлите новое имя текстом:")

    async def change_age_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Введите ваш возраст:")
        await state.set_state(ChangeProfileStates.age_changing)
        await call.answer()

    async def new_age_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        try:
            age = int(message.text)
            if settings.MIN_AGE <= age <= settings.MAX_AGE:
                await self.user_service.update_user_profile_field(tg_chat_id, "age", age)
                await message.answer("Возраст успешно изменен.")
                await state.clear()
            else:
                await message.answer(f"Укажите ваш возраст (от {settings.MIN_AGE} до {settings.MAX_AGE}):")
                await state.set_state(ChangeProfileStates.age_changing)
        except ValueError:
            await message.answer("Пожалуйста, введите целое число.\nПопробуйте еще раз:")
            await state.set_state(ChangeProfileStates.age_changing)

    async def new_age_invalid(self, message: types.Message, state: FSMContext):
        # int(None) дал бы TypeError, который не ловится в основном хендлере
        await message.answer(f"Вы сейчас меняете возраст. Пожалуйста, напишите его числом "
                             f"(от {settings.MIN_AGE} до {settings.MAX_AGE}):")

    async def change_city_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Введите новый город:")
        await state.set_state(ChangeProfileStates.city_changing)
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
                await state.set_state(ChangeProfileStates.city_mistake)
            else:
                await message.answer("В нашем боте нет города с таким названием! Попробуйте еще раз:")
                await state.set_state(ChangeProfileStates.city_changing)

    async def new_city_invalid(self, message: types.Message, state: FSMContext):
        # Название города должно быть текстом, иначе .strip() упадет на None
        await message.answer("Вы сейчас меняете город. Пожалуйста, напишите его название текстом:")

    async def city_mistake_text(self, message: types.Message, state: FSMContext):
        # Ждем выбор из подсказок, но текст принимаем как новую попытку ввести город,
        # иначе пользователь, которому подсказки не подошли, остается без выхода
        await self.new_city_to_db(message, state)

    async def city_mistake_invalid(self, message: types.Message, state: FSMContext):
        await message.answer("Выберите город кнопкой ниже или напишите название текстом:")

    async def gender_changing_invalid(self, message: types.Message, state: FSMContext):
        await message.answer("Пожалуйста, выберите ваш пол кнопкой ниже:", reply_markup=gender_keyboard())

    async def preferred_gender_changing_invalid(self, message: types.Message, state: FSMContext):
        await message.answer("Пожалуйста, выберите предпочитаемый пол кнопкой ниже:",
                             reply_markup=preferred_gender_keyboard())

    async def photo_selection_invalid(self, message: types.Message, state: FSMContext):
        await message.answer("Выберите действие с фотографиями кнопкой выше.")

    async def photo_changing_invalid(self, message: types.Message, state: FSMContext):
        await message.answer("Пожалуйста, отправьте фотографию.")

    async def city_mistake_button(self, call: types.CallbackQuery, state: FSMContext):
        message = call.message
        tg_chat_id = call.from_user.id
        if call.data == "city_no":
            await message.answer("Попробуйте ввести ваш город еще раз:")
            await state.set_state(ChangeProfileStates.city_changing)
        else:
            city_from_keyboard = call.data.replace("city_", "")
            await self.user_service.update_user_profile_field(tg_chat_id, "city", city_from_keyboard)
            await message.answer("Город успешно изменен.")
            await state.clear()
        await call.answer()

    async def change_gender_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer("Выберите ваш пол:", reply_markup=gender_keyboard())
        await state.set_state(ChangeProfileStates.gender_changing)
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
        await state.set_state(ChangeProfileStates.description_changing)
        await call.answer()

    async def new_description_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        if len(message.text) > settings.MAX_DESCRIPTION_LENGTH:
            await message.answer(f"Лимит превышен ({settings.MAX_DESCRIPTION_LENGTH} символов).\n"
                                 f"Попробуйте еще раз:")
            return await state.set_state(ChangeProfileStates.description_changing)

        await self.user_service.update_user_profile_field(tg_chat_id, "description", message.text)
        await message.answer("Описание успешно изменено.")
        await state.clear()

    async def new_description_invalid(self, message: types.Message, state: FSMContext):
        # Описание должно быть текстом, иначе len(None) упадет
        await message.answer(f"Вы сейчас меняете описание. Пожалуйста, пришлите его текстом "
                             f"(лимит — {settings.MAX_DESCRIPTION_LENGTH} символов):")

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
        await state.set_state(ChangeProfileStates.photo_selection)
        await call.answer()

    async def photo_selected_action(self, call: types.CallbackQuery, state: FSMContext):
        tg_chat_id = call.from_user.id
        message = call.message

        request_from_user = call.data
        await state.update_data(request_from_user=request_from_user)

        if request_from_user.startswith("add_photo") or request_from_user.startswith("change_photo"):
            await message.answer("Отправьте фото:")
            await state.set_state(ChangeProfileStates.photo_changing)
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
        await state.set_state(ChangeProfileStates.preferred_gender_changing)
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
        await state.set_state(ChangeProfileStates.preferred_age_lower)
        await call.answer()

    async def lower_age_point_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        try:
            lower_point = int(message.text)
            if settings.MIN_AGE <= lower_point <= settings.MAX_AGE:
                await self.user_service.update_user_profile_field(tg_chat_id, "age_lower_point", lower_point)
                await message.answer("Введите верхний предел вашего предпочитаемого возраста:")
                await state.set_state(ChangeProfileStates.preferred_age_upper)
            else:
                await message.answer(f"Введите число от {settings.MIN_AGE} до {settings.MAX_AGE}:")
                await state.set_state(ChangeProfileStates.preferred_age_lower)
        except ValueError:
            await message.answer("Пожалуйста, введите целое число.\nПопробуйте еще раз:")
            await state.set_state(ChangeProfileStates.preferred_age_lower)

    async def lower_age_point_invalid(self, message: types.Message, state: FSMContext):
        await message.answer(f"Вы сейчас меняете предпочитаемый возраст. Пожалуйста, напишите числом "
                             f"его нижний предел (от {settings.MIN_AGE} до {settings.MAX_AGE}):")

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
            if settings.MIN_AGE <= high_point <= settings.MAX_AGE and high_point >= lower_age_point:
                await self.user_service.update_user_profile_field(tg_chat_id, "age_high_point", high_point)
                await message.answer("Предпочитаемый возраст успешно изменен.")
                await state.clear()
            else:
                await message.answer(f"Введите число от {settings.MIN_AGE} до {settings.MAX_AGE} "
                                     f"и больше или равное {lower_age_point}:")
                await state.set_state(ChangeProfileStates.preferred_age_upper)
        except ValueError:
            await message.answer("Пожалуйста, введите целое число.\nПопробуйте еще раз:")
            await state.set_state(ChangeProfileStates.preferred_age_upper)

    async def high_age_point_invalid(self, message: types.Message, state: FSMContext):
        await message.answer(f"Вы сейчас меняете предпочитаемый возраст. Пожалуйста, напишите числом "
                             f"его верхний предел (от {settings.MIN_AGE} до {settings.MAX_AGE}):")

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        # not_command нужен, чтобы команды не съедались хендлерами состояний,
        # а доходили до роутеров ниже по цепочке (/searchi, /admin, /complains) —
        # иначе "/searchi" во время смены имени был бы записан как новое имя.
        # Fallback-хендлеры ловят только нетекстовые сообщения и регистрируются
        # после основных: в aiogram 3 порядок регистрации задаёт приоритет
        not_command = ~F.text.startswith("/")

        self.router.callback_query.register(self.change_name_button, F.data == "change_name",
                                            is_registered_filter)
        self.router.message.register(self.new_name_to_db, StateFilter(ChangeProfileStates.name_changing), F.text,
                                     not_command)
        self.router.message.register(self.new_name_invalid, StateFilter(ChangeProfileStates.name_changing),
                                     not_command)

        self.router.callback_query.register(self.change_age_button, F.data == "change_age",
                                            is_registered_filter)
        self.router.message.register(self.new_age_to_db, StateFilter(ChangeProfileStates.age_changing), F.text,
                                     not_command)
        self.router.message.register(self.new_age_invalid, StateFilter(ChangeProfileStates.age_changing),
                                     not_command)

        self.router.callback_query.register(self.change_city_button, F.data == "change_city",
                                            is_registered_filter)
        self.router.message.register(self.new_city_to_db, StateFilter(ChangeProfileStates.city_changing), F.text,
                                     not_command)
        self.router.message.register(self.new_city_invalid, StateFilter(ChangeProfileStates.city_changing),
                                     not_command)
        self.router.callback_query.register(self.city_mistake_button, F.data.startswith("city_"),
                                            StateFilter(ChangeProfileStates.city_mistake))
        self.router.message.register(self.city_mistake_text, StateFilter(ChangeProfileStates.city_mistake),
                                     F.text, not_command)
        self.router.message.register(self.city_mistake_invalid, StateFilter(ChangeProfileStates.city_mistake),
                                     not_command)

        self.router.callback_query.register(self.change_gender_button, F.data == "change_gender",
                                            is_registered_filter)
        self.router.callback_query.register(self.new_gender_to_db, F.data.in_({'Male', 'Female', 'Other'}),
                                            StateFilter(ChangeProfileStates.gender_changing))
        self.router.message.register(self.gender_changing_invalid, StateFilter(ChangeProfileStates.gender_changing),
                                     not_command)

        self.router.callback_query.register(self.change_description_button, F.data == "change_description",
                                            is_registered_filter)
        self.router.message.register(self.new_description_to_db, StateFilter(ChangeProfileStates.description_changing),
                                     F.text, not_command)
        self.router.message.register(self.new_description_invalid,
                                     StateFilter(ChangeProfileStates.description_changing), not_command)

        self.router.callback_query.register(self.change_photo_button, F.data == "change_photo",
                                            is_registered_filter)
        self.router.callback_query.register(self.photo_selected_action,
                                            F.data.startswith("change_photo") | F.data.startswith(
                                                "delete_photo") | F.data.startswith("add_photo"),
                                            StateFilter(ChangeProfileStates.photo_selection))
        self.router.message.register(self.photo_selection_invalid, StateFilter(ChangeProfileStates.photo_selection),
                                     not_command)
        self.router.message.register(self.new_photo_to_db, StateFilter(ChangeProfileStates.photo_changing), F.photo)
        self.router.message.register(self.photo_changing_invalid, StateFilter(ChangeProfileStates.photo_changing),
                                     not_command)

        self.router.callback_query.register(self.change_preferred_gender_button, F.data == 'change_preferred_gender',
                                            is_registered_filter)
        self.router.callback_query.register(self.new_preferred_gender_to_db, F.data.in_({'Male', 'Female', 'Any'}),
                                            StateFilter(ChangeProfileStates.preferred_gender_changing))
        self.router.message.register(self.preferred_gender_changing_invalid,
                                     StateFilter(ChangeProfileStates.preferred_gender_changing), not_command)

        self.router.callback_query.register(self.change_preferred_age_button, F.data == "change_preferred_age",
                                            is_registered_filter)
        self.router.message.register(self.lower_age_point_to_db, StateFilter(ChangeProfileStates.preferred_age_lower),
                                     F.text, not_command)
        self.router.message.register(self.lower_age_point_invalid,
                                     StateFilter(ChangeProfileStates.preferred_age_lower), not_command)
        self.router.message.register(self.high_age_point_to_db, StateFilter(ChangeProfileStates.preferred_age_upper),
                                     F.text, not_command)
        self.router.message.register(self.high_age_point_invalid,
                                     StateFilter(ChangeProfileStates.preferred_age_upper), not_command)
        return self.router