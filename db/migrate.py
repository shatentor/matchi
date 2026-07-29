# db/migrate.py

"""Версионированные миграции схемы.

Запуск (строго из корня проекта):

    python db/migrate.py            # применить всё неприменённое
    python db/migrate.py --status   # только показать состояние

Миграции лежат в db/migrations/ и называются NNN_описание.sql, где NNN —
трёхзначный номер по порядку. Применённые версии учитываются в таблице
schema_migrations, поэтому повторный запуск ничего не делает.
"""

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set

import asyncpg

# Скрипт запускают как `python db/migrate.py`, поэтому sys.path[0] указывает
# на db/, и пакет config сам по себе не находится.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATION_FILE_PATTERN = re.compile(r"^(\d{3})_[0-9A-Za-z_]+\.sql$")

CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(20) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


@dataclass(frozen=True)
class Migration:
    """Одна миграция: версия (номер NNN) и файл с SQL."""

    version: str
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    def read_sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


class MigrationError(Exception):
    """Проблема с набором файлов миграций или с их применением."""


def discover_migrations() -> List[Migration]:
    """Собирает миграции с диска и сортирует по номеру версии."""
    if not MIGRATIONS_DIR.is_dir():
        raise MigrationError(f"Каталог миграций не найден: {MIGRATIONS_DIR}")

    migrations: List[Migration] = []
    for path in sorted(MIGRATIONS_DIR.iterdir()):
        if path.suffix != ".sql" or not path.is_file():
            continue
        match = MIGRATION_FILE_PATTERN.match(path.name)
        if not match:
            raise MigrationError(
                f"Имя файла миграции не по формату NNN_описание.sql: {path.name}"
            )
        migrations.append(Migration(version=match.group(1), path=path))

    seen: Set[str] = set()
    for migration in migrations:
        if migration.version in seen:
            raise MigrationError(
                f"Дублируется номер миграции {migration.version} ({migration.name})"
            )
        seen.add(migration.version)

    return migrations


async def connect() -> asyncpg.Connection:
    """Подключение теми же настройками, что использует бот."""
    return await asyncpg.connect(
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        database=settings.DB_NAME,
    )


async def fetch_applied_versions(conn: asyncpg.Connection) -> Set[str]:
    """Создаёт таблицу учёта при первом запуске и отдаёт применённые версии."""
    await conn.execute(CREATE_MIGRATIONS_TABLE)
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    return {row["version"] for row in rows}


async def apply_migration(conn: asyncpg.Connection, migration: Migration) -> None:
    """Применяет одну миграцию целиком в своей транзакции.

    SQL файла выполняется одним execute без параметров: в этом режиме asyncpg
    использует простой протокол запросов и принимает несколько команд сразу.
    Разбивать файл по ';' нельзя — это ломается на строковых литералах.
    """
    sql = migration.read_sql()
    async with conn.transaction():
        await conn.execute(sql)
        await conn.execute(
            "INSERT INTO schema_migrations (version) VALUES ($1)", migration.version
        )


async def run_migrations(migrations: List[Migration]) -> int:
    """Применяет неприменённые миграции. Возвращает код выхода процесса."""
    try:
        conn = await connect()
    except (OSError, asyncpg.PostgresError) as e:
        logger.error("Не удалось подключиться к базе '%s' на %s:%s — %s",
                     settings.DB_NAME, settings.DB_HOST, settings.DB_PORT, e)
        return 1

    try:
        applied = await fetch_applied_versions(conn)
        pending = [m for m in migrations if m.version not in applied]

        if not pending:
            logger.info("Новых миграций нет, схема актуальна (применено: %d).",
                        len(applied))
            return 0

        for migration in pending:
            logger.info("Применяю %s ...", migration.name)
            try:
                await apply_migration(conn, migration)
            except asyncpg.PostgresError as e:
                logger.error("Миграция %s провалилась, изменения откачены: %s",
                             migration.name, e)
                logger.error("Схема осталась на версии до %s. Исправьте SQL "
                             "и запустите миграции снова.", migration.version)
                return 1
            logger.info("Применена %s", migration.name)

        logger.info("Готово, применено миграций: %d", len(pending))
        return 0
    except asyncpg.PostgresError as e:
        logger.error("Ошибка PostgreSQL: %s", e)
        return 1
    finally:
        await conn.close()


async def show_status(migrations: List[Migration]) -> int:
    """Печатает список миграций с отметкой применена/нет, ничего не применяя."""
    applied: Set[str] = set()
    connected = False
    try:
        conn = await connect()
        connected = True
    except (OSError, asyncpg.PostgresError) as e:
        logger.error("Состояние в БД неизвестно: нет подключения к '%s' на %s:%s — %s",
                     settings.DB_NAME, settings.DB_HOST, settings.DB_PORT, e)

    if connected:
        try:
            applied = await fetch_applied_versions(conn)
        finally:
            await conn.close()

    logger.info("Миграции в %s:", MIGRATIONS_DIR)
    for migration in migrations:
        if not connected:
            mark = "неизвестно (нет подключения)"
        elif migration.version in applied:
            mark = "применена"
        else:
            mark = "не применена"
        logger.info("  %s — %s", migration.name, mark)

    orphans = sorted(applied - {m.version for m in migrations})
    for version in orphans:
        logger.warning("  версия %s есть в schema_migrations, но файла на диске нет",
                       version)

    # Без подключения отметки честно неизвестны, поэтому успехом это не считаем.
    return 0 if connected else 1


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Применение версионированных миграций схемы."
    )
    parser.add_argument("--status", action="store_true",
                        help="показать состояние миграций и ничего не применять")
    args = parser.parse_args()

    try:
        migrations = discover_migrations()
    except MigrationError as e:
        logger.error("%s", e)
        return 1

    if not migrations:
        logger.warning("В %s нет ни одной миграции.", MIGRATIONS_DIR)
        return 0

    if args.status:
        return await show_status(migrations)
    return await run_migrations(migrations)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
