from list_of_cities import cities


def full_coincidence(message):
    for city in cities:
        if city.lower() == message.lower():
            return city


def get_relevant_cities(message):
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
                    #in case double click or letter missing
                else:
                    if letter == split_city[letter_from_user - 1]:
                        letter_from_user -= 1
                    if letter == split_city[letter_from_user + 1]:
                        letter_from_user += 1
            # index split_city[letter_from_user + 1] can go out of massive bound
            except IndexError:
                pass
            letter_from_user += 1

        coincidence_dict[city] = coincidence_counter

    for key in coincidence_dict.keys():
        if max(coincidence_dict.values()) == coincidence_dict[key] \
                and len(list(key)) // 2 < coincidence_dict[key]:
            relevant_cities.append(key)
    return relevant_cities

