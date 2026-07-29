import logging
from contextlib import suppress
from typing import List, Optional, Tuple

from aiogram import Router, F, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config.settings import settings
from filters.custom_filters import IsRegistered
from keyboards.dialogs import (DialogCB, RouletteCB, dialog_close_keyboard, dialog_invite_keyboard,
                               dialogs_list_keyboard, roulette_interests_keyboard,
                               roulette_waiting_keyboard)
from keyboards.reply import (DIALOG_COMPLAIN, DIALOG_FINISH, DIALOG_PEER_PROFILE, dialog_keyboard,
                             remove_dialog_keyboard)
from services.dialog_service import DialogService
from services.interest_service import InterestService
from services.roulette_service import RouletteService
from services.support_service import SupportService
from services.user_service import UserService
from utils.telegram import safe_send_media_group, safe_send_message
from utils.text import escape

logger = logging.getLogger(__name__)

# Одно сообщение Telegram — не больше 4096 символов, а история показывается
# целиком одним сообщением, поэтому длинные реплики в ней подрезаются.
HISTORY_LINE_LENGTH = 200

COMPLAIN_FROM_DIALOG_REASON = "Жалоба из личного диалога (без описания)"


class DialogStates(StatesGroup):
    active = State()


class DialogHandlers:
    """Личные диалоги и рулетка по интересам.

    Состояние собеседника поменять нельзя: FSM хранится по его чату, и бот
    видит только автора текущего апдейта. Поэтому второго участника мы не
    «затаскиваем» в диалог, а присылаем ему кнопку («Ответить» под входящим
    сообщением, «Начать общение» в приглашении рулетки) — нажатие уже приходит
    от него самого и переводит в режим диалога его собственное состояние.
    """

    def __init__(self, dialog_service: DialogService, user_service: UserService,
                 support_service: SupportService, interest_service: InterestService,
                 roulette_service: RouletteService):
        self.dialog_service = dialog_service
        self.user_service = user_service
        self.support_service = support_service
        self.interest_service = interest_service
        self.roulette_service = roulette_service
        self.router = Router()

    # ---------- вспомогательное ----------

    async def _display_name(self, tg_chat_id: int) -> str:
        """Имя собеседника, уже экранированное для HTML."""
        user = await self.user_service.get_user_by_id(tg_chat_id)
        if user and user.name:
            return escape(user.name)
        if user and user.tg_username:
            return f"@{escape(user.tg_username)}"
        return f"ID: {tg_chat_id}"

    async def _plain_name(self, tg_chat_id: int) -> str:
        """Имя для подписи кнопки: подписи Telegram разбирает как plain text."""
        user = await self.user_service.get_user_by_id(tg_chat_id)
        if user and user.name:
            return user.name
        if user and user.tg_username:
            return f"@{user.tg_username}"
        return f"ID {tg_chat_id}"

    async def _show_history(self, message: types.Message, me: int, peer_id: int) -> None:
        history = await self.dialog_service.history(me, peer_id, settings.DIALOG_HISTORY_SIZE)
        if not history:
            await message.answer("Переписки с этим пользователем ещё не было.",
                                 reply_markup=dialog_close_keyboard(peer_id))
            return

        peer_name = await self._display_name(peer_id)
        lines = []
        for item in history:
            author = "Вы" if item.sender_chat_id == str(me) else peer_name
            text = item.message_text
            if len(text) > HISTORY_LINE_LENGTH:
                text = text[:HISTORY_LINE_LENGTH] + "…"
            lines.append(f"<b>{author}</b>: {escape(text)}")

        await message.answer("Последние сообщения:\n\n" + "\n".join(lines),
                             reply_markup=dialog_close_keyboard(peer_id))

    async def _enter_dialog(self, message: types.Message, state: FSMContext,
                            me: int, peer_id: int, source: str) -> bool:
        """Переводит пользователя в режим диалога с собеседником."""
        peer = await self.user_service.get_user_by_id(peer_id)
        if not peer:
            await message.answer("Этот пользователь недоступен.")
            return False

        try:
            dialog = await self.dialog_service.start(me, peer_id, source=source, bot=message.bot)
        except ValueError as e:
            logger.warning(f"Не удалось открыть диалог {me}->{peer_id}: {e}")
            await message.answer("Не удалось открыть диалог.")
            return False

        await state.set_state(DialogStates.active)
        await state.update_data(dialog_id=dialog.id, dialog_peer_id=peer_id)

        peer_name = await self._display_name(peer_id)
        await message.answer(f"Диалог с <b>{peer_name}</b> открыт.\n"
                             f"Всё, что вы напишете, уйдёт собеседнику.",
                             reply_markup=dialog_keyboard())
        await self._show_history(message, me, peer_id)
        return True

    async def _exit_dialog(self, message: types.Message, state: FSMContext, text: str) -> None:
        await state.clear()
        await message.answer(text, reply_markup=remove_dialog_keyboard())

    # ---------- вход в диалог ----------

    async def enter_dialog_callback(self, call: types.CallbackQuery, state: FSMContext,
                                    callback_data: DialogCB):
        me = call.from_user.id
        peer_id = callback_data.peer_id

        if not isinstance(call.message, types.Message):
            await call.answer("Сообщение слишком старое, откройте диалог через /dialogs.",
                              show_alert=True)
            return

        if peer_id == me:
            await call.answer("Это ваше собственное сообщение.", show_alert=True)
            return

        await call.answer()
        source = "roulette" if callback_data.action == "accept" else "profile"
        await self._enter_dialog(call.message, state, me, peer_id, source)

    async def decline_dialog_callback(self, call: types.CallbackQuery, callback_data: DialogCB):
        """Отказ от приглашения: диалог, открытый инициатором, закрываем."""
        me = call.from_user.id
        dialog = await self.dialog_service.get_active(me)
        if dialog:
            with suppress(ValueError):
                if self.dialog_service.peer_of(dialog, me) == callback_data.peer_id:
                    await self.dialog_service.close(dialog, me, bot=call.bot)
        await call.answer("Хорошо, не сейчас.")

    async def close_dialog_callback(self, call: types.CallbackQuery, state: FSMContext):
        me = call.from_user.id
        dialog = await self.dialog_service.get_active(me)
        await call.answer()

        if not isinstance(call.message, types.Message):
            return

        if not dialog:
            await self._exit_dialog(call.message, state, "Активного диалога нет.")
            return

        await self.dialog_service.close(dialog, me, bot=call.bot)
        await self._exit_dialog(call.message, state,
                                "Диалог завершён. Переписка сохранена: /dialogs")

    # ---------- кнопки клавиатуры диалога ----------

    async def finish_dialog(self, message: types.Message, state: FSMContext):
        me = message.chat.id
        dialog = await self.dialog_service.get_active(me)

        if not dialog:
            await self._exit_dialog(message, state, "Активного диалога нет.")
            return

        await self.dialog_service.close(dialog, me, bot=message.bot)
        await self._exit_dialog(message, state, "Диалог завершён. Переписка сохранена: /dialogs")

    async def show_peer_profile(self, message: types.Message, state: FSMContext):
        me = message.chat.id
        dialog = await self.dialog_service.get_active(me)

        if not dialog:
            await self._exit_dialog(message, state, "Активного диалога нет.")
            return

        peer_id = self.dialog_service.peer_of(dialog, me)
        profile = await self.user_service.get_user_profile_data(peer_id)
        if not profile:
            await message.answer("Профиль собеседника недоступен.")
            return

        media_group = await self.user_service.get_user_media_group(peer_id)
        if media_group:
            await safe_send_media_group(message.bot, me, media_group)

        await message.answer(f"Имя: <b>{escape(profile.name)}</b>\n"
                             f"Возраст: {profile.age}\n"
                             f"Город: {escape(profile.city)}\n\n"
                             f"О себе:\n {escape(profile.description)}")

    async def complain_on_peer(self, message: types.Message, state: FSMContext):
        """Жалоба на собеседника: диалог закрывается сразу, без ввода причины.

        Отдельное состояние для текста жалобы здесь не заводится намеренно:
        пока пользователь его набирал бы, он оставался бы в переписке с тем,
        на кого жалуется. Подробности админ уточнит сам по /complains.
        """
        me = message.chat.id
        dialog = await self.dialog_service.get_active(me)

        if not dialog:
            await self._exit_dialog(message, state, "Активного диалога нет.")
            return

        peer_id = self.dialog_service.peer_of(dialog, me)
        complain = await self.support_service.create_user_complain(me, peer_id,
                                                                  COMPLAIN_FROM_DIALOG_REASON)

        reporter_name = await self._display_name(me)
        reported_name = await self._display_name(peer_id)
        for admin_id in settings.ADMIN_IDS:
            await safe_send_message(message.bot, admin_id,
                                    f"Жалоба из диалога от <b>{reporter_name}</b> ({me}) "
                                    f"на <b>{reported_name}</b> ({peer_id}).\n"
                                    f"ID жалобы: {complain.id}")

        await self.dialog_service.close(dialog, me, bot=message.bot)
        await self._exit_dialog(message, state,
                                "Жалоба отправлена администратору, диалог закрыт.")

    # ---------- релей ----------

    async def relay_text(self, message: types.Message, state: FSMContext):
        me = message.chat.id
        dialog = await self.dialog_service.get_active(me)

        if not dialog:
            await self._exit_dialog(message, state,
                                    "Диалог уже закрыт. Открыть переписку заново: /dialogs")
            return

        delivered = await self.dialog_service.relay(message.bot, dialog, me, message)
        # relay закрывает диалог, если доставка не удалась, и сам сообщает об этом,
        # состояние снимаем здесь — FSM принадлежит хендлеру
        if not delivered and await self.dialog_service.get_active(me) is None:
            await state.clear()

    async def relay_non_text(self, message: types.Message, state: FSMContext):
        me = message.chat.id
        dialog = await self.dialog_service.get_active(me)

        if not dialog:
            await self._exit_dialog(message, state,
                                    "Диалог уже закрыт. Открыть переписку заново: /dialogs")
            return

        delivered = await self.dialog_service.relay_copy(message.bot, dialog, me, message)
        if not delivered and await self.dialog_service.get_active(me) is None:
            await state.clear()

    # ---------- список переписок ----------

    async def cmd_dialogs(self, message: types.Message):
        me = message.chat.id
        peers = await self.dialog_service.partners(me, settings.DIALOG_HISTORY_SIZE)

        if not peers:
            await message.answer("Переписок пока нет. Найдите кого-нибудь: /searchi или /roulette")
            return

        titles: List[Tuple[int, str]] = [(peer_id, await self._plain_name(peer_id)) for peer_id in peers]
        await message.answer("Ваши переписки:", reply_markup=dialogs_list_keyboard(titles))

    # ---------- рулетка ----------

    async def _interest_title(self, interest_id: int) -> Optional[str]:
        for interest in await self.interest_service.list_active():
            if interest.id == interest_id:
                return interest.title
        return None

    async def cmd_roulette(self, message: types.Message):
        me = message.chat.id

        if await self.dialog_service.get_active(me):
            await message.answer("Сначала завершите текущий диалог.")
            return

        interests = await self.interest_service.list_active()
        if not interests:
            await message.answer("Список интересов пока пуст.")
            return

        await message.answer("Выберите интерес — подберём собеседника, которому он тоже интересен:",
                             reply_markup=roulette_interests_keyboard(interests))

    async def roulette_pick(self, call: types.CallbackQuery, state: FSMContext,
                            callback_data: RouletteCB):
        me = call.from_user.id
        interest_id = callback_data.interest_id

        if not isinstance(call.message, types.Message):
            await call.answer("Сообщение слишком старое, начните заново: /roulette", show_alert=True)
            return

        if await self.dialog_service.get_active(me):
            await call.answer("Сначала завершите текущий диалог.", show_alert=True)
            return

        title = await self._interest_title(interest_id)
        if title is None:
            await call.answer("Этот интерес больше недоступен.", show_alert=True)
            return

        peer_id = await self.roulette_service.join(me, interest_id)
        await call.answer()

        if peer_id is None:
            waiting = await self.roulette_service.waiting_count(interest_id)
            await call.message.answer(f"Ищем собеседника по интересу «{escape(title)}».\n"
                                      f"Ждём вместе с вами: {waiting}. "
                                      f"Как только кто-то найдётся, пришлём приглашение.",
                                      reply_markup=roulette_waiting_keyboard(interest_id))
            return

        if not await self._enter_dialog(call.message, state, me, peer_id, "roulette"):
            return

        me_name = await self._display_name(me)
        invited = await safe_send_message(call.bot, peer_id,
                                         f"Нашёлся собеседник по интересу «{escape(title)}»: "
                                         f"<b>{me_name}</b>.",
                                         reply_markup=dialog_invite_keyboard(me))
        if not invited:
            dialog = await self.dialog_service.get_active(me)
            if dialog:
                await self.dialog_service.close(dialog, me, bot=call.bot)
            await self._exit_dialog(call.message, state,
                                    "Собеседник оказался недоступен для бота. Попробуйте ещё раз: /roulette")

    async def roulette_cancel(self, call: types.CallbackQuery, callback_data: RouletteCB):
        await self.roulette_service.leave(call.from_user.id, callback_data.interest_id)
        await call.answer("Поиск отменён.")
        if isinstance(call.message, types.Message):
            with suppress(TelegramAPIError):
                await call.message.edit_reply_markup(reply_markup=None)

    # ---------- сборка роутера ----------

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        # not_command нужен, чтобы команды не уезжали собеседнику текстом:
        # в состоянии диалога релеится ЛЮБОЙ текст, и без этого фильтра
        # "/searchi" стал бы сообщением, а не командой (такой баг здесь уже
        # был в состоянии админской рассылки).
        not_command = ~F.text.startswith("/")
        in_dialog = StateFilter(DialogStates.active)

        self.router.message.register(self.cmd_dialogs, Command("dialogs"), is_registered_filter)
        self.router.message.register(self.cmd_roulette, Command("roulette"), is_registered_filter)

        self.router.callback_query.register(
            self.enter_dialog_callback,
            DialogCB.filter(F.action.in_({"reply", "open", "accept"})),
            is_registered_filter
        )
        self.router.callback_query.register(
            self.decline_dialog_callback,
            DialogCB.filter(F.action == "decline"),
            is_registered_filter
        )
        self.router.callback_query.register(
            self.close_dialog_callback,
            DialogCB.filter(F.action == "close"),
            is_registered_filter
        )
        self.router.callback_query.register(
            self.roulette_pick,
            RouletteCB.filter(F.action == "pick"),
            is_registered_filter
        )
        self.router.callback_query.register(
            self.roulette_cancel,
            RouletteCB.filter(F.action == "cancel"),
            is_registered_filter
        )

        # Кнопки клавиатуры диалога регистрируются ДО общего релея: иначе их
        # текст («✖️ Завершить» и остальные) уехал бы собеседнику сообщением.
        self.router.message.register(self.finish_dialog, in_dialog, F.text == DIALOG_FINISH)
        self.router.message.register(self.show_peer_profile, in_dialog, F.text == DIALOG_PEER_PROFILE)
        self.router.message.register(self.complain_on_peer, in_dialog, F.text == DIALOG_COMPLAIN)

        self.router.message.register(self.relay_text, in_dialog, F.text, not_command)
        # Fallback на нетекстовые сообщения — после основного хендлера состояния
        self.router.message.register(self.relay_non_text, in_dialog, not_command)
        return self.router
