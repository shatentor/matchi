import mariadb

def connect_to_database():
    try:
        conn = mariadb.connect(
            user="user",
            password="**********",
            host="**************",
            port=3306,
            database="match_bot",
            autocommit=True
        )
        return conn
    except mariadb.Error as e:
        print(f"Error connecting to MariaDB Platform: {e}")
        return None


def is_admin(nickname):
    if nickname == "admin":
        return True


def add_sticker_to_db(sticker_id):
    connect_to_database().cur.execute(f'INSERT INTO stickers (lovely) VALUES(?)', (sticker_id,))
