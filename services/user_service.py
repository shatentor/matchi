from typing import Optional, List, Any
from models.user import User, UserProfileData
from db.repositories.user_repo import UserRepository
from db.repositories.like_repo import LikeRepository
from aiogram.types import InputMediaPhoto # ИМПОРТИРОВАНО InputMediaPhoto
import time


class UserService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo

    async def get_or_create_user(self, tg_chat_id: int, username: Optional[str]) -> User:
        user = await self.user_repo.get_by_id(str(tg_chat_id))
        if user is None:
            user = User(tg_chat_id=str(tg_chat_id), tg_username=username, is_registered="no")
            user = await self.user_repo.create(user)
        return user

    async def sync_username(self, user: User, username: Optional[str]) -> User:
        """Догоняет сменившийся @username.

        Юзернейм пишется в БД только при регистрации, а взаимные лайки и жалобы
        показывают именно его — без синхронизации контакт может оказаться нерабочим.
        """
        if username == user.tg_username:
            return user
        await self.user_repo.update_username(user.tg_chat_id, username)
        user.tg_username = username
        return user

    async def update_user_profile_field(self, tg_chat_id: int, field_name: str, new_value: Any) -> User:
        user = await self.user_repo.get_by_id(str(tg_chat_id))
        if not user:
            raise ValueError(f"User with chat_id {tg_chat_id} not found")

        if field_name == "description":
            await self.user_repo.update_description(str(tg_chat_id), new_value)
        elif field_name.startswith("photo_link"):
            num_map = {"photo_link": 1, "photo_link_two": 2, "photo_link_three": 3}
            photo_num = num_map.get(field_name, None)
            if photo_num:
                await self.user_repo.update_photo_link(str(tg_chat_id), photo_num, new_value)
            else:
                raise ValueError(f"Invalid photo field name: {field_name}")
        elif field_name == "support_time":
            await self.user_repo.update_support_time(str(tg_chat_id), new_value)
        elif field_name == "last_shown_profile":
            await self.user_repo.update_last_shown_profile(str(tg_chat_id), new_value)
        elif field_name == "is_registered":
            await self.user_repo.update_register_status(str(tg_chat_id), new_value)
        else:
            setattr(user, field_name, new_value)
            user = await self.user_repo.update(user)

        if field_name not in ["description", "photo_link", "photo_link_two", "photo_link_three", "support_time",
                              "last_shown_profile", "is_registered"]:
            user = await self.user_repo.get_by_id(str(tg_chat_id))
        elif field_name == "is_registered":
            user = await self.user_repo.get_by_id(str(tg_chat_id))

        return user

    async def get_user_profile_data(self, tg_chat_id: int) -> Optional[UserProfileData]:
        user = await self.user_repo.get_by_id(str(tg_chat_id))
        if not user:
            return None
        description = await self.user_repo.get_description(str(tg_chat_id))

        if not all([user.name, user.age, user.city, user.gender, user.preferred_gender,
                    user.age_lower_point, user.age_high_point, description]):
            return None

        photo_ids = [pid for pid in [user.photo_link, user.photo_link_two, user.photo_link_three] if pid]

        return UserProfileData(
            tg_chat_id=user.tg_chat_id,
            tg_username=user.tg_username,
            name=user.name,
            age=user.age,
            city=user.city,
            gender=user.gender,
            description=description,
            preferred_gender=user.preferred_gender,
            age_range=f"{user.age_lower_point}-{user.age_high_point}",
            photo_ids=photo_ids
        )

    async def get_user_media_group(self, tg_chat_id: int) -> List[InputMediaPhoto]: # ВОЗВРАЩАЕТ СПИСОК InputMediaPhoto
        user = await self.user_repo.get_by_id(str(tg_chat_id))
        media_group_photos = []
        if user and user.photo_link:
            media_group_photos.append(InputMediaPhoto(media=user.photo_link)) # Используем InputMediaPhoto
        if user and user.photo_link_two:
            media_group_photos.append(InputMediaPhoto(media=user.photo_link_two))
        if user and user.photo_link_three:
            media_group_photos.append(InputMediaPhoto(media=user.photo_link_three))
        return media_group_photos

    async def get_registration_status(self, tg_chat_id: int) -> Optional[str]:
        user = await self.user_repo.get_by_id(str(tg_chat_id))
        return user.is_registered if user else None

    async def get_user_last_support_time(self, tg_chat_id: int) -> int:
        return await self.user_repo.get_support_time(str(tg_chat_id))

    async def get_all_user_chat_ids(self) -> List[str]:
        return await self.user_repo.get_all_chat_ids()

    async def get_user_by_id(self, tg_chat_id: int) -> Optional[User]:
        return await self.user_repo.get_by_id(str(tg_chat_id))