import logging

from aiogram import types, Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command

from config.settings import settings
from filters.custom_filters import IsRegistered
from keyboards.interests import InterestCB, interests_keyboard
from services.interest_service import InterestService
from utils.text import escape

logger = logging.getLogger(__name__)

EMPTY_CATALOG_TEXT = ("Справочник интересов пока пуст — администратор ещё не заполнил его. "
                      "Попробуйте позже.")


class InterestHandlers:
    def __init__(self, interest_service: InterestService):
        self.interest_service = interest_service
        self.router = Router()

    def _hint_text(self, selected_count: int) -> str:
        return (f"<b>Ваши интересы</b>\n\n"
                f"Отметьте до {settings.MAX_USER_INTERESTS} интересов — по ним подбираются анкеты.\n"
                f"Выбрано: {selected_count} из {settings.MAX_USER_INTERESTS}.")

    async def show_interests(self, message: types.Message):
        tg_chat_id = message.chat.id
        active = await self.interest_service.list_active()

        if not active:
            await message.answer(EMPTY_CATALOG_TEXT)
            return

        selected_ids = {interest.id for interest in await self.interest_service.get_user_interests(tg_chat_id)}
        await message.answer(self._hint_text(len(selected_ids)),
                             reply_markup=interests_keyboard(active, selected_ids))

    async def toggle_interest(self, call: types.CallbackQuery, callback_data: InterestCB):
        tg_chat_id = call.from_user.id
        changed, reason = await self.interest_service.toggle(tg_chat_id, callback_data.interest_id)

        if not changed:
            await call.answer(reason, show_alert=True)
            return

        active = await self.interest_service.list_active()
        selected_ids = {interest.id for interest in await self.interest_service.get_user_interests(tg_chat_id)}

        if call.message:
            try:
                # Перерисовываем ту же клавиатуру, чтобы не плодить сообщения в чате
                await call.message.edit_reply_markup(reply_markup=interests_keyboard(active, selected_ids))
            except TelegramBadRequest as e:
                logger.warning(f"Не удалось обновить клавиатуру интересов для {tg_chat_id}: {e}")

        await call.answer(f"{reason} Выбрано: {len(selected_ids)} из {settings.MAX_USER_INTERESTS}.")

    async def finish_interests(self, call: types.CallbackQuery):
        tg_chat_id = call.from_user.id
        selected = await self.interest_service.get_user_interests(tg_chat_id)

        if call.message:
            try:
                await call.message.edit_reply_markup(reply_markup=None)
            except TelegramBadRequest as e:
                logger.warning(f"Не удалось убрать клавиатуру интересов у {tg_chat_id}: {e}")

        if selected:
            titles = "\n".join(f"• {escape(interest.title)}" for interest in selected)
            text = f"Сохранено. Ваши интересы:\n{titles}"
        else:
            text = "Вы не выбрали ни одного интереса. Открыть список снова: /interests"

        if call.message:
            await call.message.answer(text)
        await call.answer()

    def get_router(self, is_registered_filter: IsRegistered) -> Router:
        self.router.message.register(self.show_interests, Command("interests"), is_registered_filter)
        self.router.callback_query.register(self.toggle_interest, InterestCB.filter(F.action == "toggle"),
                                           is_registered_filter)
        self.router.callback_query.register(self.finish_interests, InterestCB.filter(F.action == "done"),
                                           is_registered_filter)
        return self.router
