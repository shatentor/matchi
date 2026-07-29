from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Optional
from models.user import User


def start_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text='Start!🚶', callback_data='go')
    return builder.as_markup()


def gender_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text='M👨', callback_data='Male')
    builder.button(text='F👩', callback_data='Female')
    builder.button(text='Other🏳‍🌈', callback_data='Other')
    builder.adjust(3) # Распределит кнопки по 3 в ряд
    return builder.as_markup()


def admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text='Message to all users', callback_data='message_to_all')
    builder.button(text='Show all complains', callback_data='show_complains')
    builder.adjust(1) # По одной кнопке в ряд
    return builder.as_markup()


def change_profile_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Name📛", callback_data="change_name")
    builder.button(text="Gender 🌓", callback_data="change_gender")
    builder.button(text="City🏙", callback_data="change_city")
    builder.button(text="Age🧓", callback_data="change_age")
    builder.button(text="Description🗒", callback_data="change_description")
    builder.button(text="Photos📸", callback_data="change_photo")
    builder.button(text="Preferred gender💕", callback_data="change_preferred_gender")
    builder.button(text="Preferred age", callback_data="change_preferred_age")
    builder.adjust(2) # Распределит кнопки по 2 в ряд
    return builder.as_markup()


def photo_management_keyboard(user: User):
    builder = InlineKeyboardBuilder()

    has_photo_one = user.photo_link is not None
    has_photo_two = user.photo_link_two is not None
    has_photo_three = user.photo_link_three is not None

    # Кнопки для существующих фото
    if has_photo_one:
        builder.row( # row() используется для явного создания ряда
            types.InlineKeyboardButton(text="Изменить фото 1", callback_data="change_photo_one"),
            types.InlineKeyboardButton(text="Удалить фото 1", callback_data="delete_photo_one")
        )
    if has_photo_two:
        builder.row(
            types.InlineKeyboardButton(text="Изменить фото 2", callback_data="change_photo_two"),
            types.InlineKeyboardButton(text="Удалить фото 2", callback_data="delete_photo_two")
        )
    if has_photo_three:
        builder.row(
            types.InlineKeyboardButton(text="Изменить фото 3", callback_data="change_photo_three"),
            types.InlineKeyboardButton(text="Удалить фото 3", callback_data="delete_photo_three")
        )

    # Фото добавляются по порядку, поэтому предлагаем только первый свободный слот.
    # Текст кнопки нейтральный: номер слота пользователю не важен.
    # Ряд добавляем через row(), а не button() + adjust(): adjust() пересобирает
    # разметку из плоского списка всех кнопок и разрушил бы пары "Изменить/Удалить".
    if not has_photo_one:
        builder.row(types.InlineKeyboardButton(text="Добавить фото", callback_data="add_photo_one"))
    elif not has_photo_two:
        builder.row(types.InlineKeyboardButton(text="Добавить фото", callback_data="add_photo_two"))
    elif not has_photo_three:
        builder.row(types.InlineKeyboardButton(text="Добавить фото", callback_data="add_photo_three"))

    return builder.as_markup()


def preferred_gender_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text='M👨', callback_data='Male')
    builder.button(text='F👩', callback_data='Female')
    builder.button(text='Any💛', callback_data='Any')
    builder.adjust(3)
    return builder.as_markup()


def yes_or_no_keyboard(cid: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="Yes", callback_data="yes" + cid)
    builder.button(text="No", callback_data="no" + cid)
    builder.adjust(2)
    return builder.as_markup()


def searching_profiles_keyboard(tg_chat_id: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="Like👍", callback_data="like" + tg_chat_id)
    builder.button(text="Dislike👎", callback_data="dislike" + tg_chat_id)
    builder.button(text="Message💌", callback_data="message" + tg_chat_id)
    builder.button(text="Complain⛔", callback_data="complain" + tg_chat_id)
    builder.adjust(2)
    return builder.as_markup()


def city_keyboard(suggested_cities: List[str]):
    builder = InlineKeyboardBuilder()
    for city in suggested_cities:
        builder.button(text=city, callback_data=f"city_{city}")
    builder.button(text="There is no my city here", callback_data=f"city_no")
    builder.adjust(2, repeat=True) # По 2 кнопки в ряд, если это применимо
    return builder.as_markup()


def start_show_profiles():
    builder = InlineKeyboardBuilder()
    builder.button(text="Start viewing profiles", callback_data="searchi")
    return builder.as_markup()