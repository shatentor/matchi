import mariadb
import asyncio
from cities_functions import full_coincidence, get_relevant_cities
from config import token
from class_user import User
from data_base.redis_conn import storage
import logging
from aiogram import Bot, Dispatcher, types
from keyboard import gender_keyboard, preferred_gender_keyboard, city_keyboard, start_show_profiles
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup



bot = Bot(token=token)
dp = Dispatcher(bot, storage=storage)
loop = asyncio.get_event_loop()


logging.basicConfig(level=logging.INFO)


class Register(StatesGroup):
    name = State()
    city = State()
    city_to_db = State()
    age = State()
    gender = State()
    description = State()
    preferred_gender = State()
    preferred_age = State()
    age_high_point = State()
    photo = State()


async def name_func(call):
    message = call.message
    cid = call.from_user.id
    username = call.from_user.username
    if User(cid).is_registered() is None:
        try:
            User(cid).crate_new_user(username)
            await message.answer('What is your name?')
            await Register.name.set()

        except mariadb.IntegrityError:
            await call.message.answer('It is not possible to registrate without username.')
    elif User(cid).is_registered() == "yes":
        await message.answer('You are already registered')
    else:
        await message.answer("Please end registration")
    User(cid).update_register_status("no")


async def city_func(message: types.Message):
    try:
        User(message.chat.id).update_name(message.text)
        await message.answer('Enter your city:')
        await Register.city.set()
    except mariadb.DataError:
        await message.answer("To long name. \n"
                             "Try one more:")
        await Register.name.set()


async def correct_city_func(message: types.Message):
    try:
        if full_coincidence(message.text):
            User(message.chat.id).update_full_coincidence_city(message.text)
            await message.answer("How old are you ?")
            await Register.age.set()

        else:
            if get_relevant_cities(message.text):
                await message.answer('Perhaps you meant:', reply_markup=city_keyboard(get_relevant_cities(
                    message.text)))
                await Register.city_to_db.set()
            else:
                await message.answer("Try one more time")
    except IndexError:
        await message.answer("There is not any city with such name in our bot! "
                             "Try it one more time:")


async def age_func(call: types.CallbackQuery):
    message = call.message
    if call.data != "city_no":
        User(call.from_user.id).update_city(call.data)
        await message.answer("How old are you?")
        await Register.age.set()
    else:
        await message.answer("Try one more time to enter your city:")
        await Register.city.set()


async def gender_func(message: types.Message):
    try:
        age = int(message.text)
        if 10 < age < 100:
            User(message.chat.id).update_age(age)
            await message.answer('Choose your gender:', reply_markup=gender_keyboard())
            await Register.gender.set()
        else:
            await message.answer("Specify you age (between 10 and 100):")

    except ValueError:
        await message.answer("Error: try to input integer numbers.")


async def description_func(call):
    gender = call.data
    message = call.message
    User(call.from_user.id).update_gender(gender)

    await message.answer("Write you profile description (Limit - 1000 simbols):")
    await Register.description.set()


async def preferred_gender_func(message: types.Message):
    try:
        User(message.chat.id).update_description(message.text)
        await message.answer("Select your preferred gender", reply_markup=preferred_gender_keyboard())
        await Register.preferred_gender.set()

    except mariadb.DataError:
        await message.answer("Limit exceeded.\n"
                             "Try one more time:")


async def preferred_age_func(call):
    preferred_gender = call.data
    message = call.message
    User(call.from_user.id).update_preferred_gender(preferred_gender)
    await message.answer("Please indicate the lower limit of your preferred age:")
    await Register.preferred_age.set()


async def age_high_point_func(message: types.Message):
    try:
        lower_point = int(message.text)
        if 10 < lower_point < 100:
            User(message.chat.id).update_lower_age_point(message.text)
            await message.answer("Indicate the higher limit of your preferred age:")
            await Register.age_high_point.set()
        else:
            await message.answer("Indicate number between 10 and 100:")
    except ValueError:
        await message.answer("One more time :")


async def photo_func(message):
    lower_point = User(message.chat.id).get_lower_age_point()
    try:
        high_point = int(message.text)
        if 10 < high_point < 100 and high_point > lower_point:
            User(message.chat.id).update_high_age_point(message.text)
            await message.answer("And the last one...")
            await message.answer("Send up to three photos of yourself (in one message): ")
            await Register.photo.set()
        else:
            await message.answer("Indicate number between 10 and 100 and bigger than lower age point:")
    except ValueError:
        await message.answer("One more time:")


async def photo_to_db(message: types.Message, state: FSMContext):
    cid = message.chat.id
    # Iterate over each PhotoSize object in the list
    for photo in message.photo:
        # Access the file ID of each photo
        file_id = photo.file_id
        try:
            if User(cid).get_photo_one_id() is None:
                User(cid).update_photo_link(file_id)
                await message.answer("Thank you!\n"
                                     "Registration completed", reply_markup=start_show_profiles())
                User(cid).update_register_status("yes")
                return
            if User(cid).get_photo_two_id() is None:
                User(cid).update_photo_link_two(file_id)
                return
            if User(cid).get_photo_three_id() is None:
                User(cid).update_photo_link_three(file_id)
                return
        except Exception as e:
            logging.error(f"Error processing photo upload: {e}")
            await message.answer("An error occurred while processing your photos. Please try again.")
            return
    await state.finish()

def register_handlers_registration(dp: Dispatcher):
    dp.register_callback_query_handler(name_func, lambda call: call.data == 'go' and ( User(call.from_user.id).is_registered()is None),
                                       state="*")

    dp.register_message_handler(city_func, state=Register.name)
    dp.register_message_handler(correct_city_func, state=Register.city)
    dp.register_callback_query_handler(age_func, lambda call: call.data.stertswith("city"),
                                       state=Register.city_to_db)
    dp.register_message_handler(gender_func, state=Register.age)

    dp.register_callback_query_handler(description_func, lambda call: (call.data == 'Male' or call.data
                                                                       == 'Female' or call.data == 'Other'),
                                       state=Register.gender)

    dp.register_message_handler(preferred_gender_func, state=Register.description)
    dp.register_callback_query_handler(preferred_age_func, lambda call: (call.data == 'Male' or call.data
                                                                         == 'Female' or call.data == 'Any'),
                                       state=Register.preferred_gender)
    dp.register_message_handler(age_high_point_func, state=Register.preferred_age)

    dp.register_message_handler(photo_func, state=Register.age_high_point)
    dp.register_message_handler(photo_to_db, state=Register.photo, content_types="photo")
