import os
import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
MANAGER_USERNAME = os.getenv("MANAGER_USERNAME")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

DB_PATH = "bot.db"

class AddProductState(StatesGroup):
    name = State()
    description = State()
    category = State()
    price = State()
    photos = State()

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT, price INTEGER, photos TEXT, category TEXT)"
        )
        await db.execute(
            "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, last_action TEXT)"
        )
        await db.commit()

@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    await save_user(message.from_user)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM products") as cursor:
            products = await cursor.fetchall()
            if not products:
                await message.answer("Товары временно отсутствуют.")
                return
            for p in products:
                name, desc, price, photos, *_ = p[1:]
                photo_list = photos.split(",")
                for i, photo_url in enumerate(photo_list):
                    caption = f"<b>{name}</b>\n{desc}\nЦена: {price}₽" if i == 0 else ""
                    btn = InlineKeyboardMarkup().add(
                        InlineKeyboardButton("Купить", url=f"https://t.me/{MANAGER_USERNAME}")
                    )
                    await bot.send_photo(message.chat.id, photo_url, caption=caption, parse_mode="HTML", reply_markup=btn)

async def save_user(user):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (id, username, first_name, last_action) VALUES (?, ?, ?, ?)",
            (user.id, user.username, user.first_name, "start")
        )
        await db.commit()

@dp.message_handler(commands=["admin"])
async def admin_prompt(message: types.Message):
    await message.answer("Введите пароль:")

@dp.message_handler(lambda m: m.text == ADMIN_PASSWORD)
async def admin_panel(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ Добавить товар", callback_data="add_product"),
        InlineKeyboardButton("📦 Все товары", callback_data="list_products"),
        InlineKeyboardButton("📤 Рассылка", callback_data="broadcast")
    )
    await message.answer("Админ-панель:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "add_product")
async def start_add_product(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название товара:")
    await AddProductState.name.set()
    await state.update_data(photos=[])

@dp.message_handler(state=AddProductState.name)
async def product_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите описание товара:")
    await AddProductState.description.set()

@dp.message_handler(state=AddProductState.description)
async def product_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Введите категорию товара:")
    await AddProductState.category.set()

@dp.message_handler(state=AddProductState.category)
async def product_category(message: types.Message, state: FSMContext):
    # Обновляем данные состояния
    await state.update_data(category=message.text)
    # Отправляем следующий вопрос
    await message.answer("Введите цену товара (только число):")
    # Переходим в состояние price
    await AddProductState.price.set()

@dp.message_handler(state=AddProductState.price)
async def product_price(message: types.Message, state: FSMContext):
    await state.update_data(price=message.text)
    await message.answer("Отправьте фото товара (по одному). Когда закончите — напишите 'Готово'")
    await AddProductState.photos.set()

@dp.message_handler(content_types=types.ContentType.PHOTO, state=AddProductState.photos)
async def product_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    data = await state.get_data()
    photo_list = data.get("photos", [])
    photo_list.append(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_id}")
    await state.update_data(photos=photo_list)
    await message.answer("Фото добавлено. Отправьте ещё или напишите 'Готово'.")

@dp.message_handler(lambda m: m.text.lower() == "готово", state=AddProductState.photos)
async def finish_product(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = ",".join(data["photos"])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO products (name, description, price, photos, category) VALUES (?, ?, ?, ?, ?)",
            (data["name"], data["description"], int(data["price"]), photos, data["category"])
        )
        await db.commit()
    await message.answer("Товар успешно добавлен!")
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == "broadcast")
async def handle_broadcast(callback: types.CallbackQuery):
    await callback.message.answer("Введите текст рассылки:")
    dp.register_message_handler(process_broadcast, content_types=types.ContentTypes.TEXT, state="*")

async def process_broadcast(message: types.Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM users") as cursor:
            users = await cursor.fetchall()
            for (uid,) in users:
                try:
                    await bot.send_message(uid, message.text)
                except:
                    pass
    await message.answer("Рассылка завершена.")
    dp.message_handlers.unregister(process_broadcast)

if name == "__main__":
    asyncio.run(init_db())
    executor.start_polling(dp, skip_updates=True)
