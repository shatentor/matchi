import logging
from aiogram import types, Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from config.settings import settings
from services.user_service import UserService
from keyboards.inline import city_keyboard, photo_management_keyboard
from utils.cities_functions import full_coincidence, get_relevant_cities
from filters.custom_filters import IsRegistered

logger = logging.getLogger(__name__)

# Строка, которой пользователь очищает необязательное поле профиля:
# иначе заполненный статус или ссылки нельзя было бы убрать
CLEAR_MARK = "-"


class ChangeProfileStates(StatesGroup):
    name_changing = State()
    city_changing = State()
    city_mistake = State()
    role_changing = State()
    status_changing = State()
    links_changing = State()
    description_changing = State()
    can_help_changing = State()
    looking_for_changing = State()
    photo_selection = State()
    photo_changing = State()


class ProfileManagementHandlers:
    def __init__(self, user_service: UserService):
        self.user_service = user_service
        self.router = Router()

    async def _save_optional_field(self, message: types.Message, state: FSMContext,
                                   field_name: str, limit: int, label: str):
        """Сохраняет необязательное текстовое поле профиля, «-» очищает его."""
        tg_chat_id = message.chat.id
        value = message.text.strip()

        if len(value) > limit:
            await message.answer(f"Лимит превышен (максимум {limit} символов).\nПопробуйте еще раз:")
            return

        if value == CLEAR_MARK:
            await self.user_service.update_user_profile_field(tg_chat_id, field_name, None)
            await message.answer(f"{label}: поле очищено.")
        else:
            await self.user_service.update_user_profile_field(tg_chat_id, field_name, value)
            await message.answer(f"{label}: изменено.")
        await state.clear()

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

    async def change_role_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer(f"Кем вы работаете и с чем? Например: «backend, Python» "
                                  f"(лимит — {settings.MAX_ROLE_LENGTH} символов):")
        await state.set_state(ChangeProfileStates.role_changing)
        await call.answer()

    async def new_role_to_db(self, message: types.Message, state: FSMContext):
        tg_chat_id = message.chat.id
        role = message.text.strip()

        # Роль — обязательная часть профиля, очистить её нельзя
        if not role:
            await message.answer("Роль не может быть пустой. Напишите, кем вы работаете:")
            return
        if len(role) > settings.MAX_ROLE_LENGTH:
            await message.answer(f"Лимит превышен (максимум {settings.MAX_ROLE_LENGTH} символов).\n"
                                 f"Попробуйте еще раз:")
            return

        await self.user_service.update_user_profile_field(tg_chat_id, "role", role)
        await message.answer("Роль успешно изменена.")
        await state.clear()

    async def new_role_invalid(self, message: types.Message, state: FSMContext):
        # Роль должна быть текстом, иначе .strip() упадёт на None
        await message.answer(f"Вы сейчас меняете роль. Пожалуйста, напишите её текстом "
                             f"(лимит — {settings.MAX_ROLE_LENGTH} символов):")

    async def change_status_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer(f"Чем вы сейчас заняты? (лимит — {settings.MAX_STATUS_LENGTH} символов, "
                                  f"«{CLEAR_MARK}» — убрать статус):")
        await state.set_state(ChangeProfileStates.status_changing)
        await call.answer()

    async def new_status_to_db(self, message: types.Message, state: FSMContext):
        await self._save_optional_field(message, state, "status", settings.MAX_STATUS_LENGTH, "Статус")

    async def new_status_invalid(self, message: types.Message, state: FSMContext):
        await message.answer(f"Вы сейчас меняете статус. Пожалуйста, пришлите его текстом "
                            f"(лимит — {settings.MAX_STATUS_LENGTH} символов, «{CLEAR_MARK}» — убрать):")

    async def change_links_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer(f"Пришлите ваши ссылки: github, сайт, канал "
                                  f"(лимит — {settings.MAX_LINKS_LENGTH} символов, "
                                  f"«{CLEAR_MARK}» — убрать ссылки):")
        await state.set_state(ChangeProfileStates.links_changing)
        await call.answer()

    async def new_links_to_db(self, message: types.Message, state: FSMContext):
        await self._save_optional_field(message, state, "links", settings.MAX_LINKS_LENGTH, "Ссылки")

    async def new_links_invalid(self, message: types.Message, state: FSMContext):
        await message.answer(f"Вы сейчас меняете ссылки. Пожалуйста, пришлите их текстом "
                            f"(лимит — {settings.MAX_LINKS_LENGTH} символов, «{CLEAR_MARK}» — убрать):")

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
        # Описание должно быть текстом, иначе len(None) упадёт
        await message.answer(f"Вы сейчас меняете описание. Пожалуйста, пришлите его текстом "
                             f"(лимит — {settings.MAX_DESCRIPTION_LENGTH} символов):")

    async def change_can_help_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer(f"Чем вы можете помочь другим? (лимит — {settings.MAX_OFFER_LENGTH} символов, "
                                  f"«{CLEAR_MARK}» — убрать):")
        await state.set_state(ChangeProfileStates.can_help_changing)
        await call.answer()

    async def new_can_help_to_db(self, message: types.Message, state: FSMContext):
        await self._save_optional_field(message, state, "can_help", settings.MAX_OFFER_LENGTH, "«Чем могу помочь»")

    async def new_can_help_invalid(self, message: types.Message, state: FSMContext):
        await message.answer(f"Вы сейчас меняете «чем могу помочь». Пожалуйста, пришлите текст "
                            f"(лимит — {settings.MAX_OFFER_LENGTH} символов, «{CLEAR_MARK}» — убрать):")

    async def change_looking_for_button(self, call: types.CallbackQuery, state: FSMContext):
        await call.message.answer(f"Что вы ищете в сети? (лимит — {settings.MAX_OFFER_LENGTH} символов, "
                                  f"«{CLEAR_MARK}» — убрать):")
        await state.set_state(ChangeProfileStates.looking_for_changing)
        await call.answer()

    async def new_looking_for_to_db(self, message: types.Message, state: FSMContext):
        await self._save_optional_field(message, state, "looking_for", settings.MAX_OFFER_LENGTH, "«Что ищу»")

    async def new_looking_for_invalid(self, message: types.Message, state: FSMContext):
        await message.answer(f"Вы сейчас меняете «что ищу». Пожалуйста, пришлите текст "
                            f"(лимит — {settings.MAX_OFFER_LENGTH} символов, «{CLEAR_MARK}» — убрать):")

    async def photo_selection_invalid(self, message: types.Message, state: FSMContext):
        await message.answer("Выберите действие с фотографиями кнопкой выше.")

    async def photo_changing_invalid(self, message: types.Message, state: FSMContext):
        await message.answer("Пожалуйста, отправьте фотографию.")

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

        self.router.callback_query.register(self.change_role_button, F.data == "change_role",
                                            is_registered_filter)
        self.router.message.register(self.new_role_to_db, StateFilter(ChangeProfileStates.role_changing),
                                     F.text, not_command)
        self.router.message.register(self.new_role_invalid, StateFilter(ChangeProfileStates.role_changing),
                                     not_command)

        self.router.callback_query.register(self.change_status_button, F.data == "change_status",
                                            is_registered_filter)
        self.router.message.register(self.new_status_to_db, StateFilter(ChangeProfileStates.status_changing),
                                     F.text, not_command)
        self.router.message.register(self.new_status_invalid, StateFilter(ChangeProfileStates.status_changing),
                                     not_command)

        self.router.callback_query.register(self.change_links_button, F.data == "change_links",
                                            is_registered_filter)
        self.router.message.register(self.new_links_to_db, StateFilter(ChangeProfileStates.links_changing),
                                     F.text, not_command)
        self.router.message.register(self.new_links_invalid, StateFilter(ChangeProfileStates.links_changing),
                                     not_command)

        self.router.callback_query.register(self.change_description_button, F.data == "change_description",
                                            is_registered_filter)
        self.router.message.register(self.new_description_to_db, StateFilter(ChangeProfileStates.description_changing),
                                     F.text, not_command)
        self.router.message.register(self.new_description_invalid,
                                     StateFilter(ChangeProfileStates.description_changing), not_command)

        self.router.callback_query.register(self.change_can_help_button, F.data == "change_can_help",
                                            is_registered_filter)
        self.router.message.register(self.new_can_help_to_db, StateFilter(ChangeProfileStates.can_help_changing),
                                     F.text, not_command)
        self.router.message.register(self.new_can_help_invalid, StateFilter(ChangeProfileStates.can_help_changing),
                                     not_command)

        self.router.callback_query.register(self.change_looking_for_button, F.data == "change_looking_for",
                                            is_registered_filter)
        self.router.message.register(self.new_looking_for_to_db,
                                     StateFilter(ChangeProfileStates.looking_for_changing), F.text, not_command)
        self.router.message.register(self.new_looking_for_invalid,
                                     StateFilter(ChangeProfileStates.looking_for_changing), not_command)

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
        return self.router
