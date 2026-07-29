-- Посты с фотографиями и лента внутри бота.
--
-- Зачем: закрытая сеть перестала быть только каталогом анкет — люди хотят
-- показывать друг другу тусовки и поездки. Раньше единственным способом
-- что-то опубликовать была комната-релей, но там сообщение живёт минуту и
-- теряется, а к нему нельзя вернуться, поставить реакцию или ответить.
--
-- Зачем feed_views: в боте нет скролла, лента показывается по одному посту
-- кнопками «Раньше»/«Свежее». Без сохранённой позиции нельзя ответить на
-- вопрос «что нового с прошлого раза»: клиент Telegram не сообщает, докуда
-- человек дочитал, а FSM-состояние в Redis живёт только пока пользователь в
-- ленте и теряется при очистке Redis. Поэтому последний увиденный пост
-- хранится в БД одной строкой на человека.
--
-- Идемпотентность: db/migrate.py прогоняет файл целиком одним execute, поэтому
-- каждый объект создаётся через IF NOT EXISTS — повторный прогон (например,
-- после падения на более поздней миграции) не должен ронять схему.

CREATE TABLE IF NOT EXISTS posts (
    id SERIAL PRIMARY KEY,
    author_chat_id VARCHAR(20) NOT NULL REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    -- Тема поста необязательна, а удаление интереса не должно уносить посты.
    interest_id INTEGER REFERENCES interests(id) ON DELETE SET NULL,
    text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Удаление мягкое: id постов служат позицией в ленте (feed_views,
    -- before_id при листании), и физическое удаление её бы сдвигало.
    deleted_at TIMESTAMPTZ
);
-- Основной запрос ленты — свежие сверху и только живые посты. Частичный
-- индекс не хранит удалённые строки, поэтому они не растят индекс и не
-- отсеиваются потом фильтром.
CREATE INDEX IF NOT EXISTS idx_posts_feed ON posts (created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_posts_author ON posts (author_chat_id);

CREATE TABLE IF NOT EXISTS post_media (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    -- file_id выдаёт Telegram, своих копий файлов бот не держит.
    file_id VARCHAR(255) NOT NULL,
    media_type VARCHAR(16) NOT NULL DEFAULT 'photo',
    -- Порядок в медиагруппе задаёт автор, поэтому он хранится явно.
    position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_post_media_post ON post_media (post_id, position);

-- Одна реакция на человека на пост: составной первичный ключ это и
-- обеспечивает, а смена эмодзи делается через ON CONFLICT DO UPDATE.
CREATE TABLE IF NOT EXISTS post_reactions (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    tg_chat_id VARCHAR(20) NOT NULL REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    emoji VARCHAR(8) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (post_id, tg_chat_id)
);

CREATE TABLE IF NOT EXISTS post_comments (
    id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author_chat_id VARCHAR(20) NOT NULL REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_post_comments_post ON post_comments (post_id, created_at);

-- Докуда человек долистал ленту; одна строка на пользователя.
CREATE TABLE IF NOT EXISTS feed_views (
    tg_chat_id VARCHAR(20) PRIMARY KEY REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    -- 0 означает «не видел ничего», поэтому первый вход покажет всю ленту
    -- как непрочитанную.
    last_seen_post_id INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Уведомления о новых постах включены по умолчанию: веер идёт через Outbox,
-- и выключить их человек может сам командой.
ALTER TABLE users ADD COLUMN IF NOT EXISTS feed_notify BOOLEAN NOT NULL DEFAULT TRUE;
