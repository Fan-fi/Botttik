import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.enums import ChatMemberStatus
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ---------- КОНФИГ ----------
TOKEN = "8397741728:AAHkiT4YZxFKMbydL7P02WMVNiRLfM5tsys"
OWNER_ID = 1930961190  # твой Telegram ID
DB_NAME = "shop_bot.db"
# ----------------------------

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ---------- БАЗА ДАННЫХ ----------
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price INTEGER NOT NULL,
                description TEXT DEFAULT '',
                creator_id INTEGER
            )
        """)
        await db.commit()

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
async def is_admin(chat_id: int, user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception:
        return False

async def add_user(user_id: int, username: str, first_name: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
            (user_id, username, first_name)
        )
        await db.commit()

async def get_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0

async def change_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id=?",
            (amount, user_id)
        )
        await db.commit()

# ---------- КОМАНДЫ ДЛЯ ВСЕХ ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await message.answer(
        "Привет! Я бот-магазин.\n"
        "/shop — посмотреть товары\n"
        "/balance — мой баланс\n"
        "Админы могут добавлять товары и начислять ебланкоины."
    )

@dp.message(Command("balance"))
async def cmd_balance(message: types.Message):
    balance = await get_balance(message.from_user.id)
    await message.answer(f"Ваш баланс: {balance} ебланкоин.")

# ---------- МАГАЗИН (ИНЛАЙН-КНОПКИ) ----------
@dp.message(Command("shop"))
async def cmd_shop(message: types.Message):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, name, price, description FROM items LIMIT 10")
        items = await cursor.fetchall()

    if not items:
        await message.answer("Магазин пуст.")
        return

    builder = InlineKeyboardBuilder()
    for item in items:
        item_id, name, price, desc = item
        text = f"{name} — {price} ебланкоин"
        if desc:
            text += f"\n{desc}"
        builder.row(InlineKeyboardButton(
            text=f"Купить: {name} ({price} ебланкоин)",
            callback_data=f"buy_{item_id}"
        ))
    builder.adjust(1)
    await message.answer("🛒 Доступные товары:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    item_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    balance = await get_balance(user_id)

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT name, price FROM items WHERE id=?", (item_id,))
        item = await cursor.fetchone()
    if not item:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    name, price = item
    if balance < price:
        await callback.answer(f"Недостаточно ебланкоинов. Ваш баланс: {balance}", show_alert=True)
        return

    await change_balance(user_id, -price)
    await callback.answer(f"Вы купили {name} за {price} ебланкоин!", show_alert=True)
    await callback.message.answer(
        f"✅ Пользователь {callback.from_user.full_name} купил \"{name}\" за {price} ебланкоин."
    )

# ---------- АДМИНСКИЕ КОМАНДЫ ----------
@dp.message(Command("add_balance"))
async def cmd_add_balance(message: types.Message):
    if message.chat.type == "private":
        await message.answer("Эту команду нужно выполнять в группе, ответив на сообщение пользователя.")
        return
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("Только администраторы могут пополнять баланс.")
        return
    if not message.reply_to_message:
        await message.reply("Ответьте на сообщение пользователя, которому нужно начислить ебланкоины.\nПример: `/add_balance 100`")
        return

    target = message.reply_to_message.from_user
    try:
        amount = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.reply("Укажите сумму: `/add_balance 100`")
        return

    await add_user(target.id, target.username, target.first_name)
    await change_balance(target.id, amount)
    await message.reply(f"✅ Пользователю {target.full_name} начислено {amount} ебланкоин.")

@dp.message(Command("add_item"))
async def cmd_add_item(message: types.Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("Только администраторы могут добавлять товары.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Формат: `/add_item Название | Цена | Описание`\nРазделитель — вертикальная черта.")
        return

    parts = args[1].split("|")
    if len(parts) < 2:
        await message.reply("Неверный формат. Пример: `/add_item Меч-кладенец | 500 | Острый как бритва`")
        return

    name = parts[0].strip()
    try:
        price = int(parts[1].strip())
    except ValueError:
        await message.reply("Цена должна быть числом.")
        return
    description = parts[2].strip() if len(parts) > 2 else ""

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO items (name, price, description, creator_id) VALUES (?, ?, ?, ?)",
            (name, price, description, message.from_user.id)
        )
        await db.commit()

    await message.reply(f"Товар \"{name}\" добавлен (цена: {price} ебланкоин).")

@dp.message(Command("items"))
async def cmd_items(message: types.Message):
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("Только для админов.")
        return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, name, price FROM items")
        items = await cursor.fetchall()
    if not items:
        await message.reply("Список товаров пуст.")
        return
    text = "ID | Название | Цена\n" + "\n".join(f"{i[0]} | {i[1]} | {i[2]} ебланкоин" for i in items)
    await message.reply(text)

@dp.message(Command("sync"))
async def cmd_sync(message: types.Message):
    if message.chat.type == "private":
        await message.answer("Эту команду нужно выполнять в группе.")
        return
    if not await is_admin(message.chat.id, message.from_user.id):
        await message.reply("Только администраторы могут синхронизировать пользователей.")
        return

    await message.reply("⏳ Синхронизирую участников...")
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        for member in admins:
            user = member.user
            await add_user(user.id, user.username, user.first_name)
        await message.reply(f"✅ Добавлено {len(admins)} администраторов. Остальные пользователи добавляются автоматически при входе или команде /start.")
    except Exception as e:
        await message.reply(f"Ошибка: {e}. Убедитесь, что бот — администратор группы.")

@dp.message(F.new_chat_members)
async def on_user_join(message: types.Message):
    for user in message.new_chat_members:
        await add_user(user.id, user.username, user.first_name)

# ---------- ЗАПУСК ----------
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())