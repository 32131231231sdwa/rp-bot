"""
Telegram RP Country Archive Bot
Requires: pip install aiogram asyncpg
"""

import asyncio
import logging
import asyncpg
from datetime import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.enums import ParseMode
import os

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "8828014458:AAGo-lRVykbmNQWnbH_v_dW7ZIIGRwFyrxM")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:zsVNGaIPcFaCYBUbipeooPAoittPneWi@postgres.railway.internal:5432/railway")
SUPER_ADMINS: set[int] = {1360482515, 6089338514, 6299402428}

# Статусы стран
STATUSES = {
    "active":   "🟢 Активна",
    "frozen":   "🔵 Заморожена",
    "destroyed": "💀 Уничтожена",
}
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

db_pool: asyncpg.Pool = None


# ─── FSM STATES ───────────────────────────────────────────────────────────────
class RegisterCountry(StatesGroup):
    name = State()
    description = State()
    capital = State()
    government = State()
    photo = State()
    link = State()
    confirm = State()


class EditCountry(StatesGroup):
    choose_field = State()
    new_value = State()
    new_photo = State()


class CreateAlliance(StatesGroup):
    name = State()
    description = State()
    confirm = State()


# ─── DATABASE ─────────────────────────────────────────────────────────────────
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id SERIAL PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                owner_username TEXT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                capital TEXT,
                government TEXT,
                photo_id TEXT,
                link TEXT,
                approved INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alliances (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                creator_id BIGINT NOT NULL,
                creator_username TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS alliance_members (
                alliance_id INTEGER REFERENCES alliances(id) ON DELETE CASCADE,
                country_id INTEGER REFERENCES countries(id) ON DELETE CASCADE,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (alliance_id, country_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id SERIAL PRIMARY KEY,
                admin_id BIGINT NOT NULL,
                admin_username TEXT,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


# ── Countries ──
async def db_get_country(name: str):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM countries WHERE LOWER(name) = LOWER($1) AND approved = 1", name)


async def db_search_countries(query: str):
    async with db_pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM countries WHERE LOWER(name) LIKE LOWER($1) AND approved = 1 LIMIT 10",
            f"%{query}%")


async def db_all_countries():
    async with db_pool.acquire() as conn:
        return await conn.fetch(
            "SELECT id, name, capital, government, link, status FROM countries WHERE approved = 1 ORDER BY name")


async def db_pending_countries():
    async with db_pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM countries WHERE approved = 0 ORDER BY created_at")


async def db_add_country(owner_id, owner_username, name, description, capital, government, photo_id, link):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO countries (owner_id, owner_username, name, description, capital, government, photo_id, link, approved, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 0, 'active')
        """, owner_id, owner_username, name, description, capital, government, photo_id, link)


async def db_approve_country(country_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE countries SET approved = 1 WHERE id = $1", country_id)


async def db_delete_country(country_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM countries WHERE id = $1", country_id)


async def db_delete_country_by_name(name: str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM countries WHERE LOWER(name) = LOWER($1)", name)
        if row:
            await conn.execute("DELETE FROM countries WHERE id = $1", row["id"])
            return row["id"]
        return None


async def db_get_user_country(owner_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT * FROM countries WHERE owner_id = $1 ORDER BY created_at DESC LIMIT 1", owner_id)


async def db_get_country_by_id(country_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM countries WHERE id = $1", country_id)


async def db_update_field(owner_id: int, field: str, value):
    allowed = {"name", "description", "capital", "government", "photo_id", "link", "status"}
    if field not in allowed:
        return False
    async with db_pool.acquire() as conn:
        await conn.execute(f"UPDATE countries SET {field} = $1 WHERE owner_id = $2", value, owner_id)
    return True


async def db_update_status_by_name(name: str, status: str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM countries WHERE LOWER(name) = LOWER($1)", name)
        if row:
            await conn.execute("UPDATE countries SET status = $1 WHERE id = $2", status, row["id"])
            return True
        return False


# ── Alliances ──
async def db_create_alliance(name, description, creator_id, creator_username):
    async with db_pool.acquire() as conn:
        return await conn.fetchval("""
            INSERT INTO alliances (name, description, creator_id, creator_username)
            VALUES ($1, $2, $3, $4) RETURNING id
        """, name, description, creator_id, creator_username)


async def db_get_all_alliances():
    async with db_pool.acquire() as conn:
        return await conn.fetch("SELECT * FROM alliances ORDER BY name")


async def db_get_alliance_by_name(name: str):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM alliances WHERE LOWER(name) = LOWER($1)", name)


async def db_get_alliance_members(alliance_id: int):
    async with db_pool.acquire() as conn:
        return await conn.fetch("""
            SELECT c.name, c.government FROM countries c
            JOIN alliance_members am ON am.country_id = c.id
            WHERE am.alliance_id = $1
        """, alliance_id)


async def db_join_alliance(alliance_id: int, country_id: int):
    async with db_pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT 1 FROM alliance_members WHERE alliance_id = $1 AND country_id = $2",
            alliance_id, country_id)
        if existing:
            return False
        await conn.execute(
            "INSERT INTO alliance_members (alliance_id, country_id) VALUES ($1, $2)",
            alliance_id, country_id)
        return True


async def db_leave_alliance(alliance_id: int, country_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM alliance_members WHERE alliance_id = $1 AND country_id = $2",
            alliance_id, country_id)


async def db_delete_alliance_by_name(name: str):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM alliances WHERE LOWER(name) = LOWER($1)", name)
        if row:
            await conn.execute("DELETE FROM alliances WHERE id = $1", row["id"])
            return True
        return False


# ── Admin logs ──
async def db_log_action(admin_id: int, admin_username: str, action: str, details: str = ""):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO admin_logs (admin_id, admin_username, action, details)
            VALUES ($1, $2, $3, $4)
        """, admin_id, admin_username, action, details)


async def db_get_logs(limit: int = 20):
    async with db_pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM admin_logs ORDER BY created_at DESC LIMIT $1", limit)


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def country_card_text(c) -> str:
    gov = c["government"] or "—"
    cap = c["capital"] or "—"
    desc = c["description"] or "—"
    link = c["link"] or "—"
    status = STATUSES.get(c.get("status", "active"), "🟢 Активна")
    return (
        f"🌍 <b>{c['name']}</b>  {status}\n"
        f"👑 {gov}\n"
        f"🏙 Столица: {cap}\n"
        f"📜 {desc}\n"
        f"🔗 Полная анкета: {link}"
    )


async def is_chat_admin(message: Message) -> bool:
    if message.from_user.id in SUPER_ADMINS:
        return True
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False


def approve_kb(country_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{country_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{country_id}"),
    ]])


def edit_fields_kb() -> InlineKeyboardMarkup:
    fields = [
        ("Название", "name"), ("Описание", "description"),
        ("Столица", "capital"), ("Форма правления", "government"),
        ("Фото/Флаг", "photo"), ("Ссылка на анкету", "link"),
        ("Статус страны", "status"),
    ]
    buttons = [[InlineKeyboardButton(text=label, callback_data=f"editfield:{key}")] for label, key in fields]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="editfield:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def status_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Активна", callback_data="setstatus:active")],
        [InlineKeyboardButton(text="🔵 Заморожена", callback_data="setstatus:frozen")],
        [InlineKeyboardButton(text="💀 Уничтожена", callback_data="setstatus:destroyed")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="setstatus:cancel")],
    ])


LINK_STEP_TEXT = (
    "Шаг 6/6: Введи <b>ссылку на полную анкету</b>.\n\n"
    "💡 <i>Как получить ссылку:</i> отправь анкету своей страны в чат, затем нажми и удержи сообщение → "
    "<b>Скопировать ссылку на сообщение</b> — вот это и вставляй сюда.\n\n"
    "Или напиши <code>нет</code> если ссылки пока нет."
)


# ─── GROUP CHAT COMMANDS ──────────────────────────────────────────────────────
@router.message(Command("country"))
async def cmd_country(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Использование: /country НазваниеСтраны")
        return

    query = args[1].strip()
    country = await db_get_country(query)

    if country:
        text = country_card_text(country)
        kb = None
        if country["link"]:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📖 Открыть полную анкету", url=country["link"])
            ]])
        if country["photo_id"]:
            await message.reply_photo(photo=country["photo_id"], caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await message.reply(text, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    results = await db_search_countries(query)
    if not results:
        await message.reply(f'❌ Страна "{query}" не найдена.')
        return

    names = "\n".join(f"• {r['name']}" for r in results)
    await message.reply(f'❓ Точное совпадение не найдено. Похожие страны:\n{names}')


@router.message(Command("countries"))
async def cmd_countries(message: Message):
    all_c = await db_all_countries()
    if not all_c:
        await message.reply("📭 Каталог пуст. Пока ни одна страна не зарегистрирована.")
        return

    lines = [f"🗺 <b>Каталог государств</b> ({len(all_c)} стран)\n"]
    buttons = []
    for c in all_c:
        gov = c["government"] or "—"
        cap = c["capital"] or "—"
        status = STATUSES.get(c.get("status", "active"), "🟢")
        status_icon = status.split()[0]
        lines.append(f"{status_icon} <b>{c['name']}</b> | {gov} | 🏙 {cap}")
        buttons.append([InlineKeyboardButton(text=f"🌍 {c['name']}", callback_data=f"show:{c['id']}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb)


@router.callback_query(F.data.startswith("show:"))
async def cb_show_country(callback: CallbackQuery):
    country_id = int(callback.data.split(":")[1])
    c = await db_get_country_by_id(country_id)
    await callback.answer()

    if not c or not c["approved"]:
        await callback.answer("❌ Страна не найдена.", show_alert=True)
        return

    text = country_card_text(c)
    kb = None
    if c["link"]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔗 Полная анкета", url=c["link"])
        ]])

    if c["photo_id"]:
        await callback.message.answer_photo(photo=c["photo_id"], caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await callback.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)


@router.message(Command("deleteCountry"))
async def cmd_delete_country(message: Message):
    if not await is_chat_admin(message):
        await message.reply("🚫 Только администраторы могут удалять страны.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Использование: /deleteCountry НазваниеСтраны")
        return

    name = args[1].strip()
    country_id = await db_delete_country_by_name(name)
    if country_id:
        username = message.from_user.username or str(message.from_user.id)
        await db_log_action(message.from_user.id, username, "Удаление страны", f'Страна: {name}')
        await message.reply(f'✅ Страна "{name}" удалена из каталога.')
    else:
        await message.reply(f'❌ Страна "{name}" не найдена.')


@router.message(Command("setstatus"))
async def cmd_set_status(message: Message):
    if not await is_chat_admin(message):
        await message.reply("🚫 Только администраторы могут менять статус стран.")
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply(
            "Использование: /setstatus НазваниеСтраны статус\n\n"
            "Статусы: <code>active</code> / <code>frozen</code> / <code>destroyed</code>",
            parse_mode=ParseMode.HTML)
        return

    name = args[1].strip()
    status = args[2].strip().lower()
    if status not in STATUSES:
        await message.reply("❌ Неверный статус. Используй: active / frozen / destroyed")
        return

    ok = await db_update_status_by_name(name, status)
    if ok:
        username = message.from_user.username or str(message.from_user.id)
        await db_log_action(message.from_user.id, username, "Смена статуса", f'{name} → {STATUSES[status]}')
        await message.reply(f'✅ Статус страны "<b>{name}</b>" изменён на {STATUSES[status]}', parse_mode=ParseMode.HTML)
    else:
        await message.reply(f'❌ Страна "{name}" не найдена.')


@router.message(Command("alliances"))
async def cmd_alliances(message: Message):
    alliances = await db_get_all_alliances()
    if not alliances:
        await message.reply("📭 Альянсов пока нет. Создай первый: /createalliance")
        return

    lines = [f"🤝 <b>Альянсы</b> ({len(alliances)})\n"]
    buttons = []
    for a in alliances:
        lines.append(f"🔹 <b>{a['name']}</b> — {a['description'] or '—'}")
        buttons.append([InlineKeyboardButton(text=f"🔹 {a['name']}", callback_data=f"alliance:{a['id']}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb)


@router.callback_query(F.data.startswith("alliance:"))
async def cb_show_alliance(callback: CallbackQuery):
    alliance_id = int(callback.data.split(":")[1])
    async with db_pool.acquire() as conn:
        a = await conn.fetchrow("SELECT * FROM alliances WHERE id = $1", alliance_id)
    await callback.answer()

    if not a:
        await callback.answer("❌ Альянс не найден.", show_alert=True)
        return

    members = await db_get_alliance_members(alliance_id)
    member_lines = "\n".join(f"  • {m['name']} ({m['government'] or '—'})" for m in members) or "  (нет участников)"
    text = (
        f"🤝 <b>{a['name']}</b>\n"
        f"📜 {a['description'] or '—'}\n"
        f"👤 Создан: @{a['creator_username']}\n\n"
        f"🌍 <b>Участники:</b>\n{member_lines}"
    )
    await callback.message.answer(text, parse_mode=ParseMode.HTML)


@router.message(Command("pending"))
async def cmd_pending(message: Message):
    if not await is_chat_admin(message):
        await message.reply("🚫 Только администраторы могут просматривать очередь.")
        return
    await message.reply("📋 Проверь очередь в ЛС боту командой /pending там.")


@router.message(Command("adminlogs"))
async def cmd_admin_logs(message: Message):
    if not await is_chat_admin(message):
        await message.reply("🚫 Только администраторы.")
        return

    logs = await db_get_logs(15)
    if not logs:
        await message.reply("📭 Лог действий пуст.")
        return

    lines = ["📋 <b>Последние действия админов:</b>\n"]
    for log in logs:
        dt = log["created_at"].strftime("%d.%m %H:%M")
        lines.append(f"[{dt}] @{log['admin_username']} — {log['action']}: {log['details']}")

    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)


# ─── PRIVATE COMMANDS ─────────────────────────────────────────────────────────
@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start_private(message: Message):
    await message.answer(
        "👋 Привет! Я бот-каталог государств для РП.\n\n"
        "<b>Личные команды:</b>\n"
        "/register — зарегистрировать страну\n"
        "/edit — редактировать свою анкету\n"
        "/mycard — посмотреть свою карточку\n"
        "/mystatus — статус заявки\n"
        "/createalliance — создать альянс\n"
        "/joinalliance — вступить в альянс\n"
        "/leavealliance — выйти из альянса\n"
        "/pending — очередь модерации (суперадмины)\n\n"
        "<b>В групповом чате:</b>\n"
        "/country НазваниеСтраны — карточка страны\n"
        "/countries — список всех стран\n"
        "/alliances — список альянсов\n"
        "/setstatus НазваниеСтраны статус — сменить статус (админы)\n"
        "/deleteCountry НазваниеСтраны — удалить страну (админы)\n"
        "/adminlogs — лог действий админов",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("mycard"), F.chat.type == "private")
async def cmd_mycard(message: Message):
    country = await db_get_user_country(message.from_user.id)
    if not country:
        await message.answer("❌ У тебя нет зарегистрированной страны. Используй /register")
        return

    text = country_card_text(country)
    if not country["approved"]:
        text += "\n\n⏳ <i>На модерации — ещё не видна другим</i>"

    kb = None
    if country["link"]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔗 Полная анкета", url=country["link"])
        ]])

    if country["photo_id"]:
        await message.answer_photo(photo=country["photo_id"], caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=kb)


@router.message(Command("register"), F.chat.type == "private")
async def cmd_register(message: Message, state: FSMContext):
    existing = await db_get_user_country(message.from_user.id)
    if existing:
        await message.answer(
            f"⚠️ У тебя уже есть зарегистрированная страна: <b>{existing['name']}</b>\n"
            "Используй /edit чтобы редактировать анкету.",
            parse_mode=ParseMode.HTML
        )
        return

    await state.set_state(RegisterCountry.name)
    await message.answer(
        "📝 Начнём регистрацию страны!\n\n"
        "Шаг 1/6: Введи <b>название страны</b>:",
        parse_mode=ParseMode.HTML
    )


@router.message(RegisterCountry.name)
async def reg_name(message: Message, state: FSMContext):
    name = message.text.strip()
    existing = await db_get_country(name)
    if existing:
        await message.answer("❌ Страна с таким названием уже существует. Введи другое название:")
        return
    await state.update_data(name=name)
    await state.set_state(RegisterCountry.description)
    await message.answer("Шаг 2/6: Введи <b>краткое описание</b> страны (1-3 предложения):", parse_mode=ParseMode.HTML)


@router.message(RegisterCountry.description)
async def reg_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(RegisterCountry.capital)
    await message.answer("Шаг 3/6: Введи <b>столицу</b>:", parse_mode=ParseMode.HTML)


@router.message(RegisterCountry.capital)
async def reg_capital(message: Message, state: FSMContext):
    await state.update_data(capital=message.text.strip())
    await state.set_state(RegisterCountry.government)
    await message.answer("Шаг 4/6: Введи <b>форму правления</b> (например: Монархия, Республика, Теократия):", parse_mode=ParseMode.HTML)


@router.message(RegisterCountry.government)
async def reg_government(message: Message, state: FSMContext):
    await state.update_data(government=message.text.strip())
    await state.set_state(RegisterCountry.photo)
    await message.answer(
        "Шаг 5/6: Отправь <b>фото</b> (просто пришли 2 фото — карта где ты и флаг).\n"
        "Или напиши <code>пропустить</code> чтобы добавить позже.",
        parse_mode=ParseMode.HTML
    )


@router.message(RegisterCountry.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo_id=photo_id)
    await state.set_state(RegisterCountry.link)
    await message.answer(LINK_STEP_TEXT, parse_mode=ParseMode.HTML)


@router.message(RegisterCountry.photo)
async def reg_photo_skip(message: Message, state: FSMContext):
    if message.text and message.text.lower() in ("пропустить", "skip", "-"):
        await state.update_data(photo_id=None)
        await state.set_state(RegisterCountry.link)
        await message.answer(LINK_STEP_TEXT, parse_mode=ParseMode.HTML)
    else:
        await message.answer("Пожалуйста, отправь фото или напиши <code>пропустить</code>.", parse_mode=ParseMode.HTML)


@router.message(RegisterCountry.link)
async def reg_link(message: Message, state: FSMContext):
    link = message.text.strip()
    if link.lower() in ("нет", "no", "-", "none"):
        link = None
    await state.update_data(link=link)

    data = await state.get_data()
    await state.set_state(RegisterCountry.confirm)

    preview = (
        f"📋 <b>Проверь анкету:</b>\n\n"
        f"🌍 Название: {data['name']}\n"
        f"📜 Описание: {data['description']}\n"
        f"🏙 Столица: {data['capital']}\n"
        f"👑 Форма правления: {data['government']}\n"
        f"🖼 Фото: {'Есть' if data.get('photo_id') else 'Нет'}\n"
        f"🔗 Ссылка: {link or 'Нет'}\n\n"
        "Отправить на модерацию? Напиши <b>да</b> или <b>нет</b>."
    )

    if data.get("photo_id"):
        await message.answer_photo(photo=data["photo_id"], caption=preview, parse_mode=ParseMode.HTML)
    else:
        await message.answer(preview, parse_mode=ParseMode.HTML)


@router.message(RegisterCountry.confirm)
async def reg_confirm(message: Message, state: FSMContext):
    if message.text.lower() not in ("да", "yes", "y", "д"):
        await state.clear()
        await message.answer("❌ Регистрация отменена. Начни заново: /register")
        return

    data = await state.get_data()
    username = message.from_user.username or str(message.from_user.id)

    await db_add_country(
        owner_id=message.from_user.id,
        owner_username=username,
        name=data["name"],
        description=data["description"],
        capital=data["capital"],
        government=data["government"],
        photo_id=data.get("photo_id"),
        link=data.get("link"),
    )

    await state.clear()
    await message.answer(
        f"✅ Заявка на регистрацию страны <b>{data['name']}</b> отправлена на модерацию!\n"
        "Ты получишь уведомление после проверки.",
        parse_mode=ParseMode.HTML
    )

    pending = await db_pending_countries()
    last = pending[-1] if pending else None
    if last:
        for admin_id in SUPER_ADMINS:
            try:
                text = (
                    f"📬 <b>Новая заявка на регистрацию страны!</b>\n\n"
                    f"{country_card_text(last)}\n\n"
                    f"👤 Игрок: @{username}"
                )
                if last["photo_id"]:
                    await bot.send_photo(admin_id, last["photo_id"], caption=text,
                                        parse_mode=ParseMode.HTML, reply_markup=approve_kb(last["id"]))
                else:
                    await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML,
                                          reply_markup=approve_kb(last["id"]))
            except Exception as e:
                logger.warning(f"Не удалось уведомить админа {admin_id}: {e}")


# ─── EDIT ─────────────────────────────────────────────────────────────────────
@router.message(Command("edit"), F.chat.type == "private")
async def cmd_edit(message: Message, state: FSMContext):
    country = await db_get_user_country(message.from_user.id)
    if not country:
        await message.answer("❌ У тебя нет зарегистрированной страны. Используй /register")
        return

    await state.set_state(EditCountry.choose_field)
    await message.answer(
        f"✏️ Редактирование анкеты: <b>{country['name']}</b>\n\nЧто хочешь изменить?",
        parse_mode=ParseMode.HTML,
        reply_markup=edit_fields_kb()
    )


@router.callback_query(EditCountry.choose_field, F.data.startswith("editfield:"))
async def edit_choose_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    await callback.answer()

    if field == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Редактирование отменено.")
        return

    await state.update_data(edit_field=field)

    if field == "photo":
        await state.set_state(EditCountry.new_photo)
        await callback.message.edit_text("📸 Отправь новое фото (флаг / карта):")
    elif field == "status":
        await callback.message.edit_text("🔄 Выбери новый статус страны:", reply_markup=status_kb())
    else:
        await state.set_state(EditCountry.new_value)
        labels = {
            "name": "название страны",
            "description": "описание",
            "capital": "столицу",
            "government": "форму правления",
            "link": "ссылку на анкету",
        }
        await callback.message.edit_text(f"✏️ Введи новое {labels.get(field, field)}:")


@router.callback_query(F.data.startswith("setstatus:"))
async def cb_set_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":")[1]
    await callback.answer()

    if status == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Редактирование отменено.")
        return

    await db_update_field(callback.from_user.id, "status", status)
    await state.clear()
    await callback.message.edit_text(f"✅ Статус изменён на {STATUSES[status]}")


@router.message(EditCountry.new_value)
async def edit_new_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data["edit_field"]
    value = message.text.strip()

    await db_update_field(message.from_user.id, field, value)
    await state.clear()
    await message.answer("✅ Поле обновлено!", reply_markup=ReplyKeyboardRemove())


@router.message(EditCountry.new_photo, F.photo)
async def edit_new_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await db_update_field(message.from_user.id, "photo_id", photo_id)
    await state.clear()
    await message.answer("✅ Фото обновлено!")


@router.message(EditCountry.new_photo)
async def edit_new_photo_wrong(message: Message):
    await message.answer("Пожалуйста, отправь фото.")


# ─── STATUS & PENDING ─────────────────────────────────────────────────────────
@router.message(Command("mystatus"), F.chat.type == "private")
async def cmd_mystatus(message: Message):
    country = await db_get_user_country(message.from_user.id)
    if not country:
        await message.answer("❌ У тебя нет зарегистрированной страны.")
        return

    status = "✅ Одобрена" if country["approved"] else "⏳ На модерации"
    await message.answer(
        f"📋 Твоя страна: <b>{country['name']}</b>\nСтатус: {status}",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("pending"), F.chat.type == "private")
async def cmd_pending_private(message: Message):
    if message.from_user.id not in SUPER_ADMINS:
        await message.answer("🚫 Только суперадмины могут просматривать очередь.")
        return

    pending = await db_pending_countries()
    if not pending:
        await message.answer("✅ Очередь на модерацию пуста.")
        return

    for c in pending:
        text = f"📬 Заявка #{c['id']}\n\n{country_card_text(c)}\n\n👤 Игрок: @{c['owner_username']}"
        if c["photo_id"]:
            await message.answer_photo(c["photo_id"], caption=text,
                                       parse_mode=ParseMode.HTML, reply_markup=approve_kb(c["id"]))
        else:
            await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=approve_kb(c["id"]))


# ─── ALLIANCES ────────────────────────────────────────────────────────────────
@router.message(Command("createalliance"), F.chat.type == "private")
async def cmd_create_alliance(message: Message, state: FSMContext):
    country = await db_get_user_country(message.from_user.id)
    if not country or not country["approved"]:
        await message.answer("❌ У тебя должна быть одобренная страна чтобы создать альянс.")
        return

    await state.set_state(CreateAlliance.name)
    await message.answer("🤝 Создание альянса!\n\nШаг 1/2: Введи <b>название альянса</b>:", parse_mode=ParseMode.HTML)


@router.message(CreateAlliance.name)
async def alliance_name(message: Message, state: FSMContext):
    name = message.text.strip()
    existing = await db_get_alliance_by_name(name)
    if existing:
        await message.answer("❌ Альянс с таким названием уже существует. Введи другое:")
        return
    await state.update_data(name=name)
    await state.set_state(CreateAlliance.description)
    await message.answer("Шаг 2/2: Введи <b>краткое описание</b> альянса (или напиши <code>нет</code>):", parse_mode=ParseMode.HTML)


@router.message(CreateAlliance.description)
async def alliance_description(message: Message, state: FSMContext):
    desc = message.text.strip()
    if desc.lower() in ("нет", "no", "-"):
        desc = None
    await state.update_data(description=desc)
    data = await state.get_data()
    await state.set_state(CreateAlliance.confirm)
    await message.answer(
        f"📋 Проверь:\n🤝 <b>{data['name']}</b>\n📜 {desc or '—'}\n\nСоздать? <b>да</b> / <b>нет</b>",
        parse_mode=ParseMode.HTML
    )


@router.message(CreateAlliance.confirm)
async def alliance_confirm(message: Message, state: FSMContext):
    if message.text.lower() not in ("да", "yes", "y", "д"):
        await state.clear()
        await message.answer("❌ Создание отменено.")
        return

    data = await state.get_data()
    username = message.from_user.username or str(message.from_user.id)
    alliance_id = await db_create_alliance(data["name"], data.get("description"), message.from_user.id, username)

    # Автовступление страны создателя
    country = await db_get_user_country(message.from_user.id)
    if country:
        await db_join_alliance(alliance_id, country["id"])

    await state.clear()
    await message.answer(f"✅ Альянс <b>{data['name']}</b> создан! Твоя страна автоматически добавлена.", parse_mode=ParseMode.HTML)


@router.message(Command("joinalliance"), F.chat.type == "private")
async def cmd_join_alliance(message: Message):
    country = await db_get_user_country(message.from_user.id)
    if not country or not country["approved"]:
        await message.answer("❌ У тебя должна быть одобренная страна чтобы вступить в альянс.")
        return

    alliances = await db_get_all_alliances()
    if not alliances:
        await message.answer("📭 Альянсов пока нет. Создай первый: /createalliance")
        return

    buttons = [[InlineKeyboardButton(text=f"🤝 {a['name']}", callback_data=f"join:{a['id']}")] for a in alliances]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Выбери альянс для вступления:", reply_markup=kb)


@router.callback_query(F.data.startswith("join:"))
async def cb_join_alliance(callback: CallbackQuery):
    alliance_id = int(callback.data.split(":")[1])
    country = await db_get_user_country(callback.from_user.id)
    await callback.answer()

    if not country or not country["approved"]:
        await callback.answer("❌ Нет одобренной страны.", show_alert=True)
        return

    ok = await db_join_alliance(alliance_id, country["id"])
    async with db_pool.acquire() as conn:
        a = await conn.fetchrow("SELECT name FROM alliances WHERE id = $1", alliance_id)

    if ok:
        await callback.message.answer(f"✅ Страна <b>{country['name']}</b> вступила в альянс <b>{a['name']}</b>!", parse_mode=ParseMode.HTML)
    else:
        await callback.message.answer("⚠️ Твоя страна уже в этом альянсе.")


@router.message(Command("leavealliance"), F.chat.type == "private")
async def cmd_leave_alliance(message: Message):
    country = await db_get_user_country(message.from_user.id)
    if not country:
        await message.answer("❌ У тебя нет зарегистрированной страны.")
        return

    async with db_pool.acquire() as conn:
        memberships = await conn.fetch("""
            SELECT a.id, a.name FROM alliances a
            JOIN alliance_members am ON am.alliance_id = a.id
            WHERE am.country_id = $1
        """, country["id"])

    if not memberships:
        await message.answer("❌ Твоя страна не состоит ни в одном альянсе.")
        return

    buttons = [[InlineKeyboardButton(text=f"🚪 {m['name']}", callback_data=f"leave:{m['id']}")] for m in memberships]
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer("Из какого альянса выйти?", reply_markup=kb)


@router.callback_query(F.data.startswith("leave:"))
async def cb_leave_alliance(callback: CallbackQuery):
    alliance_id = int(callback.data.split(":")[1])
    country = await db_get_user_country(callback.from_user.id)
    await callback.answer()

    if not country:
        return

    await db_leave_alliance(alliance_id, country["id"])
    async with db_pool.acquire() as conn:
        a = await conn.fetchrow("SELECT name FROM alliances WHERE id = $1", alliance_id)

    await callback.message.answer(f"✅ Страна <b>{country['name']}</b> вышла из альянса <b>{a['name']}</b>.", parse_mode=ParseMode.HTML)


# ─── ALLIANCE ADMIN ───────────────────────────────────────────────────────────
@router.message(Command("deleteAlliance"))
async def cmd_delete_alliance(message: Message):
    if not await is_chat_admin(message):
        await message.reply("🚫 Только администраторы могут удалять альянсы.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Использование: /deleteAlliance НазваниеАльянса")
        return

    name = args[1].strip()
    deleted = await db_delete_alliance_by_name(name)
    if deleted:
        username = message.from_user.username or str(message.from_user.id)
        await db_log_action(message.from_user.id, username, "Удаление альянса", f"Альянс: {name}")
        await message.reply(f'✅ Альянс "{name}" удалён.')
    else:
        await message.reply(f'❌ Альянс "{name}" не найден.')


# ─── MODERATION CALLBACKS ─────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(callback: CallbackQuery):
    if callback.from_user.id not in SUPER_ADMINS:
        await callback.answer("🚫 Нет прав.", show_alert=True)
        return

    country_id = int(callback.data.split(":")[1])
    await db_approve_country(country_id)
    await callback.answer("✅ Одобрено!")

    username = callback.from_user.username or str(callback.from_user.id)
    c = await db_get_country_by_id(country_id)
    if c:
        await db_log_action(callback.from_user.id, username, "Одобрение страны", f'Страна: {c["name"]}')

    try:
        if callback.message.caption:
            await callback.message.edit_caption(callback.message.caption + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode=ParseMode.HTML)
        else:
            await callback.message.edit_text(callback.message.text + "\n\n✅ <b>ОДОБРЕНО</b>", parse_mode=ParseMode.HTML)
    except Exception:
        pass

    if c:
        try:
            await bot.send_message(c["owner_id"], f"🎉 Твоя страна <b>{c['name']}</b> одобрена и добавлена в каталог!", parse_mode=ParseMode.HTML)
        except Exception:
            pass


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(callback: CallbackQuery):
    if callback.from_user.id not in SUPER_ADMINS:
        await callback.answer("🚫 Нет прав.", show_alert=True)
        return

    country_id = int(callback.data.split(":")[1])
    c = await db_get_country_by_id(country_id)
    await db_delete_country(country_id)
    await callback.answer("❌ Отклонено и удалено.")

    username = callback.from_user.username or str(callback.from_user.id)
    if c:
        await db_log_action(callback.from_user.id, username, "Отклонение заявки", f'Страна: {c["name"]}')

    try:
        if callback.message.caption:
            await callback.message.edit_caption((callback.message.caption or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode=ParseMode.HTML)
        else:
            await callback.message.edit_text((callback.message.text or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>", parse_mode=ParseMode.HTML)
    except Exception:
        pass

    if c:
        try:
            await bot.send_message(c["owner_id"], f"❌ Заявка на регистрацию страны <b>{c['name']}</b> отклонена администратором.\nТы можешь попробовать снова: /register", parse_mode=ParseMode.HTML)
        except Exception:
            pass


# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    await init_db()
    logger.info("Bot started.")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query"],
        handle_signals=True,
    )

if __name__ == "__main__":
    asyncio.run(main())
