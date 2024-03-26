from class_user import execute_query
import config
import logging
from aiogram.dispatcher import FSMContext
from aiogram import Bot, Dispatcher, types
from keyboard import searching_profiles_keyboard, yes_or_no_keyboard
from aiogram.dispatcher.filters.state import State, StatesGroup
from class_user import User
from data_base.redis_conn import storage

bot = Bot(token=config.token)
dp = Dispatcher(bot, storage=storage)
logging.basicConfig(level=logging.INFO)


class Searching(StatesGroup):
    people_searching = State()
    end_of_profiles = State()
    message = State()
    complain = State()
    message_or_complain_send = State()


def get_random_sticker():
    result = execute_query(f"SELECT lovely FROM stickers ORDER BY RAND() LIMIT 1")
    return result[0][0]

async def show_profile(shown_profile_id, message: types.Message):
    await message.answer_media_group(media=User(shown_profile_id).get_media_group())
    result = execute_query("SELECT users.name, users.age, users.city, descriptions.descr"
                " FROM users"
                " LEFT JOIN descriptions"
                " ON users.tg_chat_id = ?"
                " WHERE descriptions.tg_chat_id = ?", (shown_profile_id, shown_profile_id))

    for (name, age, city, descr) in result:
        await message.answer(f"Name: {name}\n"
                             f"Age: {age}\n"
                             f"City: {city}\n\n"
                             f"About:\n {descr}", reply_markup=searching_profiles_keyboard(str(shown_profile_id)))


async def people_searching_mes(message: types.Message, state: FSMContext):
    cid = message.chat.id
    try:
        shown_profile_id = int(User(cid).get_list_of_profiles()[0])
        await show_profile(shown_profile_id, message)
        User(cid).update_last_shown_profile(shown_profile_id)

        await state.update_data(shown_profile_id = shown_profile_id)

        await Searching.people_searching.set()
    except IndexError:
        await message.answer("The profiles are over. Come back tomorrow!")
        await Searching.end_of_profiles.set()


async def people_searching_cal(call: types.CallbackQuery, state: FSMContext):
    message = call.message
    cid = message.chat.id
    try:
        shown_profile_id = int(User(cid).get_list_of_profiles()[0])
        await state.update_data(shown_profile_id=shown_profile_id)
        await show_profile(shown_profile_id, message)
        User(cid).update_last_shown_profile(shown_profile_id)

        await Searching.people_searching.set()
    except IndexError:
        await message.answer("The profiles are over. Come back tomorrow!")
        await Searching.end_of_profiles.set()


async def mutual_profiles_show(call, shown_profile_id):
    username = call.from_user.username
    cid = call.from_user.id
    message = call.message

    if User(cid).mutual_like(shown_profile_id):
        shown_username = User(shown_profile_id).get_username()
        await message.answer("you have a mutual like with this user!\n"
                             f"Take his profile: @{shown_username}")

        await bot.send_message(shown_profile_id, f"You have a mutual like with user:\n"
                                                 f"@{username}!")

        await bot.send_media_group(shown_profile_id, User(cid).get_media_group())
    else:
        return


async def message_or_complain(call, state: FSMContext):
    cid = call.from_user.id
    message = call.message
    data = await state.get_data()
    shown_profile = data.get("shown_profile_id", "default_value")
    if call.data.startswith('message'):
        if not User(cid).get_message_state(shown_profile):
            User(cid).update_message_state(shown_profile)
            await message.answer(f"Message to {User(shown_profile).get_name()}:")
            await Searching.message.set()
        else:
            await message.answer(f"Your message has been sent!")
            await Searching.people_searching.set()
    if call.data.startswith("complain"):
        if not User(cid).get_complain_state(shown_profile):
            User(cid).update_complain_state(shown_profile)
            await message.answer(f"Describe the problem?:")
            await Searching.complain.set()
        else:
            await message.answer(f"Your complain is handling.")
            await Searching.people_searching.set()


async def message_to_shown(message: types.Message, state: FSMContext):
    cid = message.chat.id
    data = await state.get_data()
    shown_profile = data.get("shown_profile_id", "default_value")
    await message.answer("Message sent")
    await bot.send_message(shown_profile, "You got the message:\n"
                                                          f"{message.text}" )
    await bot.send_message(shown_profile,
                           "Do you want to see this user's profile",
                           reply_markup=yes_or_no_keyboard(cid))
    await Searching.message_or_complain_send.set()


async def yes_or_no_handler(call: types.CallbackQuery, state: FSMContext):
    if call.data.startswith('yes'):
        shown_profile = int(call.data[3:])
        await show_profile(shown_profile, call.message)
        User(call.from_user.id).update_last_shown_profile(shown_profile)
        await state.update_data(shown_profile_id=shown_profile)

        await Searching.people_searching.set()
    else:
        await call.message.answer("Ok")


async def complain_to_shown(message: types.Message, state : FSMContext):
    data = await state.get_data()
    shown_profile = data.get("shown_profile_id", "default_value")
    await bot.send_message(435472318,
                           f"Complain on {shown_profile}:\n"
                           f"{message.text}")
    await message.answer("Your complain sent!")
    await Searching.message_or_complain_send.set()


async def feedback_to_db(call, state : FSMContext):
    cid = call.from_user.id
    message = call.message

    if call.data.startswith("like"):
        if not User(cid).is_liked(call.data[4:]):
            User(cid).update_liked(call.data[4:])

            await mutual_profiles_show(call, call.data[4:])

            await bot.send_sticker(cid, get_random_sticker())
        else:
            await message.answer("I understand: You LIKED this user.")
            return
    else:
        if not User(cid).is_disliked(call.data[7:]):
            User(cid).update_disliked(call.data[7:])
        else:
            await message.answer("I understand: You DISLIKED this user.")
            return
    if User(cid).get_list_of_profiles().size == 0:
        await message.answer("The profiles are over. Come back tomorrow!")
        await Searching.end_of_profiles.set()

    else:
        shown_profile_id = int(User(cid).get_list_of_profiles()[0])
        await show_profile(shown_profile_id, message)
        await state.update_data(shown_profile_id=shown_profile_id)
        User(cid).update_last_shown_profile(shown_profile_id)
        await Searching.people_searching.set()




def register_handlers_searching(dp: Dispatcher):
    dp.register_message_handler(people_searching_mes, commands="searchi", state="*")
    dp.register_callback_query_handler(people_searching_cal, lambda call: call.data == "searchi", state="*")
    dp.register_callback_query_handler(feedback_to_db, lambda call: call.data == f"like{User(call.from_user.id).get_last_shown_profile()}"
                                       or call.data == f"dislike{User(call.from_user.id).get_last_shown_profile()}",
                                       state=[Searching.people_searching, Searching.message_or_complain_send])
    dp.register_callback_query_handler(message_or_complain,
                                       lambda call: call.data.startswith("message") or call.data.startswith("complain"),
                                       state=Searching.people_searching)

    dp.register_message_handler(message_to_shown, state=Searching.message)
    dp.register_message_handler(complain_to_shown, state=Searching.complain)

    dp.register_callback_query_handler(yes_or_no_handler,
                                       lambda call: call.data.startswith("yes")
                                       or call.data.startswith("no"),
                                       state="*")
