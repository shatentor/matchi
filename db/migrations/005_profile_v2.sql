-- Профиль v2: бот перестал быть дейтингом и стал закрытой сетью для друзей
-- и знакомых, в основном программистов. Людей больше не подбирают по полу
-- и возрасту, поэтому эти поля не просто перестают использоваться — они
-- становятся лишними персональными данными, и мы их удаляем.
-- Вместо них профиль описывает человека профессионально: кем работает,
-- чем занят сейчас, где его найти, чем может помочь и что ищет.
--
-- DROP COLUMN необратим: значения age/gender/preferred_gender и границ
-- возраста после применения не восстановить ничем, кроме бэкапа.
--
-- Идемпотентность: IF EXISTS / IF NOT EXISTS нужны, потому что db/migrate.py
-- прогоняет файл целиком одним execute, и повторный запуск (например, после
-- падения на более поздней миграции) не должен ронять схему.

ALTER TABLE users DROP COLUMN IF EXISTS age;
ALTER TABLE users DROP COLUMN IF EXISTS gender;
ALTER TABLE users DROP COLUMN IF EXISTS preferred_gender;
ALTER TABLE users DROP COLUMN IF EXISTS age_lower_point;
ALTER TABLE users DROP COLUMN IF EXISTS age_high_point;

-- role обязательна при регистрации, но в схеме остаётся NULL-able: колонка
-- добавляется к уже существующим строкам, а обязательность шага живёт в
-- проверке минимума профиля (name, city, role, description), а не в NOT NULL.
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(60);
ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(140);
ALTER TABLE users ADD COLUMN IF NOT EXISTS links VARCHAR(300);
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_help TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS looking_for TEXT;
