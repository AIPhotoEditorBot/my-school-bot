import asyncio
import logging
import sys
from datetime import datetime, timedelta
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = "8293585417:AAHsbZv7_ChcIPdMjwRegILTixwZOjdIt1Y" 
DB_NAME = "school_data.db"

# Включаем логирование
logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- СОСТОЯНИЯ (FSM) ---
class HWState(StatesGroup):
    choosing_subject = State()
    writing_task = State()

class SetupState(StatesGroup):
    choosing_day = State()      # Выбор дня для настройки
    waiting_for_lessons = State() # Ожидание списка уроков

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS schedule (
                chat_id INTEGER,
                day_int INTEGER,
                lesson_num INTEGER,
                subject TEXT,
                PRIMARY KEY (chat_id, day_int, lesson_num)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS homework (
                chat_id INTEGER,
                date_str TEXT,
                subject TEXT,
                task TEXT,
                PRIMARY KEY (chat_id, date_str, subject)
            )
        ''')
        await db.commit()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def get_day_name(date_obj):
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    return days[date_obj.weekday()]

def get_day_name_by_int(day_int):
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]
    if 0 <= day_int < 6:
        return days[day_int]
    return "Неизвестно"

async def generate_schedule_text(chat_id: int, date_obj: datetime.date):
    day_int = date_obj.weekday()
    date_str = date_obj.strftime("%Y-%m-%d")
    
    header = f"📅 *{date_obj.strftime('%d.%m.%Y')}* ({get_day_name(date_obj)})\n"
    header += "〰️〰️〰️〰️〰️〰️〰️\n"
    
    if day_int == 6:
        return header + "🏖 *Сегодня выходной!* Уроков нет."

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT lesson_num, subject FROM schedule WHERE chat_id = ? AND day_int = ? ORDER BY lesson_num",
            (chat_id, day_int)
        )
        lessons = await cursor.fetchall()
        
        if not lessons:
            return header + "📂 *Расписание пусто.*\nИспользуйте /setup для настройки."

        lesson_map = {l[0]: l[1] for l in lessons}

        cursor_hw = await db.execute(
            "SELECT subject, task FROM homework WHERE chat_id = ? AND date_str = ?",
            (chat_id, date_str)
        )
        hw_rows = await cursor_hw.fetchall()
        hw_map = {h[0]: h[1] for h in hw_rows}

    text = header
    has_lessons = False
    # Выводим до 8 уроков, или до последнего заполненного, если их меньше 8, но хотя бы 1 есть
    max_lesson = max(lesson_map.keys()) if lesson_map else 8
    limit = 8 # Всегда 8 строк, как в дневнике, или можно limit = max_lesson
    
    for i in range(1, 9):
        subject = lesson_map.get(i, "—")
        
        # Красивое отображение: если предмета нет, просто прочерк
        if subject == "—":
            line = f"{i}. —"
        else:
            has_lessons = True
            hw_text = hw_map.get(subject, "Нет Д/з")
            line = f"{i}. *{subject}*: {hw_text}"
        
        text += line + "\n"
    
    return text

def get_keyboard(chat_id, date_obj):
    date_str = date_obj.strftime("%Y-%m-%d")
    prev_date = (date_obj - timedelta(days=1)).strftime("%Y-%m-%d")
    next_date = (date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⬅️", callback_data=f"nav_{prev_date}"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"refresh_{date_str}"),
        InlineKeyboardButton(text="➡️", callback_data=f"nav_{next_date}")
    )
    if bot_info and bot_info.username:
        bot_link = f"https://t.me/{bot_info.username}?start=fill_{chat_id}_{date_str}"
        builder.row(InlineKeyboardButton(text="✍️ Заполнить ДЗ", url=bot_link))
    
    return builder.as_markup()

# Клавиатура для настройки дней недели
def get_setup_keyboard():
    builder = InlineKeyboardBuilder()
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб"]
    for i, day in enumerate(days):
        builder.button(text=day, callback_data=f"setup_day_{i}")
    builder.adjust(3) # по 3 кнопки в ряд
    builder.row(InlineKeyboardButton(text="✅ Готово / Выход", callback_data="setup_done"))
    return builder.as_markup()

# --- ХЕНДЛЕРЫ НАСТРОЙКИ РАСПИСАНИЯ (/setup) ---

@dp.message(Command("setup"))
async def cmd_setup(message: types.Message, state: FSMContext):
    # В идеале здесь стоит добавить проверку на админа: 
    # if message.chat.type != 'private' and ... (проверка прав)
    
    await message.answer(
        "🛠 *Режим настройки расписания*\n"
        "Выберите день недели для редактирования:",
        reply_markup=get_setup_keyboard(),
        parse_mode="Markdown"
    )
    await state.set_state(SetupState.choosing_day)

@dp.callback_query(SetupState.choosing_day, F.data.startswith("setup_day_"))
async def setup_day_chosen(callback: types.CallbackQuery, state: FSMContext):
    day_int = int(callback.data.split("_")[2])
    day_name = get_day_name_by_int(day_int)
    
    await state.update_data(setup_day_int=day_int)
    
    await callback.message.edit_text(
        f"Редактируем: *{day_name}*.\n\n"
        "Напишите список предметов *через запятую* или с новой строки.\n"
        "Если урока нет, поставьте прочерк или минус.\n\n"
        "_Пример:_\n"
        "Алгебра, Геометрия, -, Физика, Английский",
        parse_mode="Markdown"
    )
    await state.set_state(SetupState.waiting_for_lessons)

@dp.message(SetupState.waiting_for_lessons)
async def setup_receive_lessons(message: types.Message, state: FSMContext):
    data = await state.get_data()
    day_int = data.get('setup_day_int')
    chat_id = message.chat.id
    raw_text = message.text
    
    # Парсинг текста (разбиваем по запятым или переносам строк)
    text = raw_text.replace('\n', ',')
    lessons_list = [s.strip() for s in text.split(',') if s.strip()]
    
    # Обрезаем до 8 уроков
    lessons_list = lessons_list[:8]
    
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Удаляем старое расписание на этот день
        await db.execute(
            "DELETE FROM schedule WHERE chat_id = ? AND day_int = ?", 
            (chat_id, day_int)
        )
        
        # 2. Записываем новое
        records = []
        for i, subj in enumerate(lessons_list):
            # Если пользователь написал "-" или "нет", сохраняем как прочерк
            if subj in ["-", "нет", "окно"]:
                subj = "—"
            records.append((chat_id, day_int, i + 1, subj))
        
        if records:
            await db.executemany("INSERT INTO schedule VALUES (?, ?, ?, ?)", records)
            await db.commit()
    
    await message.answer(
        f"✅ Расписание на {get_day_name_by_int(day_int)} сохранено!\n"
        "Выберите другой день или нажмите Готово.",
        reply_markup=get_setup_keyboard()
    )
    # Возвращаемся к выбору дня
    await state.set_state(SetupState.choosing_day)

@dp.callback_query(SetupState.choosing_day, F.data == "setup_done")
async def setup_finish(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("✅ Настройка расписания завершена.\nНапишите 'дз', чтобы проверить.")
# --- ХЕНДЛЕРЫ ДЗ И ЛОГИКА (Остальное без изменений) ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message, command: CommandObject, state: FSMContext):
    args = command.args
    if not args:
        await message.answer("Привет! Добавь меня в чат и введи /setup для настройки расписания.")
        return

    if args.startswith("fill_"):
        try:
            _, chat_id_str, date_str = args.split("_")
            chat_id = int(chat_id_str)
            await state.update_data(target_chat_id=chat_id, target_date=date_str)
            
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            day_int = dt.weekday()
            
            async with aiosqlite.connect(DB_NAME) as db:
                cursor = await db.execute(
                    "SELECT subject FROM schedule WHERE chat_id = ? AND day_int = ?",
                    (chat_id, day_int)
                )
                subjects = await cursor.fetchall()
            
            # Фильтруем пустые уроки (прочерки)
            valid_subjects = [s[0] for s in subjects if s[0] != "—"]
            
            if not valid_subjects:
                await message.answer("На этот день уроков нет или расписание не настроено.")
                return

            builder = InlineKeyboardBuilder()
            for sub in valid_subjects:
                builder.button(text=sub, callback_data=f"sethw_{sub}")
            builder.adjust(2)
            
            await message.answer(f"Выбери предмет для записи ДЗ на {date_str}:", reply_markup=builder.as_markup())
            await state.set_state(HWState.choosing_subject)
            
        except Exception as e:
            logging.error(e)
            await message.answer("Ошибка ссылки.")

@dp.callback_query(HWState.choosing_subject, F.data.startswith("sethw_"))
async def subject_chosen(callback: types.CallbackQuery, state: FSMContext):
    subject = callback.data.split("_")[1]
    await state.update_data(subject=subject)
    await callback.message.edit_text(f"Выбран предмет: *{subject}*\n\nНапиши задание одним сообщением:")
    await state.set_state(HWState.writing_task)

@dp.message(HWState.writing_task)
async def task_received(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get('target_chat_id')
    date_str = data.get('target_date')
    subject = data.get('subject')
    task_text = message.text

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT OR REPLACE INTO homework (chat_id, date_str, subject, task)
            VALUES (?, ?, ?, ?)
        ''', (chat_id, date_str, subject, task_text))
        await db.commit()

    await message.answer(f"✅ ДЗ по {subject} сохранено! Вернись в чат и нажми 'Обновить'.")
    await state.clear()

@dp.message(F.text.lower().contains("дз"))
async def show_hw_command(message: types.Message):
    now = datetime.now()
    text = await generate_schedule_text(message.chat.id, now.date())
    kb = get_keyboard(message.chat.id, now.date())
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("nav_") | F.data.startswith("refresh_"))
async def nav_callback(callback: types.CallbackQuery):
    action, date_str = callback.data.split("_")
    current_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    
    new_text = await generate_schedule_text(callback.message.chat.id, current_date)
    new_kb = get_keyboard(callback.message.chat.id, current_date)
    
    try:
        await callback.message.edit_text(new_text, reply_markup=new_kb, parse_mode="Markdown")
    except Exception:
        await callback.answer("Данные актуальны")
    else:
        await callback.answer()

async def main():
    await init_db()
    global bot_info
    bot_info = await bot.get_me()
    print("Бот запущен...")
    await dp.start_polling(bot)
if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
