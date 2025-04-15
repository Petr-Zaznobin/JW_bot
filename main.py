import asyncio
import logging
import string
import re
import ast

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile

import database
from config import *

# logging
logging.basicConfig(
    # level=logging.INFO,  # Уровень логирования
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # Формат сообщения
    handlers=[
        logging.FileHandler("app.log"),  # Запись логов в файл "app.log"
        # logging.StreamHandler()  # Вывод логов на консоль
    ]
)
logger = logging.getLogger(__name__)

# FSM
storage = MemoryStorage()

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# postgresql
database = database.AsyncDatabase(
    db_name=db_name,
    user=user,
    password=password,
    host=host,
    port=port
)

class PhoneState(StatesGroup):
    waiting_for_phone = State()

@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext):
    tg_user_id: int = int(message.from_user.id)
    chat_id: int = int(message.chat.id)

    user_exist = await database.user_exists(chat_id)
    if user_exist:
        await main_menu(chat_id)
    else:
        await message.answer("👋 Добро пожаловать! Рады вас видеть.")
        is_admin = check_admin(tg_user_id)
        if is_admin:
            await message.answer("Добро пожаловать, в админ-панель.")
        else:
            await message.answer("Введите, пожалуйста, Ваш номер телефона в формате '7xxxxxxxxxx'")
            await state.set_state(PhoneState.waiting_for_phone)

@router.message(PhoneState.waiting_for_phone)
async def process_phone_number(message: Message, state: FSMContext):
    phone_number: str = message.text.strip()
    pattern = re.compile(r'^7\d{10}$')
    if not pattern.match(phone_number):
        await message.answer("Неверный формат номера телефона. Пожалуйста, введите номер в формате '7xxxxxxxxxx'")
        return

    await state.update_data(phone_number=phone_number)
    await message.answer(f"Ваш номер телефона: {phone_number} получен.")
    await message.answer(
        text="Все верно?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Все верно!", callback_data="confirm_phone")],
            [InlineKeyboardButton(text="Изменить", callback_data="change_phone")]
        ])
    )

@router.callback_query(lambda c: c.data == "confirm_phone")
async def callback_confirm_phone(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    phone_number = data.get("phone_number")
    if phone_number is None:
        await callback.answer("Номер телефона не найден. Пожалуйста, введите заново.")
        return

    # Добавить код для сохранения номера телефона в базу данных.
    # Например:
    # await database.insert_phone_number(callback.from_user.id, phone_number)

    await callback.message.answer(f"Ваш номер телефона {phone_number} сохранён в базе данных.")
    await state.clear()
    await main_menu(int(callback.message.chat.id))
    await callback.answer()

@router.callback_query(lambda c: c.data == "change_phone")
async def callback_change_phone(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Введите, пожалуйста, Ваш номер телефона в формате '7xxxxxxxxxx'")
    await state.set_state(PhoneState.waiting_for_phone)
    await callback.answer()

def check_admin(tg_user_id: string)->bool:
    # Получаем строковое значение переменной из .env (например, "[]" или "[123456789, 987654321]")
    raw_admin_tg_ids = os.getenv("admin_tg_ids", "[]").strip()
    try:
        # Преобразуем строку в список
        admin_tg_ids = ast.literal_eval(raw_admin_tg_ids)
    except Exception as e:
        print(f"Ошибка при парсинге admin_tg_ids: {e}")
        admin_tg_ids = []
    try:
        # Приводим элементы списка к целочисленному типу, если они не числа
        admin_ids = [int(x) for x in admin_tg_ids]
    except Exception as e:
        print(f"Ошибка при преобразовании admin_tg_ids в int: {e}")
        admin_ids = []

    return tg_user_id in admin_ids


#---------------------------
# Безопасное удаление последнего сообщения
async def safely_delete_last_message(tg_user_id, chat_id):
    try:
        last_messages = await database.get_last_messages_by_user_id(tg_user_id)
        if last_messages is not None:
            for message in last_messages:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message)
                    # print(f"[Bot] Сообщение {message} пользователя {tg_user_id} успешно удалено")
                except Exception as e:
                    # print(f"[Bot] Ошибка при удалении сообщения для пользователя {tg_user_id}: {str(e)}")
                    continue
            await  database.clear_last_message_ids_by_user_id(tg_user_id)
            # print(f"[DB] Все сообщения удалениы из базы данных {tg_user_id}")

            await database.set_last_message_by_user_id(tg_user_id, None)
    except Exception as e:
        logger.error("Произошла ошибка в safely_delete_last_message: %s", e)


async def main_menu(tg_user_id: int):
    try:
        await bot.send_message(tg_user_id, "Добро пожаловать в главное меню!")
    except Exception as e:
        logger.error("Произошла ошибка в main_menu: %s", e)


#----------------------------

@router.callback_query(lambda call: call.data == "main_menu")
async def MMenu(callback: CallbackQuery):
    try:
        tg_user_id: int = int(callback.from_user.id)
        await main_menu(tg_user_id)
    except Exception as e:
        logger.error("Произошла ошибка в MMenu: %s", e)


async def on_startup():
    try:
        await database.connect()
    except Exception as e:
        logger.error("Произошла ошибка в on_startup: %s", e)


# Запуск процесса
async def main():
    try:
        dp.startup.register(on_startup)
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error("Произошла ошибка в main: %s", e)


if __name__ == '__main__':  # выполняется, если код вызван непосредственно
    try:
        asyncio.run(main())
        print("[Bot Running] Бот включён")
    except Exception as e:
        logger.error("Произошла ошибка в __name__: %s", e)
