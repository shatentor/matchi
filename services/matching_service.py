import logging
from typing import List, Optional, Tuple

from config.settings import settings
from db.repositories.user_repo import UserRepository
from db.repositories.like_repo import LikeRepository
from db.repositories.dislike_repo import DislikeRepository
from db.repositories.sticker_repo import StickerRepository

logger = logging.getLogger(__name__)


class MatchingService:
    def __init__(self, user_repo: UserRepository, like_repo: LikeRepository,
                 dislike_repo: DislikeRepository, sticker_repo: StickerRepository):
        self.user_repo = user_repo
        self.like_repo = like_repo
        self.dislike_repo = dislike_repo
        self.sticker_repo = sticker_repo

    async def get_profiles_for_user(self, current_user_id: int) -> List[str]:
        current_user = await self.user_repo.get_by_id(str(current_user_id))
        if not current_user or current_user.is_registered != 'yes':
            return []  # Только зарегистрированные пользователи могут искать

        return await self.user_repo.get_candidate_ids(
            tg_chat_id=str(current_user_id),
            limit=settings.CANDIDATES_LIMIT,
        )

    async def process_like(self, liker_id: int, liked_id: int) -> Tuple[bool, bool, Optional[str]]:
        """
        Обрабатывает лайк. Возвращает (успешно ли лайкнул, есть ли взаимный лайк, ID стикера).
        """
        liker_id_str = str(liker_id)
        liked_id_str = str(liked_id)

        if await self.like_repo.has_liked(liker_id_str, liked_id_str):
            return False, False, None  # Уже лайкнул

        await self.like_repo.add_like(liker_id_str, liked_id_str)

        is_mutual = await self.like_repo.is_mutual_like_pair(liker_id_str, liked_id_str)
        sticker_id = await self.sticker_repo.get_random_sticker_id() if is_mutual else None

        return True, is_mutual, sticker_id

    async def process_dislike(self, disliker_id: int, disliked_id: int) -> bool:
        """
        Обрабатывает дизлайк. Возвращает True, если дизлайк новый.
        """
        disliker_id_str = str(disliker_id)
        disliked_id_str = str(disliked_id)

        if await self.dislike_repo.has_disliked(disliker_id_str, disliked_id_str):
            return False

        try:
            await self.dislike_repo.add_dislike(disliker_id_str, disliked_id_str)
            return True
        except Exception as e:
            logger.error(f"Не удалось добавить дизлайк {disliker_id_str} -> {disliked_id_str}: {e}")
            return False

    async def get_mutual_likes(self, tg_chat_id: int) -> List[str]:
        return await self.like_repo.get_mutual_likes_for_user(str(tg_chat_id))
