import telebot
from telebot import types
import sqlite3
import random
import string
import requests

# --- НАСТРОЙКИ ---
BOT_TOKEN = '8693826106:AAHpDM2dhyB1tSnhAJbNtx62rNYmgvkWTxY' # Замените на ваш токен от @BotFather
MAIN_ADMIN = 'iootbox'        # Главный админ (без @)
PASTEBIN_API_KEY = 'eqZXUzvpOVb7rnh2-jIK5cqDTImGs4bT'  # Ваш API ключ Pastebin

bot = telebot.TeleBot(BOT_TOKEN)

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
def init_db():
    conn = sqlite3.connect('filebot.db')
    cursor = conn.cursor()
    # Таблица файлов
    cursor.execute('''CREATE TABLE IF NOT EXISTS files 
                      (code TEXT PRIMARY KEY, file_id TEXT, file_type TEXT, description TEXT, password TEXT, uploader_id INTEGER, uploader_username TEXT)''')
    # Таблица админов
    cursor.execute('''CREATE TABLE IF NOT EXISTS admins (username TEXT PRIMARY KEY)''')
    # Таблица каналов для обязательной подписки
    cursor.execute('''CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY, url TEXT)''')
    conn.commit()
    conn.close()

init_db()

# Словарь для временного хранения состояний пользователей
user_states = {}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def upload_to_pastebin(paste_text, api_dev_key=PASTEBIN_API_KEY):
    """
    Отправляет текст в Pastebin и возвращает ссылку на raw-версию.
    """
    if not api_dev_key:
        return None
    
    url = "https://pastebin.com/api/api_post.php"
    
    data = {
        'api_dev_key': api_dev_key,
        'api_paste_code': paste_text,
        'api_option': 'paste',
        'api_paste_name': 'files_list.txt',
        'api_paste_format': 'text'
    }
    
    try:
        response = requests.post(url, data=data, timeout=10)
        
        if response.status_code == 200 and response.text.startswith("https://pastebin.com/"):
            paste_url = response.text.strip()
            # Преобразуем в raw-ссылку
            paste_code = paste_url.split("/")[-1]
            raw_url = f"https://pastebin.com/raw/{paste_code}"
            return raw_url
        else:
            return None
    except Exception:
        return None

def get_all_files_list():
    """Получает список всех файлов из БД в форматированном виде"""
    conn = sqlite3.connect('filebot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT code, file_id, file_type, description, password, uploader_id, uploader_username FROM files ORDER BY uploader_id')
    files = cursor.fetchall()
    conn.close()
    
    if not files:
        return "📂 Список файлов пуст."
    
    result = "📁 СПИСОК ВСЕХ ФАЙЛОВ:\n\n"
    for code, file_id, file_type, description, password, uploader_id, uploader_username in files:
        result += f"🔑 Код: {code}\n"
        result += f"📎 Тип: {file_type}\n"
        result += f"🆔 ID файла: {file_id}\n"
        result += f"📝 Описание: {description or 'Нет'}\n"
        result += f"🔒 Пароль: {password or 'Нет'}\n"
        result += f"👤 Юзернейм создателя: {uploader_username or 'Неизвестен'}\n"
        result += f"🆔 ID создателя: {uploader_id}\n"
        result += "-" * 30 + "\n"
    
    return result

def is_admin(username):
    if username and username.lower() == MAIN_ADMIN.lower():
        return True
    if not username:
        return False
    conn = sqlite3.connect('filebot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT username FROM admins WHERE username=?', (username.lower(),))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def is_main_admin(username):
    return username and username.lower() == MAIN_ADMIN.lower()

def generate_random_code():
    return str(random.randint(1000, 99999999))

def check_subscription(user_id):
    conn = sqlite3.connect('filebot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT channel_id, url FROM channels')
    channels = cursor.fetchall()
    conn.close()

    unsubbed = []
    for ch_id, url in channels:
        try:
            status = bot.get_chat_member(ch_id, user_id).status
            if status in ['left', 'kicked']:
                unsubbed.append(url)
        except Exception:
            # Если бот не админ в канале или канал не существует
            pass 
    return unsubbed

def get_main_menu(username):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('📥 Добавить файл'), types.KeyboardButton('📤 Скачать файл'))
    if is_admin(username):
        markup.add(types.KeyboardButton('🛠 Панель управления'))
    return markup

# --- ОБРАБОТЧИКИ ---

@bot.message_handler(commands=['start'])
def start_command(message):
    unsubbed = check_subscription(message.from_user.id)
    if unsubbed:
        markup = types.InlineKeyboardMarkup()
        for i, url in enumerate(unsubbed):
            markup.add(types.InlineKeyboardButton(f"Подписаться на канал {i+1}", url=url))
        markup.add(types.InlineKeyboardButton("✅ Я подписался", callback_data="check_sub"))
        bot.send_message(message.chat.id, "❌ Для использования бота необходимо подписаться на наши каналы:", reply_markup=markup)
        return

    args = message.text.split()
    if len(args) >= 2:
        code = args[1]
        password = args[2] if len(args) > 2 else None
        # Проверяем, есть ли у файла пароль
        conn = sqlite3.connect('filebot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT password FROM files WHERE code=?', (code,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] and password is None:
            # У файла есть пароль, но пароль не введен — запрашиваем
            user_states[message.chat.id] = {'code': code}
            bot.send_message(message.chat.id, "🔒 Этот файл защищен паролем. Введите пароль:")
            bot.register_next_step_handler(message, ask_password_for_code)
        else:
            # Либо пароля нет, либо он введен
            process_download(message.chat.id, code, password)
    else:
        bot.send_message(message.chat.id, "👋 Добро пожаловать в файлообменник!", reply_markup=get_main_menu(message.from_user.username))

def ask_password_for_code(message):
    """Запрашивает пароль, если пользователь ввел только код через /start"""
    chat_id = message.chat.id
    state = user_states.get(chat_id, {})
    code = state.get('code')
    
    if not code:
        bot.send_message(chat_id, "❌ Ошибка: код не найден. Попробуйте снова через /start <код>")
        return
    
    password = message.text.strip()
    process_download(chat_id, code, password)
    user_states.pop(chat_id, None)

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def callback_check_sub(call):
    unsubbed = check_subscription(call.from_user.id)
    if not unsubbed:
        bot.answer_callback_query(call.id, "✅ Подписка подтверждена!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "Доступ открыт!", reply_markup=get_main_menu(call.from_user.username))
    else:
        bot.answer_callback_query(call.id, "❌ Вы подписались не на все каналы!", show_alert=True)

# --- ЛОГИКА СКАЧИВАНИЯ ---

@bot.message_handler(func=lambda m: m.text == '📤 Скачать файл')
def download_menu(message):
    bot.send_message(message.chat.id, "Введите код файла (и пароль через пробел, если есть):", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(message, process_download_step)

def process_download_step(message):
    args = message.text.split()
    if not args:
        return bot.send_message(message.chat.id, "Код не распознан.", reply_markup=get_main_menu(message.from_user.username))
    code = args[0]
    password = args[1] if len(args) > 1 else None
    process_download(message.chat.id, code, password)

def process_download(chat_id, code, password):
    conn = sqlite3.connect('filebot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT file_id, file_type, description, password FROM files WHERE code=?', (code,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        bot.send_message(chat_id, "❌ Файл с таким кодом не найден.", reply_markup=get_main_menu(None))
        return

    file_id, file_type, desc, real_password = row

    # Если у файла есть пароль
    if real_password:
        if password != real_password:
            # Сохраняем код и запрашиваем пароль
            user_states[chat_id] = {'code': code}
            msg = bot.send_message(chat_id, "🔒 Введите пароль:")
            bot.register_next_step_handler(msg, ask_password_callback)
            return

    # Отправляем файл (если пароля нет или он верный)
    caption = f"📝 *Описание:* {desc}" if desc else ""
    try:
        if file_type == 'document':
            bot.send_document(chat_id, file_id, caption=caption, parse_mode="Markdown")
        elif file_type == 'photo':
            bot.send_photo(chat_id, file_id, caption=caption, parse_mode="Markdown")
        elif file_type == 'video':
            bot.send_video(chat_id, file_id, caption=caption, parse_mode="Markdown")
        bot.send_message(chat_id, "✅ Файл отправлен!", reply_markup=get_main_menu(None))
    except Exception as e:
        bot.send_message(chat_id, "❌ Ошибка при отправке файла.")

def ask_password_callback(message):
    """Callback для получения пароля"""
    chat_id = message.chat.id
    state = user_states.get(chat_id, {})
    code = state.get('code')
    
    if not code:
        bot.send_message(chat_id, "❌ Ошибка: код не найден. Попробуйте снова.")
        return
    
    password = message.text.strip()
    user_states.pop(chat_id, None)
    process_download(chat_id, code, password)

# --- АДМИН-КОМАНДЫ ---

@bot.message_handler(commands=['files'])
def send_files_list(message):
    """Команда для админов - получить список всех файлов в Pastebin"""
    if not is_admin(message.from_user.username):
        bot.send_message(message.chat.id, "❌ У вас нет прав для этой команды.")
        return
    
    # Отправляем уведомление о начале обработки
    status_msg = bot.send_message(message.chat.id, "⏳ Собираю список файлов и загружаю в Pastebin...")
    
    # Получаем список файлов
    files_text = get_all_files_list()
    
    if files_text == "📂 Список файлов пуст.":
        bot.edit_message_text(files_text, message.chat.id, status_msg.message_id)
        return
    
    # Загружаем в Pastebin
    raw_url = upload_to_pastebin(files_text)
    
    if raw_url:
        # Формируем сообщение с ссылкой
        response_text = f"✅ Список всех файлов успешно загружен!\n\n🔗 Ссылка: {raw_url}\n\n📊 Статистика: файлов найдено - {files_text.count('🔑 Код:')}"
        bot.edit_message_text(response_text, message.chat.id, status_msg.message_id)
    else:
        # Если не удалось загрузить в Pastebin, отправляем текстом
        if len(files_text) <= 4000:
            bot.edit_message_text(files_text, message.chat.id, status_msg.message_id)
        else:
            # Если текст слишком длинный, разбиваем на части
            bot.edit_message_text("❌ Не удалось загрузить в Pastebin. Отправляю частями:", message.chat.id, status_msg.message_id)
            for i in range(0, len(files_text), 3000):
                bot.send_message(message.chat.id, files_text[i:i+3000], disable_web_page_preview=True)

@bot.message_handler(commands=['delete'])
def admin_delete(message):
    if not is_admin(message.from_user.username): return
    args = message.text.split()
    if len(args) < 2: return
    conn = sqlite3.connect('filebot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM files WHERE code=?', (args[1],))
    conn.commit()
    bot.send_message(message.chat.id, f"Результат: удалено {cursor.rowcount} шт.")
    conn.close()

@bot.message_handler(commands=['add_admin', 'del_admin'])
def manage_admins(message):
    if not is_main_admin(message.from_user.username): return
    args = message.text.split()
    if len(args) < 2: return
    user = args[1].replace('@', '').lower()
    conn = sqlite3.connect('filebot.db')
    cursor = conn.cursor()
    if 'add' in message.text:
        cursor.execute('INSERT OR IGNORE INTO admins VALUES (?)', (user,))
        bot.send_message(message.chat.id, f"✅ {user} теперь админ.")
    else:
        cursor.execute('DELETE FROM admins WHERE username=?', (user,))
        bot.send_message(message.chat.id, f"❌ {user} больше не админ.")
    conn.commit()
    conn.close()

@bot.message_handler(commands=['add_channel', 'del_channel'])
def manage_channels(message):
    if not is_main_admin(message.from_user.username): return
    args = message.text.split()
    conn = sqlite3.connect('filebot.db')
    cursor = conn.cursor()
    if 'add' in message.text and len(args) >= 3:
        cursor.execute('INSERT OR REPLACE INTO channels VALUES (?, ?)', (args[1], args[2]))
        bot.send_message(message.chat.id, "✅ Канал добавлен.")
    elif 'del' in message.text and len(args) >= 2:
        cursor.execute('DELETE FROM channels WHERE channel_id=?', (args[1],))
        bot.send_message(message.chat.id, "❌ Канал удален.")
    conn.commit()
    conn.close()

@bot.message_handler(func=lambda m: m.text == '🛠 Панель управления' and is_admin(m.from_user.username))
def admin_panel(message):
    text = "🛠 *Панель управления*\n\n`/files` — получить список всех файлов\n`/delete КОД` — удалить файл\n"
    if is_main_admin(message.from_user.username):
        text += "\n👑 *GA Команды:*\n`/add_admin @user` / `/del_admin @user`"
        text += "\n`/add_channel @id link`\n`/del_channel @id`"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# --- ЛОГИКА ЗАГРУЗКИ ---

@bot.message_handler(func=lambda m: m.text == '📥 Добавить файл')
def add_file_menu(message):
    if check_subscription(message.from_user.id):
        return start_command(message)
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('❌ Отмена'))
    bot.send_message(message.chat.id, "Прикрепите файл, фото или видео:", reply_markup=markup)
    user_states[message.chat.id] = {}
    bot.register_next_step_handler(message, receive_file)

def receive_file(message):
    if message.text == '❌ Отмена':
        return bot.send_message(message.chat.id, "Отменено.", reply_markup=get_main_menu(message.from_user.username))

    f_id, f_type = None, None
    if message.document: f_id, f_type = message.document.file_id, 'document'
    elif message.photo: f_id, f_type = message.photo[-1].file_id, 'photo'
    elif message.video: f_id, f_type = message.video.file_id, 'video'
    
    if not f_id:
        bot.send_message(message.chat.id, "Пожалуйста, отправьте именно файл/фото/видео.")
        bot.register_next_step_handler(message, receive_file)
        return

    username = message.from_user.username or f"user_{message.from_user.id}"
    user_states[message.chat.id] = {
        'file_id': f_id, 
        'file_type': f_type, 
        'desc': message.caption or "",
        'uploader_username': username
    }
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('Пропустить'), types.KeyboardButton('❌ Отмена'))
    
    if message.caption:
        bot.send_message(message.chat.id, f"Описание взято из подписи. Введите пароль (или 'Пропустить'):", reply_markup=markup)
        bot.register_next_step_handler(message, receive_password)
    else:
        bot.send_message(message.chat.id, "Введите описание файла (или 'Пропустить'):", reply_markup=markup)
        bot.register_next_step_handler(message, receive_description)

def receive_description(message):
    if message.text == '❌ Отмена': return bot.send_message(message.chat.id, "Отменено.", reply_markup=get_main_menu(message.from_user.username))
    if message.text != 'Пропустить': user_states[message.chat.id]['desc'] = message.text
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('Пропустить'), types.KeyboardButton('❌ Отмена'))
    bot.send_message(message.chat.id, "Введите пароль (или 'Пропустить'):", reply_markup=markup)
    bot.register_next_step_handler(message, receive_password)

def receive_password(message):
    if message.text == '❌ Отмена': return bot.send_message(message.chat.id, "Отменено.", reply_markup=get_main_menu(message.from_user.username))
    user_states[message.chat.id]['password'] = None if message.text == 'Пропустить' else message.text

    if is_admin(message.from_user.username):
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton('Сгенерировать случайно'), types.KeyboardButton('❌ Отмена'))
        bot.send_message(message.chat.id, "Введите кастомный код (4-10 симв.) или нажмите кнопку:", reply_markup=markup)
        bot.register_next_step_handler(message, receive_custom_code)
    else:
        finish_upload(message, generate_random_code())

def receive_custom_code(message):
    if message.text == '❌ Отмена': return bot.send_message(message.chat.id, "Отменено.", reply_markup=get_main_menu(message.from_user.username))
    if message.text == 'Сгенерировать случайно':
        code = generate_random_code()
    else:
        code = message.text.strip()
        if not (4 <= len(code) <= 10) or not code.isalnum():
            bot.send_message(message.chat.id, "Неверный формат. Нужно 4-10 символов (буквы/цифры):")
            bot.register_next_step_handler(message, receive_custom_code)
            return
    finish_upload(message, code)

def finish_upload(message, code):
    chat_id = message.chat.id
    username = message.from_user.username
    data = user_states.get(chat_id)
    if not data: return

    conn = sqlite3.connect('filebot.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO files (code, file_id, file_type, description, password, uploader_id, uploader_username) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (code, data['file_id'], data['file_type'], data['desc'], data['password'], chat_id, data.get('uploader_username', username)))
        conn.commit()
        
        msg = f"✅ Готово!\n\n🔑 Код: `{code}`"
        if data['password']: msg += f"\n🔒 Пароль: `{data['password']}`"
        bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=get_main_menu(username))
    except sqlite3.IntegrityError:
        bot.send_message(chat_id, "❌ Код уже занят. Попробуйте еще раз.", reply_markup=get_main_menu(username))
    finally:
        conn.close()
        user_states.pop(chat_id, None)

if __name__ == '__main__':
    bot.infinity_polling()
