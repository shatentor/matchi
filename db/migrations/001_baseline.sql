-- Базовая линия: существующая схема бота (перенесена из db/sql_templates.sql
-- без изменений в определениях). Применяется безопасно и к пустой базе,
-- и к уже работающей, потому что все таблицы создаются через IF NOT EXISTS.

-- Таблица пользователей
CREATE TABLE IF NOT EXISTS users (
    tg_chat_id VARCHAR(20) PRIMARY KEY NOT NULL,
    tg_username VARCHAR(50) UNIQUE,
    name VARCHAR(30),
    age INTEGER,
    city VARCHAR(30),
    gender VARCHAR(10),
    photo_link VARCHAR(255),
    photo_link_two VARCHAR(255),
    photo_link_three VARCHAR(255),
    preferred_gender VARCHAR(20),
    age_lower_point INTEGER,
    age_high_point INTEGER,
    last_shown_profile VARCHAR(20),
    support_time BIGINT,
    is_registered VARCHAR(10) DEFAULT 'no'
);

-- Таблица описаний профилей
CREATE TABLE IF NOT EXISTS descriptions (
    tg_chat_id VARCHAR(20) PRIMARY KEY NOT NULL,
    descr VARCHAR(1000),
    FOREIGN KEY (tg_chat_id) REFERENCES users(tg_chat_id) ON DELETE CASCADE
);

-- Таблица стикеров
CREATE TABLE IF NOT EXISTS stickers (
    id SERIAL PRIMARY KEY,
    lovely VARCHAR(255) NOT NULL
);

-- Таблица лайков (многие-ко-многим)
CREATE TABLE IF NOT EXISTS likes (
    liker_chat_id VARCHAR(20) NOT NULL,
    liked_chat_id VARCHAR(20) NOT NULL,
    PRIMARY KEY (liker_chat_id, liked_chat_id),
    FOREIGN KEY (liker_chat_id) REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    FOREIGN KEY (liked_chat_id) REFERENCES users(tg_chat_id) ON DELETE CASCADE
);

-- Таблица дизлайков (многие-ко-многим)
CREATE TABLE IF NOT EXISTS dislikes (
    disliker_chat_id VARCHAR(20) NOT NULL,
    disliked_chat_id VARCHAR(20) NOT NULL,
    PRIMARY KEY (disliker_chat_id, disliked_chat_id),
    FOREIGN KEY (disliker_chat_id) REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    FOREIGN KEY (disliked_chat_id) REFERENCES users(tg_chat_id) ON DELETE CASCADE
);

-- Таблица сообщений (многие-ко-многим)
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    sender_chat_id VARCHAR(20) NOT NULL,
    receiver_chat_id VARCHAR(20) NOT NULL,
    message_text TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sender_chat_id) REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    FOREIGN KEY (receiver_chat_id) REFERENCES users(tg_chat_id) ON DELETE CASCADE
);

-- Таблица жалоб (многие-ко-многим)
CREATE TABLE IF NOT EXISTS complains (
    id SERIAL PRIMARY KEY,
    reporter_chat_id VARCHAR(20) NOT NULL,
    reported_chat_id VARCHAR(20) NOT NULL,
    reason TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (reporter_chat_id) REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    FOREIGN KEY (reported_chat_id) REFERENCES users(tg_chat_id) ON DELETE CASCADE
);
