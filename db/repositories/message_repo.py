import asyncpg
from typing import List, Optional
from models.message import Message
from db.repositories.base import BaseRepository

class MessageRepository(BaseRepository):
    def __init__(self, pool: asyncpg.Pool):
        super().__init__(pool, Message, "messages")

    async def create_message(self, message: Message) -> Message:
        query = """
        INSERT INTO messages (sender_chat_id, receiver_chat_id, message_text)
        VALUES ($1, $2, $3)
        RETURNING *;
        """
        record = await self._fetch_one(query, message.sender_chat_id, message.receiver_chat_id, message.message_text)
        return record if record else message

    async def get_messages_between_users(self, user1_id: str, user2_id: str) -> List[Message]:
        query = """
        SELECT * FROM messages
        WHERE (sender_chat_id = $1 AND receiver_chat_id = $2)
           OR (sender_chat_id = $2 AND receiver_chat_id = $1)
        ORDER BY timestamp ASC;
        """
        return await self._fetch_all(query, user1_id, user2_id)