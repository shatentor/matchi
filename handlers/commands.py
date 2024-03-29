import asyncio
from main_structure import config
import logging
from aiogram import Bot, Dispatcher, types
from main_structure.keyboard import start_keyboard
from data_base.redis_conn import storage
from main_structure.keyboard import change_profile_keyboard
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher import FSMContext
from main_structure.class_user import User, execute_query

bot = Bot(token=config.token)
dp = Dispatcher(bot, storage=storage)
loop = asyncio.get_event_loop()
logging.basicConfig(level=logging.INFO)


class Commands(StatesGroup):
    change_my_profile = State()
    support_create = State()
    delete_prof = State()



async def start_func(message: types.Message):
    cid = message.chat.id
    if User(cid).is_registered() is None:
        await message.answer('Hi🙋! This is *Matchi* - dating bot. \n\n'
                             'You can find people who are interesting to you here. \n'
                             'First you need to answer a few questions.', reply_markup=start_keyboard(),
                             parse_mode="MARKDOWN")
    elif User(cid).is_registered() == "yes":
        await message.answer('You are already registered')
    else:
        await message.answer("Please end registration")

async def help_func(message: types.Message):
    await message.answer('Use the menu or write "/"'
                         " to search for commands \n\n "
                         " For any question, you can write to the administrator: /support\n\n"
                         " Here I'm talking about my projects:\n"
                         " https://t.me/Mister_Senna_channel")



async def show_profile_func(message: types.Message):
    cid = message.chat.id
    age_lower_point = User(cid).get_lower_age_point()
    age_high_point = User(cid).get_high_age_point()


    await message.answer('*Your profile*:\n\n'
                         f' *Name*: {User(cid).get_name()}\n'
                         f' *Age*: {User(cid).get_age()}\n'
                         f' *City*: {User(cid).get_city()}\n'
                         f' *Gender*: {User(cid).get_gender()}\n'
                         f' *Preferred gender*: {User(cid).get_preferred_gender()}\n'
                         f' *Preferred age*: [{age_lower_point}-{age_high_point}\n\n] '
                         f'*Description*:\n'
                         f'  {User(cid).get_description()}', parse_mode='MARKDOWN')

    await message.answer_media_group(media=User(cid).get_media_group())

async def change_profile(message: types.Message):
    await message.answer("Select the parameter you want to *change:* ", parse_mode="MARKDOWN",
                         reply_markup=change_profile_keyboard())


async def support_create(message: types.Message):
    cid = message.chat.id
    time = int(message.date.timestamp())

    if User(cid).get_support_time() + 120 < time:
        User(cid).update_support_time(time)
        await message.answer("*Write:*", parse_mode="MARKDOWN")
        await Commands.support_create.set()
    else:
        await message.answer(f"You can contact the admin in:\n"
                             f"{User(cid).get_support_time() + 120 - time} seconds")


async def support_send(message: types.Message, state: FSMContext):
    await bot.send_message(435472318, f"Support request from {message.chat.id}:\n"
                                      f"{message.text}")
    await message.answer("Message send and will be handled.")
    await state.finish()


async def show_profile_without_keyboard(shown_profile_id, message: types.Message):
    await message.answer_media_group(media=User(shown_profile_id).get_media_group())
    result = execute_query("SELECT users.name, users.age, users.city, descriptions.descr, users.tg_username"
                " FROM users"
                " LEFT JOIN descriptions"
                " ON users.tg_chat_id = ?"
                " WHERE descriptions.tg_chat_id = ?", (shown_profile_id, shown_profile_id))

    for (name, age, city, descr, username) in result:
        await message.answer(f"Name: {name}\n"
                             f"Age: {age}\n"
                             f"City: {city}\n\n"
                             f"About:\n {descr}\n\n"
                             f"Username: @{username}")


async def show_mutual_liked(message: types.Message):
    user_cid = message.chat.id
    await message.answer("Your mutual likes:")
    for cid in User(user_cid).get_list_of_liked():
        if User(user_cid).mutual_like(cid[0]):
            await show_profile_without_keyboard(cid[0],message)


def register_handlers_commands(dp: Dispatcher):
    dp.register_message_handler(start_func, commands="start",state ="*")
    dp.register_message_handler(help_func, commands="help", state="*")
    dp.register_message_handler(show_profile_func, lambda message: User(message.chat.id).is_registered() == "yes", commands="show_my_profile",
                                state="*")
    dp.register_message_handler(change_profile, lambda message: User(message.chat.id).is_registered()== "yes", commands="change_my_profile",
                                state="*")
    dp.register_message_handler(support_create, lambda message: User(message.chat.id).is_registered()== "yes", commands="support",
                                state="*")
    dp.register_message_handler(support_send, state=Commands.support_create)
    dp.register_message_handler(show_mutual_liked,lambda message: User(message.chat.id).is_registered()== "yes", commands="show_mutual_likes",
                                state="*")