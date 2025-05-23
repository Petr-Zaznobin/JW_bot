import asyncio
import logging
import re
import ast
import os
import json

from aiogram.types import FSInputFile
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

import asyncpg
import database
from config import *

# logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
    ]
)
logger = logging.getLogger(__name__)

# FSM storage
storage = MemoryStorage()

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# PostgreSQL main pool для обычных запросов
database = database.AsyncDatabase(
    db_name=db_name,
    user=user,
    password=password,
    host=host,
    port=port
)

# -------------------------------------------------
# State definitions
class PhoneState(StatesGroup):
    waiting_for_phone = State()

class ChangePhoneStates(StatesGroup):
    waiting_for_old_phone = State()
    waiting_for_new_phone = State()

# -------------------------------------------------
# Telegram handlers
@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext):
    tg_user_id = message.from_user.id
    chat_id = message.chat.id
    is_admin = check_admin(tg_user_id)

    user_exist = await database.user_exists(chat_id)
    if user_exist:
        if is_admin:
            await main_menu_admin(tg_user_id)
        else:
            await main_menu_client(tg_user_id)
        return

    await message.answer("👋 Добро пожаловать! Рады вас видеть.")

    if is_admin:
        await database.user_registration(tg_user_id, 'admin')
        await database.admin_registration(tg_user_id)
        await main_menu_admin(tg_user_id)
        print(tg_user_id)
    else:
        await database.user_registration(tg_user_id, 'client')
        await message.answer("Введите, пожалуйста, Ваш номер телефона в формате '7xxxxxxxxxx'")
        await state.set_state(PhoneState.waiting_for_phone)
        print(tg_user_id)

@router.callback_query(lambda c: c.data == "admin_change_phone")
async def callback_admin_change_phone(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    # Запустим flow для смены номера: первый шаг — ввод старого номера
    await callback.message.answer(
        "Введите старый номер телефона, который хотите изменить, в формате '7xxxxxxxxxx' "
        "(или 'x' для отмены и возврата в меню):"
    )
    await state.set_state(ChangePhoneStates.waiting_for_old_phone)
    # Снимем «часики» у кнопки
    await callback.answer()

@router.message(ChangePhoneStates.waiting_for_old_phone)
async def process_old_phone(message: Message, state: FSMContext):
    text = message.text.strip()
    # Выход в меню админа по 'x' или 'х'
    if text.lower() in ('x', 'х', 'X', 'Х'):
        await state.clear()
        await main_menu_admin(message.from_user.id)
        return

    # Валидация старого номера
    if not re.match(r'^7\d{10}$', text):
        await message.answer("Неверный формат. Попробуйте ещё раз или введите 'x' для выхода.")
        return

    old_phone = text
    await state.update_data(old_phone=old_phone)

    client_tg_id = await database.get_id_from_phone(old_phone)
    if not client_tg_id:
        await message.answer("Пользователь с таким номером не найден. Введите другой номер или 'x' для выхода.")
        return

    await state.update_data(client_tg_id=client_tg_id)
    await message.answer(f"Пользователь с номером {old_phone} найден!\nТеперь введите новый номер телефона в формате '7xxxxxxxxxx' (или 'x' для выхода):")
    await state.set_state(ChangePhoneStates.waiting_for_new_phone)

@router.message(ChangePhoneStates.waiting_for_new_phone)
async def change_new_phone(message: Message, state: FSMContext):
    text = message.text.strip()
    # Выход в меню админа
    if text.lower() in ('x', 'х'):
        await state.clear()
        await main_menu_admin(message.from_user.id)
        return

    # Валидация нового номера
    if not re.match(r'^7\d{10}$', text):
        await message.answer("Неверный формат нового номера. Попробуйте ещё раз или введите 'x' для выхода.")
        return

    new_phone = text
    data = await state.get_data()
    client_tg_id = data.get('client_tg_id')

    if client_tg_id:
        await database.change_phone(client_tg_id, new_phone)
        await message.answer(f"Номер телефона пользователя успешно изменён на {new_phone}.")
        client_text = f"Ваш номер успешно изменен на {new_phone}."
        try:
            await bot.send_message(client_tg_id, text=client_text)
        except Exception as e:
            logger.error(f"Не удалось уведомить пользователя {client_tg_id} об изменении номера: {e}")
            await bot.send_message(message.from_user.id, text="Не удалось уведомить пользователя об изменении номера(")
        await state.clear()
        await main_menu_admin(message.from_user.id)
    else:
        await message.answer("Не удалось получить информацию о пользователе. Попробуйте заново или введите 'x' для выхода.")

    await state.clear()


@router.message(PhoneState.waiting_for_phone)
async def process_phone_number(message: Message, state: FSMContext):
    tg_user_id: int = int(message.from_user.id)
    chat_id: int = int(message.chat.id)
    phone_number = message.text.strip()

    if not re.match(r'^7\d{10}$', phone_number):
        await message.answer("Неверный формат номера телефона. Пожалуйста, введите номер в формате '7xxxxxxxxxx'")
        return

    await state.update_data(phone_number=phone_number)
    await message.answer(f"Ваш номер телефона: {phone_number} получен.")
    sent = await message.answer(
        text="Все верно?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Все верно!", callback_data="confirm_phone")],
            [InlineKeyboardButton(text="Изменить", callback_data="change_phone")]
        ])
    )
    await database.set_last_message_by_user_id(tg_user_id, sent.message_id)

@router.callback_query(lambda c: c.data == "confirm_phone")
async def callback_confirm_phone(callback: CallbackQuery, state: FSMContext):
    tg_user_id: int = int(callback.from_user.id)
    chat_id: int = int(callback.message.chat.id)
    await safely_delete_last_message(tg_user_id, chat_id)
    data = await state.get_data()
    phone_number = data.get("phone_number")

    await database.client_registration(tg_user_id, phone_number)
    await callback.message.answer(f"Ваш номер телефона {phone_number} сохранён в базе данных.")
    # **Уведомляем админов**
    admin_ids = await database.get_all_admin_ids()
    notification = f"Новый клиент зарегистрирован с номером: {phone_number} (tg_id: {tg_user_id})"
    for admin_id in admin_ids:
        # не забудьте обработать возможные ошибки отправки
        try:
            await bot.send_message(chat_id=admin_id, text=notification)
        except Exception as e:
            logger.error(f"Не удалось уведомить администратора {admin_id}: {e}")

    # Завершаем FSM и показываем клиенту меню
    await state.clear()
    await main_menu_client(chat_id)
    await callback.answer()

@router.callback_query(lambda c: c.data == "change_phone")
async def callback_change_phone(callback: CallbackQuery, state: FSMContext):
    tg_user_id: int = int(callback.from_user.id)
    chat_id: int = int(callback.message.chat.id)
    await state.clear()
    await safely_delete_last_message(tg_user_id, chat_id)
    await callback.message.answer("Введите, пожалуйста, Ваш номер телефона в формате '7xxxxxxxxxx'")
    await state.set_state(PhoneState.waiting_for_phone)
    await callback.answer()

@router.callback_query(lambda call: call.data == "main_menu")
async def MMenu(callback: CallbackQuery):
    await main_menu_client(callback.from_user.id)

# -------------------------------------------------
# Admin check (unchanged)
def check_admin(tg_user_id: int) -> bool:
    raw_ids = os.getenv("admin_tg_ids", "[]").strip()
    try:
        ids = ast.literal_eval(raw_ids)
        ids = [int(x) for x in ids]
    except Exception:
        ids = []
    return tg_user_id in ids

# -------------------------------------------------
# Safe delete last messages (unchanged)
async def safely_delete_last_message(tg_user_id: int, chat_id: int):
    try:
        last_messages = await database.get_last_messages_by_user_id(tg_user_id)
        for msg_id in last_messages or []:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception:
                continue
        await database.clear_last_message_ids_by_user_id(tg_user_id)
    except Exception as e:
        logger.error("Ошибка в safely_delete_last_message: %s", e)

async def main_menu_client(tg_user_id: int):
    try:
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            #[InlineKeyboardButton(text='Изменить номер', callback_data='change_phone')]
        ])
        await bot.send_message(tg_user_id, "Добро пожаловать в главное меню!")
        await bot.send_message(tg_user_id, "Выберите действие:", reply_markup=inline_kb)
    except Exception as e:
        logger.error("Ошибка в main_menu: %s", e)

async def main_menu_admin(tg_user_id: int):
    try:
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Изменить номер', callback_data='admin_change_phone')]
        ])
        await bot.send_message(tg_user_id, "Добро пожаловать в админ-панель!")
        await bot.send_message(tg_user_id, "Выберите действие:", reply_markup=inline_kb)
    except Exception as e:
        logger.error("Ошибка в main_menu: %s", e)

# -------------------------------------------------
# PostgreSQL LISTEN/NOTIFY listener for client_update channel
async def start_listener():
    conn = await asyncpg.connect(
        database=db_name,
        user=user,
        password=password,
        host=host,
        port=port,
    )

    async def on_notify(_conn, pid, channel, payload):
        logger.info(f"[notify] channel={channel}, payload={payload!r}")
        try:
            data = json.loads(payload)
            old = data.get('old', {})
            new = data.get('new', {})
            tg = int(new.get('tg_user_id') or old.get('tg_user_id'))

            # 1) Текст уведомления
            new_text = new.get('notif_text')
            if new_text and new_text != old.get('notif_text'):
                await bot.send_message(chat_id=tg, text=new_text)

            # 2) Фото изделия
            new_prod = new.get('product_photo_path')
            if new_prod and new_prod != old.get('product_photo_path'):
                if os.path.exists(new_prod):
                    photo = FSInputFile(new_prod)
                else:
                    photo = new_prod
                await bot.send_photo(chat_id=tg, photo=photo)

            # 3) Фото квитанции
            new_rec = new.get('receipt_photo_path')
            if new_rec and new_rec != old.get('receipt_photo_path'):
                if os.path.exists(new_rec):
                    photo = FSInputFile(new_rec)
                else:
                    photo = new_rec
                await bot.send_photo(chat_id=tg, photo=photo)

        except Exception as e:
            logger.error("Notify handler error: %s", e)

    await conn.add_listener('client_update', on_notify)
    logger.info("Listening on client_update...")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await conn.close()


# -------------------------------------------------
# Startup and polling
async def on_startup():
    await database.connect()
    asyncio.create_task(start_listener())

async def safe_polling(dp: Dispatcher):
    delay = 1
    while True:
        try:
            await dp.start_polling(bot, skip_updates=True)
            break
        except Exception as e:
            logger.warning(f"Polling error: {e}. Reconnecting in {delay}s...")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

async def main():
    dp.startup.register(on_startup)
    await safe_polling(dp)

if __name__ == '__main__':
    try:
        asyncio.run(main())
        print("[Bot Running] Бот включён")
    except Exception as e:
        logger.error("Ошибка в __main__: %s", e)
