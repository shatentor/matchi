from pydantic import BaseModel, ConfigDict


class Like(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    liker_chat_id: str
    liked_chat_id: str
