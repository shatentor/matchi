from pydantic import BaseModel, ConfigDict


class Dislike(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    disliker_chat_id: str
    disliked_chat_id: str
