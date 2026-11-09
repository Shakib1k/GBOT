import os
import zipfile
import subprocess
import logging
import random
import string
import threading
import shutil
import gc
import time
import json
import hashlib
from functools import wraps
import requests
from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "").strip() or hashlib.sha256((BOT_TOKEN + ADMIN_PASSWORD).encode()).hexdigest()
ADMIN_ID = 7058712225
BASE_DIR = os.getcwd()
TEMP_DIR = os.path.join(BASE_DIR, "temp")
DB_FILE = os.environ.get("DATABASE_FILE", os.path.join(BASE_DIR, "bot_database.json"))
os.makedirs(TEMP_DIR, exist_ok=True)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add BOT_TOKEN in Railway Variables.")
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD is missing. Add ADMIN_PASSWORD in Railway Variables.")

app = Flask(__name__, template_folder='.')
app.secret_key = FLASK_SECRET_KEY
CORS(app)

DB_LOCK = threading.RLock()
active_reaction_apps = {}

DEFAULT_DB = {
    "users": {}, "keys": {}, "history": [], "join_channels": [], "reaction_bots": [],
    "settings": {
        "premium_link": "https://t.me/YourAdminUsername", "trial_credits": 15,
        "trial_wait_time": 30,
        "welcome_text": "👋 **Welcome to the APK Protector Bot!**\n\nPlease login or start a free trial to continue.",
        "trial_btn_text": "🎁 Free Trial", "premium_btn_text": "💎 Buy Premium"
    }
}

def load_db():
    with DB_LOCK:
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for k, v in DEFAULT_DB.items():
                    if k not in data: data[k] = v.copy() if isinstance(v, dict) else list(v)
                for k, v in DEFAULT_DB['settings'].items(): data['settings'].setdefault(k, v)
                return data
            except Exception as e:
                logger.error('Database load failed: %s', e)
        return json.loads(json.dumps(DEFAULT_DB, ensure_ascii=False))

db = load_db()

def save_db():
    with DB_LOCK:
        tmp = DB_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DB_FILE)

def gen_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        return fn(*args, **kwargs)
    return wrapper

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    password = str((request.json or {}).get('password', ''))
    if password != ADMIN_PASSWORD:
        return jsonify({'success': False, 'message': 'Wrong password'}), 401
    session['admin_logged_in'] = True
    return jsonify({'success': True})

@app.route('/api/logout', methods=['POST'])
@require_login
def api_logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/auth_status')
def auth_status():
    return jsonify({'logged_in': bool(session.get('admin_logged_in'))})

@app.route('/api/get_users')
@require_login
def get_users():
    return jsonify([{"key": k, "user_id": v.get("user_id"), "credits": v.get("credits"), "used": v.get("used", False)} for k, v in db["keys"].items()])

@app.route('/api/get_trial_users')
@require_login
def get_trial_users():
    return jsonify([{"user_id": uid, "credits": d.get("credits")} for uid, d in db["users"].items() if d.get("trial_used")])

@app.route('/api/get_history')
@require_login
def get_history():
    return jsonify(db["history"])

@app.route('/api/get_settings')
@require_login
def get_settings():
    safe_bots = []
    for rb in db['reaction_bots']:
        safe = dict(rb)
        token = str(safe.get('token', ''))
        safe['token_masked'] = token[:8] + '...' + token[-5:] if len(token) > 15 else '••••••'
        safe.pop('token', None)
        safe_bots.append(safe)
    return jsonify({"settings": db["settings"], "channels": db["join_channels"], "reaction_bots": safe_bots})

@app.route('/api/update_settings', methods=['POST'])
@require_login
def update_settings():
    data = request.json or {}
    db["settings"].update(data)
    save_db()
    return jsonify({"success": True})

@app.route('/api/add_channel', methods=['POST'])
@require_login
def add_channel():
    data = request.json or {}
    db["join_channels"].append({"name": data.get("name"), "link": data.get("link"), "type": data.get("type"), "chat_id": data.get("chat_id", "")})
    save_db()
    return jsonify({"success": True})

@app.route('/api/delete_channel', methods=['POST'])
@require_login
def delete_channel():
    index = int((request.json or {}).get("index", -1))
    if 0 <= index < len(db["join_channels"]): db["join_channels"].pop(index)
    save_db()
    return jsonify({"success": True})

@app.route('/api/create_user', methods=['POST'])
@require_login
def create_user():
    data = request.json or {}
    uid, credits, key = str(data.get('user_id')), int(data.get('credits', 0)), data.get('key') or gen_key()
    db["keys"][key] = {"user_id": uid, "credits": credits, "used": False}
    save_db()
    return jsonify({"success": True, "key": key})

@app.route('/api/edit_key', methods=['POST'])
@require_login
def edit_key():
    data = request.json or {}
    old_key, new_key, credits = data.get('old_key'), data.get('new_key'), int(data.get('credits', 0))
    if old_key in db["keys"]:
        if new_key and new_key != old_key:
            db["keys"][new_key] = db["keys"].pop(old_key)
        else: new_key = old_key
        db["keys"][new_key]["credits"] = credits
        save_db()
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/api/delete_key', methods=['POST'])
@require_login
def delete_key():
    key = (request.json or {}).get('key')
    db["keys"].pop(key, None)
    save_db()
    return jsonify({"success": True})

# ==================== ROBUST REACTION BOT ====================

def normalize_channel_id(value):
    raw = str(value or '').strip()
    if raw.startswith('@'):
        return raw
    if raw.startswith('-100') and raw[4:].isdigit():
        return raw
    if raw.startswith('-') and raw[1:].isdigit():
        return raw
    if raw.isdigit():
        return '-100' + raw if not raw.startswith('100') else '-' + raw
    return raw

def telegram_api(token, method, payload=None, timeout=12):
    url = f'https://api.telegram.org/bot{token}/{method}'
    try:
        r = requests.post(url, json=payload or {}, timeout=timeout)
        try: data = r.json()
        except Exception: data = {'ok': False, 'description': r.text}
        return data
    except Exception as e:
        return {'ok': False, 'description': str(e)}

def verify_reaction_bot(token, channel_id):
    me = telegram_api(token, 'getMe', {})
    if not me.get('ok'):
        return False, 'Invalid bot token: ' + str(me.get('description', 'Unknown error'))
    bot_id = me['result']['id']
    chat = telegram_api(token, 'getChat', {'chat_id': channel_id})
    if not chat.get('ok'):
        return False, 'Channel ID is invalid or this bot cannot access the channel: ' + str(chat.get('description', 'Unknown error'))
    member = telegram_api(token, 'getChatMember', {'chat_id': channel_id, 'user_id': bot_id})
    if not member.get('ok'):
        return False, 'Could not check bot membership: ' + str(member.get('description', 'Unknown error'))
    status = member.get('result', {}).get('status')
    if status not in ('administrator', 'creator'):
        return False, f'Bot is not an administrator in this channel (status: {status}).'
    return True, f"Verified @{me['result'].get('username','')} as {status} in {chat['result'].get('title', channel_id)}"

@app.route('/api/add_reaction_bot', methods=['POST'])
@require_login
def add_reaction_bot():
    data = request.json or {}
    token = str(data.get('token', '')).strip()
    channel_id = normalize_channel_id(data.get('channel_id'))
    emojis = str(data.get('emojis', '')).strip()
    if not token or not channel_id or not emojis:
        return jsonify({'success': False, 'message': 'Bot token, Channel ID and emoji are required.'}), 400
    if token == BOT_TOKEN:
        return jsonify({'success': False, 'message': 'Use a separate reaction-bot token. The main bot cannot run a second polling worker with the same token.'}), 400
    ok, msg = verify_reaction_bot(token, channel_id)
    if not ok:
        return jsonify({'success': False, 'message': msg}), 400
    emoji_list = [x.strip() for x in emojis.split(',') if x.strip()]
    with DB_LOCK:
        existing = next((x for x in db['reaction_bots'] if x.get('token') == token and str(x.get('channel_id')) == str(channel_id)), None)
        item = {'token': token, 'channel_id': channel_id, 'emojis': ', '.join(emoji_list)}
        if existing: existing.update(item)
        else: db['reaction_bots'].append(item)
        save_db()
    start_single_reaction_bot(token, channel_id, item['emojis'])
    return jsonify({'success': True, 'message': msg})

@app.route('/api/delete_reaction_bot', methods=['POST'])
@require_login
def delete_reaction_bot():
    index = int((request.json or {}).get('index', -1))
    if 0 <= index < len(db['reaction_bots']):
        bot_data = db['reaction_bots'].pop(index)
        stop_single_reaction_bot(bot_data.get('token'))
        save_db()
    return jsonify({'success': True})

def _react_message(token, channel_id, message_id, emoji):
    time.sleep(random.uniform(1.0, 2.5))
    result = telegram_api(token, 'setMessageReaction', {
        'chat_id': channel_id,
        'message_id': message_id,
        'reaction': [{'type': 'emoji', 'emoji': emoji}],
        'is_big': False
    })
    if not result.get('ok'):
        logger.error('REACTION FAILED bot=%s channel=%s msg=%s emoji=%s: %s', token[:10], channel_id, message_id, emoji, result.get('description'))
    else:
        logger.info('REACTION OK channel=%s msg=%s emoji=%s', channel_id, message_id, emoji)


def run_reaction_bot_sync(token, stop_event):
    """Independent Telegram Bot API long-poll worker.
    It listens only for channel_post / edited_channel_post updates, so it does
    not depend on python-telegram-bot's ReactionType classes or message filters.
    """
    offset = 0
    logger.info('Reaction worker starting for token=%s', token[:10])
    while not stop_event.is_set():
        try:
            result = telegram_api(token, 'getUpdates', {
                'offset': offset,
                'timeout': 30,
                'allowed_updates': ['channel_post', 'edited_channel_post']
            }, timeout=40)
            if not result.get('ok'):
                logger.error('Reaction getUpdates failed for %s: %s', token[:10], result.get('description'))
                time.sleep(3)
                continue
            for upd in result.get('result', []):
                offset = max(offset, int(upd.get('update_id', 0)) + 1)
                post = upd.get('channel_post') or upd.get('edited_channel_post')
                if not post:
                    continue
                channel_id = str(post.get('chat', {}).get('id'))
                configured = [x for x in db.get('reaction_bots', []) if str(x.get('channel_id')) == channel_id and x.get('token') == token]
                if not configured:
                    continue
                for rb in configured:
                    emojis = [x.strip() for x in str(rb.get('emojis', '')).split(',') if x.strip()]
                    if emojis:
                        threading.Thread(
                            target=_react_message,
                            args=(token, channel_id, int(post.get('message_id')), emojis[0]),
                            daemon=True
                        ).start()
        except Exception as e:
            logger.exception('Reaction worker error for %s: %s', token[:10], e)
            time.sleep(3)
    logger.info('Reaction worker stopped for token=%s', token[:10])


def start_single_reaction_bot(token, channel_id, emojis):
    if token in active_reaction_apps:
        return
    stop_event = threading.Event()
    thread = threading.Thread(target=run_reaction_bot_sync, args=(token, stop_event), daemon=True, name=f'reaction-{token[:8]}')
    active_reaction_apps[token] = {
        'thread': thread,
        'stop_event': stop_event,
        'channel_id': channel_id,
        'emojis': emojis
    }
    thread.start()
    logger.info('Reaction bot registered for channel=%s', channel_id)


def stop_single_reaction_bot(token):
    worker = active_reaction_apps.pop(token, None)
    if worker:
        worker['stop_event'].set()

# ==================== APK BOT LOGIC ====================
async def check_channels(user_id, context):
    not_joined = []
    for ch in db['join_channels']:
        if ch.get('chat_id'):
            try:
                member = await context.bot.get_chat_member(chat_id=ch['chat_id'], user_id=user_id)
                if member.status in ['left', 'kicked']: not_joined.append(ch)
            except: not_joined.append(ch)
    return not_joined

async def send_welcome(update, context):
    user_id = str(update.effective_user.id)
    user = db['users'].get(user_id)
    if user and user.get('is_logged_in') and user.get('credits', 0) > 0:
        await show_main_menu(update, context, user['credits']); return
    if user and user.get('trial_used'):
        keyboard = [[InlineKeyboardButton('🔑 Login with Key', callback_data='user_login')], [InlineKeyboardButton(db['settings']['premium_btn_text'], url=db['settings']['premium_link'])]]
        text = '👋 Welcome back!\n\nYou have already used your free trial. Please login or buy premium.'
    else:
        keyboard = [[InlineKeyboardButton(db['settings']['trial_btn_text'], callback_data='free_trial')], [InlineKeyboardButton('🔑 Login with Key', callback_data='user_login')], [InlineKeyboardButton(db['settings']['premium_btn_text'], url=db['settings']['premium_link'])]]
        text = db['settings']['welcome_text']
    if update.callback_query: await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def start(update, context):
    context.user_data.clear()
    not_joined = await check_channels(str(update.effective_user.id), context)
    if not_joined:
        buttons = [[InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch['link'])] for ch in not_joined if ch.get('link')]
        buttons.append([InlineKeyboardButton('✅ Verify Joined', callback_data='verify_join')])
        await update.message.reply_text('⚠️ **Please join our channels to use this bot!**', reply_markup=InlineKeyboardMarkup(buttons))
        return
    await send_welcome(update, context)

async def show_main_menu(update, context, credits):
    keyboard = [[InlineKeyboardButton(f'🛡️ Protect APK (Credits: {credits})', callback_data='protect')]]
    text = f'✅ **Login Successful!**\n\n💳 **Your Credits:** {credits}'
    if update.callback_query: await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_text(update, context):
    user_id, text = str(update.effective_user.id), update.message.text.strip()
    if context.user_data.get('awaiting_key'):
        key_data = db['keys'].get(text)
        if key_data and str(key_data['user_id']) == user_id and not key_data['used']:
            db['users'][user_id] = {'key': text, 'credits': key_data['credits'], 'is_logged_in': True, 'trial_used': db['users'].get(user_id, {}).get('trial_used', False)}
            db['keys'][text]['used'] = True
            context.user_data['awaiting_key'] = False
            save_db()
            await update.message.reply_text(f'🎉 **Login Successful!**\nYou have {key_data["credits"]} credits.')
            await show_main_menu(update, context, key_data['credits'])
        else: await update.message.reply_text('❌ Invalid Key or already used.')

async def handle_callbacks(update, context):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    if query.data == 'verify_join':
        if not await check_channels(user_id, context):
            await query.edit_message_text('✅ **Verification Successful!**')
            await send_welcome(update, context)
        else: await query.edit_message_text("❌ You haven't joined all channels yet.")
    elif query.data == 'free_trial':
        user = db['users'].get(user_id, {})
        if user.get('trial_used'): return await query.edit_message_text('❌ You have already used your free trial.')
        db['users'][user_id] = {'credits': db['settings']['trial_credits'], 'is_logged_in': True, 'trial_used': True, 'last_protect_time': 0}
        save_db()
        await query.edit_message_text(f"🎁 **Free Trial Activated!**\n\nYou have {db['settings']['trial_credits']} credits.")
        await show_main_menu(update, context, db['settings']['trial_credits'])
    elif query.data == 'user_login':
        context.user_data['awaiting_key'] = True
        await query.edit_message_text('🔑 **Please enter your Key to login:**\n\n(Example: `ABCD123456`)')
    elif query.data == 'protect':
        await query.edit_message_text('📤 **Please send the APK file** you want to protect.')

async def handle_document(update, context):
    user_id, document = str(update.effective_user.id), update.message.document
    if not document.file_name.endswith('.apk'): return await update.message.reply_text('❌ Please send a valid APK file.')
    user = db['users'].get(user_id)
    if not user or user.get('credits', 0) <= 0: return await update.message.reply_text('❌ Not enough credits or not logged in.')
    if user.get('trial_used') and 'last_protect_time' in user:
        rem = (db['settings']['trial_wait_time'] * 60) - (time.time() - user['last_protect_time'])
        if rem > 0: return await update.message.reply_text(f"⏳ **Trial Limit:** Please wait **{int(rem//60)}m {int(rem%60)}s** before protecting another APK.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('💎 Buy Premium', url=db['settings']['premium_link'])]]))
    context.user_data.update({'apk_id': document.file_id, 'apk_name': document.file_name})
    keyboard = [[InlineKeyboardButton('Google', callback_data='prot_google')], [InlineKeyboardButton('Tencent', callback_data='prot_tencent')], [InlineKeyboardButton('360', callback_data='prot_360')], [InlineKeyboardButton('Arm', callback_data='prot_arm')], [InlineKeyboardButton('Skip', callback_data='prot_skip')]]
    await update.message.reply_text('🛡️ **Which protection do you want to apply?**', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_protection(update, context):
    query = update.callback_query
    await query.answer()
    choice, user_id = query.data, str(query.from_user.id)
    file_id, apk_name = context.user_data.get('apk_id'), context.user_data.get('apk_name')
    if not file_id: return await query.edit_message_text('❌ Session expired. Please send the APK again.')
    file = await context.bot.get_file(file_id)
    input_path = os.path.join(TEMP_DIR, apk_name)
    await file.download_to_drive(input_path)
    eta = '2-3 mins' if os.path.getsize(input_path)/(1024*1024) < 5 else '4-6 mins'
    progress_msg = await query.edit_message_text(f'⏳ **Processing APK...**\n\n[□□□□□□□□□□] 0%\n⏱️ **Target Time: {eta}**')
    executable_dir = os.path.join(BASE_DIR, 'executable')
    try:
        if not os.path.exists(executable_dir):
            shell_zip = os.path.join(BASE_DIR, 'dpt-shell-v2.21.1.zip')
            if not os.path.exists(shell_zip): raise FileNotFoundError('dpt-shell-v2.21.1.zip not found in project')
            with zipfile.ZipFile(shell_zip, 'r') as z: z.extractall(BASE_DIR)
        output_name = apk_name.replace('.apk', '_signed.apk')
        generated_file = os.path.join(executable_dir, output_name)
        await progress_msg.edit_text(f'⏳ **Processing APK...**\n\n[■■■□□□□□□□] 30%\n⏱️ **Target Time: {eta}**')
        subprocess.run(['java', '-Xmx512m', '-jar', os.path.join(executable_dir, 'dpt.jar'), '-f', input_path], cwd=executable_dir, capture_output=True, text=True, timeout=600)
        if os.path.exists(generated_file):
            zip_map = {'prot_google':'google.zip','prot_tencent':'腾讯御安全.zip','prot_360':'360.zip','prot_arm':'arm.zip'}
            if choice in zip_map:
                zip_path = os.path.join(BASE_DIR, zip_map[choice])
                if os.path.exists(zip_path):
                    temp_zip = generated_file + '.zip'; os.rename(generated_file, temp_zip)
                    extract_dir = os.path.join(TEMP_DIR, 'inject_lib'); os.makedirs(extract_dir, exist_ok=True)
                    with zipfile.ZipFile(zip_path, 'r') as z: z.extractall(extract_dir)
                    with zipfile.ZipFile(temp_zip, 'a', zipfile.ZIP_DEFLATED) as z:
                        for root, _, files in os.walk(extract_dir):
                            for f in files:
                                if f.endswith('.so'): z.write(os.path.join(root, f), arcname=f'assets/{f}')
                    os.rename(temp_zip, generated_file); shutil.rmtree(extract_dir, ignore_errors=True)
            await progress_msg.edit_text('✅ **Processing Complete!**\n\n[■■■■■■■■■■] 100%')
            with open(generated_file, 'rb') as fh: await query.message.reply_document(document=fh, filename=output_name, caption=f'✅ **Protected Successfully!**\nType: {choice}')
            db['users'][user_id]['credits'] -= 1
            if db['users'][user_id].get('trial_used'): db['users'][user_id]['last_protect_time'] = time.time()
            db['history'].append({'tg_id': user_id, 'apk_name': output_name, 'type': choice})
            save_db()
            await query.message.reply_text(f"💳 Remaining Credits: {db['users'][user_id]['credits']}")
            os.remove(generated_file); os.remove(input_path); gc.collect()
        else: await progress_msg.edit_text('❌ Protection failed. Memory issue or unsupported APK.')
    except Exception as e:
        logger.exception('APK protection error')
        await progress_msg.edit_text('❌ Error occurred during protection. Check server logs.')


def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), threaded=True)

def main():
    threading.Thread(target=run_flask, daemon=True, name='web').start()
    for rb in list(db.get('reaction_bots', [])):
        try:
            ok, msg = verify_reaction_bot(rb.get('token'), normalize_channel_id(rb.get('channel_id')))
            if ok:
                start_single_reaction_bot(rb['token'], normalize_channel_id(rb['channel_id']), rb.get('emojis',''))
            else:
                logger.error('Saved reaction bot verification failed: %s', msg)
        except Exception as e:
            logger.error('Could not restore reaction bot: %s', e)
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler('start', start))
    app_bot.add_handler(CallbackQueryHandler(handle_callbacks, pattern='^(verify_join|free_trial|user_login|protect)$'))
    app_bot.add_handler(CallbackQueryHandler(handle_protection, pattern='^prot_'))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app_bot.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    logger.info('Main Bot and Web Server are running...')
    app_bot.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
