"""Поиск города по вводу пользователя.

Модуль отвечает за сопоставление введённой пользователем строки со списком
поддерживаемых городов: точное совпадение (`full_coincidence`) и подсказка
похожих названий при опечатке или недописанном слове (`get_relevant_cities`).

Список городов задан статически прямо в модуле — осознанное упрощение,
внешнего хранилища/конфига для него нет.
"""
from difflib import SequenceMatcher
from typing import List, Optional

# Максимум подсказок, которые уходят в клавиатуру бота.
MAX_SUGGESTIONS = 5
# Минимальная длина ввода, при которой имеет смысл искать похожие города.
MIN_QUERY_LENGTH = 2
# Порог схожести difflib: ниже — считаем, что города не похожи.
SIMILARITY_THRESHOLD = 0.6

cities = [
    "Moscow", "Istanbul", "London", "Saint Petersburg", "Berlin",
    "Madrid", "Kiev", "Rome", "Paris", "Bucharest",
    "Budapest", "Warsaw", "Vienna", "Barcelona", "Kharkiv",
    "Munich", "Milan", "Prague", "Sofia", "Brussels",
    "Birmingham", "Cologne", "Naples", "Stockholm", "Amsterdam",
    "Zagreb", "Frankfurt", "Marseille", "Belgrade", "Oslo",
    "Copenhagen", "Helsinki", "Dublin", "Rotterdam", "Lisbon",
    "Manchester", "Athens", "Hamburg", "Vilnius",
    "Zurich", "Lyon", "Riga",
    "Stuttgart", "Glasgow", "Porto",
    "Poznan", "Seville", "Geneva", "Valencia",
    "Krakow", "Leipzig", "Palermo", "Bristol", "Turin",
    "Bremen", "Bratislava", "Katowice", "Antwerp", "The Hague",
    "Utrecht", "Thessaloniki", "Tallinn", "Dresden", "Bologna",
    "Genoa", "Gothenburg", "Sheffield", "Hanover", "Nuremberg",
    "Szczecin", "Bydgoszcz",
    "Mannheim", "Ostrava", "Timisoara", "Ljubljana",
    "Bochum", "Wuppertal", "Murcia", "Valladolid", "Wroclaw",
    "Aarhus", "Varna", "Gdansk",
    "Constanta", "Brno", "Florence",
    "Graz", "Linz", "Salzburg", "Innsbruck",
    "Klagenfurt", "Villach", "Wels", "Sankt Pölten", "Dornbirn",
    "Steyr", "Wiener Neustadt", "Feldkirch", "Bregenz", "Wolfsberg",
    "Baden", "Klosterneuburg", "Leoben", "Krems", "Traun",
    "Amstetten", "Lustenau", "Kapfenberg", "Mödling", "Hallein",
    "Kufstein", "Hohenems", "Bludenz", "Wörgl", "Eisenstadt",
    "Leonding", "Gmunden", "Tulln", "Braunau am Inn", "Ansfelden",
    "Stockerau", "Telfs", "Feldkirchen in Kärnten", "Bad Ischl", "Schwaz",
    "Hall in Tirol", "Bruck an der Mur", "Ternitz", "Korneuburg",
    "Rankweil", "Knittelfeld", "Perchtoldsdorf", "Traiskirchen", "Trofaiach",
    "Mistelbach"
]


def _normalize(message: Optional[str]) -> str:
    """Приводит ввод к нижнему регистру без пробелов по краям, None -> ''."""
    return message.strip().lower() if message else ""


def _similarity(query: str, city: str) -> float:
    """Схожесть ввода с названием города: максимум по всему названию и его словам.

    Отдельные слова сравниваем только если они сопоставимы по длине с вводом,
    иначе короткие служебные слова ("in", "am") дают ложные совпадения.
    """
    city_lower = city.lower()
    words = [word for word in city_lower.split()
             if len(word) >= 3 and abs(len(word) - len(query)) <= 2]
    return max(SequenceMatcher(None, query, part).ratio()
               for part in (city_lower, *words))


def full_coincidence(message: Optional[str]) -> Optional[str]:
    """Возвращает город при точном совпадении (без учёта регистра), иначе None."""
    query = _normalize(message)
    if not query:
        return None
    for city in cities:
        if city.lower() == query:
            return city
    return None


def get_relevant_cities(message: Optional[str]) -> List[str]:
    """Подсказывает до MAX_SUGGESTIONS похожих городов для введённой строки.

    Порядок выдачи: сначала города, начинающиеся с введённой строки, затем
    содержащие её как подстроку, затем похожие по difflib (опечатки).
    Внутри группы — по убыванию схожести, затем по длине названия и алфавиту.
    Если ничего подходящего нет, возвращается пустой список.
    """
    query = _normalize(message)
    if len(query) < MIN_QUERY_LENGTH:
        return []

    scored: List[tuple[int, float, int, str]] = []
    for city in cities:
        city_lower = city.lower()
        similarity = _similarity(query, city)
        if city_lower.startswith(query):
            group = 0
        elif query in city_lower:
            group = 1
        elif similarity >= SIMILARITY_THRESHOLD:
            group = 2
        else:
            continue
        scored.append((group, -similarity, len(city), city))

    scored.sort()
    # dict.fromkeys — страховка от дубликатов в списке городов.
    return list(dict.fromkeys(item[3] for item in scored))[:MAX_SUGGESTIONS]
