import asyncio
from main_structure import config
import logging
from aiogram import Bot, Dispatcher, types
from data_base.redis_conn import storage
from data_base.db_connect_users import is_admin
from aiogram.dispatcher.filters.state import State, StatesGroup
from main_structure.keyboard import admin_keyboard
from aiogram.dispatcher import FSMContext
from main_structure.class_user import select_all_tg_chat_id


bot = Bot(token=config.token)
dp = Dispatcher(bot, storage=storage)
loop = asyncio.get_event_loop()
logging.basicConfig(level=logging.INFO)

class Admin(StatesGroup):
    choose_action = State()
    send_message_to_all = State()


async def admin_command(message: types.Message):
    username = message.from_user.username
    if is_admin(username):
        await message.answer("Select an action", parse_mode="MARKDOWN",
                             reply_markup=admin_keyboard())
        await Admin.choose_action.set()
    else:
        await message.answer("Don`t do that!")


async def message_to_all_users(call):
    message = call.message
    await message.answer("Write your message:")
    await Admin.send_message_to_all.set()


async def send_message(message: types.Message, state: FSMContext):
    for cid in select_all_tg_chat_id():
        await bot.send_message(cid[0], f"{message.text}")
    await state.finish()

def register_admin_commands(dp: Dispatcher):
    dp.register_message_handler(admin_command, commands="admin",state ="*")
    dp.register_callback_query_handler(message_to_all_users, lambda call: call.data == "message_to_all", state= Admin.choose_action)
    dp.register_message_handler(send_message, state=Admin.send_message_to_all)


