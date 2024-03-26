import mariadb
from data_base.redis_conn import storage
from class_user import User
import config
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from keyboard import gender_keyboard, preferred_gender_keyboard, city_keyboard, photo_change_keyboard
from cities_functions import full_coincidence, get_relevant_cities



bot = Bot(token=config.token)
dp = Dispatcher(bot, storage=storage)
logging.basicConfig(level=logging.INFO)


class Change(StatesGroup):
    name_changing = State()
    age_changing = State()
    city_changing = State()
    city_mistake = State()
    gender_changing = State()
    description_changing = State()
    photo_selection = State()
    photo_changing = State()
    preferred_gender_changing = State()
    preferred_age_changing = State()
    high_preferred_age_point = State()
    preferred_age_to_db = State()


async def change_name_button(call):
    message = call.message
    await message.answer("Enter a new name:")
    await Change.name_changing.set()


async def new_name_to_db(message: types.Message):
    try:
        User(message.chat.id).update_name(message.text)
        await message.answer("Name changed successfully")
    except mariadb.DataError:
        await message.answer("To long name. \n"
                             "Try one more time:")
        await Change.name_changing.set()


async def change_age_button(call):
    message = call.message
    await message.answer("Enter your age:")
    await Change.age_changing.set()


async def new_age_to_db(message: types.Message):
    try:
        age = int(message.text)
        if 10 < age < 100:
            User(message.chat.id).update_age(age)
            await message.answer("Age changed successfully")
        else:
            await message.answer("Specify your age between 10 and 100:")
    except ValueError:
        await message.answer("Input an integer number.\n"
                             "Try one more time:")


async def change_city_button(call):
    message = call.message
    await message.answer("Enter new city:")
    await Change.city_changing.set()


async def new_city_to_db(message: types.Message):
    try:
        if full_coincidence(message.text):

            User(message.chat.id).update_full_coincidence_city(message.text)
            await message.answer("City changed successfully")

        else:
            if get_relevant_cities(message.text):
                await message.answer('Perhaps you meant:', reply_markup=city_keyboard(
                    get_relevant_cities(message.text)))
                await Change.city_mistake.set()
            else:
                await message.answer("Try one more time")

    except IndexError:
        await message.answer("There is not any city with such name in our bot! "
                             "Try it one more time:")


async def citi_mistake_button(call: types.CallbackQuery):
    message = call.message
    if call.data != "city_no":
        User(call.from_user.id).update_city(call.data)
        await message.answer("City changed successfully")
    else:
        await message.answer("Try one more time to enter your city:")
        await Change.city_changing.set()


async def change_gender_button(call):
    message = call.message
    await message.answer("Choose your gender:", reply_markup=gender_keyboard())
    await Change.gender_changing.set()


async def new_gender_to_db(call):
    message = call.message
    gender = call.data
    User(call.from_user.id).update_gender(gender)
    await message.answer("Gender changed successfully")


async def change_description_button(call):
    message = call.message
    await message.answer("Enter new profile description:")
    await Change.description_changing.set()


async def new_description_to_db(message: types.Message):
    try:
        User(message.chat.id).update_description(message.text)
        await message.answer("Description changed successfully")
    except mariadb.DataError:
        await message.answer("Limit exceeded.\n"
                             "Try one more time:")

def last_photo(cid):
    user = User(cid)
    photo_two_id = user.get_photo_two_id()
    photo_three_id = user.get_photo_three_id()

    if photo_three_id is None and photo_two_id is None:
        return "one"
    if photo_three_id is None and photo_two_id:
        return "two"
    if photo_three_id and photo_two_id is None:
        return "three"
    if photo_two_id and photo_three_id:
        return "all_exists"



async def change_photo_button(call):
    cid = call.from_user.id
    message = call.message

    photo_mapping = {
        "one": (True, False, False),
        "two": (False, True, False),
        "three": (False, False, True),
        "all_exists": (False, False, False)
    }

    add_one, add_two, add_three = photo_mapping.get(last_photo(cid), (False, False, False))

    await message.answer_photo(User(cid).get_photo_one_id(), reply_markup=photo_change_keyboard("_one", add_one))
    if User(cid).get_photo_two_id():
        await message.answer_photo(User(cid).get_photo_two_id(), reply_markup=photo_change_keyboard("_two", add_two))
    if User(cid).get_photo_three_id():
        await message.answer_photo(User(cid).get_photo_three_id(),
                                   reply_markup=photo_change_keyboard("_three", add_three))
    await Change.photo_selection.set()



async def photo_selected(call, state: FSMContext):
    cid = call.from_user.id
    message = call.message

    request_from_user = call.data
    await state.update_data(request_from_user = request_from_user)

    if call.data.startswith("add_photo"):
        await message.answer("Send photo:")
        await Change.photo_changing.set()

    elif call.data == "delete_photo_three":
        User(cid).delete_photo("delete_photo_three")
        await message.answer("Photo deleted")
    elif call.data == "delete_photo_two":
        User(cid).delete_photo("delete_photo_two")
        await message.answer("Photo deleted")

    else:
        await message.answer("Send new photo:")
        await Change.photo_changing.set()

async def new_photo_to_db(message: types.Message, state: FSMContext):
    cid = message.chat.id
    file_id = message.photo[-1].file_id

    data = await state.get_data()
    request_from_user = data.get('request_from_user', 'default_value')

    photo_functions = {
        "change_photo_one": User(cid).update_photo_link,
        "change_photo_two": User(cid).update_photo_link_two,
        "change_photo_three": User(cid).update_photo_link_three,
        "add_photo_one": User(cid).update_photo_link_two,
        "add_photo_two": User(cid).update_photo_link_three,
        "add_photo_three": User(cid).update_photo_link_two,
    }

    photo_functions[request_from_user](file_id)

    if request_from_user.startswith('change'):
        await message.answer("Photo changed successfully")
    else:
        await message.answer("Photo added successfully")



async def change_preferred_gender_button(call):
    message = call.message
    await message.answer("Choose preferred gender:", reply_markup=preferred_gender_keyboard())
    await Change.preferred_gender_changing.set()


async def new_preferred_gender_to_db(call):
    message = call.message
    preferred_gender = call.data
    User(message.chat.id).update_preferred_gender(preferred_gender)
    await message.answer("Preferred gender changed successfully")


async def change_preferred_age_button(call):
    message = call.message
    await message.answer("Enter the lower limit of your preferred age")
    await Change.preferred_age_changing.set()


async def lower_age_point_to_db(message: types.Message):
    try:
        lower_point = int(message.text)
        if 10 < lower_point < 100:
            User(message.chat.id).update_lower_age_point(message.text)
            await message.answer("Enter the upper limit of your preferred age")
            await Change.high_preferred_age_point.set()
        else:
            await message.answer("Enter a number from 10 to 100")
            await Change.preferred_age_changing.set()
    except ValueError:
        await message.answer("Try one more time")
        await Change.preferred_age_changing.set()


async def high_age_point_to_db(message: types.Message):
    lower_age_point = User(message.chat.id).get_lower_age_point()
    try:
        high_point = int(message.text)
        if 10 < high_point < 100 and high_point >= lower_age_point:
            User(message.chat.id).update_high_age_point(message.text)
            await message.answer("Preferred age changed successfully")
            await Change.preferred_age_to_db.set()
        else:
            await message.answer("Enter a number from 10 to 100")
            await Change.high_preferred_age_point.set()
    except ValueError:
        await message.answer("Try one more time")
        await Change.high_preferred_age_point.set()


def register_handlers_change_profile(dp: Dispatcher):
    dp.register_callback_query_handler(change_name_button,
                                       lambda call: call.data == "change_name", state="*")
    dp.register_message_handler(new_name_to_db, state=Change.name_changing)

    dp.register_callback_query_handler(change_age_button,
                                       lambda call: call.data == "change_age", state="*")
    dp.register_message_handler(new_age_to_db, state=Change.age_changing)

    dp.register_callback_query_handler(change_city_button,
                                       lambda call: call.data == "change_city", state="*")
    dp.register_message_handler(new_city_to_db, state=Change.city_changing)
    dp.register_callback_query_handler(citi_mistake_button,lambda call: call.data.startswith("city_"), state=Change.city_mistake)

    dp.register_callback_query_handler(change_gender_button,
                                       lambda call: call.data == "change_gender", state="*")
    dp.register_callback_query_handler(new_gender_to_db,
                                       lambda call: (call.data == 'Male' or call.data
                                                     == 'Female' or call.data == 'Other'),
                                       state=Change.gender_changing)
    dp.register_callback_query_handler(change_description_button,
                                       lambda call: call.data == "change_description", state="*")
    dp.register_message_handler(new_description_to_db, state=Change.description_changing)

    dp.register_callback_query_handler(change_photo_button,
                                       lambda call: call.data == "change_photo", state="*")
    dp.register_callback_query_handler(photo_selected,
                                       lambda call: call.data.startswith("change_photo")
                                       or call.data.startswith("delete_photo")
                                       or call.data.startswith("add_photo"), state=Change.photo_selection)
    dp.register_message_handler(new_photo_to_db, state=Change.photo_changing, content_types="photo")

    dp.register_callback_query_handler(change_preferred_gender_button,
                                       lambda call: call.data == 'change_preferred_gender', state="*")
    dp.register_callback_query_handler(new_preferred_gender_to_db,
                                       lambda call: (call.data == 'Male' or call.data
                                                     == 'Female' or call.data == 'Any'),
                                       state=Change.preferred_gender_changing)

    dp.register_callback_query_handler(change_preferred_age_button,
                                       lambda call: call.data == "change_preferred_age", state="*")
    dp.register_message_handler(lower_age_point_to_db, state=Change.preferred_age_changing)
    dp.register_message_handler(high_age_point_to_db, state=Change.high_preferred_age_point)
