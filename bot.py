"""
Telegram RP Country Archive Bot
Requires: pip install aiogram==3.x aiosqlite
"""

import asyncio
import logging
import aiosqlite
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
BOT_TOKEN = "8828014458:AAGo-lRVykbmNQWnbH_v_dW7ZIIGRwFyrxM"  # <-- Вставь токен сюда
DB_PATH = "countries.db"
# Telegram user IDs суперадминов (через запятую). Чат-админы определяются автоматически.
SUPER_ADMINS: set[int] = {1360482515, 6089338514, 6299402428}  # <-- Вставь свой Telegram ID
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


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


# ─── DATABASE ─────────────────────────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                owner_username TEXT,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                capital TEXT,
                government TEXT,
                photo_id TEXT,
                link TEXT,
                approved INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def db_get_country(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM countries WHERE LOWER(name) = LOWER(?) AND approved = 1",
            (name,)
        ) as cursor:
            return await cursor.fetchone()


async def db_search_countries(query: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM countries WHERE LOWER(name) LIKE LOWER(?) AND approved = 1 LIMIT 10",
            (f"%{query}%",)
        ) as cursor:
            return await cursor.fetchall()


async def db_all_countries():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name, capital, government FROM countries WHERE approved = 1 ORDER BY name"
        ) as cursor:
            return await cursor.fetchall()


async def db_pending_countries():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM countries WHERE approved = 0 ORDER BY created_at"
        ) as cursor:
            return await cursor.fetchall()


async def db_add_country(owner_id, owner_username, name, description, capital, government, photo_id, link):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO countries (owner_id, owner_username, name, description, capital, government, photo_id, link, approved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (owner_id, owner_username, name, description, capital, government, photo_id, link))
        await db.commit()


async def db_approve_country(country_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE countries SET approved = 1 WHERE id = ?", (country_id,))
        await db.commit()


async def db_delete_country(country_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM countries WHERE id = ?", (country_id,))
        await db.commit()


async def db_delete_country_by_name(name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM countries WHERE LOWER(name) = LOWER(?)", (name,)) as cursor:
            row = await cursor.fetchone()
        if row:
            await db.execute("DELETE FROM countries WHERE id = ?", (row[0],))
            await db.commit()
            return True
        return False


async def db_get_user_country(owner_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM countries WHERE owner_id = ? ORDER BY created_at DESC LIMIT 1",
            (owner_id,)
        ) as cursor:
            return await cursor.fetchone()


async def db_update_field(owner_id: int, field: str, value):
    allowed = {"name", "description", "capital", "government", "photo_id", "link"}
    if field not in allowed:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE countries SET {field} = ? WHERE owner_id = ?",
            (value, owner_id)
        )
        await db.commit()
    return True


# ─── HELPERS ──────────────────────────────────────────────────────────────────
def country_card_text(c) -> str:
    gov = c["government"] or "—"
    cap = c["capital"] or "—"
    desc = c["description"] or "—"
    link = c["link"] or "—"
    return (
        f"🌍 <b>{c['name']}</b>\n"
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
    ]
    buttons = [[InlineKeyboardButton(text=label, callback_data=f"editfield:{key}")] for label, key in fields]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="editfield:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── COMMANDS IN GROUP CHAT ───────────────────────────────────────────────────
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

    # Поиск похожих
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
        lines.append(f"🌍 <b>{c['name']}</b> | {gov} | 🏙 {cap}")
        if c["link"]:
            buttons.append([InlineKeyboardButton(text=f"📖 {c['name']}", url=c["link"])])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=kb)


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
    deleted = await db_delete_country_by_name(name)
    if deleted:
        await message.reply(f'✅ Страна "{name}" удалена из каталога.')
    else:
        await message.reply(f'❌ Страна "{name}" не найдена.')


@router.message(Command("pending"))
async def cmd_pending(message: Message):
    if not await is_chat_admin(message):
        await message.reply("🚫 Только администраторы могут просматривать очередь.")
        return

    pending = await db_pending_countries()
    if not pending:
        await message.reply("✅ Очередь на модерацию пуста.")
        return

    await message.reply(f"📋 Заявок на модерацию: {len(pending)}. Проверьте ЛС бота командой /pending там.")


# ─── PRIVATE: REGISTRATION ────────────────────────────────────────────────────
@router.message(CommandStart(), F.chat.type == "private")
async def cmd_start_private(message: Message):
    await message.answer(
        "👋 Привет! Я бот-каталог государств для РП.\n\n"
        "Команды:\n"
        "/register — зарегистрировать свою страну\n"
        "/edit — редактировать свою анкету\n"
        "/mystatus — статус своей заявки\n"
        "/pending — список заявок на одобрение (для суперадминов)\n\n"
        "В групповом чате:\n"
        "/country НазваниеСтраны — карточка государства\n"
        "/countries — список всех стран\n"
        "/deleteCountry НазваниеСтраны — удалить страну (для админов чата)"
    )


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


LINK_STEP_TEXT = (
    "Шаг 6/6: Введи <b>ссылку на полную анкету</b>.\n\n"
    "💡 <i>Как получить ссылку:</i> отправь анкету своей страны в чат, затем нажми и удержи сообщение → "
    "<b>Скопировать ссылку на сообщение</b> — вот это и вставляй сюда.\n\n"
    "Или напиши <code>нет</code> если ссылки пока нет."
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

    # Уведомить суперадминов
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


# ─── PRIVATE: EDIT ────────────────────────────────────────────────────────────
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


@router.message(EditCountry.new_value)
async def edit_new_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data["edit_field"]
    value = message.text.strip()

    await db_update_field(message.from_user.id, field, value)
    await state.clear()
    await message.answer(f"✅ Поле обновлено!", reply_markup=ReplyKeyboardRemove())


@router.message(EditCountry.new_photo, F.photo)
async def edit_new_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await db_update_field(message.from_user.id, "photo_id", photo_id)
    await state.clear()
    await message.answer("✅ Фото обновлено!")


@router.message(EditCountry.new_photo)
async def edit_new_photo_wrong(message: Message):
    await message.answer("Пожалуйста, отправь фото.")


# ─── PRIVATE: STATUS & PENDING ────────────────────────────────────────────────
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


# ─── MODERATION CALLBACKS ─────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(callback: CallbackQuery):
    if callback.from_user.id not in SUPER_ADMINS:
        await callback.answer("🚫 Нет прав.", show_alert=True)
        return

    country_id = int(callback.data.split(":")[1])
    await db_approve_country(country_id)
    await callback.answer("✅ Одобрено!")
    await callback.message.edit_caption(
        callback.message.caption + "\n\n✅ <b>ОДОБРЕНО</b>",
        parse_mode=ParseMode.HTML
    ) if callback.message.caption else await callback.message.edit_text(
        callback.message.text + "\n\n✅ <b>ОДОБРЕНО</b>",
        parse_mode=ParseMode.HTML
    )

    # Уведомить владельца
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM countries WHERE id = ?", (country_id,)) as cur:
            c = await cur.fetchone()
    if c:
        try:
            await bot.send_message(
                c["owner_id"],
                f"🎉 Твоя страна <b>{c['name']}</b> одобрена и добавлена в каталог!",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(callback: CallbackQuery):
    if callback.from_user.id not in SUPER_ADMINS:
        await callback.answer("🚫 Нет прав.", show_alert=True)
        return

    country_id = int(callback.data.split(":")[1])

    # Уведомить владельца перед удалением
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM countries WHERE id = ?", (country_id,)) as cur:
            c = await cur.fetchone()

    await db_delete_country(country_id)
    await callback.answer("❌ Отклонено и удалено.")
    await callback.message.edit_caption(
        (callback.message.caption or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>",
        parse_mode=ParseMode.HTML
    ) if callback.message.caption else await callback.message.edit_text(
        (callback.message.text or "") + "\n\n❌ <b>ОТКЛОНЕНО</b>",
        parse_mode=ParseMode.HTML
    )

    if c:
        try:
            await bot.send_message(
                c["owner_id"],
                f"❌ Заявка на регистрацию страны <b>{c['name']}</b> отклонена администратором.\n"
                "Ты можешь попробовать снова: /register",
                parse_mode=ParseMode.HTML
            )
        except Exception:
            pass


# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    await init_db()
    logger.info("Bot started.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
