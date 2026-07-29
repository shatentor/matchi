import logging
from typing import List, Optional

from aiogram import Bot, types
from aiogram.types import ReplyKeyboardRemove

from config.settings import settings
from db.repositories.dialog_repo import DialogRepository
from db.repositories.message_repo import MessageRepository
from db.repositories.user_repo import UserRepository
from keyboards.dialogs import dialog_reply_keyboard
from models.dialog import Dialog
from models.message import Message
from utils.telegram import safe_send_message, send_with_retry
from utils.text import escape

logger = logging.getLogger(__name__)

# Telegram обрезает сообщение длиннее 4096 символов, а к тексту автора мы
# добавляем заголовок с его именем — оставляем запас под заголовок.
MAX_RELAY_TEXT_LENGTH = 3500


class DialogService:
    """Личные диалоги: релей сообщений между двумя пользователями.

    Экземпляр Bot нужен только для уведомлений второму участнику (он в этот
    момент не отправлял апдейт, взять bot из его сообщения нельзя). Его можно
    либо задать один раз через set_bot_instance, либо передать в вызов
    аргументом bot — без него уведомление просто не уйдёт.
    """

    def __init__(self, dialog_repo: DialogRepository, message_repo: MessageRepository,
                 user_repo: UserRepository):
        self.dialog_repo = dialog_repo
        self.message_repo = message_repo
        self.user_repo = user_repo
        self.bot: Optional[Bot] = None

    def set_bot_instance(self, bot_instance: Bot) -> None:
        self.bot = bot_instance

    def _bot(self, bot: Optional[Bot] = None) -> Optional[Bot]:
        return bot or self.bot

    async def _display_name(self, tg_chat_id: int) -> str:
        """Готовое к подстановке в HTML имя пользователя."""
        user = await self.user_repo.get_by_id(str(tg_chat_id))
        if user and user.name:
            return escape(user.name)
        if user and user.tg_username:
            return f"@{escape(user.tg_username)}"
        return f"ID: {tg_chat_id}"

    async def start(self, initiator_id: int, peer_id: int, source: str = "profile",
                    bot: Optional[Bot] = None) -> Dialog:
        """Открывает диалог с собеседником или возвращает уже открытый.

        У пользователя может быть только один активный диалог: иначе неясно,
        кому релеить его следующее сообщение. Поэтому прежние диалоги обоих
        участников закрываются, а их брошенные собеседники получают уведомление.
        """
        if initiator_id == peer_id:
            raise ValueError("Нельзя открыть диалог с самим собой")

        initiator, peer = str(initiator_id), str(peer_id)

        existing = await self.dialog_repo.get_active_pair(initiator, peer)
        if existing:
            return existing

        for participant in (initiator, peer):
            stale = await self.dialog_repo.get_active_for_user(participant)
            if stale and stale.id is not None:
                await self.dialog_repo.close_dialog(stale.id)
                await self._notify_dropped(stale, int(participant), bot)

        return await self.dialog_repo.open_dialog(initiator, peer, source)

    async def _notify_dropped(self, dialog: Dialog, left_by: int, bot: Optional[Bot]) -> None:
        """Сообщает брошенному собеседнику, что диалог закрылся."""
        active_bot = self._bot(bot)
        if not active_bot:
            logger.warning("Экземпляр бота не задан, участник диалога %s не уведомлён о закрытии", dialog.id)
            return
        try:
            dropped_id = self.peer_of(dialog, left_by)
        except ValueError:
            return
        await safe_send_message(active_bot, dropped_id,
                                "Собеседник начал другой диалог, ваша переписка закрыта.\n"
                                "Переписка сохранена: /dialogs",
                                reply_markup=ReplyKeyboardRemove())

    async def get_active(self, tg_chat_id: int) -> Optional[Dialog]:
        return await self.dialog_repo.get_active_for_user(str(tg_chat_id))

    def peer_of(self, dialog: Dialog, tg_chat_id: int) -> int:
        """Возвращает собеседника. Пара в строке упорядочена, а не «инициатор/второй»."""
        me = str(tg_chat_id)
        if me == dialog.user_one:
            return int(dialog.user_two)
        if me == dialog.user_two:
            return int(dialog.user_one)
        raise ValueError(f"Пользователь {me} не участник диалога {dialog.id}")

    async def relay(self, bot: Bot, dialog: Dialog, sender_id: int, message: types.Message) -> bool:
        """Пересылает текст собеседнику и сохраняет его в истории.

        В БД пишем plain-текст, собеседнику отправляем html_text — так
        сохраняется форматирование автора и остаётся экранированным всё
        остальное. Отправка через send_with_retry: молча потерять сообщение
        диалога нельзя, в отличие от веерной рассылки.
        """
        peer_id = self.peer_of(dialog, sender_id)
        plain_text = message.text or ""

        if not plain_text.strip():
            await message.answer("Пустое сообщение отправить нельзя.")
            return False

        if len(message.html_text) > MAX_RELAY_TEXT_LENGTH:
            await message.answer("Сообщение слишком длинное, отправьте его частями.")
            return False

        sender_name = await self._display_name(sender_id)
        delivered = await send_with_retry(
            bot, peer_id,
            f"💬 <b>{sender_name}</b>:\n{message.html_text}",
            reply_markup=dialog_reply_keyboard(sender_id)
        )

        if not delivered:
            if dialog.id is not None:
                await self.dialog_repo.close_dialog(dialog.id)
            await message.answer("Сообщение не доставлено: собеседник недоступен для бота. "
                                 "Диалог закрыт.", reply_markup=ReplyKeyboardRemove())
            return False

        # Сохраняем только доставленное, чтобы история не расходилась с тем,
        # что собеседник действительно видел.
        await self.message_repo.create_message(Message(
            sender_chat_id=str(sender_id),
            receiver_chat_id=str(peer_id),
            message_text=plain_text,
        ))
        return True

    async def relay_copy(self, bot: Bot, dialog: Dialog, sender_id: int,
                         message: types.Message) -> bool:
        """Пересылает нетекстовое вложение копией.

        copy_message, а не forward_message: копия не раскрывает исходный чат
        и имя отправителя. В таблице messages вложение не сохраняется —
        message_text там NOT NULL и хранить file_id вместо текста нельзя.
        """
        peer_id = self.peer_of(dialog, sender_id)
        sender_name = await self._display_name(sender_id)

        header = await send_with_retry(bot, peer_id, f"💬 <b>{sender_name}</b> прислал(а) вложение:")
        if not header:
            if dialog.id is not None:
                await self.dialog_repo.close_dialog(dialog.id)
            await message.answer("Вложение не доставлено: собеседник недоступен для бота. "
                                 "Диалог закрыт.", reply_markup=ReplyKeyboardRemove())
            return False

        try:
            await bot.copy_message(chat_id=peer_id, from_chat_id=message.chat.id,
                                   message_id=message.message_id,
                                   reply_markup=dialog_reply_keyboard(sender_id))
            return True
        except Exception as e:
            logger.warning("Не удалось скопировать вложение в чат %s: %s", peer_id, e)
            await message.answer("Такое вложение переслать не удалось. Попробуйте текстом.")
            return False

    async def close(self, dialog: Dialog, closed_by: int, bot: Optional[Bot] = None) -> None:
        """Закрывает диалог и уведомляет второго участника."""
        if dialog.id is not None:
            await self.dialog_repo.close_dialog(dialog.id)

        active_bot = self._bot(bot)
        if not active_bot:
            logger.warning("Экземпляр бота не задан, собеседник не уведомлён о закрытии диалога %s", dialog.id)
            return

        try:
            peer_id = self.peer_of(dialog, closed_by)
        except ValueError:
            return

        await safe_send_message(active_bot, peer_id,
                                "Собеседник завершил диалог.\nПереписка сохранена: /dialogs",
                                reply_markup=ReplyKeyboardRemove())

    async def close_all_for_user(self, tg_chat_id: int) -> None:
        await self.dialog_repo.close_all_for_user(str(tg_chat_id))

    async def history(self, a: int, b: int, limit: int = settings.DIALOG_HISTORY_SIZE) -> List[Message]:
        """Последние сообщения между двумя пользователями, от старых к новым.

        get_messages_between_users отдаёт всю переписку по возрастанию времени,
        поэтому лимит применяем здесь: MessageRepository принадлежит другой
        фиче, и добавлять в него параметр ради диалогов не стоит.
        """
        messages = await self.message_repo.get_messages_between_users(str(a), str(b))
        if limit and len(messages) > limit:
            return messages[-limit:]
        return messages

    async def partners(self, tg_chat_id: int, limit: int = settings.DIALOG_HISTORY_SIZE) -> List[int]:
        """ID собеседников, с которыми была переписка, от свежих к старым."""
        dialogs = await self.dialog_repo.get_recent_for_user(str(tg_chat_id), limit)
        peers: List[int] = []
        for dialog in dialogs:
            try:
                peers.append(self.peer_of(dialog, tg_chat_id))
            except ValueError:
                logger.warning("Диалог %s не содержит пользователя %s", dialog.id, tg_chat_id)
        return peers
