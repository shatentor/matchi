"""Быстрая проверка сборки Matchi без живой БД и без токена Telegram.

Запуск из корня проекта: python scripts/smoke_check.py
Проверяет импорты, сборку роутеров, фильтры, middleware, экранирование,
клавиатуры, подсказки городов и синтаксис SQL (последнее — если стоит sqlglot).
"""
import asyncio
import os
import pathlib
import re
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("BOT_TOKEN", "123456:test")
os.environ.setdefault("ADMIN_IDS", "111")

FAILURES = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(name)


# ---------- 1. Импорт всех модулей проекта ----------
import importlib

MODULES = [
    "config.settings", "utils.text", "utils.telegram", "utils.cities_functions",
    "models.user", "models.like", "models.dislike", "models.complain", "models.message",
    "db.connection", "db.repositories.base", "db.repositories.user_repo",
    "db.repositories.like_repo", "db.repositories.dislike_repo", "db.repositories.sticker_repo",
    "db.repositories.complain_repo", "db.repositories.message_repo",
    "services.user_service", "services.matching_service", "services.admin_service",
    "services.support_service",
    "filters.custom_filters", "middlewares.user_context", "keyboards.inline",
    "handlers.registration", "handlers.commands", "handlers.profile_management",
    "handlers.profile_search", "handlers.admin", "main",
]
for m in MODULES:
    try:
        importlib.import_module(m)
        check(f"import {m}", True)
    except Exception as e:
        check(f"import {m}", False, f"{type(e).__name__}: {e}")

if FAILURES:
    print("\nАварийный выход: модули не импортируются")
    sys.exit(1)

# ---------- 2. Модели Pydantic v2 ----------
from models.complain import Complain
from models.message import Message as MsgModel
from models.user import User

try:
    Complain(reporter_chat_id="1", reported_chat_id="2", reason="spam")
    MsgModel(sender_chat_id="1", receiver_chat_id="2", message_text="hi")
    check("Complain/Message создаются без id", True)
except Exception as e:
    check("Complain/Message создаются без id", False, f"{type(e).__name__}: {e}")

# ---------- 3. Сборка всех роутеров и диспетчера ----------
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from db.repositories.complain_repo import ComplainRepository
from db.repositories.dislike_repo import DislikeRepository
from db.repositories.like_repo import LikeRepository
from db.repositories.message_repo import MessageRepository
from db.repositories.sticker_repo import StickerRepository
from db.repositories.user_repo import UserRepository
from filters.custom_filters import IsAdmin, IsFeedbackForCurrentProfile, IsRegistered
from handlers.admin import AdminHandlers
from handlers.commands import CommandHandlers
from handlers.profile_management import ProfileManagementHandlers
from handlers.profile_search import ProfileSearchHandlers
from handlers.registration import RegistrationHandlers
from middlewares.user_context import UserContextMiddleware
from services.admin_service import AdminService
from services.matching_service import MatchingService
from services.support_service import SupportService
from services.user_service import UserService


class FakeAcquire:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        return self.pool

    async def __aexit__(self, *exc):
        return False


class FakePool:
    """Заглушка asyncpg.Pool: фиксирует запросы, ничего не выполняет."""

    def __init__(self):
        self.queries = []

    def acquire(self):
        return FakeAcquire(self)

    async def fetch(self, query, *args):
        self.queries.append((query, args))
        return []

    async def fetchrow(self, query, *args):
        self.queries.append((query, args))
        # COUNT(*) в PostgreSQL всегда возвращает ровно одну строку
        if "count(*)" in query.lower():
            return (0,)
        return None

    async def execute(self, query, *args):
        self.queries.append((query, args))
        return None


pool = FakePool()
user_repo = UserRepository(pool)
like_repo = LikeRepository(pool)
dislike_repo = DislikeRepository(pool)
message_repo = MessageRepository(pool)
complain_repo = ComplainRepository(pool)
sticker_repo = StickerRepository(pool)

user_service = UserService(user_repo=user_repo)
matching_service = MatchingService(user_repo=user_repo, like_repo=like_repo,
                                   dislike_repo=dislike_repo, sticker_repo=sticker_repo)
admin_service = AdminService(user_repo=user_repo, complain_repo=complain_repo)
support_service = SupportService(user_repo=user_repo, complain_repo=complain_repo, message_repo=message_repo)

bot = Bot(token="123456:test", default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

mw = UserContextMiddleware(user_service)
dp.message.outer_middleware(mw)
dp.callback_query.outer_middleware(mw)

is_registered = IsRegistered(user_service, "yes")
is_admin = IsAdmin(admin_service)
is_feedback = IsFeedbackForCurrentProfile(user_service)

try:
    r1 = RegistrationHandlers(user_service).get_router()
    r2 = CommandHandlers(user_service, matching_service, support_service).get_router(
        is_registered_filter=is_registered)
    r3 = ProfileManagementHandlers(user_service).get_router(is_registered_filter=is_registered)
    ps = ProfileSearchHandlers(user_service, matching_service, support_service)
    ps.set_bot_instance(bot)
    r4 = ps.get_router(is_registered_filter=is_registered,
                       is_feedback_for_current_profile_filter=is_feedback)
    ah = AdminHandlers(admin_service, user_service)
    ah.set_bot_instance(bot)
    r5 = ah.get_router(is_admin_filter=is_admin)
    for r in (r1, r2, r3, r4, r5):
        dp.include_router(r)
    counts = {r.name: (len(r.message.handlers), len(r.callback_query.handlers)) for r in (r1, r2, r3, r4, r5)}
    check("роутеры собраны и включены в Dispatcher", True, str(counts))
except Exception as e:
    check("роутеры собраны и включены в Dispatcher", False, f"{type(e).__name__}: {e}")

# ---------- 4. Внедрение данных middleware в фильтры ----------
from aiogram.dispatcher.event.handler import CallableObject


class ExplodingUserService(UserService):
    """Если фильтр полезет в БД вместо готовой модели — тест это заметит."""

    async def get_registration_status(self, tg_chat_id):
        raise AssertionError("фильтр пошёл в БД, хотя user был передан из middleware")


async def test_filter_injection():
    filt = IsRegistered(ExplodingUserService(user_repo), "yes")
    co = CallableObject(filt.__call__)
    user = User(tg_chat_id="42", is_registered="yes")

    class FakeFrom:
        id = 42

    class FakeEvent:
        from_user = FakeFrom()

    res = await co.call(FakeEvent(), user=user, bot=bot, some_other_key=1)
    check("IsRegistered использует user из middleware", res is True, f"result={res}")

    filt_no = IsRegistered(ExplodingUserService(user_repo), "no")
    res2 = await co.call(FakeEvent(), user=User(tg_chat_id="42", is_registered="no"))
    res3 = await CallableObject(filt_no.__call__).call(FakeEvent(), user=User(tg_chat_id="42", is_registered="no"))
    check("IsRegistered различает статусы", res2 is False and res3 is True, f"{res2}/{res3}")

    fb = IsFeedbackForCurrentProfile(user_service)
    co_fb = CallableObject(fb.__call__)

    class FakeCall:
        def __init__(self, data):
            self.data = data
            self.from_user = FakeFrom()

    u = User(tg_chat_id="42", last_shown_profile="777")
    ok_like = await co_fb.call(FakeCall("like777"), user=u)
    ok_dislike = await co_fb.call(FakeCall("dislike777"), user=u)
    stale = await co_fb.call(FakeCall("like555"), user=u)
    check("IsFeedbackForCurrentProfile: like/dislike текущей анкеты", ok_like is True and ok_dislike is True,
          f"like={ok_like} dislike={ok_dislike}")
    check("IsFeedbackForCurrentProfile: отсекает старую анкету", stale is False, f"stale={stale}")


async def test_middleware():
    calls = {}

    class Svc(UserService):
        async def get_user_by_id(self, tg_chat_id):
            calls["get"] = calls.get("get", 0) + 1
            return User(tg_chat_id=str(tg_chat_id), tg_username="old", is_registered="yes")

        async def sync_username(self, user, username):
            calls["sync"] = (user.tg_username, username)
            return await super().sync_username(user, username)

    class FakeTgUser:
        id = 42
        username = "new"
        is_bot = False

    async def handler(event, data):
        return data

    m = UserContextMiddleware(Svc(user_repo))
    data = await m(handler, object(), {"event_from_user": FakeTgUser()})
    check("middleware кладёт user в data", isinstance(data.get("user"), User), str(type(data.get("user"))))
    check("middleware обновляет сменившийся username",
          data["user"].tg_username == "new" and calls.get("sync") == ("old", "new"), str(calls))
    check("middleware делает ровно один SELECT пользователя", calls.get("get") == 1, str(calls.get("get")))

    # Падение БД не должно ронять апдейт
    class Broken(UserService):
        async def get_user_by_id(self, tg_chat_id):
            raise RuntimeError("db down")

    data2 = await UserContextMiddleware(Broken(user_repo))(handler, object(), {"event_from_user": FakeTgUser()})
    check("middleware переживает недоступность БД", data2.get("user") is None)


async def test_matching_sql():
    """Проверяем, что отбор кандидатов ушёл в один запрос и не зовёт несуществующие методы."""
    pool.queries.clear()

    class Repo(UserRepository):
        async def get_by_id(self, tg_chat_id):
            return User(tg_chat_id=tg_chat_id, is_registered="yes", preferred_gender="Any",
                        age_lower_point=20, age_high_point=30)

    ms = MatchingService(user_repo=Repo(pool), like_repo=like_repo,
                         dislike_repo=dislike_repo, sticker_repo=sticker_repo)
    res = await ms.get_profiles_for_user(42)
    check("get_profiles_for_user возвращает list", isinstance(res, list), type(res).__name__)
    check("отбор кандидатов — один запрос к БД", len(pool.queries) == 1, f"{len(pool.queries)} запрос(ов)")
    check("MatchingService больше не использует numpy",
          "numpy" not in (PROJECT_ROOT / "services/matching_service.py").read_text())

    # process_dislike не должен обращаться к like_repo (там нет has_disliked)
    assert not hasattr(like_repo, "has_disliked"), "у LikeRepository внезапно появился has_disliked"
    ok = await ms.process_dislike(1, 2)
    check("process_dislike работает через DislikeRepository", ok is True, f"result={ok}")


async def main_async():
    await test_filter_injection()
    await test_middleware()
    await test_matching_sql()


asyncio.run(main_async())

# ---------- 5. Экранирование HTML ----------
from utils.text import escape

check("escape экранирует < & >", escape('<b>x</b> & "q"') == '&lt;b&gt;x&lt;/b&gt; &amp; "q"', escape('<b>x</b> & "q"'))
check("escape(None) == ''", escape(None) == "")

# ---------- 6. Клавиатуры ----------
from keyboards.inline import (admin_keyboard, change_profile_keyboard, city_keyboard, gender_keyboard,
                              photo_management_keyboard, preferred_gender_keyboard, searching_profiles_keyboard,
                              start_keyboard, start_show_profiles, yes_or_no_keyboard)

kb = photo_management_keyboard(User(tg_chat_id="1", photo_link="a", photo_link_two="b"))
rows = [[b.text for b in row] for row in kb.inline_keyboard]
pairs_ok = all(len(row) == 2 for row in kb.inline_keyboard[:2])
check("photo_management_keyboard: пары Изменить/Удалить в своих рядах", pairs_ok, str(rows))
adm = [[b.callback_data for b in row] for row in admin_keyboard().inline_keyboard]
check("admin_keyboard содержит show_complains", any("show_complains" in r for r in adm), str(adm))
for fn in (start_keyboard, gender_keyboard, preferred_gender_keyboard, change_profile_keyboard, start_show_profiles):
    fn()
searching_profiles_keyboard("123")
yes_or_no_keyboard("123")
city_keyboard(["Moscow", "Berlin"])
check("остальные клавиатуры строятся", True)

# ---------- 7. Города ----------
from utils.cities_functions import cities, full_coincidence, get_relevant_cities

check("нет дубликатов городов", len(cities) == len(set(cities)), f"{len(cities)}/{len(set(cities))}")
check("Moskow -> Moscow", "Moscow" in get_relevant_cities("Moskow"), str(get_relevant_cities("Moskow")))
check("Berln -> Berlin", "Berlin" in get_relevant_cities("Berln"), str(get_relevant_cities("Berln")))
check("мусор -> []", get_relevant_cities("qqqqqq") == [] and get_relevant_cities("") == [])
check("full_coincidence игнорирует регистр и пробелы", full_coincidence("  paris ") == "Paris")

# ---------- 8. Возрастные ограничения ----------
from config.settings import settings

src_reg = (PROJECT_ROOT / "handlers/registration.py").read_text()
src_pm = (PROJECT_ROOT / "handlers/profile_management.py").read_text()
check("MIN_AGE == 18", settings.MIN_AGE == 18, str(settings.MIN_AGE))
check("хардкод возраста 10/100 убран из хендлеров",
      not re.search(r"10\s*<\s*\w*age\w*\s*<\s*100", src_reg + src_pm) and "< 100" not in src_reg + src_pm)

# ---------- 9. Отсутствие обращений к settings.Settings ----------
proj = PROJECT_ROOT
SELF = pathlib.Path(__file__).resolve()
bad = [str(p.relative_to(proj)) for p in proj.rglob("*.py")
       if "venv" not in str(p) and p.resolve() != SELF and "settings.Settings" in p.read_text()]
check("нигде нет settings.Settings.<ATTR>", not bad, str(bad))

# ---------- 10. Все SQL-запросы валидны для PostgreSQL ----------
try:
    import sqlglot

    sql_re = re.compile(r'"""(.*?)"""|"((?:SELECT|INSERT|UPDATE|DELETE)[^"]*)"', re.S | re.I)
    checked = 0
    bad_sql = []
    for p in sorted((proj / "db").rglob("*.py")):
        text = p.read_text()
        for m in sql_re.finditer(text):
            q = (m.group(1) or m.group(2) or "").strip()
            if not re.match(r"^(SELECT|INSERT|UPDATE|DELETE)", q, re.I):
                continue
            if "{" in q:  # f-string шаблон (имя таблицы/колонки подставляется кодом)
                continue
            checked += 1
            try:
                sqlglot.parse_one(q, dialect="postgres")
            except Exception as e:
                bad_sql.append((str(p.relative_to(proj)), q[:60], str(e)[:120]))
    check(f"SQL парсится диалектом postgres ({checked} запросов)", not bad_sql, str(bad_sql))
except ImportError:
    print("SKIP  проверка SQL: sqlglot не установлен")

# ---------- Итог ----------
print()
if FAILURES:
    print(f"ПРОВАЛЕНО {len(FAILURES)}: {FAILURES}")
    sys.exit(1)
print("ВСЁ ЗЕЛЁНОЕ")
