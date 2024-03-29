from aiogram import types


def start_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=5)
    keyboard.add(types.InlineKeyboardButton('Start!🚶', callback_data='go'))
    return keyboard


def gender_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    keyboard.add(types.InlineKeyboardButton('M👨', callback_data='Male'))
    keyboard.add(types.InlineKeyboardButton('F👩', callback_data='Female'))
    keyboard.add(types.InlineKeyboardButton('Other🏳‍🌈', callback_data='Other'))
    return keyboard

def admin_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=4)
    keyboard.add(types.InlineKeyboardButton('Message to all users', callback_data='message_to_all'))
    return keyboard

def change_profile_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=4)
    keyboard.add(types.InlineKeyboardButton("Name📛", callback_data="change_name"))
    keyboard.add(types.InlineKeyboardButton("Gender 🌓", callback_data="change_gender"))
    keyboard.add(types.InlineKeyboardButton("City🏙", callback_data="change_city"))
    keyboard.add(types.InlineKeyboardButton("Age🧓", callback_data="change_age"))
    keyboard.add(types.InlineKeyboardButton("Description🗒", callback_data="change_description"))
    keyboard.add(types.InlineKeyboardButton("Photos📸", callback_data="change_photo"))
    keyboard.add(types.InlineKeyboardButton("Preferred gender💕", callback_data="change_preferred_gender"))
    keyboard.add(types.InlineKeyboardButton("Preferred age", callback_data="change_preferred_age"))
    return keyboard


def photo_change_keyboard(number, add):
    keyboard = types.InlineKeyboardMarkup(row_width=4)
    change_button = types.InlineKeyboardButton("Change", callback_data="change_photo"+number)
    delete_button = types.InlineKeyboardButton("Delete", callback_data="delete_photo"+number)
    add_photo_button = types.InlineKeyboardButton("Add photo", callback_data="add_photo"+number)
    if number == "_one":
        keyboard.add(change_button)
    else:
        keyboard.row(change_button, delete_button)
    if add:
        keyboard.add(add_photo_button)
    return keyboard


def preferred_gender_keyboard():
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    keyboard.add(types.InlineKeyboardButton('M👨', callback_data='Male'))
    keyboard.add(types.InlineKeyboardButton('F👩', callback_data='Female'))
    keyboard.add(types.InlineKeyboardButton('Any💛', callback_data='Any'))
    return keyboard


def yes_or_no_keyboard(cid):
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    yes_button = types.InlineKeyboardButton("Yes", callback_data="yes"+str(cid))
    no_button = types.InlineKeyboardButton("No", callback_data="no"+str(cid))
    keyboard.row(yes_button, no_button)
    return keyboard


def searching_profiles_keyboard(tg_chat_id):
    keyboard = types.InlineKeyboardMarkup(row_width=3)
    like_button = types.InlineKeyboardButton("Like👍", callback_data="like" + tg_chat_id)
    dislike_button = types.InlineKeyboardButton("Dislike👎", callback_data="dislike" + tg_chat_id)
    send_message_button = types.InlineKeyboardButton("Message💌", callback_data="message" + tg_chat_id)
    complain_button = types.InlineKeyboardButton("Complain⛔", callback_data="complain" + tg_chat_id)
    keyboard.row(like_button, dislike_button)
    keyboard.row(send_message_button, complain_button)
    return keyboard


def city_keyboard(suggested_cities):
    keyboard = types.InlineKeyboardMarkup(row_width=4)
    for city in suggested_cities:
        keyboard.add(types.InlineKeyboardButton(city, callback_data=f"city_{city}"))
        keyboard.add(types.InlineKeyboardButton("There is no my city here", callback_data=f"city_no"))
    return keyboard


def start_show_profiles():
    keyboard = types.InlineKeyboardMarkup(row_width=5)
    start_button = types.InlineKeyboardButton("Start viewing profiles", callback_data="searchi")
    keyboard.add(start_button)
    return keyboard
