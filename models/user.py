from pydantic import BaseModel, Field
from typing import Optional, List, Any

class User(BaseModel):
    tg_chat_id: str
    tg_username: Optional[str] = None
    name: Optional[str] = None
    age: Optional[int] = None
    city: Optional[str] = None
    gender: Optional[str] = None
    photo_link: Optional[str] = None
    photo_link_two: Optional[str] = None
    photo_link_three: Optional[str] = None
    preferred_gender: Optional[str] = None
    age_lower_point: Optional[int] = None
    age_high_point: Optional[int] = None
    last_shown_profile: Optional[str] = None
    support_time: Optional[int] = None # Unix timestamp
    is_registered: str = "no" # 'yes', 'no', 'in_progress'

    class Config:
        # orm_mode = True # УДАЛЕНО
        from_attributes = True # ИСПРАВЛЕНО

class UserProfileData(BaseModel): # Модель для отображения полной информации о профиле
    tg_chat_id: str
    tg_username: Optional[str] = None
    name: str
    age: int
    city: str
    gender: str
    description: str
    preferred_gender: str
    age_range: str # e.g., "20-30"
    photo_ids: List[str] = Field(default_factory=list)