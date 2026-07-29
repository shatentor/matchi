from db.repositories.user_repo import UserRepository
from db.repositories.complain_repo import ComplainRepository
from db.repositories.message_repo import MessageRepository
from models.complain import Complain
from models.message import Message
from config.settings import settings
import time


class SupportService:
    def __init__(self, user_repo: UserRepository, complain_repo: ComplainRepository, message_repo: MessageRepository):
        self.user_repo = user_repo
        self.complain_repo = complain_repo
        self.message_repo = message_repo

    async def check_support_cooldown(self, tg_chat_id: int) -> int:
        """Возвращает 0, если обращаться в поддержку можно, иначе секунды до разблокировки.

        Побочный эффект: при успешной проверке время обращения сразу обновляется,
        поэтому кулдаун стартует с момента вызова, а не с момента отправки текста.
        """
        last_support_time = await self.user_repo.get_support_time(str(tg_chat_id))
        current_time = int(time.time())
        cooldown = settings.SUPPORT_COOLDOWN

        if current_time >= last_support_time + cooldown:
            await self.user_repo.update_support_time(str(tg_chat_id), current_time)
            return 0  # Кулдаун прошел
        else:
            return (last_support_time + cooldown) - current_time

    async def create_user_complain(self, reporter_id: int, reported_id: int, reason: str) -> Complain:
        complain = Complain(reporter_chat_id=str(reporter_id), reported_chat_id=str(reported_id), reason=reason)
        return await self.complain_repo.create_complain(complain)

    async def send_user_message(self, sender_id: int, receiver_id: int, text: str) -> Message:
        message = Message(sender_chat_id=str(sender_id), receiver_chat_id=str(receiver_id), message_text=text)
        return await self.message_repo.create_message(message)