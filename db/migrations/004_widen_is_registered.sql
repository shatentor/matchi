-- users.is_registered объявлен как VARCHAR(10), а код пишет туда 'in_progress' —
-- это 11 символов. Из-за этого регистрация падала на первом же шаге с
-- StringDataRightTruncationError: value too long for type character varying(10).
-- Расширяем с запасом на будущие статусы.
ALTER TABLE users ALTER COLUMN is_registered TYPE VARCHAR(20);
