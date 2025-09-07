import numpy as np
from typing import Optional, List, Tuple
from db.repositories.user_repo import UserRepository
from db.repositories.like_repo import LikeRepository
from db.repositories.sticker_repo import StickerRepository
from models.user import User  # Для фильтрации по полям User


class MatchingService:
    def __init__(self, user_repo: UserRepository, like_repo: LikeRepository, sticker_repo: StickerRepository):
        self.user_repo = user_repo
        self.like_repo = like_repo
        self.sticker_repo = sticker_repo

    async def get_profiles_for_user(self, current_user_id: int) -> np.ndarray:
        current_user = await self.user_repo.get_by_id(str(current_user_id))
        if not current_user or current_user.is_registered != 'yes':
            return np.array([])  # Только зарегистрированные пользователи могут искать

        preferred_gender = current_user.preferred_gender
        lower_age = current_user.age_lower_point
        high_age = current_user.age_high_point

        if not all([preferred_gender, lower_age, high_age]):
            return np.array([])  # Нет настроек для поиска

        # Получаем всех потенциальных пользователей
        all_users = await self.user_repo.pool.fetch(
            "SELECT tg_chat_id, gender, age FROM users WHERE is_registered = 'yes'")

        eligible_profiles = []
        for user_record in all_users:
            profile_id = user_record['tg_chat_id']
            profile_gender = user_record['gender']
            profile_age = user_record['age']

            if profile_id == str(current_user_id):
                continue  # Исключаем себя

            # Проверка по полу
            if preferred_gender != "Any" and profile_gender != preferred_gender:
                continue

            # Проверка по возрасту
            if not (lower_age <= profile_age <= high_age):
                continue

            # Проверка на уже лайкнутые/дизлайкнутые
            if await self.like_repo.has_liked(str(current_user_id), profile_id) or \
                    await self.like_repo.has_disliked(str(current_user_id), profile_id):  # Нужен DislikeRepository
                continue

            eligible_profiles.append(profile_id)

        if eligible_profiles:
            return np.random.permutation(eligible_profiles)
        return np.array([])

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
        Обрабатывает дизлайк. Возвращает True, если успешно.
        """
        disliker_id_str = str(disliker_id)
        disliked_id_str = str(disliked_id)

        # Здесь нужна реализация DislikeRepository.
        # Для примера, используем execute_query напрямую, но лучше создать DislikeRepository.
        # if await self.dislike_repo.has_disliked(disliker_id_str, disliked_id_str):
        #     return False
        # await self.dislike_repo.add_dislike(disliker_id_str, disliked_id_str)

        # Временная заглушка, пока не будет DislikeRepository
        try:
            await self.user_repo.pool.execute(
                "INSERT INTO dislikes (disliker_chat_id, disliked_chat_id) VALUES ($1, $2) ON CONFLICT (disliker_chat_id, disliked_chat_id) DO NOTHING;",
                disliker_id_str, disliked_id_str
            )
            return True
        except Exception as e:
            logger.error(f"Error adding dislike: {e}")
            return False

    async def get_mutual_likes(self, tg_chat_id: int) -> List[str]:
        return await self.like_repo.get_mutual_likes_for_user(str(tg_chat_id))