-- Интересы, личные диалоги и комнаты по интересам.
-- Новые таблицы используют TIMESTAMPTZ (старые оставлены на TIMESTAMP — так исторически).
-- tg_chat_id пользователя везде VARCHAR(20), как в users.

CREATE TABLE IF NOT EXISTS interests (
    id SERIAL PRIMARY KEY,
    slug VARCHAR(40) UNIQUE NOT NULL,
    title VARCHAR(60) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS user_interests (
    tg_chat_id VARCHAR(20) NOT NULL REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    interest_id INTEGER NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
    PRIMARY KEY (tg_chat_id, interest_id)
);
CREATE INDEX IF NOT EXISTS idx_user_interests_interest ON user_interests(interest_id);

CREATE TABLE IF NOT EXISTS dialogs (
    id SERIAL PRIMARY KEY,
    user_one VARCHAR(20) NOT NULL REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    user_two VARCHAR(20) NOT NULL REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    source VARCHAR(20) NOT NULL DEFAULT 'profile',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    CONSTRAINT dialogs_pair_ordered CHECK (user_one < user_two)
);
-- Пара упорядочена констрейнтом выше, поэтому частичный UNIQUE запрещает
-- второй открытый диалог для той же пары, но разрешает историю закрытых.
CREATE UNIQUE INDEX IF NOT EXISTS idx_dialogs_active_pair ON dialogs (user_one, user_two) WHERE closed_at IS NULL;

CREATE TABLE IF NOT EXISTS rooms (
    id SERIAL PRIMARY KEY,
    interest_id INTEGER REFERENCES interests(id) ON DELETE SET NULL,
    title VARCHAR(60) NOT NULL,
    description VARCHAR(300),
    mode VARCHAR(10) NOT NULL DEFAULT 'relay',
    tg_chat_id BIGINT,
    member_limit INTEGER NOT NULL DEFAULT 30,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS room_members (
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    tg_chat_id VARCHAR(20) NOT NULL REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    muted_until TIMESTAMPTZ,
    PRIMARY KEY (room_id, tg_chat_id)
);

CREATE TABLE IF NOT EXISTS room_messages (
    id SERIAL PRIMARY KEY,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    author_chat_id VARCHAR(20) NOT NULL REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_room_messages_room ON room_messages (room_id, created_at DESC);

CREATE TABLE IF NOT EXISTS room_bans (
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    tg_chat_id VARCHAR(20) NOT NULL REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    reason TEXT,
    banned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (room_id, tg_chat_id)
);

-- Взаимные лайки джойнят likes по liked_chat_id, а составной первичный ключ
-- начинается с liker_chat_id и для обратного направления не работает.
CREATE INDEX IF NOT EXISTS idx_likes_liked ON likes (liked_chat_id);
CREATE INDEX IF NOT EXISTS idx_dislikes_disliked ON dislikes (disliked_chat_id);
