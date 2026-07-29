import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError

from config.settings import settings
from db.repositories.community_repo import CommunityRepository
from models.community import Community, topic_link

logger = logging.getLogger(__name__)

# community.title объявлен VARCHAR(120), а Telegram допускает название чата
# до 128 символов — режем сами, иначе получим ошибку вставки.
MAX_TITLE_LENGTH = 120
# Ограничения Telegram: name у ссылки-приглашения — 32 символа,
# name у форум-топика — 1..128 символов.
INVITE_NAME_LENGTH = 32
TOPIC_NAME_LENGTH = 128
# Ссылка-приглашение выдаётся одному человеку, поэтому одноразовая.
INVITE_MEMBER_LIMIT = 1

# Что владелец делает руками: бот не может ни создать супергруппу, ни включить
# в ней темы, ни выдать себе права — всё это доступно только человеку.
SETUP_INSTRUCTION = (
    "Бот не может создать супергруппу сам — её создаёт человек. Порядок такой:\n"
    "1. Создайте закрытую супергруппу.\n"
    "2. Включите в ней темы: Управление группой → Темы (Topics).\n"
    "3. Добавьте бота в группу и сделайте администратором с правами "
    "«Управление темами» и «Пригласительные ссылки».\n"
    "4. Отправьте в этой группе команду /community_bind"
)


def explain_api_error(error: TelegramAPIError) -> str:
    """Переводит ошибку Telegram в понятное админу «чего именно не хватает».

    Telegram отвечает на нехватку прав обычным Bad Request с текстом, разбирать
    приходится по нему: отдельного класса исключения для каждого случая нет.
    """
    text = str(getattr(error, "message", "") or error).lower()

    if isinstance(error, TelegramForbiddenError) or "bot was kicked" in text or "bot is not a member" in text:
        return "бот не состоит в этой супергруппе (его удалили или он туда не добавлен)"
    if "not enough rights" in text or "chat_admin_required" in text or "administrator rights" in text:
        return ("боту не хватает прав администратора. Нужны «Управление темами» "
                "(can_manage_topics) и «Пригласительные ссылки»")
    if "topic" in text or "forum" in text:
        return ("в супергруппе не включён режим форума. Управление группой → Темы, "
                "потом повторите")
    if "chat not found" in text:
        return "чат не найден: бота убрали из группы или id устарел"
    return f"Telegram ответил ошибкой: {error}"


class CommunityService:
    """Одна закрытая супергруппа сообщества с форум-топиками.

    Бот не может создать супергруппу — её создаёт человек и добавляет бота
    администратором. Зато бот может создавать в ней топики методом
    create_forum_topic, если у него есть право can_manage_topics и у самой
    супергруппы включён режим форума (chat.is_forum).
    """

    def __init__(self, community_repo: CommunityRepository):
        self.community_repo = community_repo

    # ---------- чтение ----------

    async def get(self) -> Optional[Community]:
        return await self.community_repo.get()

    async def get_chat_id(self) -> Optional[int]:
        community = await self.community_repo.get()
        return community.chat_id if community else None

    def topic_url(self, chat_id: Optional[int], thread_id: Optional[int]) -> Optional[str]:
        return topic_link(chat_id, thread_id)

    # ---------- привязка ----------

    async def bind(self, chat_id: int, title: Optional[str] = None) -> Tuple[bool, str]:
        """Сохраняет супергруппу сообщества.

        Проверку типа чата и включённых тем делает хендлер: только у него есть
        объект Chat из апдейта, а второй запрос get_chat ради этого лишний.
        """
        clean_title = (title or "").strip()[:MAX_TITLE_LENGTH] or None
        community = await self.community_repo.bind(chat_id, clean_title)
        name = community.title or str(community.chat_id)
        return True, f"Супергруппа «{name}» привязана как сообщество."

    async def unbind(self) -> Tuple[bool, str]:
        if await self.community_repo.get() is None:
            return False, "Сообщество и так не привязано."
        await self.community_repo.unbind()
        return True, "Привязка сообщества снята. Комнаты-топики останутся без ссылок."

    # ---------- права бота ----------

    async def bot_rights(self, bot: Bot, chat_id: int) -> Tuple[bool, str]:
        """Проверяет, что бот админ супергруппы и может управлять топиками.

        Проверка отдельная и заранее, чтобы админ узнал о нехватке прав при
        привязке, а не при первой попытке создать комнату.
        """
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=bot.id)
        except TelegramAPIError as e:
            logger.error(f"Не удалось прочитать права бота в чате {chat_id}: {e}")
            return False, explain_api_error(e)

        if member.status not in ("administrator", "creator"):
            return False, ("бот не администратор этой группы. Дайте ему права администратора "
                           "с «Управление темами» и «Пригласительные ссылки»")

        # У creator прав всегда достаточно, но ботов владельцами не делают;
        # у administrator can_manage_topics может быть не выдан.
        if getattr(member, "can_manage_topics", None) is False:
            return False, ("боту не выдано право «Управление темами» (can_manage_topics) — "
                           "без него он не создаст ни одного топика")
        if getattr(member, "can_invite_users", None) is False:
            return False, ("боту не выдано право «Пригласительные ссылки» (can_invite_users) — "
                           "без него он не выдаст ссылку в сообщество")
        return True, ""

    # ---------- приглашение ----------

    async def invite_link(self, bot: Bot, for_user_id: Optional[int] = None) -> Tuple[Optional[str], str]:
        """Одноразовая ссылка-приглашение в супергруппу сообщества.

        member_limit=1 и срок settings.ROOM_INVITE_TTL: ссылка выдаётся лично и
        не должна расходиться дальше. Название ссылки помогает админу понять в
        списке приглашений, кому она выдавалась.
        """
        chat_id = await self.get_chat_id()
        if chat_id is None:
            return None, ("Сообщество ещё не настроено администратором. "
                          "Напишите ему: /support")

        name = f"matchi-{for_user_id}" if for_user_id else "matchi-community"
        expire_date = datetime.now(timezone.utc) + timedelta(seconds=settings.ROOM_INVITE_TTL)
        try:
            link = await bot.create_chat_invite_link(
                chat_id=chat_id,
                name=name[:INVITE_NAME_LENGTH],
                expire_date=expire_date,
                member_limit=INVITE_MEMBER_LIMIT,
            )
        except TelegramAPIError as e:
            logger.error(f"Не удалось создать приглашение в сообщество {chat_id}: {e}")
            return None, explain_api_error(e)

        return link.invite_link, ""

    # ---------- топики ----------

    async def create_topic(self, bot: Bot, name: str) -> Tuple[Optional[int], str]:
        """Создаёт форум-топик в супергруппе сообщества и возвращает его thread_id.

        Это единственный способ для бота завести «место» в сообществе: саму
        супергруппу он создать не может, а топик — может, при праве
        can_manage_topics и включённом режиме форума.
        """
        chat_id = await self.get_chat_id()
        if chat_id is None:
            return None, ("Супергруппа сообщества не привязана — топик создавать негде.\n\n"
                          + SETUP_INSTRUCTION)

        clean_name = (name or "").strip()[:TOPIC_NAME_LENGTH]
        if not clean_name:
            return None, "Название топика не может быть пустым."

        try:
            topic = await bot.create_forum_topic(chat_id=chat_id, name=clean_name)
        except TelegramAPIError as e:
            logger.error(f"Не удалось создать топик «{clean_name}» в сообществе {chat_id}: {e}")
            return None, f"Топик не создан: {explain_api_error(e)}."

        return topic.message_thread_id, ""
