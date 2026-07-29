from typing import List, Optional, Sequence, Tuple

from aiogram import types
from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder

from keyboards.dialogs import DialogCB
from models.interest import Interest

# Номера участников на странице показываем по четыре в ряд: подписи короткие,
# а в один столбец страница из восьми человек занимает весь экран.
NUMBERS_PER_ROW = 4
# Интересы и города — по два в ряд, их названия длиннее номера.
FILTERS_PER_ROW = 2
# Сколько городов предлагать кнопками. Дальше список всё равно не читается,
# а каждая кнопка — это ещё и риск не влезть в 64 байта callback_data.
CITIES_LIMIT = 12


class DirectoryCB(CallbackData, prefix="dir"):
    """callback_data каталога участников.

    Фабрика вместо склейки префиксов: склейка в этом проекте уже дала коллизию
    ("message" внутри "message_to_all"), и для новых кнопок так больше не делаем.

    action: page — страница списка, open — карточка участника,
    search — попросить текст для поиска, interests/cities — меню фильтра,
    interest/city — выбранный фильтр (0 и "" означают «все»),
    reset — снять все фильтры.

    Текста поиска здесь нет намеренно: callback_data ограничена 64 байтами, и
    произвольная строка (тем более кириллицей) в неё не укладывается — активный
    фильтр живёт в данных FSM.
    """
    action: str
    page: int = 0
    peer_id: int = 0
    interest_id: int = 0
    city: str = ""


def _button(text: str, action: str, page: int = 0, peer_id: int = 0,
            interest_id: int = 0, city: str = "") -> Optional[types.InlineKeyboardButton]:
    """Кнопка каталога или None, если callback_data не укладывается в 64 байта.

    Название города приходит из анкеты, то есть от человека: длинное значение
    или двоеточие в нём иначе уронили бы отрисовку всей клавиатуры.
    """
    try:
        data = DirectoryCB(action=action, page=page, peer_id=peer_id,
                           interest_id=interest_id, city=city).pack()
    except ValueError:
        return None
    return types.InlineKeyboardButton(text=text, callback_data=data)


def _rows(builder: InlineKeyboardBuilder,
          buttons: Sequence[types.InlineKeyboardButton], per_row: int) -> None:
    """Раскладывает кнопки по per_row в ряд.

    Только row(): adjust() пересобирает разметку из плоского списка и утащил бы
    кнопки фильтров в общий ряд с номерами участников.
    """
    row: List[types.InlineKeyboardButton] = []
    for button in buttons:
        row.append(button)
        if len(row) == per_row:
            builder.row(*row)
            row = []
    if row:
        builder.row(*row)


def directory_list_keyboard(entries: Sequence[Tuple[int, int]], page: int, pages: int,
                            has_filters: bool = False) -> types.InlineKeyboardMarkup:
    """Список каталога: номера участников, листание и фильтры.

    entries — пары (номер в списке, tg_chat_id). Номер совпадает с номером
    строки в тексте сообщения: имя в подписи кнопки заняло бы весь ряд, а
    в боте нет прокрутки, чтобы сопоставлять длинный список с длинными кнопками.
    """
    builder = InlineKeyboardBuilder()

    numbers = [button for button in
               (_button(str(number), "open", page=page, peer_id=peer_id)
                for number, peer_id in entries)
               if button is not None]
    _rows(builder, numbers, NUMBERS_PER_ROW)

    # Стрелки показываем только там, куда действительно можно уйти; хендлер всё
    # равно приводит номер страницы к существующему — кнопку могли нажать в
    # старом сообщении, когда людей уже стало меньше.
    nav: List[types.InlineKeyboardButton] = []
    if page > 0:
        nav.append(_button("⬅️", "page", page=page - 1))
    if pages and page < pages - 1:
        nav.append(_button("➡️", "page", page=page + 1))
    nav = [button for button in nav if button is not None]
    if nav:
        builder.row(*nav)

    filters = [_button("🔎 Поиск", "search", page=page),
               _button("🏷 По интересу", "interests", page=page),
               _button("📍 По городу", "cities", page=page)]
    _rows(builder, [button for button in filters if button is not None], FILTERS_PER_ROW)

    if has_filters:
        reset = _button("✖️ Сбросить фильтры", "reset")
        if reset is not None:
            builder.row(reset)

    return builder.as_markup()


def directory_card_keyboard(peer_id: int, back_page: int = 0) -> types.InlineKeyboardMarkup:
    """Карточка участника: написать ему и вернуться к списку.

    «Написать» намеренно упаковано в DialogCB существующих личных диалогов:
    её подхватывает уже работающий хендлер `DialogHandlers.enter_dialog_callback`
    (action="open"), и второй релей сообщений каталогу не нужен.
    """
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(
        text="💬 Написать",
        callback_data=DialogCB(action="open", peer_id=peer_id).pack()
    ))
    back = _button("⬅️ К списку", "page", page=back_page)
    if back is not None:
        builder.row(back)
    return builder.as_markup()


def directory_interests_keyboard(interests: Sequence[Interest],
                                 selected_id: Optional[int] = None
                                 ) -> types.InlineKeyboardMarkup:
    """Выбор одного интереса для фильтра. Выбранный помечен галочкой."""
    builder = InlineKeyboardBuilder()

    buttons = []
    for interest in interests:
        if interest.id is None:
            continue
        mark = "✅ " if interest.id == selected_id else ""
        button = _button(f"{mark}{interest.title}", "interest", interest_id=interest.id)
        if button is not None:
            buttons.append(button)
    _rows(builder, buttons, FILTERS_PER_ROW)

    all_button = _button("Любой интерес", "interest", interest_id=0)
    if all_button is not None:
        builder.row(all_button)
    back = _button("⬅️ К списку", "page")
    if back is not None:
        builder.row(back)
    return builder.as_markup()


def directory_cities_keyboard(cities: Sequence[Tuple[str, int]],
                             selected: Optional[str] = None) -> types.InlineKeyboardMarkup:
    """«Кто рядом»: города с числом участников."""
    builder = InlineKeyboardBuilder()

    buttons = []
    for city, members in cities[:CITIES_LIMIT]:
        mark = "✅ " if selected and city == selected else ""
        button = _button(f"{mark}{city} · {members}", "city", city=city)
        if button is not None:
            buttons.append(button)
    _rows(builder, buttons, FILTERS_PER_ROW)

    all_button = _button("Любой город", "city", city="")
    if all_button is not None:
        builder.row(all_button)
    back = _button("⬅️ К списку", "page")
    if back is not None:
        builder.row(back)
    return builder.as_markup()


def search_cancel_keyboard() -> types.InlineKeyboardMarkup:
    """Выход из состояния поиска кнопкой: иначе из него виден только выход командой."""
    builder = InlineKeyboardBuilder()
    button = _button("✖️ Не искать", "reset")
    if button is not None:
        builder.row(button)
    return builder.as_markup()
