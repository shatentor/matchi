-- Вход по инвайту и одна закрытая супергруппа сообщества.
--
-- Зачем инвайты: сеть закрытая, случайный человек с /start в неё попасть
-- не должен. Код выдаёт участник, поэтому у каждого нового профиля есть
-- пригласивший — это и модерация на входе, и социальный граф.
--
-- Зачем invite_uses отдельно от invites.used_count: счётчик отвечает только
-- на вопрос «сколько раз использован», а знать надо, КТО кого привёл, и не
-- дать одному человеку истратить один код дважды. Составной первичный ключ
-- (code, tg_chat_id) даёт эту защиту на уровне схемы.
--
-- Зачем rooms.thread_id: контент переезжает в форум-топики супергруппы,
-- комната в режиме native теперь указывает не только на чат, но и на топик
-- внутри него.

CREATE TABLE IF NOT EXISTS invites (
    code VARCHAR(16) PRIMARY KEY,
    -- Удаление автора кода не должно уносить историю приглашений, поэтому
    -- SET NULL, а не CASCADE.
    created_by VARCHAR(20) REFERENCES users(tg_chat_id) ON DELETE SET NULL,
    max_uses INTEGER NOT NULL DEFAULT 3,
    used_count INTEGER NOT NULL DEFAULT 0,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS invite_uses (
    code VARCHAR(16) NOT NULL REFERENCES invites(code) ON DELETE CASCADE,
    tg_chat_id VARCHAR(20) NOT NULL REFERENCES users(tg_chat_id) ON DELETE CASCADE,
    used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (code, tg_chat_id)
);
-- Первичный ключ начинается с code, поэтому обратный вопрос «каким кодом
-- пришёл этот человек» (inviter_of) без отдельного индекса шёл бы seq scan.
CREATE INDEX IF NOT EXISTS idx_invite_uses_user ON invite_uses (tg_chat_id);

-- Одна закрытая супергруппа сообщества; ожидается ровно одна строка.
-- chat_id тут BIGINT, как rooms.tg_chat_id: id супергруппы приходит от
-- Telegram числом с префиксом -100 и в VARCHAR(20) пользователей не лежит.
CREATE TABLE IF NOT EXISTS community (
    chat_id BIGINT PRIMARY KEY,
    title VARCHAR(120),
    bound_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Комнаты становятся топиками супергруппы: NULL означает «топика нет»
-- (комната в режиме relay или ещё не привязанная).
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS thread_id BIGINT;
