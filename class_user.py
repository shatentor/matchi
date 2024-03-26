from data_base.db_connect_users import connect_to_database
from cities_functions import full_coincidence
import numpy as np
import mariadb
from aiogram import types

def execute_query(query, parameters=None):
    conn = connect_to_database()
    cur = conn.cursor()
    try:
        if parameters:
            cur.execute(query, parameters)
        else:
            cur.execute(query)
        try:
            result = cur.fetchall()
            return result
        #in case, when cursor is empty
        except mariadb.Error:
            pass
    except mariadb.Error:
        print ('Error: {e}')
        #create new connection
        conn = connect_to_database()
        cur = conn.cursor()
        if parameters:
            cur.execute(query, parameters)
        else:
            cur.execute(query)
        try:
            result = cur.fetchall()
            return result
        except mariadb.Error:
            pass

def get_id_by_gender(preferred_gender):
    ids = []
    if preferred_gender == "Any":
        result = execute_query("SELECT tg_chat_id FROM users")
        for tg_chat_id in result:
            ids.append(int(tg_chat_id[0]))
        return np.array(ids)
    else:
        result = execute_query("SELECT tg_chat_id FROM users WHERE gender = ?", (preferred_gender,))
        for tg_chat_id in result:
            ids.append(int(tg_chat_id[0]))
        return np.array(ids)


def get_id_by_city(city):
    result = execute_query("SELECT tg_chat_id FROM users WHERE city = ?", (city,))
    return np.array(result)


def get_list_of_gendered_ids(profile_id):
    result = execute_query(f'SELECT preferred_gender FROM users WHERE tg_chat_id = ?', (profile_id,))
    preferred_gender = result[0][0]
    return np.array(get_id_by_gender(preferred_gender))


def get_list_of_ids_by_city(profile_id):
    result = execute_query(f'SELECT city FROM users WHERE tg_chat_id = ?', (profile_id,))
    city = result[0][0]
    return get_id_by_city(city)


def get_list_of_no_shown_profiles(cid):
    no_shown = []
    result = execute_query("SELECT u.tg_chat_id FROM users u"
                f" LEFT JOIN dislikes d ON u.tg_chat_id = d.user_{cid}"
                f" LEFT JOIN likes l ON u.tg_chat_id = l.user_{cid}"
                f" WHERE d.user_{cid} IS NULL AND l.user_{cid} IS NULL")

    for tg_chat_id in result:
        no_shown.append(int(tg_chat_id[0]))
    return no_shown

def get_list_of_ids_by_age(lower_point, high_point):
    aged_list = []
    result = execute_query(f"SELECT tg_chat_id FROM users WHERE age > ? ", (lower_point-1,))
    for tg_chat_id in result:
        aged_list.append(int(tg_chat_id[0]))
    result = execute_query(f"SELECT tg_chat_id FROM users WHERE age < ? ", (high_point+1,))
    for tg_chat_id in result:
        if int(tg_chat_id[0]) not in aged_list:
            aged_list.append(int(tg_chat_id[0]))
    return aged_list



class User:
    def __init__(self, tg_chat_id):
        self.tg_chat_id = int(tg_chat_id)

    def crate_new_user(self, username):
        execute_query("INSERT INTO users (tg_username, tg_chat_id) \
                        VALUES(?,?)",
                      (username, self.tg_chat_id))
        execute_query("INSERT INTO descriptions (tg_chat_id) VALUES(?) ", (self.tg_chat_id,))
        execute_query(f"ALTER TABLE likes ADD COLUMN user_{self.tg_chat_id} VARCHAR(20) DEFAULT NULL")
        execute_query(f"ALTER TABLE dislikes ADD COLUMN user_{self.tg_chat_id} VARCHAR(20) DEFAULT NULL")
        execute_query(f"ALTER TABLE messages ADD COLUMN user_{self.tg_chat_id} VARCHAR(20) DEFAULT NULL")
        execute_query(f"ALTER TABLE complains ADD COLUMN user_{self.tg_chat_id} VARCHAR(20) DEFAULT NULL")
        execute_query(f"INSERT INTO likes (user_{self.tg_chat_id}) VALUES(?)", (None,))
        execute_query(f"INSERT INTO messages (user_{self.tg_chat_id}) VALUES(?)", (None,))
        execute_query(f"INSERT INTO dislikes (user_{self.tg_chat_id}) VALUES(?)", (None,))
        execute_query(f"INSERT INTO complains (user_{self.tg_chat_id}) VALUES(?)", (None,))
        return None

    def get_username(self):
        result = execute_query(f"SELECT tg_username FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None

    def get_name(self):
        result = execute_query(f"SELECT name FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None

    def get_age(self):
        result = execute_query(f"SELECT age FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None


    def update_name(self, message_name):
        execute_query(f'UPDATE users SET name = ? WHERE tg_chat_id = ?', (message_name, self.tg_chat_id))
        return None


    def update_full_coincidence_city(self, message_city):
        execute_query(f'UPDATE users SET city = ? WHERE tg_chat_id = ?',
                      (full_coincidence(message_city), self.tg_chat_id))
        return None


    def get_city(self):
        result = execute_query(f"SELECT city FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None


    def update_city(self, data_city):
        execute_query(f"UPDATE users SET city = ? WHERE tg_chat_id = ?", (data_city, self.tg_chat_id))
        return None


    def update_age(self, age):
        execute_query(f'UPDATE users SET age = ? WHERE tg_chat_id = ?', (age, self.tg_chat_id))
        return None


    def get_gender(self):
        result = execute_query(f"SELECT gender FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None


    def update_gender(self, data_gender):
        execute_query(f'UPDATE users SET gender = ? WHERE tg_chat_id = ?', (data_gender, self.tg_chat_id))
        return None


    def update_description(self, description):
        execute_query(f"UPDATE descriptions SET descr = ? WHERE tg_chat_id = ?", (description, self.tg_chat_id))
        return None


    def get_description(self):
        result = execute_query(f"SELECT descr FROM descriptions WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None


    def update_preferred_gender(self, preferred_gender):
        execute_query(f"UPDATE users SET preferred_gender = ? WHERE tg_chat_id = ?",
                      (preferred_gender, self.tg_chat_id))
        return None


    def get_preferred_gender(self):
        result = execute_query(f"SELECT preferred_gender FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None


    def update_photo_link(self, file_id):
        execute_query(f"UPDATE users SET photo_link = ? WHERE tg_chat_id = ?", (file_id, self.tg_chat_id))
        return None


    def update_photo_link_two(self, file_id):
        execute_query(f"UPDATE users SET photo_link_two = ? WHERE tg_chat_id = ?", (file_id, self.tg_chat_id))
        return None


    def update_photo_link_three(self, file_id):
        execute_query(f"UPDATE users SET photo_link_three = ? WHERE tg_chat_id = ?", (file_id, self.tg_chat_id))
        return None


    def get_list_of_profiles(self):
        # intersection
        gendered_no_shown_profiles = np.intersect1d(get_list_of_no_shown_profiles(self.tg_chat_id),
                                                    get_list_of_gendered_ids(self.tg_chat_id))

        aged_list = np.intersect1d(gendered_no_shown_profiles, get_list_of_ids_by_age(
            User(self.tg_chat_id).get_lower_age_point(), User(self.tg_chat_id).get_high_age_point()))

        # delete our user from list
        user_index = np.argwhere(aged_list == self.tg_chat_id)
        # sorted without cities
        without_cities = np.delete(aged_list, user_index)

        # delete all unregistered users
        for chat_id in without_cities:
            if User(chat_id).is_registered() == "no" or User(chat_id).is_registered() is None:
                index = np.argwhere(without_cities == chat_id)
                without_cities = np.delete(without_cities, index)
        return without_cities


    def mutual_like(self, shown_profile_id):
        result = execute_query(f"SELECT COUNT(*) FROM likes WHERE user_{shown_profile_id} = {self.tg_chat_id}")
        if result[0][0] == 0:
            return False
        else:
            return True

    def get_list_of_liked(self):
        result = execute_query(f"SELECT user_{self.tg_chat_id} FROM likes WHERE user_{self.tg_chat_id} IS NOT NULL")
        return result if result else None

    def get_photo_one_id(self):
        result = execute_query(f"SELECT photo_link FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None


    def get_photo_two_id(self):
        result = execute_query(f"SELECT photo_link_two FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None


    def get_photo_three_id(self):
        result = execute_query(f"SELECT photo_link_three FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None


    def get_media_group(self):
        media = types.MediaGroup()
        media.attach_photo(User(self.tg_chat_id).get_photo_one_id(), '')
        if User(self.tg_chat_id).get_photo_two_id():
            media.attach_photo(User(self.tg_chat_id).get_photo_two_id(), '')
        if User(self.tg_chat_id).get_photo_three_id():
            media.attach_photo(User(self.tg_chat_id).get_photo_three_id(), '')
        return media

    def is_liked(self, shown_profile_id):
        result = execute_query(f"SELECT COUNT(*) FROM likes WHERE user_{self.tg_chat_id} = {shown_profile_id}")
        if result[0][0] == 0:
            return False
        else:
            return True

    def is_disliked(self, shown_profile_id):
        result = execute_query(f"SELECT COUNT(*) FROM dislikes WHERE user_{self.tg_chat_id} = {shown_profile_id}")
        if result[0][0] == 0:
            return False
        else:
            return True

    def delete_photo(self, number):
        if number == "delete_photo_two":
            execute_query(f"UPDATE users SET photo_link_two = null WHERE tg_chat_id = ?", (self.tg_chat_id,))
        if number == "delete_photo_three":
            execute_query(f"UPDATE users SET photo_link_three = null WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return None


    def update_last_shown_profile(self, shown_profile):
        execute_query(f"UPDATE users SET last_shown_profile = ? WHERE tg_chat_id = ?", (shown_profile, self.tg_chat_id))
        return None


    def get_last_shown_profile(self):
        result = execute_query(f"SELECT last_shown_profile FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None


    def update_support_time(self, time):
        execute_query(f"UPDATE users SET support_time = ? WHERE tg_chat_id = ?", (time, self.tg_chat_id))
        return None


    def get_support_time(self):
        result = execute_query(f"SELECT support_time FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return int(result[0][0]) if result else None


    def get_complain_state(self, shown_profile_id):
        result = execute_query(f"SELECT COUNT(*) FROM complains WHERE user_{self.tg_chat_id} = {shown_profile_id}")
        if result[0][0] == 0:
            return False
        else:
            return True


    def get_message_state(self, shown_profile_id):
        result = execute_query(f"SELECT COUNT(*) FROM messages WHERE user_{self.tg_chat_id} = {shown_profile_id}")
        if result[0][0] == 0:
            return False
        else:
            return True


    def update_complain_state(self, shown_id):
        result = execute_query(f"SELECT id FROM complains WHERE user_{self.tg_chat_id} IS NULL")
        number = result[0][0]
        execute_query(f"UPDATE complains SET user_{self.tg_chat_id} = ? WHERE id = ? ", (shown_id, number))
        return None


    def update_message_state(self, shown_id):
        result = execute_query(f"SELECT id FROM messages WHERE user_{self.tg_chat_id} IS NULL")
        number = result[0][0]
        execute_query(f"UPDATE messages SET user_{self.tg_chat_id} = ? WHERE id = ? ", (shown_id, number))
        return None


    def update_liked(self, shown_id):
        result = execute_query(f"SELECT id FROM likes WHERE user_{self.tg_chat_id} IS NULL")
        insert_number = result[0][0]
        execute_query(f"UPDATE likes SET user_{self.tg_chat_id} = ? WHERE id = ?", (shown_id, insert_number))
        return None


    def update_disliked(self, shown_id):
        result = execute_query(f"SELECT id FROM dislikes WHERE user_{self.tg_chat_id} IS NULL")
        insert_number = result[0][0]
        execute_query(f"UPDATE dislikes SET user_{self.tg_chat_id} = ? where id = ?", (shown_id, insert_number))
        return None


    def is_registered(self):
        result = execute_query(f"SELECT is_registered FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return result[0][0] if result else None


    def update_register_status(self, status):
        execute_query(f"UPDATE users SET is_registered = ? WHERE tg_chat_id = ?", (status, self.tg_chat_id))
        return None


    def get_lower_age_point(self):
        result = execute_query(f"SELECT age_lower_point FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return int(result[0][0]) if result else None


    def get_high_age_point(self):
        result = execute_query(f"SELECT age_high_point FROM users WHERE tg_chat_id = ?", (self.tg_chat_id,))
        return int(result[0][0]) if result else None


    def update_lower_age_point(self, l_age_point):
        execute_query(f"UPDATE users SET age_lower_point = ? WHERE tg_chat_id = ?", (l_age_point, self.tg_chat_id))
        return None


    def update_high_age_point(self, h_age_point):
        execute_query(f"UPDATE users SET age_high_point = ? WHERE tg_chat_id = ?", (h_age_point, self.tg_chat_id))
        return None


def select_all_tg_chat_id():
    result = execute_query(f"SELECT tg_chat_id FROM users")
    return result if result else None

