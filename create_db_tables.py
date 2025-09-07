# create_db_tables.py

import asyncio
import asyncpg
import os
import logging
from typing import List

# Импортируем настройки из вашего config/settings.py
from config.settings import settings

# Настройка логирования
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)


async def get_sql_commands(file_path: str) -> List[str]:
    """
    Читает SQL-команды из файла, разделяя их по ';',
    и фильтрует пустые строки и комментарии.
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    # Удаляем однострочные комментарии (--)
    lines = sql_content.split('\n')
    cleaned_lines = []
    for line in lines:
        if '--' in line:
            line = line.split('--')[0]  # Оставляем только часть до комментария
        cleaned_lines.append(line)
    sql_content = '\n'.join(cleaned_lines)

    # Разделяем по ';' и фильтруем пустые строки
    commands = [cmd.strip() for cmd in sql_content.split(';') if cmd.strip()]
    return commands


async def create_tables():
    """
    Подключается к базе данных и создает таблицы,
    используя SQL-скрипт из db/sql_templates.sql.
    """
    logger.info("Запуск скрипта создания таблиц...")

    # Формируем полный путь к SQL-файлу
    # os.path.dirname(__file__) даст путь к директории db, если скрипт в db/,
    # или к корневой директории, если скрипт там же, что и config.
    # Предположим, что sql_templates.sql находится в db/, а этот скрипт - в корне
    # Или, если этот скрипт находится в db/, то:
    # sql_file_path = os.path.join(os.path.dirname(__file__), 'sql_templates.sql')

    # Для корневой директории проекта:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sql_file_path = os.path.join(current_dir, 'db', 'sql_templates.sql')

    if not os.path.exists(sql_file_path):
        logger.error(f"Ошибка: SQL-файл не найден по пути: {sql_file_path}")
        logger.error("Убедитесь, что файл 'sql_templates.sql' находится в папке 'db/' "
                     "относительно места запуска этого скрипта.")
        return

    try:
        # Подключение к базе данных
        conn = await asyncpg.connect(
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=settings.DB_NAME
        )
        logger.info(f"Успешно подключено к базе данных '{settings.DB_NAME}' "
                    f"как пользователь '{settings.DB_USER}'.")

        # Получаем SQL-команды
        sql_commands = await get_sql_commands(sql_file_path)

        # Выполняем команды в транзакции
        async with conn.transaction():
            for i, command in enumerate(sql_commands):
                if command:  # Пропускаем пустые команды после разделения
                    try:
                        await conn.execute(command)
                        logger.info(
                            f"[{i + 1}/{len(sql_commands)}] Успешно выполнено: {command.splitlines()[0][:100]}...")
                    except asyncpg.exceptions.DuplicateTableError:
                        logger.warning(
                            f"[{i + 1}/{len(sql_commands)}] Таблица уже существует (пропущено): {command.splitlines()[0][:100]}...")
                    except Exception as e:
                        logger.error(
                            f"[{i + 1}/{len(sql_commands)}] Ошибка при выполнении команды: {command.splitlines()[0][:100]}...\nОшибка: {e}")
                        logger.error("Транзакция будет отменена из-за ошибки.")
                        raise  # Перебрасываем ошибку, чтобы откатить транзакцию

        logger.info("Все SQL-команды успешно выполнены. Таблицы созданы/проверены.")

    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка PostgreSQL при создании таблиц: {e}")
        logger.error("Возможные причины: неверные учетные данные, база данных не существует, "
                     "проблемы с правами доступа или сервер PostgreSQL не запущен.")
    except FileNotFoundError:
        logger.error(f"Файл SQL-шаблонов не найден по пути: {sql_file_path}")
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка: {e}")
    finally:
        if 'conn' in locals() and conn:
            await conn.close()
            logger.info("Соединение с базой данных закрыто.")


async def main():
    await create_tables()


if __name__ == '__main__':
    asyncio.run(main())