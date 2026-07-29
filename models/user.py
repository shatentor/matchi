from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any

class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tg_chat_id: str
    tg_username: Optional[str] = None
    name: Optional[str] = None
    city: Optional[str] = None
    role: Optional[str] = None # кем работает: «backend, Python»
    status: Optional[str] = None # чем занят сейчас
    links: Optional[str] = None # github/сайт/канал
    can_help: Optional[str] = None
    looking_for: Optional[str] = None
    photo_link: Optional[str] = None
    photo_link_two: Optional[str] = None
    photo_link_three: Optional[str] = None
    last_shown_profile: Optional[str] = None
    support_time: Optional[int] = None # Unix timestamp
    is_registered: str = "no" # 'yes', 'no', 'in_progress'

class UserProfileData(BaseModel): # Модель для отображения полной информации о профиле
    tg_chat_id: str
    tg_username: Optional[str] = None
    name: str
    city: str
    role: str
    description: str
    status: Optional[str] = None
    links: Optional[str] = None
    can_help: Optional[str] = None
    looking_for: Optional[str] = None
    photo_ids: List[str] = Field(default_factory=list)
