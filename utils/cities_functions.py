# from main_structure.list_of_cities import cities # <-- Устаревший импорт
from typing import List, Optional

# В идеале cities должен быть загружен из файла/конфига, а не хардкодом.
# Для текущей структуры мы предположим, что list_of_cities.py будет перемещен в utils/
# или его содержимое будет встроено. Для чистоты - прямое импортирование.
# Если list_of_cities.py перемещен в utils/, то импорт будет from .list_of_cities import cities

# Пока что скопируем список cities для автономности utils/cities_functions.py
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
    "Vienna", "Graz", "Linz", "Salzburg", "Innsbruck",
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


def full_coincidence(message: str) -> Optional[str]:
    for city in cities:
        if city.lower() == message.lower():
            return city
    return None


def get_relevant_cities(message: str) -> List[str]:
    split_city = list(message.lower())
    coincidence_dict = {}
    relevant_cities = []

    for city in cities:
        lettered_city = list(city.lower())
        letter_from_user = 0
        coincidence_counter = 0
        for letter in lettered_city:
            try:
                if letter == split_city[letter_from_user]:
                    coincidence_counter += 1
                else:
                    # Попытка учесть опечатки на одну букву вперед/назад
                    if letter_from_user > 0 and letter == split_city[letter_from_user - 1]:
                        pass  # Уже учтено или пропуск
                    elif letter_from_user + 1 < len(split_city) and letter == split_city[letter_from_user + 1]:
                        letter_from_user += 1  # Пропускаем букву пользователя, если совпала следующая
            except IndexError:
                pass
            letter_from_user += 1

        coincidence_dict[city] = coincidence_counter

    # Выбираем города с максимальным совпадением, если оно достаточно велико
    if not coincidence_dict:
        return []

    max_coincidence = 0
    if coincidence_dict:
        max_coincidence = max(coincidence_dict.values())

    for key, value in coincidence_dict.items():
        if value == max_coincidence and len(list(key)) // 2 < value:  # Добавлено условие, что совпадение значимо
            relevant_cities.append(key)

    # Сортируем по совпадению (чем больше, тем лучше), затем по длине (короче - лучше), затем по алфавиту
    relevant_cities.sort(key=lambda c: (-coincidence_dict[c], len(c), c))
    return relevant_cities[:5]  # Ограничим до 5 наиболее релевантных городов