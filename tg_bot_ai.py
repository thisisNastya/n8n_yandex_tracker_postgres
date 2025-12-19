# tg_bot_ai_modified.py
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove, BotCommand, KeyboardButton, ReplyKeyboardMarkup, BotCommandScopeChat
import psycopg2
from datetime import datetime, date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import logging
import time
import pytz
import threading
import requests 
import json

# ==================== НАСТРОЙКИ ====================

TRACKER_ORG_ID = "bpf2qp........"  # твой X-Cloud-Org-ID
IAM_TOKEN = None  # будем получать свежий при каждом запросе
IAM_TOKEN_EXPIRES = 0

TELEGRAM_TOKEN = '8027083575:AAGeg...........'

DB_CONFIG = {
    "dbname": "default_db",
    "user": "gen_user",
    "password": ".........",
    "host": ".............",
    "port": "5432"
}

DAILY_HOUR = 9      # 09:00 — начало daily
REMINDER_HOUR = 10  # 10:00 — напоминание

# Определение групп ролей (измените имена, если они отличаются в вашей БД)
DEV_QA_ROLES = ["Developer", "QA"]  # Роли для daily, сводки и онбординга v1
LEAD_PM_ROLES = ["Team Lead", "PM"]  # Роли для дайджеста и онбординга v2

# ==================== YANDEX TRACKER API ====================
def get_iam_token():
    """Получаем свежий IAM-токен (кешируем на час)"""
    global IAM_TOKEN, IAM_TOKEN_EXPIRES
    current_time = time.time()
    
    if IAM_TOKEN and current_time < IAM_TOKEN_EXPIRES - 60:
        return IAM_TOKEN
    
    url = "https://iam.api.cloud.yandex.net/iam/v1/tokens"
    headers = {"Content-Type": "application/json"}
    data = {
        "yandexPassportOauthToken": "y0__xD6o................................."  # твой OAuth-токен
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        token_data = response.json()
        IAM_TOKEN = token_data["iamToken"]
        IAM_TOKEN_EXPIRES = current_time + 3600  # токен живёт ~1 час
        logging.info("Получен новый IAM-токен")
        return IAM_TOKEN
    except Exception as e:
        logging.error(f"Ошибка получения IAM-токена: {e}")
        return None

# Функция для получения текущей задачи пользователя из Yandex Tracker
def get_current_task(chat_id):
    """Получает текущую задачу в статусе 'В работе' для пользователя"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT tracker_user_id, name FROM users WHERE chat_id = %s
                """, (chat_id,))
                row = cur.fetchone()
                if not row:
                    return None, "Пользователь не найден в базе."
                
                tracker_uid, user_name = row
                
                if not tracker_uid:
                    return None, "У тебя не указан tracker_user_id. Обратитесь к администратору."

        iam_token = get_iam_token()
        if not iam_token:
            return None, "Не удалось получить доступ к Yandex Tracker."

        url = "https://api.tracker.yandex.net/v2/issues/_search"
        headers = {
            "Authorization": f"Bearer {iam_token}",
            "X-Cloud-Org-ID": TRACKER_ORG_ID,
            "Content-Type": "application/json"
        }
        body = {
            "filter": {
                "assignee": tracker_uid,
                "-status": ["Закрыт", "Решен"]
            },
            "perPage": 10
        }

        response = requests.post(url, headers=headers, json=body)
        if response.status_code != 200:
            logging.error(f"Tracker error {response.status_code}: {response.text}")
            return None, "Ошибка связи с Yandex Tracker."

        issues = response.json()
        
        if not issues:
            return None, "У тебя сейчас нет задач в работе. Отдыхай! ☕"

        # Берём первую (или можно все, если несколько)
        task = issues[0]
        key = task["key"]
        summary = task.get("summary", "Без названия")
        status = task["status"]["display"]
        link = f"https://tracker.yandex.ru/{key}"

        message = (
            f"Твоя текущая задача в работе:\n\n"
            f"<b>{key}</b> — {summary}\n"
            f"Статус: <i>{status}</i>\n\n"
            f"<a href='{link}'>Открыть в Tracker</a>"
        )
        return True, message

    except Exception as e:
        logging.error(f"Ошибка в get_current_task: {e}")
        return None, "Произошла ошибка при запросе задач."

# ==================== TZ_MAPPING ====================

tz_mapping = {
    # Россия
    "калининградское время (utc+2)": "Europe/Kaliningrad",
    "московское время (utc+3)": "Europe/Moscow",
    "самарское время (utc+4)": "Europe/Samara",
    "екатеринбургское время (utc+5)": "Asia/Yekaterinburg",
    "омское время (utc+6)": "Asia/Omsk",
    "красноярское время (utc+7)": "Asia/Krasnoyarsk",
    "иркутское время (utc+8)": "Asia/Irkutsk",
    "якутское время (utc+9)": "Asia/Yakutsk",
    "владивостокское время (utc+10)": "Asia/Vladivostok",
    "магаданское время (utc+11)": "Asia/Magadan",
    "камчатское время (utc+12)": "Asia/Kamchatka",

    # СНГ
    "казахстан: алматы, астана (utc+5)": "Asia/Almaty",
    "узбекистан: ташкент (utc+5)": "Asia/Tashkent",
    "беларусь: минск (utc+3)": "Europe/Minsk",
    "армения: ереван (utc+4)": "Asia/Yerevan",
    "кыргызстан: бишкек (utc+6)": "Asia/Bishkek",
    "таджикистан: душанбе (utc+5)": "Asia/Dushanbe",

    # Мир
    "европа: лондон (utc+0/+1)": "Europe/London",
    "европа: берлин, париж (utc+1/+2 cet)": "Europe/Berlin",
    "сша: нью-йорк (восточное, utc-5/-4)": "America/New_York",
    "сша: чикаго (центральное, utc-6/-5)": "America/Chicago",
    "сша: лос-анджелес (тихоокеанское, utc-8/-7)": "America/Los_Angeles",
    "канада: торонто (utc-5/-4)": "America/Toronto",
    "бразилия: сан-паулу (utc-3)": "America/Sao_Paulo",
    "индия: мумбаи (utc+5:30)": "Asia/Kolkata",
    "китай: пекин (utc+8)": "Asia/Shanghai",
    "япония: токио (utc+9)": "Asia/Tokyo",
    "австралия: сидней (utc+10/+11)": "Australia/Sydney",
}
# Группировка
RUSSIA_TZ = [k for k in tz_mapping.keys() if "россия" not in k.lower() and any(x in k.lower() for x in ["московское", "калининградское", "самарское", "екатеринбургское", "омское", "красноярское", "иркутское", "якутское", "владивостокское", "магаданское", "камчатское"])]
CIS_TZ = [k for k in tz_mapping.keys() if any(x in k.lower() for x in ["казахстан", "узбекистан", "беларусь", "армения", "кыргызстан", "таджикистан"])]
WORLD_TZ = [k for k in tz_mapping.keys() if k not in RUSSIA_TZ and k not in CIS_TZ]


# ==================== ЛОГИРОВАНИЕ ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

bot = telebot.TeleBot(TELEGRAM_TOKEN)
user_states = {}
user_last_messages = {}  # Для хранения ID последнего сообщения с главным меню


# Вспомогательная функция — подключение к БД с retry
def get_db_connection(max_retries=3, retry_delay=5):
    """Подключение к БД с retry"""
    for attempt in range(max_retries):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            logging.info("Успешное подключение к БД")
            return conn
        except Exception as e:
            logging.error(f"Ошибка подключения к БД (попытка {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    logging.critical("Не удалось подключиться к БД после всех попыток")
    raise Exception("Ошибка подключения к БД")

# Вспомогательная функция — получаем данные пользователя
def get_user_by_chat_id(chat_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT u.id, u.name, u.timezone, u.email, r.name as role_name,
                           u.current_task_key, u.daily_active, u.tracker_user_id,
                           u.task_assigned_at
                    FROM users u
                    JOIN roles r ON u.role_id = r.id
                    WHERE u.chat_id = %s
                """, (chat_id,))
                row = cur.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'name': row[1],
                        'timezone': row[2],
                        'email': row[3],
                        'role_name': row[4],
                        'current_task_key': row[5],
                        'daily_active': row[6],
                        'tracker_user_id': row[7],
                        'task_assigned_at': row[8]  # ← новое поле
                    }
    except Exception as e:
        logging.error(f"Ошибка получения профиля {chat_id}: {e}")
    return None

# Красивые названия часовых поясов (обратное маппинг)
def get_pretty_timezone(iana_tz):
    reverse_map = {v: k.title() for k, v in tz_mapping.items()}
    return reverse_map.get(iana_tz, iana_tz)


# ==================== ГЛАВНОЕ МЕНЮ (зависит от роли) ====================

def main_menu(role_name):
    markup = InlineKeyboardMarkup(row_width=2)
    if role_name in DEV_QA_ROLES:
        # Меню для Developer и QA
        markup.add(
            InlineKeyboardButton("Профиль", callback_data="menu_profile"),
            InlineKeyboardButton("Daily", callback_data="menu_daily"),
        )
        markup.add(
            InlineKeyboardButton("Онбординг", callback_data="menu_onboarding"),
            InlineKeyboardButton("Персональная сводка", callback_data="menu_summary"),
        )
    elif role_name in LEAD_PM_ROLES:
        # Меню для Team Lead и PM
        markup.add(
            InlineKeyboardButton("Профиль", callback_data="menu_profile"),
            InlineKeyboardButton("Дайджест", callback_data="menu_digest"),
        )
        markup.add(
            InlineKeyboardButton("Онбординг", callback_data="menu_onboarding"),
        )
    markup.add(
        InlineKeyboardButton("Помощь /start", callback_data="menu_start"),
    )
    return markup

# Универсальная функция для показа главного меню
def send_or_update_menu(chat_id, text="🏠 <b>Главное меню</b>", role_name=None):
    if not role_name:
        user = get_user_by_chat_id(chat_id)
        if user:
            role_name = user['role_name']
        else:
            role_name = "Unknown"  # Fallback

    if chat_id in user_last_messages:
        try:
            bot.delete_message(chat_id, user_last_messages[chat_id])
        except:
            pass
    
    msg = bot.send_message(
        chat_id,
        text,
        reply_markup=main_menu(role_name),
        parse_mode="HTML"
    )
    user_last_messages[chat_id] = msg.message_id

# Обработчик нажатий в главном меню
@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_"))
def handle_main_menu(call):
    chat_id = call.message.chat.id
    data = call.data

    user = get_user_by_chat_id(chat_id)
    if not user:
        bot.send_message(chat_id, "Сначала зарегистрируйся: /start")
        return

    role_name = user['role_name']

    try:
        bot.delete_message(chat_id, call.message.id)
    except:
        pass

    if data == "menu_start":
        cmd_start(call.message)
        return

    elif data == "menu_profile":
        cmd_profile(call.message)
        return

    elif data == "menu_daily":
        if role_name not in DEV_QA_ROLES:
            bot.send_message(chat_id, "Эта функция недоступна для вашей роли.")
            send_or_update_menu(chat_id, role_name=role_name)
            return
        start_daily_for_user(chat_id, user['id'])
        return

    elif data == "menu_onboarding":
        send_onboarding(chat_id, role_name, show_final_button=False)
        return

    elif data == "menu_summary":
        if role_name not in DEV_QA_ROLES:
            bot.send_message(chat_id, "Эта функция недоступна для вашей роли.")
            send_or_update_menu(chat_id, role_name=role_name)
            return
        send_personal_summary(chat_id)
        return

    elif data == "menu_digest":
        if role_name not in LEAD_PM_ROLES:
            bot.send_message(chat_id, "Эта функция недоступна для вашей роли.")
            send_or_update_menu(chat_id, role_name=role_name)
            return
        send_digest(chat_id, role_name)
        return

    # Если ни одно действие не выполнено — просто показываем меню
    send_or_update_menu(chat_id, role_name=role_name)

# Обновление команд бота в зависимости от роли
def update_bot_commands_for_user(chat_id, role_name):
    if role_name in DEV_QA_ROLES:
        commands = [
            BotCommand("start", "Главное меню и регистрация"),
            BotCommand("profile", "Мой профиль"),
            BotCommand("daily", "Заполнить daily опрос"),
            BotCommand("summary", "Персональная сводка"),
            BotCommand("onboarding", "Важная информация для новичков"),
        ]
    elif role_name in LEAD_PM_ROLES:
        commands = [
            BotCommand("start", "Главное меню и регистрация"),
            BotCommand("profile", "Мой профиль"),
            BotCommand("onboarding", "Важная информация для новичков"),
            BotCommand("digest", "Получить ежедневный дайджест"),
            BotCommand("task", "Сводка по сотрудникам"),
        ]
    else:
        commands = [
            BotCommand("start", "Главное меню и регистрация"),
            BotCommand("profile", "Мой профиль"),
            BotCommand("onboarding", "Важная информация для новичков"),
        ]

    try:
        scope = BotCommandScopeChat(chat_id=chat_id)
        bot.set_my_commands(commands, scope=scope)
        logging.info(f"Обновлены команды для пользователя {chat_id} (роль: {role_name})")
    except Exception as e:
        logging.warning(f"Не удалось обновить команды для {chat_id}: {e}")


# ==================== РЕГИСТРАЦИЯ ПРОФИЛЯ ====================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    chat_id = message.chat.id
    logging.info(f"Команда /start от chat_id: {chat_id}")

    user = get_user_by_chat_id(chat_id)
    if user:
        update_bot_commands_for_user(chat_id, user['role_name'])
        bot.send_message(
            chat_id,
            f"С возвращением, {user['name']}!\n"
            "🏠 <b>Главное меню</b>",
            reply_markup=main_menu(user['role_name']),
            parse_mode="HTML"   
        )
        return

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE chat_id = %s", (chat_id,))
                if cur.fetchone():
                    bot.send_message(chat_id, "Вы уже зарегистрированы! Используйте главное меню.", reply_markup=main_menu("Unknown"))
                    return
    except Exception as e:
        logging.error(f"Ошибка БД при проверке регистрации {chat_id}: {e}")
        bot.send_message(chat_id, "Ошибка подключения к базе. Попробуйте позже.")
        return

    bot.send_message(chat_id, "Привет! Это бот для daily опросов\n\nДавай познакомимся. Как тебя зовут?")
    user_states[chat_id] = {'step': 'name'}
    bot.register_next_step_handler(message, process_name_step)

# ввод имени
def process_name_step(message):
    chat_id = message.chat.id
    name = message.text.strip()

    if not name:
        bot.send_message(chat_id, "❌ Имя не может быть пустым. Попробуй ещё раз:")
        bot.register_next_step_handler(message, process_name_step)
        return

    ask_role_inline(chat_id, name)  # Переходим к inline выбору роли

# выбор роли 
def ask_role_inline(chat_id, name):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name FROM roles ORDER BY name")
                roles = cur.fetchall()
    except Exception as e:
        logging.error(f"Ошибка загрузки ролей: {e}")
        bot.send_message(chat_id, "Ошибка загрузки ролей. Попробуйте позже.")
        return

    if not roles:
        bot.send_message(chat_id, "Нет доступных ролей в базе. Обратитесь к администратору.")
        return

    markup = InlineKeyboardMarkup(row_width=2)
    for role_id, role_name in roles:
        markup.add(InlineKeyboardButton(role_name, callback_data=f"role_{role_id}"))

    user_states[chat_id] = {'step': 'wait_role', 'data': {'name': name}}
    bot.send_message(chat_id, f"Отлично, {name}! Теперь выбери свою роль:", reply_markup=markup)

# обработка выбора роли
@bot.callback_query_handler(func=lambda call: call.data.startswith("role_"))
def handle_role_selection(call):
    chat_id = call.message.chat.id
    role_id = int(call.data.split("_")[1])

    state = user_states.get(chat_id)
    if not state or state['step'] != 'wait_role':
        return

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name, is_daily_participant FROM roles WHERE id = %s", (role_id,))
                role_row = cur.fetchone()
                if not role_row:
                    raise ValueError(f"Роль с id {role_id} не найдена")
                role_name, is_participant = role_row
    except Exception as e:
        logging.error(f"Ошибка получения роли: {e}")
        bot.send_message(chat_id, "Ошибка при выборе роли. Попробуйте позже или начните заново: /start")
        if chat_id in user_states:
            del user_states[chat_id]
        return

    bot.delete_message(chat_id, call.message.id)
    bot.send_message(chat_id, f"✅ Роль выбрана: {role_name}")

    if 'data' not in state:
        state['data'] = {}
    state['data'].update({
        'role_id': role_id,
        'role_name': role_name,
        'is_daily_participant': is_participant
    })
    state['step'] = 'email'  # переходим к вводу email

    bot.send_message(chat_id, "Теперь укажи свой рабочий email (например, ivan@yandex.ru) для связи его с Яндекс Трекером:")

# поиск tracker_user_id по email через API Яндекс Трекера
def get_tracker_user_id_by_email(email: str) -> str | None:
    try:
        iam_response = requests.post(
            "https://iam.api.cloud.yandex.net/iam/v1/tokens",
            json={"yandexPassportOauthToken": "y0__xD6oZKUBhjHqDwg_9yB1RWKs8qw32o9-XqFOnqvnscwuyfbqQ"}
        )
        if iam_response.status_code != 200:
            logging.error(f"IAM error: {iam_response.text}")
            return None

        iam_token = iam_response.json()["iamToken"]
        headers = {"Authorization": f"Bearer {iam_token}", "X-Cloud-Org-ID": "bpf2qpu7qte0m2fj8n1o"}

        # Варианты поиска
        queries = [
            email,  # полный email
            email.split('@')[0],  # только login (vasyilii.simakov)
            f"email:{email}",
            f"email:{email.split('@')[0]}"
        ]

        for q in queries:
            params = {"query": q}
            response = requests.get("https://api.tracker.yandex.net/v2/users", headers=headers, params=params)
            logging.info(f"Попытка поиска с query='{q}': status {response.status_code}, body: {response.text}")

            if response.status_code == 200:
                users = response.json()
                if users:
                    # Ищем точное совпадение по email
                    for user in users:
                        if user.get("email", "").lower() == email.lower():
                            uid = user.get("uid") or user.get("id")
                            logging.info(f"Найден пользователь: uid={uid}, email={user.get('email')}")
                            return uid
                    # Если не точное — берём первого (fallback)
                    uid = users[0].get("uid") or users[0].get("id")
                    logging.info(f"Найден по частичному совпадению: uid={uid}")
                    return uid

        logging.warning(f"Не найден пользователь по всем вариантам для email {email}")
        return None

    except Exception as e:
        logging.error(f"Ошибка поиска: {e}", exc_info=True)
        return None


# ввод email
@bot.message_handler(func=lambda m: user_states.get(m.chat.id, {}).get('step') == 'email')
def process_email_step(message):
    chat_id = message.chat.id
    email = message.text.strip().lower()

    if not email:
        bot.send_message(chat_id, "❌ Email не может быть пустым.\nПопробуй ещё раз:")
        bot.register_next_step_handler(message, process_email_step)
        return

    if '@' not in email or '.' not in email.split('@')[-1] or len(email.split('@')[0]) == 0:
        bot.send_message(chat_id, "❌ Некорректный формат email.\nПример: ivan@yandex.ru\nПопробуй ещё раз:")
        bot.register_next_step_handler(message, process_email_step)
        return

    state = user_states[chat_id]
    role_name = state['data'].get('role_name')

    state['data']['email'] = email

    tracker_user_id = get_tracker_user_id_by_email(email)
    
    animate_loading(
        chat_id,
        base_text="🔍 Проверяю твой email в Yandex Track",
        cycles=3,           
        auto_delete=True    
    )

    if tracker_user_id:
        state['data']['tracker_user_id'] = tracker_user_id
        bot.send_message(
            chat_id,
            f"✅ Отлично! Ты найден в Yandex Tracker.\n"
            f"Email: {email}\n"
            f"Связь с трекером установлена."
        )
        ask_timezone_category_inline(chat_id, None, role_name)
    else:
        bot.send_message(
            chat_id,
            "❌ Не удалось найти тебя в Yandex Tracker по этому email.\n\n"
            "Это теперь обязательно для всех ролей.\n"
            "Возможные причины:\n"
            "• Неправильный email\n"
            "• Ты не добавлен в организацию Yandex Tracker\n"
            "• Email в Tracker отличается\n\n"
            "Укажи правильный рабочий email:",
            reply_markup=ReplyKeyboardRemove()
        )
        bot.register_next_step_handler(message, process_email_step)
    

# выбор часового пояса для регистрации
def ask_timezone_category_inline(chat_id, user_id, role_name):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("Россия", callback_data="tz_category_russia"),
        InlineKeyboardButton("СНГ", callback_data="tz_category_cis"),
    )
    markup.add(
        InlineKeyboardButton("Остальной мир", callback_data="tz_category_world"),
        InlineKeyboardButton("Другой — напишу сам", callback_data="tz_category_custom"),
    )
    
    if chat_id not in user_states:
        user_states[chat_id] = {'data': {}}
    
    state = user_states[chat_id]
    state['step'] = 'wait_tz_category'
    
    # Обновляем только нужные поля, НЕ стираем name, email, role_id и т.д.
    state['data'].setdefault('user_id', user_id)
    state['data']['role_name'] = role_name
    state['data']['edit_mode'] = False
    
    bot.send_message(chat_id, "Выбери категорию часового пояса:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("tz_category_"))
def handle_tz_category(call):
    chat_id = call.message.chat.id
    category = call.data.split("_")[2]
    state = user_states.get(chat_id)
    if not state or state['step'] != 'wait_tz_category':
        return

    bot.delete_message(chat_id, call.message.id)

    if category == "russia":
        show_russia_timezones_inline(chat_id)
    elif category == "cis":
        show_cis_timezones_inline(chat_id)
    elif category == "world":
        show_world_timezones_inline(chat_id)
    elif category == "custom":
        ask_custom_timezone(chat_id)

#Функций для показа поясов
def show_russia_timezones_inline(chat_id):
    markup = InlineKeyboardMarkup(row_width=1)
    for tz_name in RUSSIA_TZ:
        markup.add(InlineKeyboardButton(tz_name, callback_data=f"tz_select_{tz_name}"))
    bot.send_message(chat_id, "Выбери часовой пояс в России:", reply_markup=markup)
    user_states[chat_id]['step'] = 'wait_tz_select'

def show_cis_timezones_inline(chat_id):
    markup = InlineKeyboardMarkup(row_width=1)
    for tz_name in CIS_TZ:
        markup.add(InlineKeyboardButton(tz_name, callback_data=f"tz_select_{tz_name}"))
    bot.send_message(chat_id, "Выбери часовой пояс в СНГ:", reply_markup=markup)
    user_states[chat_id]['step'] = 'wait_tz_select'

def show_world_timezones_inline(chat_id):
    markup = InlineKeyboardMarkup(row_width=1)
    for tz_name in WORLD_TZ:
        markup.add(InlineKeyboardButton(tz_name, callback_data=f"tz_select_{tz_name}"))
    bot.send_message(chat_id, "Выбери часовой пояс в мире:", reply_markup=markup)
    user_states[chat_id]['step'] = 'wait_tz_select'

def ask_custom_timezone(chat_id):
    bot.send_message(chat_id, "Напиши свой часовой пояс (в формате IANA, например, Europe/Moscow):")
    user_states[chat_id]['step'] = 'wait_tz_custom'

@bot.callback_query_handler(func=lambda call: call.data.startswith("tz_select_"))
def handle_tz_select(call):
    chat_id = call.message.chat.id
    tz_pretty = call.data[len("tz_select_"):]  
    tz_iana = tz_mapping.get(tz_pretty.lower())

    if not tz_iana:
        bot.answer_callback_query(call.id, "Ошибка: пояс не найден")
        return

    state = user_states.get(chat_id)
    if not state:
        return

    try:
        bot.delete_message(chat_id, call.message.id)

        pretty_name = tz_pretty.title()

        # Проверяем, это редактирование или регистрация
        if state['data'].get('edit_mode', False):
            # Просто обновляем timezone в БД
            try:
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("UPDATE users SET timezone = %s WHERE chat_id = %s", (tz_iana, chat_id))
                    conn.commit()
                bot.send_message(chat_id, f"✅ Часовой пояс успешно изменён на:\n{pretty_name}")
                logging.info(f"Пользователь {chat_id} изменил timezone на {tz_iana}")
            except Exception as e:
                logging.error(f"Ошибка обновления timezone: {e}")
                bot.send_message(chat_id, "Не удалось сохранить часовой пояс. Попробуй позже.")
        else:
            # Это регистрация — сохраняем в state и завершаем
            state['data']['timezone'] = tz_iana
            bot.send_message(chat_id, f"✅ Часовой пояс выбран:\n{pretty_name}")
            complete_registration(chat_id)

        bot.answer_callback_query(call.id, "Сохранено!")
        
        # Очищаем состояние в любом случае
        user_states.pop(chat_id, None)

    except Exception as e:
        logging.error(f"Ошибка при выборе пояса: {e}")
        bot.answer_callback_query(call.id, "Ошибка")    

@bot.message_handler(func=lambda m: user_states.get(m.chat.id, {}).get('step') == 'wait_tz_custom')
def process_custom_tz(message):
    chat_id = message.chat.id
    tz_input = message.text.strip()
    try:
        pytz.timezone(tz_input)  
    except pytz.UnknownTimeZoneError:
        bot.send_message(chat_id, "Неверный формат часового пояса. Попробуй снова (пример: Europe/Moscow).")
        bot.register_next_step_handler(message, process_custom_tz)
        return

    state = user_states.get(chat_id)
    if not state:
        return

    pretty_name = get_pretty_timezone(tz_input) or tz_input

    if state['data'].get('edit_mode', False):
        # Редактирование — только UPDATE
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET timezone = %s WHERE chat_id = %s", (tz_input, chat_id))
                conn.commit()
            bot.send_message(chat_id, f"✅ Часовой пояс успешно изменён на:\n{pretty_name}")
            logging.info(f"Пользователь {chat_id} изменил timezone на {tz_input}")
        except Exception as e:
            logging.error(f"Ошибка обновления timezone: {e}")
            bot.send_message(chat_id, "Не удалось сохранить. Попробуй позже.")
    else:
        # Регистрация
        state['data']['timezone'] = tz_input
        bot.send_message(chat_id, f"✅ Часовой пояс выбран:\n{pretty_name}")
        complete_registration(chat_id)

    # Очищаем состояние
    user_states.pop(chat_id, None)

# Завершение регистрации
def complete_registration(chat_id):
    state = user_states.get(chat_id)
    if not state or 'data' not in state:
        bot.send_message(chat_id, "Ошибка состояния. Начни заново: /start")
        user_states.pop(chat_id, None)
        return False

    data = state['data']
    
    # Обязательные поля
    required = ['name', 'role_id', 'is_daily_participant', 'email', 'timezone']
    missing = [f for f in required if f not in data or not str(data[f]).strip()]
    
    if missing:
        logging.error(f"Регистрация {chat_id} прервана: отсутствуют поля {missing}. Данные: {data}")
        bot.send_message(chat_id, f"Не все данные заполнены ({', '.join(missing)}). Начни заново: /start")
        user_states.pop(chat_id, None)
        return False

    name = data['name'].strip()
    role_id = data['role_id']
    is_daily_participant = data['is_daily_participant']
    email = data['email'].strip().lower()
    timezone_iana = data['timezone']
    
    # берём tracker_user_id, если есть
    tracker_user_id = data.get('tracker_user_id')  # Может быть None — это нормально

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (
                        chat_id, name, role_id, is_daily_participant,
                        timezone, email, created_at, tracker_user_id  -- Добавили поле!
                    ) VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)     -- Добавили значение
                    RETURNING id
                """, (
                    chat_id,
                    name,
                    role_id,
                    is_daily_participant,
                    timezone_iana,
                    email,
                    tracker_user_id  # Вот сюда передаём!
                ))
                user_id = cur.fetchone()[0]
            conn.commit()

        logging.info(
            f"Успешно зарегистрирован: {name} ({email}), "
            f"chat_id={chat_id}, tz={timezone_iana}, role={data['role_name']}, "
            f"tracker_user_id={tracker_user_id}"
        )
        
        user_states.pop(chat_id, None)

        finish_registration(chat_id, data['role_name'])
        return True

    except Exception as e:
        logging.error(f"Ошибка регистрации {chat_id}: {e}", exc_info=True)
        bot.send_message(chat_id, "Не удалось сохранить профиль 😔\nПопробуй позже или начни заново: /start")
        user_states.pop(chat_id, None)
        return False

# Красивая анимация завершения регистрации
def finish_registration(chat_id, role_name):
    animate_loading(
        chat_id,
        base_text="Регистрация завершена! Подготавливаю важную информацию",
        cycles=3,           
        delay=0.5,
        final_text="Готово! Сейчас всё расскажу ✨",
        auto_delete=True    
    )

    # Небольшая пауза после анимации
    time.sleep(0.8)

    # Запускаем онбординг в зависимости от роли
    send_onboarding(chat_id, role_name, show_final_button=True)


# ==================== ОНБОРДИНГ ====================

# Версия 1 для Developer и QA 
ONBOARDING_MESSAGES_V1 = [
    {
        "text": "Привет в нашей команде! 👋\n\n"
                "Каждый день в 9:00 по твоему времени будет приходить daily-опрос:\n"
                "• Что сделал вчера\n"
                "• Что планируешь сегодня\n"
                "• Есть ли блокеры\n\n"
                "Это занимает 1–2 минуты, но очень помогает всем быть в курсе. ",
        "delay": 1.0
    },
    {
        "text": "Как правильно заполнять daily:\n\n"
                "• Вчера — пиши только то, что реально сделано (конкретные задачи, лучше с номерами из Jira/Notion).\n"
                "• Сегодня — конкретный план на день.\n"
                "• Блокеры — если что-то мешает (доступы, ожидание, баг и т.д.). Если блокеров нет — просто напиши «—» или «нет».\n "
                "Это поможет команде быстро реагировать и избегать задержек.",
        "delay": 1.0
    },
    {
        "text": "Полезные ссылки:\n\n"
                "• Текущий спринт и задачи: https://tracker.yandex.ru/pages/projects/1/board \n"
                "• Чат с админом: @stxforu\n"
                "Сохрани их! Ты теперь в команде — это круто! Если будут вопросы — пиши в личку или в общий чат, не стесняйся. "
                "Мы всегда помогаем новичкам адаптироваться.",
        "delay": 1.0
    }
]

# Версия 2 для Team Lead и PM 
ONBOARDING_MESSAGES_V2 = [
    {
        "text": "Добро пожаловать в команду в роли лидера! 👋\n\n"
                "Ты будешь получать дайджесты о прогрессе команды, метриках и ключевых блокерах.\n"
                "Это поможет тебе координировать работу и принимать решения.",
        "delay": 1.0
    },
    {
        "text": "Ключевые инструменты:\n\n"
                "• Дайджест: Ежедневный обзор (формат зависит от твоей роли).\n"
                "• Мониторинг: Следи за задачами команды в Трекере.\n"
                "• Блокеры: Фокус на рисках и зависимостях.\n"
                "Если нужно вмешаться — используй чаты или встречи.",
        "delay": 1.0
    },
    {
        "text": "Полезные ссылки:\n\n"
                "• Дашборд метрик: https://tracker.yandex.ru/dashboards \n"
                "• Чат с админом: @stxforu\n"
                "• Планирование: notion.so/planning\n"
                "Сохрани их! Если вопросы — пиши, поможем адаптироваться.",
        "delay": 1.0
    }
]

def send_onboarding(chat_id, role_name, show_final_button=True):

    if user_states.get(chat_id, {}).get("step") == "onboarding":
        return

    user_states[chat_id] = {"step": "onboarding", "index": 0}

    # Выбираем версию онбординга по роли
    messages = ONBOARDING_MESSAGES_V1 if role_name in DEV_QA_ROLES else ONBOARDING_MESSAGES_V2

    for msg_data in messages:
        try:
            bot.send_message(chat_id, msg_data["text"])
            time.sleep(msg_data["delay"])
        except Exception as e:
            logging.error(f"Ошибка отправки сообщения онбординга: {e}")

    if show_final_button:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Понятно, я в деле!", callback_data="onboarding_done"))
        try:
            bot.send_message(chat_id, "Добро пожаловать в команду! Теперь ты в курсе всего важного.", reply_markup=markup)
        except Exception as e:
            logging.error(f"Ошибка отправки финальной кнопки онбординга: {e}")
        
    # Убираем состояние
    user_states.pop(chat_id, None)

@bot.callback_query_handler(func=lambda call: call.data == "onboarding_done")
def onboarding_done(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    user = get_user_by_chat_id(call.message.chat.id)
    bot.send_message(call.message.chat.id, "Супер! Теперь ты точно готов\n", reply_markup=main_menu(user['role_name'] if user else "Unknown"))

@bot.message_handler(commands=['onboarding'])
def cmd_onboarding(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    if not user:
        bot.send_message(chat_id, "Сначала зарегистрируйся: /start")
        return
    send_onboarding(chat_id, user['role_name'], show_final_button=False)
    

# ==================== РЕДАКТИРОВАНИЕ/ИЗМЕНЕНИЕ ПРОФИЛЯ  ====================

@bot.message_handler(commands=['profile'])
def cmd_profile(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    if not user:
        bot.send_message(chat_id, "Ты ещё не зарегистрирован. Напиши /start")
        return

    tz_pretty = get_pretty_timezone(user['timezone'])
    email = user.get('email') or "не указан"

    text = (f"Твой текущий профиль:\n\n"
            f"Имя: {user['name']}\n"
            f"Роль: {user['role_name']}\n"
            f"Email: {email}\n"
            f"Часовой пояс: {tz_pretty}\n"
            f"({user['timezone']})\n\n"
            f"Что хочешь изменить?")

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Изменить имя", callback_data="profile_change_name"))
    markup.add(InlineKeyboardButton("Изменить роль", callback_data="profile_change_role"))
    markup.add(InlineKeyboardButton("Изменить email", callback_data="profile_change_email"))
    markup.add(InlineKeyboardButton("Изменить часовой пояс", callback_data="profile_change_tz"))
    markup.add(InlineKeyboardButton("Ничего, всё ок", callback_data="profile_cancel"))

    bot.send_message(chat_id, text, reply_markup=markup)
    user_states[chat_id] = {'step': 'profile_menu'}


# Обработка изменения профиля
@bot.callback_query_handler(func=lambda call: call.data.startswith("profile_"))
def handle_profile_change(call):
    chat_id = call.message.chat.id
    data = call.data
    bot.delete_message(chat_id, call.message.id)

    if data == "profile_change_name":
        bot.send_message(chat_id, "Напиши новое имя:")
        user_states[chat_id] = {'step': 'change_name'}

    elif data == "profile_change_role":
        ask_role_inline_for_change(chat_id)

    elif data == "profile_change_email":
        # Показываем предупреждение перед вводом новой почты
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("Да, понимаю, изменить", callback_data="confirm_change_email"),
            InlineKeyboardButton("Отмена", callback_data="cancel_change_email")
        )

        bot.send_message(
            chat_id,
            "⚠️ <b>Важно!</b>\n\n"
            "Твой email используется для связи с аккаунтом в Яндекс Трекере.\n"
            "Если ты изменишь почту на неверную или не связанную с твоим аккаунтом в Трекере —\n"
            "ты перестанешь получать уведомления, задачи и данные по проектам.\n\n"
            "Убедись, что новая почта точно соответствует твоему аккаунту в Яндекс.Трекере.\n\n"
            "Продолжить изменение email?",
            reply_markup=markup,
            parse_mode="HTML"
        )

    elif data == "profile_change_tz":
        ask_timezone_category_inline_edit(chat_id, get_user_by_chat_id(chat_id)['id'], get_user_by_chat_id(chat_id)['role_name'])

    elif data == "profile_cancel":
        user = get_user_by_chat_id(chat_id)
        bot.send_message(
        chat_id,
        "🏠 <b>Главное меню</b>",
        reply_markup=main_menu(user['role_name'] if user else "Unknown"),
        parse_mode="HTML"
        )

# Выбор новой роли при изменении
def ask_role_inline_for_change(chat_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name FROM roles ORDER BY name")
                roles = cur.fetchall()
    except Exception as e:
        logging.error(f"Ошибка загрузки ролей: {e}")
        bot.send_message(chat_id, "Ошибка загрузки ролей.")
        return

    markup = InlineKeyboardMarkup(row_width=2)
    for role_id, role_name in roles:
        markup.add(InlineKeyboardButton(role_name, callback_data=f"change_role_{role_id}"))

    user_states[chat_id] = {'step': 'wait_change_role'}
    bot.send_message(chat_id, "Выбери новую роль:", reply_markup=markup)

# Обработка выбора новой роли при изменении
@bot.callback_query_handler(func=lambda call: call.data.startswith("change_role_"))
def handle_change_role_selection(call):
    chat_id = call.message.chat.id
    role_id = int(call.data.split("_")[2])

    state = user_states.get(chat_id)
    if not state or state['step'] != 'wait_change_role':
        return

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name, is_daily_participant FROM roles WHERE id = %s", (role_id,))
                role_name, is_participant = cur.fetchone()
                cur.execute("UPDATE users SET role_id = %s, is_daily_participant = %s WHERE chat_id = %s", (role_id, is_participant, chat_id))
            conn.commit()
        bot.delete_message(chat_id, call.message.id)
        bot.send_message(chat_id, f"Роль изменена на: {role_name}")
        # Обновляем команды в боковом меню
        update_bot_commands_for_user(chat_id, role_name)

        # Обновляем главное инлайн-меню
        send_or_update_menu(chat_id, text=f"Роль успешно изменена на <b>{role_name}</b>!\n🏠 <b>Главное меню</b>", role_name=role_name)

        logging.info(f"Пользователь {chat_id} сменил роль на {role_name}")
    except Exception as e:
        logging.error(f"Ошибка изменения роли: {e}")
        bot.send_message(chat_id, "Ошибка изменения роли.")
    
    if chat_id in user_states:
        del user_states[chat_id]

# Изменение имени
@bot.message_handler(func=lambda m: user_states.get(m.chat.id, {}).get('step') == 'change_name')
def process_change_name(message):
    chat_id = message.chat.id
    new_name = message.text.strip()

    if not new_name:
        bot.send_message(chat_id, "❌ Имя не может быть пустым. Попробуй ещё раз:")
        return

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET name = %s WHERE chat_id = %s", (new_name, chat_id))
            conn.commit()
        bot.send_message(chat_id, f"✅ Имя успешно изменено на: {new_name}")
        logging.info(f"Пользователь {chat_id} сменил имя на {new_name}")
    except Exception as e:
        logging.error(f"Ошибка смены имени {chat_id}: {e}")
        bot.send_message(chat_id, "Не удалось сохранить имя. Попробуй позже.")

    if chat_id in user_states:
        del user_states[chat_id]

# Подтверждение изменения email
@bot.callback_query_handler(func=lambda call: call.data == "confirm_change_email")
def handle_confirm_change_email(call):
    chat_id = call.message.chat.id 
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception as e:
        logging.error(f"Не удалось удалить сообщение предупреждения: {e}")
    
    bot.send_message(
        chat_id,
        "Введите новый рабочий email (он будет проверен в Yandex Tracker):"
    )
    
    user_states[chat_id] = {'step': 'change_email'}
    
    bot.answer_callback_query(call.id)

# Отмена изменения email (если используешь cancel_change_email)
@bot.callback_query_handler(func=lambda call: call.data == "cancel_change_email")
def handle_cancel_change_email(call):
    logging.info(">>> CANCEL_CHANGE_EMAIL: обработчик сработал!")
    chat_id = call.message.chat.id
    
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception as e:
        logging.error(f"Не удалось удалить сообщение отмены: {e}")
    
    user = get_user_by_chat_id(chat_id)
    send_or_update_menu(chat_id, "Изменение email отменено.\n🏠 <b>Главное меню</b>", role_name=user['role_name'] if user else None)
    
    if chat_id in user_states:
        del user_states[chat_id]
    
    bot.answer_callback_query(call.id)

# Изменение email
@bot.message_handler(func=lambda m: user_states.get(m.chat.id, {}).get('step') == 'change_email')
def process_change_email(message):
    chat_id = message.chat.id
    new_email = message.text.strip().lower()
    
    # Валидация email
    if '@' not in new_email or '.' not in new_email.split('@')[-1]:
        bot.send_message(chat_id, "❌ Некорректный формат email. Пример: ivan@example.ru\nПопробуй ещё раз:")
        return
    
    tracker_user_id = get_tracker_user_id_by_email(new_email)  
     
    animate_loading(
        chat_id,
        base_text="🔍 Проверяю email в Yandex Track",
        cycles=3,           
        auto_delete=True    
    )
    
    if not tracker_user_id:
        bot.send_message(chat_id, "❌ Этот email не найден в Yandex Tracker.\nПопробуй другой:")
        return
    
    # Сохраняем в БД
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET email = %s, tracker_user_id = %s WHERE chat_id = %s",
                    (new_email, tracker_user_id, chat_id)
                )
            conn.commit()
        
        bot.send_message(chat_id, f"✅ Email успешно изменён на {new_email}!")
        user = get_user_by_chat_id(chat_id)
        send_or_update_menu(chat_id, "✅ Профиль обновлён!\n🏠 <b>Главное меню</b>", role_name=user['role_name'])
        
    except Exception as e:
        logging.error(f"Ошибка сохранения email: {e}")
        bot.send_message(chat_id, "❌ Ошибка сохранения. Попробуй позже.")
    
    # Очищаем состояние
    if chat_id in user_states:
        del user_states[chat_id]

        
# выбор часового пояса для редактирования профиля
def ask_timezone_category_inline_edit(chat_id, user_id, role_name):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("Россия", callback_data="tz_category_russia"),
        InlineKeyboardButton("СНГ", callback_data="tz_category_cis"),
    )
    markup.add(
        InlineKeyboardButton("Остальной мир", callback_data="tz_category_world"),
        InlineKeyboardButton("Другой — напишу сам", callback_data="tz_category_custom"),
    )
    user_states[chat_id] = {'step': 'wait_tz_category', 'data': {'user_id': user_id, 'role_name': role_name, 'edit_mode': True}}  # Флаг edit_mode=True для редактирования
    bot.send_message(chat_id, "Выбери категорию часового пояса для изменения:", reply_markup=markup)


# ==================== DAILY ОПРОС (только для DEV_QA_ROLES) ====================

# Проверка, можно ли сегодня начинать daily
def should_start_daily_today(user):
    """
    Возвращает True, если сегодня можно начинать daily:
    - Есть текущая задача
    - daily_active = True
    - task_assigned_at не NULL
    - Прошёл хотя бы один полный день с даты выдачи задачи
    """
    if not user.get('daily_active') or not user.get('current_task_key'):
        return False
    
    assigned_at = user.get('task_assigned_at')
    if not assigned_at:
        return False
    
    # Преобразуем в date (без времени)
    assigned_date = assigned_at.date()
    today = date.today()
    
    # Daily начинается на СЛЕДУЮЩИЙ день после взятия задачи
    return today > assigned_date

# Проверка, прошёл ли уже daily сегодня
def has_completed_daily_today(user):
    """
    Здесь нужно хранить дату последнего daily.
    Но если у тебя нет отдельного поля — можно проверять по логам или упростить.
    Пока сделаем просто: если daily_active=True и задача в работе — предполагаем, что нужно проходить.
    """
    # Лучше добавить поле last_daily_date в users, но пока упростим:
    # Предполагаем, что если daily_active=True — нужно проходить ежедневно
    return False  # Пока всегда предлагаем, пока не добавишь поле

# Получение активных задач из Яндекс Трекера
def get_user_active_task(tracker_user_id):
    """Получает активную задачу пользователя из Яндекс Трекера (статус inProgress)"""
    try:
        # Получаем IAM токен
        iam_response = requests.post(
            "https://iam.api.cloud.yandex.net/iam/v1/tokens",
            json={"yandexPassportOauthToken": "y0__xD6oZKUBhjHqDwg_9yB1RWKs8qw32o9-XqFOnqvnscwuyfbqQ"}
        )
        if iam_response.status_code != 200:
            return None
        
        iam_token = iam_response.json()["iamToken"]
        headers = {
            "Authorization": f"Bearer {iam_token}",
            "X-Cloud-Org-ID": "bpf2qpu7qte0m2fj8n1o"
        }
        
        # Запрос задач в статусе "В работе" (inProgress)
        params = {
            "assignee": tracker_user_id,
            "statusType": "inProgress",  # Только задачи в работе!
            "perPage": 10
        }
        
        response = requests.get(
            "https://api.tracker.yandex.net/v2/issues",
            headers=headers,
            params=params
        )
        
        if response.status_code == 200:
            tasks = response.json()
            if tasks:
                # Берём первую активную задачу
                task = tasks[0]
                return {
                    'id': task.get('key'),
                    'title': task.get('summary', 'Без названия'),
                    'status': task.get('status', {}).get('display', 'Неизвестно')
                }
        return None
    except Exception as e:
        logging.error(f"Ошибка получения задачи: {e}")
        return None

@bot.message_handler(commands=['daily'])
def cmd_daily(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    
    if not user or user['role_name'] not in DEV_QA_ROLES:
        bot.send_message(chat_id, "🔒 Daily доступен только Developer и QA.")
        return
    
    if not user.get('daily_active'):
        bot.send_message(chat_id, "У тебя сейчас нет активной задачи для daily.")
        return
    
    if not user.get('task_assigned_at'):
        bot.send_message(chat_id, "Дата выдачи задачи не известна. Обратитесь к администратору.")
        return
    
    assigned_date = user['task_assigned_at'].date()
    today = date.today()
    
    if today <= assigned_date:
        bot.send_message(chat_id, f"Daily станет доступен завтра ({(assigned_date + timedelta(days=1)).strftime('%d.%m.%Y')}). Задача выдана только {assigned_date.strftime('%d.%m.%Y')}.")
        return
    
    task_key = user['current_task_key']
    
    # Получаем актуальный статус задачи через Tracker
    tasks = get_user_tasks(user['tracker_user_id'], "in_progress")
    in_progress = any(t['key'] == task_key and t.get("status", {}).get("display") == "В работе" for t in tasks)
    
    if not in_progress:
        bot.send_message(chat_id, "Твоя задача уже не в статусе 'В работе'. Daily недоступен.")
        return
    
    # Здесь начинается опрос daily
    text = (
        f"📝 Daily по задаче <b>{task_key}</b>\n"
        f"Выдана: <i>{assigned_date.strftime('%d.%m.%Y')}</i>\n\n"
        f"Расскажи:\n"
        f"• Что сделал вчера?\n"
        f"• Какие планы на сегодня?\n"
        f"• Есть ли блокеры?"
    )
    bot.send_message(chat_id, text, parse_mode="HTML")
    # Далее — твоя логика опроса (состояния и т.д.)

def start_daily_for_user(chat_id, user_id):
    if chat_id in user_states:
        return
    
    animate_loading(
        chat_id,
        base_text="Подготавливаю daily-опрос",
        cycles=2,
        auto_delete=True
    )
    
    try:
        # Получаем пользователя
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT u.timezone, u.tracker_user_id, u.name 
                    FROM users u 
                    WHERE u.id = %s
                """, (user_id,))
                user_data = cur.fetchone()
        
        if not user_data:
            bot.send_message(chat_id, "Ошибка: пользователь не найден")
            return
            
        tz_name, tracker_user_id, user_name = user_data
        user_tz = pytz.timezone(tz_name or "Europe/Moscow")
        current_date = datetime.now(user_tz).date()
        
        # Получаем активную задачу пользователя
        active_task = None
        if tracker_user_id:
            active_task = get_user_active_task(tracker_user_id)
        
        # Начинаем daily
        if active_task:
            task_text = f"📋 <b>Ваша активная задача:</b>\n\n" \
                       f"<b>{active_task['id']}</b>: {active_task['title']}\n" \
                       f"Статус: {active_task['status']}\n\n" \
                       f"Пожалуйста, отвечайте на вопросы daily по этой задаче."
            bot.send_message(chat_id, task_text, parse_mode="HTML")
            
            # Сохраняем выбранную задачу в состоянии
            user_states[chat_id] = {
                'step': 'daily_1',
                'data': {
                    'user_id': user_id,
                    'date': current_date,
                    'selected_task_id': active_task['id'],
                    'task_title': active_task['title']
                }
            }
        else:
            # Нет активной задачи
            bot.send_message(chat_id, 
                "⚠️ <b>У вас нет активных задач в работе.</b>\n" \
                "Вы можете заполнить daily без привязки к задаче.\n\n" \
                "Возможные причины:\n" \
                "• Все задачи завершены\n" \
                "• Нет задач со статусом 'В работе'\n" \
                "• Проблема с синхронизацией с Яндекс Трекером",
                parse_mode="HTML"
            )
            
            user_states[chat_id] = {
                'step': 'daily_1',
                'data': {
                    'user_id': user_id,
                    'date': current_date,
                    'selected_task_id': None,
                    'task_title': None
                }
            }
        
        # Переходим к вопросам daily
        bot.send_message(chat_id, "Время daily!\nЧто ты сделал вчера?")
        
    except Exception as e:
        logging.error(f"Ошибка начала daily: {e}")
        bot.send_message(chat_id, "Произошла ошибка. Попробуйте позже.")

def check_daily_on_start():
    now_utc = datetime.now(pytz.UTC)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT u.chat_id, u.id, u.timezone, r.name as role_name FROM users u JOIN roles r ON u.role_id = r.id WHERE u.is_daily_participant = TRUE AND r.name IN %s", (tuple(DEV_QA_ROLES),))
                users = cur.fetchall()

        for chat_id, user_id, tz_name, role_name in users:
            if role_name not in DEV_QA_ROLES:
                continue  # Пропускаем, если роль не подходит
            tz_name = tz_name or "Europe/Moscow"
            user_tz = pytz.timezone(tz_name)
            user_time = now_utc.astimezone(user_tz)
            if user_time.hour == DAILY_HOUR and user_time.minute < 10:
                start_daily_for_user(chat_id, user_id)
    except Exception as e:
        logging.error(f"Ошибка в check_daily_on_start: {e}")

# планировщик для daily
def daily_prompt_job():
    """Ежедневно в 9:00 по локальному времени пользователя — приглашение пройти daily"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT chat_id, name, timezone, current_task_key, task_assigned_at
                    FROM users
                    WHERE daily_active = true 
                      AND task_assigned_at IS NOT NULL
                      AND current_task_key IS NOT NULL
                """)
                rows = cur.fetchall()

        for chat_id, name, tz_str, task_key, assigned_at in rows:
            if not tz_str or tz_str not in pytz.all_timezones:
                continue

            user_tz = pytz.timezone(tz_str)
            now_user = datetime.now(user_tz)

            # Проверяем, прошёл ли хотя бы один день с выдачи задачи
            if assigned_at:
                assigned_date = assigned_at.date()
                if now_user.date() <= assigned_date:
                    continue  # ещё рано

            # Отправляем только в 9:00–9:10 по времени пользователя
            if now_user.hour == 9 and now_user.minute < 10:
                assigned_str = assigned_at.strftime("%d.%m.%Y") if assigned_at else "неизвестно"
                message = (
                    f"☀️ Доброе утро, {name}!\n\n"
                    f"Пора заполнить daily по задаче <b>{task_key}</b>\n"
                    f"Задача выдана: <i>{assigned_str}</i>\n\n"
                    f"Нажми /daily и расскажи, что сделал вчера и что планируешь сегодня."
                )
                bot.send_message(chat_id, message, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Ошибка в daily_prompt_job: {e}")


def hourly_reminder_job():
    """Каждый час с 10:00 до 19:59 — напоминание о daily, если ещё не пройден"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT chat_id, name, timezone, current_task_key, task_assigned_at
                    FROM users
                    WHERE daily_active = true 
                      AND task_assigned_at IS NOT NULL
                      AND current_task_key IS NOT NULL
                      AND task_assigned_at::date < CURRENT_DATE  -- прошёл хотя бы один день
                """)
                rows = cur.fetchall()

        for chat_id, name, tz_str, task_key, assigned_at in rows:
            if not tz_str or tz_str not in pytz.all_timezones:
                continue

            user_tz = pytz.timezone(tz_str)
            now_user = datetime.now(user_tz)

            # Напоминаем только с 10:00 до 19:59
            if 10 <= now_user.hour < 20:
                message = (
                    f"⏰ {name}, не забудь заполнить daily!\n\n"
                    f"Задача: <b>{task_key}</b>\n"
                    f"Команда: /daily"
                )
                bot.send_message(chat_id, message, parse_mode="HTML")

    except Exception as e:
        logging.error(f"Ошибка в hourly_reminder_job: {e}")

# обработка ответов на вопросы daily
@bot.message_handler(func=lambda m: m.chat.id in user_states and user_states[m.chat.id]['step'].startswith('daily_'))
def handle_daily_answers(message):
    chat_id = message.chat.id
    state = user_states[chat_id]
    step = state['step']

    # Если мы в режиме повтора — просто возвращаем на нужный шаг
    if step == 'daily_3_retry' and message.text.strip() == "Попробовать снова":
        bot.send_message(
            chat_id,
            "Есть ли блокеры или риски?\n(можно «—», «нет» или пустое сообщение)",
        )
        state['step'] = 'daily_3'
        return

    # Обычная логика шагов
    answer = (message.text or "").strip()

    if step == 'daily_1':
        if not answer:
            bot.send_message(chat_id, "Ответ на «Вчера» не может быть пустым. Напиши, пожалуйста:")
            return
        state['data']['yesterday'] = answer
        bot.send_message(chat_id, "Отлично! А что планируешь сделать сегодня?")
        state['step'] = 'daily_2'
        return

    elif step == 'daily_2':
        if not answer:
            bot.send_message(chat_id, "Ответ на «Сегодня» не может быть пустым. Напиши план:")
            return
        state['data']['today'] = answer
        bot.send_message(chat_id, "Есть ли блокеры или риски?\n(можно написать «—», «нет» или пустое сообщение)")
        state['step'] = 'daily_3'
        return

    elif step == 'daily_3':
        blockers = "" if answer.lower() in ['—', '-', 'нет', 'неа', 'пропустить', ''] else answer
        state['data']['blockers'] = blockers

        if save_daily_checkin(state, chat_id):
            bot.send_message(chat_id, "✅ Спасибо! Daily сохранён")
            del user_states[chat_id]
        else:
            send_retry_keyboard(chat_id)
            state['step'] = 'daily_3_retry'  # ждём кнопку
        return

# Сохранение daily в БД
def save_daily_checkin(state, chat_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                user_id = state['data']['user_id']

                # Получаем актуальные данные пользователя, включая current_task_key
                cur.execute("""
                    SELECT role_id, current_task_key 
                    FROM users 
                    WHERE id = %s
                """, (user_id,))
                user_row = cur.fetchone()
                if not user_row:
                    logging.error(f"Пользователь {user_id} не найден при сохранении daily")
                    return False
                
                role_id = user_row[0]
                current_task_key = user_row[1]  # Это задача, установленная через webhook из Tracker

                # Определяем, какой task_id использовать для сохранения
                # Приоритет: current_task_key из БД (от Tracker) → если нет, то selected_task_id из state (ручной выбор)
                task_id_to_save = current_task_key or state['data'].get('selected_task_id')

                # Сохраняем в checkins
                cur.execute("""
                    INSERT INTO checkins (
                        user_id, checkin_date, task_id,
                        answer_yesterday, answer_today, answer_blockers,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """, (
                    user_id,
                    state['data']['date'],
                    task_id_to_save,
                    state['data']['yesterday'],
                    state['data']['today'],
                    state['data']['blockers']
                ))
                
                # Логи ответов (тоже с тем же task_id)
                answers = [state['data']['yesterday'], state['data']['today'], state['data']['blockers']]
                for q_num, text in enumerate(answers, 1):
                    cur.execute("""
                        INSERT INTO logs (
                            user_id, role_id, date, question_number, 
                            raw_answer, answer_length, timestamp, task_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
                    """, (
                        user_id, role_id,
                        state['data']['date'], q_num,
                        text, len(text or ""),
                        task_id_to_save
                    ))
            
            conn.commit()
        
        # Подтверждение пользователю
        if task_id_to_save:
            bot.send_message(
                chat_id,
                f"✅ Daily сохранён!\n"
                f"По задаче: <b>{task_id_to_save}</b>\n"
                f"Спасибо за ответы!",
                parse_mode="HTML"
            )
        else:
            bot.send_message(chat_id, "✅ Daily сохранён! Спасибо за ответы!")
        
        logging.info(f"Daily успешно сохранён для user_id={user_id}, task_id={task_id_to_save}")
        return True
        
    except Exception as e:
        logging.error(f"Ошибка сохранения daily от {chat_id}: {e}", exc_info=True)
        bot.send_message(chat_id, "❌ Ошибка при сохранении daily. Попробуй позже.")
        return False

# клавиатура для повтора при ошибке
def send_retry_keyboard(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("Попробовать снова"))
    bot.send_message(
        chat_id,
        "Произошла ошибка при сохранении daily.\n"
        "Нажми кнопку ниже, чтобы отправить ответы ещё раз:",
        reply_markup=markup
    )


BotCommand("mytask", "Мои текущие задачи в работе"),
BotCommand("summary", "Персональная сводка (в работе + новые)"),


# ==================== ПЕРСОНАЛЬНАЯ СВОДКА И ЗАДАЧИ ====================

def get_user_tasks(tracker_uid, status_filter=None):
    """Получает задачи конкретного пользователя по его tracker_uid"""
    iam_token = get_iam_token()
    if not iam_token:
        logging.error("Не удалось получить IAM-токен")
        return []

    headers = {
        "Authorization": f"Bearer {iam_token}",
        "X-Cloud-Org-ID": TRACKER_ORG_ID,
        "Content-Type": "application/json"
    }

    url = "https://api.tracker.yandex.net/v2/issues/_search"

    body = {
        "filter": {
            "assignee": tracker_uid  # Только по исполнителю — без -status!
        }
    }

    try:
        response = requests.post(url, headers=headers, json=body)
        if response.status_code != 200:
            logging.error(f"Tracker error {response.status_code}: {response.text}")
            return []

        issues = response.json()

        logging.info(f"Получено задач для {tracker_uid}: {len(issues)} (все статусы)")
        logging.info(f"Статусы: {[i.get('status', {}).get('display') for i in issues]}")  # Добавь временно для отладки

      
        new_issues = [issue for issue in issues if issue.get("status", {}).get("display") == "Открыт"]
        in_progress_issues = [issue for issue in issues if issue.get("status", {}).get("display") == "В работе"]

        if status_filter == "in_progress":
            return in_progress_issues
        elif status_filter == "new":
            return new_issues
        else:
            return issues  # Все назначенные

    except Exception as e:
        logging.error(f"Ошибка получения задач: {e}")
        return []


@bot.message_handler(commands=['summary'])
def cmd_summary(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    if not user or user['role_name'] not in DEV_QA_ROLES:
        bot.send_message(chat_id, "🔒 Эта команда доступна только Developer и QA.")
        return

    tracker_uid = user.get('tracker_user_id')
    if not tracker_uid:
        bot.send_message(chat_id, "❌ У тебя не привязан аккаунт Yandex Tracker. Обратитесь к администратору.")
        return

    # Один запрос на все задачи
    all_tasks = get_user_tasks(tracker_uid)

    # Правильные отображаемые имена статусов
    current_tasks = [t for t in all_tasks if t.get("status", {}).get("display") == "В работе"]
    future_tasks = [t for t in all_tasks if t.get("status", {}).get("display") == "Открыт"]  

    text = f"📊 *{user['name']}, твоя персональная сводка:*\n\n"

    if current_tasks:
        text += "🔥 *Задачи в работе:*\n"
        for task in current_tasks[:3]:
            key = task["key"]
            summary = task.get("summary", "Без названия")
            link = f"https://tracker.yandex.ru/{key}"
            text += f"• <a href='{link}'>{key}</a> — {summary}\n"
        text += "\n"
    else:
        text += "✅ Задач в работе нет.\n\n"

    if future_tasks:
        text += "⏳ Будущие задачи (статус 'Открыт'):\n"  # ← Обнови текст для ясности
        for task in future_tasks[:5]:
            key = task["key"]
            summary = task.get("summary", "Без названия")
            link = f"https://tracker.yandex.ru/{key}"
            text += f"• <a href='{link}'>{key}</a> — {summary}\n"
        text += "\n"
    else:
        text += "⏳ Будущих задач нет.\n"

    bot.send_message(chat_id, text or "Нет данных по задачам.", parse_mode="HTML", disable_web_page_preview=True)


def get_employees_keyboard():
    """Возвращает клавиатуру с именами сотрудников, у которых есть tracker_user_id"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name FROM users 
                    WHERE tracker_user_id IS NOT NULL AND tracker_user_id != ''
                    ORDER BY name
                """)
                rows = cur.fetchall()
                
                if not rows:
                    return None
                
                buttons = [[KeyboardButton(name[0])] for name in rows]
                keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
                return keyboard
    except Exception as e:
        logging.error(f"Ошибка создания клавиатуры сотрудников: {e}")
        return None


# ==================== ДАЙДЖЕСТ (только для LEAD_PM_ROLES) ====================


@bot.message_handler(commands=['digest'])
def cmd_digest(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    
    if not user or user['role_name'] not in LEAD_PM_ROLES:
        bot.send_message(chat_id, "ℹ️ Доступно только для Team Lead и PM.")
        return
    
    # Показываем "в процессе" и НЕ ТРОГАЕМ ЕГО больше
    bot.send_message(chat_id, "🔄 Формирую дайджест... Это может занять 30–90 секунд. Ожидайте.")
    
    webhook_url = "https://k2neurotech.app.n8n.cloud/webhook/d47fe292-a8f4-4147-9ebc-5ea1cf2e4857"
    
    payload = {
        "chat_id": chat_id,
        "user_name": user['name'],
        "user_role": user['role_name'],
        "user_email": user.get('email')
    }
    
    try:
        requests.post(webhook_url, json=payload, timeout=10)  # Просто отправляем и забываем
        logging.info(f"Webhook для дайджеста отправлен для {chat_id}")
    except Exception as e:
        # Только при реальной ошибке связи показываем проблему
        bot.send_message(chat_id, "❌ Не удалось связаться с сервером дайджеста. Попробуй позже.")
        logging.error(f"Webhook failed: {e}")

# ==================== НОВАЯ КОМАНДА /TASK ДЛЯ РУКОВОДИТЕЛЕЙ ====================

user_task_states = {}  # {chat_id: выбранный_tracker_uid}

@bot.message_handler(commands=['task'])
def cmd_task_start(message):
    chat_id = message.chat.id
    user = get_user_by_chat_id(chat_id)
    
    if not user or user['role_name'] not in LEAD_PM_ROLES:
        bot.send_message(chat_id, "🔒 Эта команда доступна только Team Lead и PM.")
        return

    # Получаем список сотрудников с tracker_user_id
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name, tracker_user_id 
                    FROM users 
                    WHERE tracker_user_id IS NOT NULL AND tracker_user_id != ''
                    ORDER BY name
                """)
                rows = cur.fetchall()
                
                if not rows:
                    bot.send_message(chat_id, "Нет сотрудников с привязанным Yandex Tracker.")
                    return
                
                # Создаём inline-клавиатуру
                markup = InlineKeyboardMarkup(row_width=2)
                for name, tracker_uid in rows:
                    button = InlineKeyboardButton(
                        text=name,
                        callback_data=f"task_user_{tracker_uid}"
                    )
                    markup.add(button)
                
                bot.send_message(
                    chat_id,
                    "👥 Выберите сотрудника для просмотра задач:",
                    reply_markup=markup
                )
                
    except Exception as e:
        logging.error(f"Ошибка в cmd_task_start: {e}")
        bot.send_message(chat_id, "Ошибка при загрузке сотрудников.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("task_user_"))
def callback_task_user(call):
    chat_id = call.message.chat.id
    leader_user = get_user_by_chat_id(chat_id)
    
    if not leader_user or leader_user['role_name'] not in LEAD_PM_ROLES:
        bot.answer_callback_query(call.id, "Доступ запрещён.")
        return
    
    try:
        tracker_uid = call.data.split("_", 2)[2]
        
        # Получаем имя сотрудника
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM users WHERE tracker_user_id = %s", (tracker_uid,))
                row = cur.fetchone()
                if not row:
                    bot.answer_callback_query(call.id, "Сотрудник не найден.")
                    return
                employee_name = row[0]
        
        # Получаем все задачи сотрудника
        all_tasks = get_user_tasks(tracker_uid)  # без фильтра — все назначенные
        
        if not all_tasks:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text=f"📭 У {employee_name} нет задач в Yandex Tracker.",
                parse_mode="HTML"
            )
            return
        
        # Фильтруем по статусам
        open_tasks = [t for t in all_tasks if t.get("status", {}).get("display") == "Открыт"]
        in_progress_tasks = [t for t in all_tasks if t.get("status", {}).get("display") == "В работе"]
        
        # Завершённые на этой неделе (updatedAt за последние 7 дней)
        from datetime import timezone  # ← Убедись, что импорт есть в начале файла!

        week_start = datetime.now(timezone.utc) - timedelta(days=7)  # aware в UTC

        completed_tasks = []
        for t in all_tasks:
            status_display = t.get("status", {}).get("display")
            updated_at_str = t.get("updatedAt")
            if status_display in ["Закрыт", "Решен"] and updated_at_str:
                try:
                    # Преобразуем updatedAt в aware datetime
                    updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                    if updated_at > week_start:
                        completed_tasks.append(t)
                except ValueError:
                    # На случай некорректного формата — пропускаем
                    continue
        
        # Формируем текст
        text = f"📋 <b>Сводка по задачам: {employee_name}</b>\n\n"
        
        if in_progress_tasks:
            text += "🔥 <b>В работе:</b>\n"
            for task in in_progress_tasks[:5]:
                key = task["key"]
                summary = task.get("summary", "Без названия")
                link = f"https://tracker.yandex.ru/{key}"
                text += f"• <a href='{link}'>{key}</a> — {summary}\n"
            if len(in_progress_tasks) > 5:
                text += f"   ... и ещё {len(in_progress_tasks) - 5}\n"
            text += "\n"
        else:
            text += "✅ <b>В работе:</b> нет задач\n\n"
        
        if open_tasks:
            text += "⏳ <b>Открытые (будущие):</b>\n"
            for task in open_tasks[:5]:
                key = task["key"]
                summary = task.get("summary", "Без названия")
                link = f"https://tracker.yandex.ru/{key}"
                text += f"• <a href='{link}'>{key}</a> — {summary}\n"
            if len(open_tasks) > 5:
                text += f"   ... и ещё {len(open_tasks) - 5}\n"
            text += "\n"
        else:
            text += "⏳ <b>Открытые:</b> нет задач\n\n"
        
        if completed_tasks:
            text += "✅ <b>Завершённые на этой неделе:</b>\n"
            for task in completed_tasks[:5]:
                key = task["key"]
                summary = task.get("summary", "Без названия")
                updated = datetime.fromisoformat(task["updatedAt"].replace("Z", "+00:00")).strftime("%d.%m")
                link = f"https://tracker.yandex.ru/{key}"
                text += f"• <a href='{link}'>{key}</a> — {summary} ({updated})\n"
            if len(completed_tasks) > 5:
                text += f"   ... и ещё {len(completed_tasks) - 5}\n"
        else:
            text += "✅ <b>Завершённые на этой неделе:</b> нет\n"
        
        # Кнопка "Назад" — чтобы снова выбрать сотрудника
        back_markup = InlineKeyboardMarkup()
        back_markup.add(InlineKeyboardButton("🔙 Выбрать другого", callback_data="task_back"))
        
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=text,
            reply_markup=back_markup,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logging.error(f"Ошибка в callback_task_user: {e}")
        bot.answer_callback_query(call.id, "Ошибка при загрузке задач.")


@bot.callback_query_handler(func=lambda call: call.data == "task_back")
def callback_task_back(call):
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    
    leader_user = get_user_by_chat_id(chat_id)
    if not leader_user or leader_user['role_name'] not in LEAD_PM_ROLES:
        bot.answer_callback_query(call.id, "Доступ запрещён.")
        return
    
    try:
        # Получаем список сотрудников
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT name, tracker_user_id 
                    FROM users 
                    WHERE tracker_user_id IS NOT NULL AND tracker_user_id != ''
                    ORDER BY name
                """)
                rows = cur.fetchall()
                
                if not rows:
                    bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="Нет сотрудников с привязанным Yandex Tracker."
                    )
                    return
                
                # Создаём клавиатуру
                markup = InlineKeyboardMarkup(row_width=2)
                for name, tracker_uid in rows:
                    button = InlineKeyboardButton(
                        text=name,
                        callback_data=f"task_user_{tracker_uid}"
                    )
                    markup.add(button)
                
                # Редактируем текущее сообщение (со сводкой) на список сотрудников
                bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="👥 Выберите сотрудника для просмотра задач:",
                    reply_markup=markup
                )
                
    except Exception as e:
        logging.error(f"Ошибка в callback_task_back: {e}")
        bot.answer_callback_query(call.id, "Ошибка при возврате к списку.")


# ==================== АНИМАЦИЯ ЗАГРУЗКИ ====================

def animate_loading(chat_id, base_text="Обработка", cycles=2, delay=0.5, final_text=None, auto_delete=True):
    """
    Универсальная функция для красивой анимации с точками.
    """
    msg = bot.send_message(chat_id, base_text)
    dots_variants = [".", "..", "..."]

    try:
        for _ in range(cycles):
            for dots in dots_variants:
                bot.edit_message_text(
                    f"{base_text}{dots}",
                    chat_id,
                    msg.message_id
                )
                time.sleep(delay)
        
        # Если указан финальный текст — показываем его
        if final_text:
            bot.edit_message_text(final_text, chat_id, msg.message_id)
            time.sleep(1.2)  # даём пользователю прочитать
        
        # Удаляем сообщение, если нужно
        if auto_delete:
            time.sleep(0.5)
            bot.delete_message(chat_id, msg.message_id)

    except Exception as e:
        logging.warning(f"Ошибка в animate_loading для {chat_id}: {e}")
        # На случай, если сообщение уже удалено или ошибка API — просто продолжаем
        try:
            if auto_delete:
                bot.delete_message(chat_id, msg.message_id)
        except:
            pass


# ==================== ЗАПУСК ====================

if __name__ == '__main__':
    try:
        bot.remove_webhook()
        time.sleep(0.5)
        logging.info("Вебхук удалён, можно использовать polling")
    except Exception as e:
        logging.warning(f"Не удалось удалить вебхук: {e}")

    try:
        bot.set_my_commands([
            BotCommand("start", "Главное меню и регистрация"),
            BotCommand("digest", "Получить ежедневный дайджест"),
            BotCommand("daily", "Заполнить daily опрос (для dev/QA)"),
            BotCommand("summary", "Персональная сводка (для dev/QA)"),
            BotCommand("onboarding", "Важная информация для новичков"),
            BotCommand("profile", "Мой профиль"),
            BotCommand("task", "Мои текущие задачи в работе"),
        ])
        logging.info("Команды меню успешно установлены")
    except Exception as e:
        logging.warning(f"Не удалось установить команды меню: {e}")
        logging.warning("Проверь токен! Если ошибка 401 — токен неверный или отозван.")

    scheduler = BackgroundScheduler(timezone="UTC")

    # Ежедневно в 9:00 UTC — но внутри функции учитываем пояс пользователя
    scheduler.add_job(daily_prompt_job, 'cron', hour=9, minute=0, id='daily_prompt')
    # Каждый час — напоминания
    scheduler.add_job(hourly_reminder_job, 'interval', hours=1, id='daily_reminder')
    scheduler.start()
    
    logging.info("Планировщик запущен")

    logging.info("Бот запущен!")
    check_daily_on_start()

    while True:
        try:
            bot.infinity_polling(none_stop=True, interval=3)
        except Exception as e:
            logging.error(f"Ошибка polling: {e}")

            time.sleep(15)
