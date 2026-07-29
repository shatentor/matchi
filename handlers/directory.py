import logging
from contextlib import suppress
from typing import Any, Dict, List, Optional, Tuple

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config.settings import settings
from filters.custom_filters import IsRegistered
from keyboards.directory import (DirectoryCB, directory_card_keyboard, directory_cities_keyboard,
                                 directory_interests_keyboard, directory_list_keyboard,
                                 search_cancel_keyboard)
from models.user import UserProfileData
from services.directory_service import DirectoryService
from services.post_service import PostService
from services.user_service import UserService
from utils.telegram import safe_send_media_group
from utils.text import escape

logger = logging.getLogger(__name__)

# Одно сообщение Telegram — не больше 4096 символов, а страница списка и карточка
# собираются из пользовательских текстов. Режем с запасом на escape().
MAX_MESSAGE_LENGTH = 3500
# Описание в карточке подрезаем: оно бывает до settings.MAX_DESCRIPTION_LENGTH,
# и вместе с остальными полями карточка перестала бы влезать в сообщение.
CARD_DESCRIPTION_LENGTH = 900
# Сколько постов участника считать для карточки. Точное число не нужно, а
# перебирать всю ленту одного человека ради подписи — лишняя работа.
POSTS_COUNT_LIMIT = 20


class DirectoryStates(StatesGroup):
    """Состояние ввода поисковой строки каталога."""
    query = State()


class DirectoryHandlers:
    """Каталог участников: список страницами, поиск и карточка участника.

    post_service необязателен: без него в карточке просто не будет числа
    постов, остальное работает.

    Активные фильтры (текст поиска, интерес, город) хранятся в данных FSM, а не
    в callback_data: 64 байта callback_data не вмещают произвольную строку,
    тем более кириллицей.
    """

    def __init__(self, directory_service: DirectoryService, user_service: UserService,
                 post_service: Optional[PostService] = None):
        self.directory_service = directory_service
        self.user_service = user_service
        self.post_service = post_service
        self.router = Router()

    # ---------- вспомогательное ----------

    @staticmethod
    def _accessible(call: types.CallbackQuery) -> Optional[types.Message]:
        """Сообщение под кнопкой или None, если Telegram отдал InaccessibleMessage.

        Для сообщений старше ~48 часов приходит InaccessibleMessage — у него нет
        ни answer, ни edit_text.
        """
        return call.message if isinstance(call.message, types.Message) else None

    @staticmethod
    async def _filters(state: FSMContext) -> Tuple[Optional[str], Optional[int], Optional[str]]:
        data = await state.get_data()
        interest_id = data.get("dir_interest_id") or None
        return data.get("dir_query") or None, interest_id, data.get("dir_city") or None

    @staticmethod
    async def _reset_filters(state: FSMContext) -> None:
        await state.update_data(dir_query=None, dir_interest_id=None, dir_city=None, dir_page=0)

    async def _interest_title(self, interest_id: Optional[int]) -> Optional[str]:
        if not interest_id:
            return None
        for interest in await self.directory_service.interests():
            if interest.id == interest_id:
                return interest.title
        return None

    async def _filters_note(self, query: Optional[str], interest_id: Optional[int],
                            city: Optional[str]) -> str:
        parts = []
        if query:
            parts.append(f"поиск «{escape(query)}»")
        title = await self._interest_title(interest_id)
        if title:
            parts.append(f"интерес «{escape(title)}»")
        if city:
            parts.append(f"город «{escape(city)}»")
        return ("Фильтры: " + ", ".join(parts)) if parts else ""

    @staticmethod
    def _short_line(number: int, profile: UserProfileData) -> str:
        pieces = [f"<b>{escape(profile.name)}</b>"]
        if profile.role:
            pieces.append(escape(profile.role))
        if profile.city:
            pieces.append(escape(profile.city))
        return f"{number}. " + " · ".join(pieces)

    async def _list_text(self, items: List[UserProfileData], total: int, pages: int, page: int,
                         query: Optional[str], interest_id: Optional[int],
                         city: Optional[str]) -> str:
        note = await self._filters_note(query, interest_id, city)

        if not items:
            head = "Никого не нашлось."
            hint = ("Попробуйте другой запрос или снимите фильтры." if note
                    else "В каталоге пока только вы. Пригласите друга: /invite")
            return "\n\n".join(part for part in (head, note, hint) if part)

        size = max(1, settings.DIRECTORY_PAGE_SIZE)
        header = f"<b>Участники</b> · найдено {total} · стр. {page + 1} из {pages}"
        lines = [header]
        if note:
            lines.append(note)

        length = sum(len(line) for line in lines)
        for offset, profile in enumerate(items, start=1):
            line = self._short_line(page * size + offset, profile)
            if length + len(line) > MAX_MESSAGE_LENGTH:
                lines.append("…")
                break
            lines.append(line)
            length += len(line) + 1

        lines.append("Откройте участника кнопкой с его номером.")
        return "\n".join(lines)

    async def _show_list(self, message: types.Message, viewer_id: int, state: FSMContext,
                         page: int, edit: bool = False) -> None:
        query, interest_id, city = await self._filters(state)
        items, total, pages = await self.directory_service.page(
            viewer_id, query=query, interest_id=interest_id, city=city, page=page
        )
        # Номер страницы приводим к существующему тем же правилом, что и сервис:
        # кнопку «➡️» могли нажать в старом сообщении, когда людей стало меньше.
        page = DirectoryService.clamp_page(page, pages)
        await state.update_data(dir_page=page)

        size = max(1, settings.DIRECTORY_PAGE_SIZE)
        entries = [(page * size + offset, int(profile.tg_chat_id))
                   for offset, profile in enumerate(items, start=1)]
        text = await self._list_text(items, total, pages, page, query, interest_id, city)
        keyboard = directory_list_keyboard(entries, page, pages,
                                           has_filters=any((query, interest_id, city)))

        if edit:
            with suppress(TelegramBadRequest):
                await message.edit_text(text, reply_markup=keyboard)
                return
        await message.answer(text, reply_markup=keyboard)

    async def _posts_note(self, peer_id: int) -> str:
        if self.post_service is None:
            return ""
        try:
            posts = await self.post_service.my_posts(peer_id, POSTS_COUNT_LIMIT)
        except Exception as e:
            # Число постов — украшение карточки, из-за него она не должна пропадать.
            logger.warning(f"Не удалось посчитать посты {peer_id}: {e}")
            return ""
        if not posts:
            return ""
        count = f"{len(posts)}+" if len(posts) >= POSTS_COUNT_LIMIT else str(len(posts))
        return f"Постов в ленте: {count}"

    async def _card_text(self, card: Dict[str, Any], peer_id: int) -> str:
        profile: UserProfileData = card["profile"]
        lines = [f"👤 <b>{escape(profile.name)}</b>",
                 f"Занимается: {escape(profile.role)}",
                 f"Город: {escape(profile.city)}"]
        # Необязательные поля пустыми не печатаем, иначе карточка станет решетом.
        if profile.status:
            lines.append(f"Сейчас: {escape(profile.status)}")
        if profile.can_help:
            lines.append(f"Может помочь: {escape(profile.can_help)}")
        if profile.looking_for:
            lines.append(f"Ищет: {escape(profile.looking_for)}")
        if profile.links:
            lines.append(f"Ссылки: {escape(profile.links)}")

        common = card.get("common") or []
        if common:
            lines.append("Общие интересы: " + ", ".join(escape(i.title) for i in common))

        inviter_name, inviter_id = card.get("inviter_name"), card.get("inviter_id")
        if inviter_name:
            lines.append(f"Пришёл по приглашению: <b>{escape(inviter_name)}</b>")
        elif inviter_id:
            lines.append(f"Пришёл по приглашению участника ID {escape(inviter_id)}")

        posts_note = await self._posts_note(peer_id)
        if posts_note:
            lines.append(posts_note)

        description = profile.description or ""
        if len(description) > CARD_DESCRIPTION_LENGTH:
            description = description[:CARD_DESCRIPTION_LENGTH] + "…"
        lines.append(f"\nО себе:\n{escape(description)}")

        if profile.tg_username:
            lines.append(f"\nКонтакт: @{escape(profile.tg_username)}")
        return "\n".join(lines)

    # ---------- список ----------

    async def people_command(self, message: types.Message, state: FSMContext) -> None:
        viewer_id = message.chat.id

        if await state.get_state() == DirectoryStates.query.state:
            # Иначе следующая реплика человека ушла бы поисковым запросом.
            await state.set_state(None)

        # Каталог открывается без фильтров: /people — это «показать всех», и
        # молча унаследованный прошлый поиск выглядел бы как пустая сеть.
        await self._reset_filters(state)
        await self._show_list(message, viewer_id, state, page=0)

    async def page_callback(self, call: types.CallbackQuery, callback_data: DirectoryCB,
                            state: FSMContext) -> None:
        # Ответ на callback идёт после проверки доступности сообщения: на один
        # callback Telegram принимает только один ответ.
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте каталог заново: /people",
                              show_alert=True)
            return
        await call.answer()
        await self._show_list(message, call.from_user.id, state, page=callback_data.page,
                              edit=True)

    async def open_callback(self, call: types.CallbackQuery, callback_data: DirectoryCB,
                            state: FSMContext) -> None:
        # Ответ на callback идёт после проверки доступности сообщения: на один
        # callback Telegram принимает только один ответ.
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте каталог заново: /people",
                              show_alert=True)
            return
        await call.answer()

        peer_id = callback_data.peer_id
        card = await self.directory_service.profile_card(peer_id, call.from_user.id)
        if card is None:
            await message.answer("Этого участника больше нет в каталоге. Обновить: /people")
            return

        media = await self.user_service.get_user_media_group(peer_id)
        if media:
            await safe_send_media_group(call.bot, call.from_user.id, media)

        text = await self._card_text(card, peer_id)
        keyboard = directory_card_keyboard(peer_id, back_page=callback_data.page)
        # Карточка заменяет список в том же сообщении: в боте нет прокрутки, и
        # каждая открытая карточка отдельным сообщением быстро забивает чат.
        with suppress(TelegramBadRequest):
            await message.edit_text(text, reply_markup=keyboard)
            return
        await message.answer(text, reply_markup=keyboard)

    # ---------- фильтры ----------

    async def search_callback(self, call: types.CallbackQuery, callback_data: DirectoryCB,
                              state: FSMContext) -> None:
        # Ответ на callback идёт после проверки доступности сообщения: на один
        # callback Telegram принимает только один ответ.
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте каталог заново: /people",
                              show_alert=True)
            return
        await call.answer()

        await state.set_state(DirectoryStates.query)
        await message.answer(
            f"Кого ищем? Пришлите часть имени, роли, города или статуса "
            f"(минимум {settings.SEARCH_MIN_QUERY} символа).",
            reply_markup=search_cancel_keyboard()
        )

    async def process_query(self, message: types.Message, state: FSMContext) -> None:
        raw = (message.text or "").strip()
        if len(raw) < settings.SEARCH_MIN_QUERY:
            # Остаёмся в состоянии: человек может уточнить запрос и прислать заново.
            await message.answer(f"Слишком короткий запрос. Нужно минимум "
                                 f"{settings.SEARCH_MIN_QUERY} символа.",
                                 reply_markup=search_cancel_keyboard())
            return

        await state.set_state(None)
        await state.update_data(dir_query=raw, dir_page=0)
        await self._show_list(message, message.chat.id, state, page=0)

    async def process_query_invalid(self, message: types.Message, state: FSMContext) -> None:
        await message.answer("Запрос должен быть текстом. Пришлите текст или отмените "
                             "кнопкой под сообщением выше.")

    async def interests_menu_callback(self, call: types.CallbackQuery,
                                      callback_data: DirectoryCB, state: FSMContext) -> None:
        # Ответ на callback идёт после проверки доступности сообщения: на один
        # callback Telegram принимает только один ответ.
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте каталог заново: /people",
                              show_alert=True)
            return
        await call.answer()

        interests = await self.directory_service.interests()
        if not interests:
            await message.answer("Список интересов пока пуст.")
            return

        _, selected, _ = await self._filters(state)
        with suppress(TelegramBadRequest):
            await message.edit_text("Показать участников с интересом:",
                                    reply_markup=directory_interests_keyboard(interests, selected))
            return
        await message.answer("Показать участников с интересом:",
                             reply_markup=directory_interests_keyboard(interests, selected))

    async def interest_pick_callback(self, call: types.CallbackQuery, callback_data: DirectoryCB,
                                     state: FSMContext) -> None:
        # Ответ на callback идёт после проверки доступности сообщения: на один
        # callback Telegram принимает только один ответ.
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте каталог заново: /people",
                              show_alert=True)
            return
        await call.answer()
        await state.update_data(dir_interest_id=callback_data.interest_id or None, dir_page=0)
        await self._show_list(message, call.from_user.id, state, page=0, edit=True)

    async def cities_menu_callback(self, call: types.CallbackQuery, callback_data: DirectoryCB,
                                   state: FSMContext) -> None:
        # Ответ на callback идёт после проверки доступности сообщения: на один
        # callback Telegram принимает только один ответ.
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте каталог заново: /people",
                              show_alert=True)
            return
        await call.answer()

        cities = await self.directory_service.cities()
        if not cities:
            await message.answer("Города участников пока неизвестны.")
            return

        _, _, selected = await self._filters(state)
        text = "Кто рядом — выберите город:"
        keyboard = directory_cities_keyboard(cities, selected)
        with suppress(TelegramBadRequest):
            await message.edit_text(text, reply_markup=keyboard)
            return
        await message.answer(text, reply_markup=keyboard)

    async def city_pick_callback(self, call: types.CallbackQuery, callback_data: DirectoryCB,
                                 state: FSMContext) -> None:
        # Ответ на callback идёт после проверки доступности сообщения: на один
        # callback Telegram принимает только один ответ.
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте каталог заново: /people",
                              show_alert=True)
            return
        await call.answer()
        await state.update_data(dir_city=callback_data.city or None, dir_page=0)
        await self._show_list(message, call.from_user.id, state, page=0, edit=True)

    async def reset_callback(self, call: types.CallbackQuery, callback_data: DirectoryCB,
                             state: FSMContext) -> None:
        # Ответ на callback идёт после проверки доступности сообщения: на один
        # callback Telegram принимает только один ответ.
        message = self._accessible(call)
        if message is None:
            await call.answer("Сообщение устарело, откройте каталог заново: /people",
                              show_alert=True)
            return
        await call.answer()

        if await state.get_state() == DirectoryStates.query.state:
            await state.set_state(None)
        await self._reset_filters(state)
        await self._show_list(message, call.from_user.id, state, page=0)

    # ---------- сборка роутера ----------

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        # not_command обязателен на текстовом хендлере состояния: иначе "/people"
        # или "/menu" ушли бы поисковым запросом вместо своих хендлеров.
        not_command = ~F.text.startswith("/")
        # Фильтр Command читает message.text ИЛИ message.caption, поэтому команда
        # в подписи к фотографии тоже обязана дойти до своего хендлера — fallback
        # ниже ловит любые нетекстовые сообщения, в том числе фото с подписью.
        not_caption_command = ~F.caption.startswith("/")

        self.router.message.register(self.people_command, Command("people"), is_registered_filter)

        self.router.callback_query.register(self.page_callback,
                                            DirectoryCB.filter(F.action == "page"),
                                            is_registered_filter)
        self.router.callback_query.register(self.open_callback,
                                            DirectoryCB.filter(F.action == "open"),
                                            is_registered_filter)
        self.router.callback_query.register(self.search_callback,
                                            DirectoryCB.filter(F.action == "search"),
                                            is_registered_filter)
        self.router.callback_query.register(self.interests_menu_callback,
                                            DirectoryCB.filter(F.action == "interests"),
                                            is_registered_filter)
        self.router.callback_query.register(self.interest_pick_callback,
                                            DirectoryCB.filter(F.action == "interest"),
                                            is_registered_filter)
        self.router.callback_query.register(self.cities_menu_callback,
                                            DirectoryCB.filter(F.action == "cities"),
                                            is_registered_filter)
        self.router.callback_query.register(self.city_pick_callback,
                                            DirectoryCB.filter(F.action == "city"),
                                            is_registered_filter)
        self.router.callback_query.register(self.reset_callback,
                                            DirectoryCB.filter(F.action == "reset"),
                                            is_registered_filter)

        # Fallback идёт после основного хендлера состояния, иначе перехватывал бы
        # корректный текст запроса, и ловит только нетекстовые сообщения.
        self.router.message.register(self.process_query, StateFilter(DirectoryStates.query),
                                     F.text, not_command)
        self.router.message.register(self.process_query_invalid,
                                     StateFilter(DirectoryStates.query),
                                     not_command, not_caption_command)
        return self.router
