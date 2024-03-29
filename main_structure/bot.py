import asyncio
import logging
from aiogram import Bot, Dispatcher
from data_base.redis_conn import storage
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types.bot_command import BotCommand
import config
from handlers.commands import register_handlers_commands
from handlers.user_registration import register_handlers_registration
from handlers.change_profile import register_handlers_change_profile
from handlers.selection_of_profiles import register_handlers_searching
from handlers.admin import register_admin_commands


# Set the log level for debugging.
logging.basicConfig(level=logging.INFO)


bot = Bot(token=config.token)
dp = Dispatcher(bot, storage=storage)
loop = asyncio.get_event_loop()


async def set_commands(bot: Bot):

    commands = [
        BotCommand(command="/show_my_profile", description="My profile"),
        BotCommand(command="/change_my_profile", description="Change my profile"),
        BotCommand(command="/searchi", description="Searching profiles"),
        BotCommand(command="/show_mutual_likes", description= "My mutual likes"),
        BotCommand(command="/support", description="Message to administrator"),
        BotCommand(command="/help", description="Help :)")
    ]
    await bot.set_my_commands(commands)


async def main():

    register_handlers_registration(dp)
    register_handlers_commands(dp)
    register_handlers_searching(dp)
    register_handlers_change_profile(dp)
    register_admin_commands(dp)
    await set_commands(bot)
    await dp.start_polling()

if __name__ == '__main__':
    dp.middleware.setup(LoggingMiddleware())
    asyncio.run(main())
