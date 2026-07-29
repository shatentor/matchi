import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config.settings import settings
from filters.custom_filters import IsAdmin, IsRegistered
from keyboards.rooms import (RoomCB, community_invite_keyboard, native_invite_keyboard,
                             room_card_keyboard, room_chat_keyboard, room_interests_keyboard,
                             rooms_keyboard)
from models.room import ROOM_MODES, ROOM_MODE_NATIVE, ROOM_MODE_RELAY, Room
from services.community_service import SETUP_INSTRUCTION, CommunityService
from services.interest_service import InterestService
from services.room_service import RoomService
from services.user_service import UserService
from utils.telegram import safe_send_message
from utils.text import escape

logger = logging.getLogger(__name__)

# Лимит текста сообщения Telegram — 4096 символов; история и каталог собираются
# из пользовательских текстов, поэтому режем с запасом на escape().
MAX_MESSAGE_LENGTH = 3500
# Ссылка-приглашение выдаётся конкретному пользователю, поэтому одноразовая.
INVITE_MEMBER_LIMIT = 1
# name у ссылки-приглашения в Telegram ограничен 32 символами.
INVITE_NAME_LENGTH = 32

MODE_HINT = {
    ROOM_MODE_RELAY: "чат через бота",
    ROOM_MODE_NATIVE: "супергруппа Telegram",
}
TOPIC_HINT = "топик в супергруппе сообщества"


class RoomStates(StatesGroup):
    chatting = State()


class RoomHandlers:
    """Каталог комнат, режим чата relay-комнаты, сообщество и админское управление."""

    def __init__(self, room_service: RoomService, interest_service: InterestService,
                 user_service: UserService,
                 community_service: Optional[CommunityService] = None):
        self.room_service = room_service
        self.interest_service = interest_service
        self.user_service = user_service
        # Без сообщества работают только relay-комнаты: топики живут в
        # супергруппе, которую админ привязывает командой /community_bind.
        self.community_service = community_service
        self.router = Router()

    # ---------- вспомогательное ----------

    @staticmethod
    def _mode_hint(room: Room) -> str:
        if room.is_topic:
            return TOPIC_HINT
        return MODE_HINT.get(room.mode, escape(room.mode))

    @classmethod
    def _room_line(cls, room: Room) -> str:
        parts = [f"<b>{escape(room.title)}</b> — {room.member_count}/{room.member_limit}, "
                 f"{cls._mode_hint(room)}"]
        if room.description:
            parts.append(escape(room.description))
        # Ссылка собрана из чисел, экранировать в ней нечего
        if room.topic_url:
            parts.append(f'<a href="{room.topic_url}">Открыть топик</a>')
        return "\n".join(parts)

    def _catalog_text(self, rooms: List[Room], filtered: bool) -> str:
        if not rooms:
            return ("Комнат пока нет." if not filtered
                    else "По этому интересу комнат пока нет.")

        header = "<b>Комнаты по интересам</b>\n\n"
        lines: List[str] = []
        length = len(header)
        for room in rooms:
            line = self._room_line(room)
            if length + len(line) > MAX_MESSAGE_LENGTH:
                lines.append("…")
                break
            lines.append(line)
            length += len(line) + 2
        return header + "\n\n".join(lines)

    async def _show_catalog(self, message: types.Message, interest_id: Optional[int] = None) -> None:
        rooms = await self.room_service.list_rooms(interest_id)
        filtered = interest_id is not None
        await message.answer(
            self._catalog_text(rooms, filtered),
            reply_markup=rooms_keyboard(rooms, with_filter=True, filtered=filtered)
        )

    @staticmethod
    def _history_text(rows: List[Dict[str, Any]]) -> str:
        if not rows:
            return "В комнате пока нет сообщений."

        blocks: List[str] = []
        length = 0
        # Идём с конца: если история не влезает в одно сообщение, лучше потерять
        # самые старые сообщения, а не самые свежие
        for row in reversed(rows):
            author = row.get("author_name") or row.get("author_chat_id") or "Кто-то"
            created = row.get("created_at")
            stamp = created.strftime('%d.%m %H:%M') if isinstance(created, datetime) else ""
            block = f"<b>{escape(str(author))}</b> {stamp}\n{escape(row.get('text') or '')}"
            if length + len(block) > MAX_MESSAGE_LENGTH:
                break
            blocks.append(block)
            length += len(block) + 2

        return "<b>Последние сообщения</b>\n\n" + "\n\n".join(reversed(blocks))

    async def _native_invite_link(self, bot: Bot, room: Room) -> Optional[str]:
        """Создаёт ссылку с ограниченным сроком жизни на супергруппу комнаты.

        Бот обязан быть администратором этой супергруппы с правом приглашать —
        иначе Telegram отвечает ошибкой, и ссылку выдать нельзя.
        """
        expire_date = datetime.now(timezone.utc) + timedelta(seconds=settings.ROOM_INVITE_TTL)
        try:
            link = await bot.create_chat_invite_link(
                chat_id=room.tg_chat_id,
                name=f"matchi-room-{room.id}"[:INVITE_NAME_LENGTH],
                expire_date=expire_date,
                member_limit=INVITE_MEMBER_LIMIT,
            )
        except TelegramAPIError as e:
            logger.error(f"Не удалось создать приглашение в чат {room.tg_chat_id} "
                         f"комнаты {room.id}: {e}")
            return None
        return link.invite_link

    async def _enter_native(self, message: types.Message, bot: Bot, room: Room) -> None:
        if not room.tg_chat_id:
            await message.answer("Эта комната ещё не привязана к группе. "
                                 "Напишите администратору: /support")
            return

        topic_url = room.topic_url
        invite_link = await self._native_invite_link(bot, room)
        if not invite_link and not topic_url:
            await message.answer("Не удалось получить приглашение в комнату. "
                                 "Попробуйте позже или напишите администратору: /support")
            return

        minutes = max(1, settings.ROOM_INVITE_TTL // 60)
        if topic_url:
            text = (f"Комната «{escape(room.title)}» — топик в закрытой супергруппе сообщества.\n"
                    f"Если вы уже в супергруппе, открывайте топик сразу.")
            if invite_link:
                text += (f"\nЕсли ещё нет — ссылка-приглашение действует {minutes} мин. "
                         f"и только для вас.")
        else:
            text = (f"Комната «{escape(room.title)}» — это группа в Telegram.\n"
                    f"Ссылка действует {minutes} мин. и только для вас.")

        await message.answer(
            text,
            reply_markup=native_invite_keyboard(invite_link, room.id or 0, topic_url)
        )

    async def _enter_relay(self, message: types.Message, state: FSMContext, room: Room) -> None:
        await state.set_state(RoomStates.chatting)
        await state.update_data(room_id=room.id)

        history = await self.room_service.history(room.id)
        if history:
            await message.answer(self._history_text(history))

        await message.answer(
            f"Вы в комнате «{escape(room.title)}». Всё, что вы напишете, "
            f"увидят остальные участники.\n"
            f"Выйти из чата — кнопка ниже или /room_exit.",
            reply_markup=room_chat_keyboard(room.id or 0)
        )

    async def _clear_chatting(self, state: FSMContext) -> bool:
        """Снимает состояние чата комнаты, не задевая состояния других сценариев."""
        if await state.get_state() != RoomStates.chatting.state:
            return False
        await state.clear()
        return True

    # ---------- каталог ----------

    async def rooms_command(self, message: types.Message, state: FSMContext) -> None:
        # Каталог нельзя открывать, оставаясь в режиме чата: следующая реплика
        # уехала бы в комнату вместо ответа на кнопку
        if await self._clear_chatting(state):
            await message.answer("Вы вышли из чата комнаты.")
        await self._show_catalog(message)

    async def list_callback(self, call: types.CallbackQuery, state: FSMContext) -> None:
        await self._clear_chatting(state)
        await self._show_catalog(call.message)
        await call.answer()

    async def filter_callback(self, call: types.CallbackQuery) -> None:
        interests = await self.interest_service.list_active()
        if not interests:
            await call.answer("Справочник интересов пуст.", show_alert=True)
            return
        await call.message.answer("Выберите интерес:", reply_markup=room_interests_keyboard(interests))
        await call.answer()

    async def pick_interest_callback(self, call: types.CallbackQuery, callback_data: RoomCB) -> None:
        interest_id = callback_data.interest_id or None
        await self._show_catalog(call.message, interest_id)
        await call.answer()

    async def open_room_callback(self, call: types.CallbackQuery, callback_data: RoomCB) -> None:
        room = await self.room_service.get_room(callback_data.room_id)
        if room is None or not room.is_active:
            await call.answer("Комната недоступна.", show_alert=True)
            return

        is_member = await self.room_service.is_member(call.from_user.id, room.id)
        text = (f"<b>{escape(room.title)}</b>\n"
                f"{escape(room.description) if room.description else 'Без описания.'}\n\n"
                f"Участников: {room.member_count}/{room.member_limit}\n"
                f"Формат: {self._mode_hint(room)}\n")
        if room.topic_url:
            text += f'Топик: <a href="{room.topic_url}">открыть</a>\n'
        text += "Вы уже участник." if is_member else ""
        await call.message.answer(text, reply_markup=room_card_keyboard(room, is_member))
        await call.answer()

    # ---------- вход, выход, история ----------

    async def join_callback(self, call: types.CallbackQuery, callback_data: RoomCB,
                            state: FSMContext) -> None:
        user_id = call.from_user.id
        room_id = callback_data.room_id

        if not await self.room_service.is_member(user_id, room_id):
            joined, reason = await self.room_service.join(user_id, room_id)
            if not joined:
                await call.answer(reason, show_alert=True)
                return
            await call.message.answer(reason)

        room = await self.room_service.get_room(room_id)
        if room is None or not room.is_active:
            await call.answer("Комната недоступна.", show_alert=True)
            return

        if room.is_native:
            await self._enter_native(call.message, call.bot, room)
        else:
            await self._enter_relay(call.message, state, room)
        await call.answer()

    async def leave_callback(self, call: types.CallbackQuery, callback_data: RoomCB,
                             state: FSMContext) -> None:
        left, reason = await self.room_service.leave(call.from_user.id, callback_data.room_id)

        data = await state.get_data()
        if data.get("room_id") == callback_data.room_id:
            await self._clear_chatting(state)

        await call.message.answer(reason)
        await call.answer()

    async def history_callback(self, call: types.CallbackQuery, callback_data: RoomCB) -> None:
        room = await self.room_service.get_room(callback_data.room_id)
        if room is None:
            await call.answer("Комната недоступна.", show_alert=True)
            return
        if room.is_native:
            await call.answer("История такой комнаты хранится в самой группе.", show_alert=True)
            return

        history = await self.room_service.history(room.id)
        await call.message.answer(self._history_text(history))
        await call.answer()

    async def complain_callback(self, call: types.CallbackQuery, callback_data: RoomCB) -> None:
        room = await self.room_service.get_room(callback_data.room_id)
        if room is None:
            await call.answer("Комната недоступна.", show_alert=True)
            return

        user = await self.user_service.get_user_by_id(call.from_user.id)
        reporter = f"@{escape(user.tg_username)}" if user and user.tg_username else f"ID: {call.from_user.id}"
        text = (f"Жалоба на комнату «{escape(room.title)}» (id {room.id})\n"
                f"От: <b>{reporter}</b> ({call.from_user.id})")

        delivered = 0
        for admin_id in settings.ADMIN_IDS:
            if await safe_send_message(call.bot, admin_id, text):
                delivered += 1
        if not delivered:
            logger.error(f"Жалоба на комнату {room.id} не доставлена ни одному админу.")

        await call.message.answer("Жалоба отправлена администратору.")
        await call.answer()

    async def exit_callback(self, call: types.CallbackQuery, state: FSMContext) -> None:
        if await self._clear_chatting(state):
            await call.message.answer("Вы вышли из чата комнаты. Участником комнаты вы остались.")
        else:
            await call.message.answer("Вы уже не в чате комнаты.")
        await call.answer()

    async def room_exit_command(self, message: types.Message, state: FSMContext) -> None:
        if await self._clear_chatting(state):
            await message.answer("Вы вышли из чата комнаты. Участником комнаты вы остались.")
        else:
            await message.answer("Вы сейчас не в чате комнаты.")

    # ---------- режим чата (relay) ----------

    async def relay_message(self, message: types.Message, state: FSMContext) -> None:
        data = await state.get_data()
        room_id = data.get("room_id")

        if not room_id:
            await state.clear()
            await message.answer("Комната потерялась. Откройте каталог заново: /rooms")
            return

        allowed, reason = await self.room_service.can_write(message.chat.id, room_id)
        if not allowed:
            await state.clear()
            await message.answer(f"{reason}\nКаталог комнат: /rooms")
            return

        if not (message.text or "").strip():
            await message.answer("Сообщение не может быть пустым.")
            return

        recipients = await self.room_service.broadcast(room_id, message.chat.id, message.text)
        if recipients == 0:
            await message.answer("В комнате пока нет других участников — сообщение сохранено в истории.")

    async def relay_message_invalid(self, message: types.Message, state: FSMContext) -> None:
        # В комнату уходит только текст: медиа веером рассылать нельзя
        # (лимиты Telegram и невозможность экранировать подписи одинаково)
        await message.answer("В комнату можно отправить только текст. "
                             "Выйти из чата — /room_exit")

    # ---------- сообщество ----------

    async def community_command(self, message: types.Message) -> None:
        """Выдаёт участнику одноразовое приглашение в супергруппу сообщества."""
        if self.community_service is None:
            logger.error("CommunityService не передан в RoomHandlers, /community не работает")
            await message.answer("Сообщество ещё не настроено. Напишите администратору: /support")
            return

        community = await self.community_service.get()
        if community is None:
            await message.answer("Администратор ещё не настроил сообщество — "
                                 "закрытая супергруппа не привязана. Напишите ему: /support")
            return

        invite_link, reason = await self.community_service.invite_link(
            message.bot, for_user_id=message.chat.id
        )
        if not invite_link:
            await message.answer("Не удалось выдать приглашение в сообщество.\n"
                                 f"Причина: {escape(reason)}\n"
                                 "Напишите администратору: /support")
            return

        minutes = max(1, settings.ROOM_INVITE_TTL // 60)
        title = escape(community.title) if community.title else "сообщество"
        await message.answer(
            f"«{title}» — закрытая супергруппа сообщества.\n"
            f"Ссылка действует {minutes} мин. и только для вас, передавать её нельзя.\n"
            f"Разделы внутри — топики; список комнат: /rooms",
            reply_markup=community_invite_keyboard(invite_link)
        )

    async def community_bind_command(self, message: types.Message) -> None:
        """Привязывает супергруппу сообщества; вызывается В САМОЙ супергруппе.

        chat.id и chat.title берутся из апдейта: это надёжнее ввода id руками,
        а получить их иначе бот и не может — создать супергруппу он не умеет.
        """
        if self.community_service is None:
            logger.error("CommunityService не передан в RoomHandlers, /community_bind не работает")
            await message.answer("Сообщество не подключено к боту: нужна правка main.py.")
            return

        chat = message.chat
        if chat.type == "private":
            await message.answer("Эту команду надо отправить В САМОЙ супергруппе сообщества — "
                                 "id чата бот берёт из апдейта.\n\n" + SETUP_INSTRUCTION)
            return

        if chat.type != "supergroup":
            await message.answer("Это не супергруппа, а "
                                 f"{escape(chat.type)} — топиков здесь не бывает.\n\n"
                                 + SETUP_INSTRUCTION)
            return

        if not chat.is_forum:
            await message.answer("В этой супергруппе не включён режим форума, поэтому топиков "
                                 "в ней нет.\nУправление группой → Темы (Topics) → включить, "
                                 "потом повторите /community_bind")
            return

        ok, reason = await self.community_service.bind(chat.id, chat.title)
        answer = escape(reason)

        rights_ok, rights_reason = await self.community_service.bot_rights(message.bot, chat.id)
        if not rights_ok:
            answer += f"\n\nНо работать это пока не будет: {escape(rights_reason)}."
        else:
            answer += ("\n\nПрав боту хватает. Создавайте комнаты: "
                       "/room_create native - Название | Описание")
        await message.answer(answer)

    async def community_unbind_command(self, message: types.Message) -> None:
        if self.community_service is None:
            await message.answer("Сообщество не подключено к боту: нужна правка main.py.")
            return
        ok, reason = await self.community_service.unbind()
        await message.answer(escape(reason))

    # ---------- админские команды ----------

    @staticmethod
    def _parse_ints(raw: str, count: int) -> Optional[List[int]]:
        parts = (raw or "").split()
        if len(parts) < count:
            return None
        values = []
        for part in parts[:count]:
            if not part.lstrip("-").isdigit():
                return None
            values.append(int(part))
        return values

    async def room_create_command(self, message: types.Message, command: CommandObject) -> None:
        hint = ("Формат: /room_create &lt;relay|native&gt; &lt;id интереса или -&gt; "
                "&lt;название&gt; | &lt;описание&gt;\n"
                "Например: /room_create relay 3 Настолки | Играем по вечерам\n\n"
                "native — комната становится топиком супергруппы сообщества "
                "(нужен привязанный /community_bind), relay — чат через бота "
                "для тех, кого в супергруппе нет.")
        raw = (command.args or "").strip()
        if not raw:
            await message.answer(hint)
            return

        head, _, description = raw.partition("|")
        parts = head.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer(hint)
            return

        mode, interest_raw, title = parts[0].lower(), parts[1], parts[2].strip()
        if mode not in ROOM_MODES:
            await message.answer(hint)
            return

        if interest_raw in ("-", "0"):
            interest_id = None
        elif interest_raw.isdigit():
            interest_id = int(interest_raw)
        else:
            await message.answer(hint)
            return

        room, reason = await self.room_service.create_room(
            title=title, interest_id=interest_id, description=description, mode=mode,
            bot=message.bot
        )
        if room is None:
            await message.answer(escape(reason))
            return

        answer = escape(reason)
        if room.is_topic:
            answer += "\n\nТопик создан ботом, участники попадут в него через /rooms."
        elif room.is_native:
            answer += ("\n\nСоздать группу бот не может. Создайте супергруппу сами, "
                       "добавьте бота администратором с правом приглашать по ссылке "
                       f"и отправьте в этой группе: /room_bind {room.id}")
        await message.answer(answer)

    async def room_bind_command(self, message: types.Message, command: CommandObject) -> None:
        hint = ("Формат: /room_bind &lt;id комнаты&gt;\n"
                "Команду надо отправить В САМОЙ супергруппе: id чата бот берёт из апдейта.\n"
                "Отправите внутри топика — комната привяжется к этому топику.")
        if message.chat.type not in ("group", "supergroup"):
            await message.answer(hint)
            return

        values = self._parse_ints(command.args or "", 1)
        if not values:
            await message.answer(hint)
            return

        # message_thread_id заполнен и у обычного ответа в ветке, поэтому топиком
        # его считаем только при is_topic_message
        thread_id = message.message_thread_id if message.is_topic_message else None
        ok, reason = await self.room_service.bind_native(values[0], message.chat.id, thread_id)
        answer = escape(reason)
        if ok and message.chat.type == "group":
            answer += ("\n\nЭто обычная группа. Лучше повысить её до супергруппы: "
                       "ссылки-приглашения и модерация там работают полнее.")
        await message.answer(answer)

    async def room_mute_command(self, message: types.Message, command: CommandObject) -> None:
        hint = ("Формат: /room_mute &lt;id комнаты&gt; &lt;id пользователя&gt; &lt;минуты&gt;\n"
                "0 минут снимает мьют.")
        values = self._parse_ints(command.args or "", 3)
        if not values:
            await message.answer(hint)
            return

        room_id, user_id, minutes = values
        ok, reason = await self.room_service.mute(room_id, user_id, minutes)
        await message.answer(escape(reason))

    async def room_ban_command(self, message: types.Message, command: CommandObject) -> None:
        hint = "Формат: /room_ban &lt;id комнаты&gt; &lt;id пользователя&gt; [причина]"
        raw = (command.args or "").strip()
        values = self._parse_ints(raw, 2)
        if not values:
            await message.answer(hint)
            return

        parts = raw.split(maxsplit=2)
        reason_text = parts[2].strip() if len(parts) > 2 else None
        ok, reason = await self.room_service.ban(values[0], values[1], reason_text)
        await message.answer(escape(reason))

    async def room_unban_command(self, message: types.Message, command: CommandObject) -> None:
        hint = "Формат: /room_unban &lt;id комнаты&gt; &lt;id пользователя&gt;"
        values = self._parse_ints(command.args or "", 2)
        if not values:
            await message.answer(hint)
            return

        ok, reason = await self.room_service.unban(values[0], values[1])
        await message.answer(escape(reason))

    def get_router(self, is_registered_filter: IsRegistered, is_admin_filter: IsAdmin) -> Router:
        # not_command нужен, чтобы команды не съедались хендлером состояния чата:
        # иначе "/rooms" или "/support" уехали бы текстом всем участникам комнаты.
        # Fallback ловит только нетекстовые сообщения и регистрируется после
        # основного: в aiogram 3 порядок регистрации задаёт приоритет.
        not_command = ~F.text.startswith("/")

        self.router.message.register(self.rooms_command, Command("rooms"), is_registered_filter)
        self.router.message.register(self.room_exit_command, Command("room_exit"), is_registered_filter)
        self.router.message.register(self.community_command, Command("community"), is_registered_filter)

        # /room_bind и /community_bind вызываются в супергруппе, поэтому проверка
        # регистрации к ним не применяется — там важны только права админа бота
        self.router.message.register(self.room_create_command, Command("room_create"), is_admin_filter)
        self.router.message.register(self.room_bind_command, Command("room_bind"), is_admin_filter)
        self.router.message.register(self.community_bind_command, Command("community_bind"),
                                     is_admin_filter)
        self.router.message.register(self.community_unbind_command, Command("community_unbind"),
                                     is_admin_filter)
        self.router.message.register(self.room_mute_command, Command("room_mute"), is_admin_filter)
        self.router.message.register(self.room_ban_command, Command("room_ban"), is_admin_filter)
        self.router.message.register(self.room_unban_command, Command("room_unban"), is_admin_filter)

        self.router.callback_query.register(self.list_callback, RoomCB.filter(F.action == "list"),
                                            is_registered_filter)
        self.router.callback_query.register(self.filter_callback, RoomCB.filter(F.action == "filter"),
                                            is_registered_filter)
        self.router.callback_query.register(self.pick_interest_callback, RoomCB.filter(F.action == "pick"),
                                            is_registered_filter)
        self.router.callback_query.register(self.open_room_callback, RoomCB.filter(F.action == "open"),
                                            is_registered_filter)
        self.router.callback_query.register(self.join_callback, RoomCB.filter(F.action == "join"),
                                            is_registered_filter)
        self.router.callback_query.register(self.leave_callback, RoomCB.filter(F.action == "leave"),
                                            is_registered_filter)
        self.router.callback_query.register(self.history_callback, RoomCB.filter(F.action == "history"),
                                            is_registered_filter)
        self.router.callback_query.register(self.complain_callback, RoomCB.filter(F.action == "complain"),
                                            is_registered_filter)
        self.router.callback_query.register(self.exit_callback, RoomCB.filter(F.action == "exit"),
                                            is_registered_filter)

        self.router.message.register(self.relay_message, StateFilter(RoomStates.chatting), F.text, not_command)
        self.router.message.register(self.relay_message_invalid, StateFilter(RoomStates.chatting), not_command)
        return self.router
