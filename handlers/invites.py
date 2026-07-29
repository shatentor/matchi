import logging
from typing import List, Optional, Sequence

from aiogram import F, Router, types
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config.settings import settings
from filters.custom_filters import IsRegistered
from models.invite import Invite
from services.invite_service import InviteService, format_deadline
from services.user_service import UserService
from utils.text import escape

logger = logging.getLogger(__name__)


class InviteCB(CallbackData, prefix="inv"):
    """callback_data приглашений.

    Фабрика вместо склейки префиксов: склейка в этом проекте уже дала коллизию
    ("message" внутри "message_to_all"), и для новых кнопок так больше не делаем.

    action: revoke
    """
    action: str
    code: str = ""


def invites_keyboard(invites: Sequence[Invite]) -> Optional[types.InlineKeyboardMarkup]:
    """Кнопка отзыва на каждый действующий код.

    Отозвать имеет смысл только действующий код, поэтому у исчерпанных и
    истёкших кнопки нет. None означает «клавиатура не нужна».
    """
    active = [invite for invite in invites if invite.is_active]
    if not active:
        return None

    builder = InlineKeyboardBuilder()
    for invite in active:
        builder.row(types.InlineKeyboardButton(
            text=f"Отозвать {invite.code}",
            callback_data=InviteCB(action="revoke", code=invite.code).pack()
        ))
    return builder.as_markup()


class InviteHandlers:
    """Выдача и отзыв кодов приглашения участником сети."""

    def __init__(self, invite_service: InviteService, user_service: UserService):
        self.invite_service = invite_service
        self.user_service = user_service
        self.router = Router()

    async def _bot_username(self, message: types.Message) -> Optional[str]:
        """@username бота для текста приглашения.

        Нужен, чтобы пересланное сообщение было самодостаточным: получатель
        должен понимать, куда именно вводить код.
        """
        try:
            me = await message.bot.get_me()
        except TelegramAPIError as e:
            logger.warning(f"Не удалось получить username бота для приглашения: {e}")
            return None
        return me.username

    async def _inviter_name(self, tg_chat_id: int) -> Optional[str]:
        user = await self.user_service.get_user_by_id(tg_chat_id)
        return user.name if user and user.name else None

    async def _invite_text(self, message: types.Message, invite: Invite) -> str:
        """Текст приглашения, который не стыдно переслать другу как есть.

        Код стоит отдельной строкой в <code>: так его удобно скопировать
        одним касанием и не зацепить соседние слова.
        """
        username = await self._bot_username(message)
        where = f"@{escape(username)}" if username else "нашего бота"
        name = await self._inviter_name(message.chat.id)
        signature = f"\nПриглашает: <b>{escape(name)}</b>." if name else ""

        return (f"<b>Приглашение в закрытую сеть</b>\n"
                f"Профили, переписки и знакомства только для своих — по коду.{signature}\n\n"
                f"<code>{escape(invite.code)}</code>\n\n"
                f"Как войти: откройте {where}, отправьте /start и введите этот код "
                f"первым шагом.\n"
                f"Код действует до {format_deadline(invite.expires_at)}, "
                f"осталось использований: {invite.uses_left} из {invite.max_uses}.")

    @staticmethod
    def _invite_line(invite: Invite) -> str:
        if invite.revoked:
            note = "отозван"
        elif invite.is_expired:
            note = f"истёк {format_deadline(invite.expires_at)}"
        elif invite.uses_left <= 0:
            note = "исчерпан"
        else:
            note = (f"осталось {invite.uses_left} из {invite.max_uses}, "
                    f"до {format_deadline(invite.expires_at)}")
        return f"<code>{escape(invite.code)}</code> — {note}"

    def _my_invites_text(self, invites: List[Invite]) -> str:
        if not invites:
            return ("У вас пока нет кодов приглашения.\n"
                    f"Получить новый — /invite (до {settings.INVITES_PER_USER} "
                    f"действующих одновременно).")

        active = [invite for invite in invites if invite.is_active]
        spent = len(invites) - len(active)

        lines = [self._invite_line(invite) for invite in active] or ["Действующих кодов нет."]
        blocks = ["<b>Ваши коды приглашения</b>", "\n".join(lines)]
        if spent:
            blocks.append(f"Недействующих кодов: {spent} (отозваны, истекли или исчерпаны).")
        blocks.append(f"Новый код — /invite (до {settings.INVITES_PER_USER} действующих "
                      f"одновременно).")

        return "\n\n".join(blocks)

    async def invite_command(self, message: types.Message) -> None:
        invite, reason = await self.invite_service.issue(message.chat.id)
        if invite is None:
            await message.answer(escape(reason))
            return
        await message.answer(await self._invite_text(message, invite))

    async def my_invites_command(self, message: types.Message) -> None:
        invites = await self.invite_service.my_invites(message.chat.id)
        await message.answer(self._my_invites_text(invites),
                             reply_markup=invites_keyboard(invites))

    async def revoke_callback(self, call: types.CallbackQuery, callback_data: InviteCB) -> None:
        ok, reason = await self.invite_service.revoke(call.from_user.id, callback_data.code)
        if not ok:
            await call.answer(reason, show_alert=True)
            return

        invites = await self.invite_service.my_invites(call.from_user.id)
        text = self._my_invites_text(invites)
        try:
            await call.message.edit_text(text, reply_markup=invites_keyboard(invites))
        except TelegramAPIError as e:
            # Сообщение могло устареть или оказаться неизменным — тогда просто
            # присылаем список заново, чтобы человек увидел результат отзыва.
            logger.info(f"Список кодов не отредактировался, отправляю новым сообщением: {e}")
            await call.message.answer(text, reply_markup=invites_keyboard(invites))
        await call.answer(reason)

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        # Приглашать может только участник сети, поэтому фильтр регистрации
        # висит и на командах, и на кнопке отзыва.
        # Текстовых состояний здесь нет, поэтому not_command не нужен.
        self.router.message.register(self.invite_command, Command("invite"), is_registered_filter)
        self.router.message.register(self.my_invites_command, Command("my_invites"),
                                     is_registered_filter)
        self.router.callback_query.register(self.revoke_callback,
                                            InviteCB.filter(F.action == "revoke"),
                                            is_registered_filter)
        return self.router
