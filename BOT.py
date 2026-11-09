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
import asyncio
import requests
from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, TypeHandler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_ID = 7058712225
BASE_DIR = os.getcwd()
DB_FILE = os.path.join(BASE_DIR, "bot_database.json")
DB_LOCK = threading.RLock()
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# Active reaction bots tracking
active_reaction_apps = {}
# Global asyncio loop reference to safely start new bots from Flask thread
main_event_loop = None

db = {
    "users": {},
    "keys": {},
    "history": [],
    "join_channels": [],
    "reaction_bots": [], # {"token": "...", "channel_id": "...", "emojis": "..."}
    "settings": {
        "premium_link": "https://t.me/YourAdminUsername",
        "trial_credits": 15,
        "trial_wait_time": 30,
        "welcome_text": "👋 **Welcome to the APK Protector Bot!**\n\nPlease login or start a free trial to continue.",
        "trial_btn_text": "🎁 Free Trial",
        "premium_btn_text": "💎 Buy Premium"
    }
}


def load_db():
    global db
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k, v in saved.items():
                    if isinstance(v, dict) and isinstance(db.get(k), dict):
                        db[k].update(v)
                    elif k in db:
                        db[k] = v
    except Exception as e:
        logging.error(f"Database load failed: {e}")

def save_db():
    try:
        tmp = DB_FILE + ".tmp"
        with DB_LOCK:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DB_FILE)
    except Exception as e:
        logging.error(f"Database save failed: {e}")

load_db()

def gen_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

app = Flask(__name__, template_folder='.')
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or hashlib.sha256(f"{BOT_TOKEN}:{ADMIN_PASSWORD}".encode()).hexdigest()
CORS(app, supports_credentials=True)

@app.route('/admin')
def admin_page(): return render_template('admin.html')

@app.post('/api/login')
def admin_login():
    password = (request.json or {}).get("password", "")
    if not ADMIN_PASSWORD:
        return jsonify({"success": False, "message": "ADMIN_PASSWORD is not configured on the server."}), 503
    if password == ADMIN_PASSWORD:
        session["admin"] = True
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Wrong password."}), 401

@app.post('/api/logout')
def admin_logout():
    session.clear()
    return jsonify({"success": True})

@app.before_request
def protect_admin_api():
    if request.path.startswith('/api/') and request.path not in ('/api/login',):
        if not session.get("admin"):
            return jsonify({"success": False, "message": "Unauthorized"}), 401

@app.route('/api/get_users')
def get_users(): return jsonify([{"key": k, "user_id": v.get("user_id"), "credits": v.get("credits"), "used": v.get("used", False)} for k, v in db["keys"].items()])

@app.route('/api/get_trial_users')
def get_trial_users(): return jsonify([{"user_id": uid, "credits": d.get("credits")} for uid, d in db["users"].items() if d.get("trial_used")])

@app.route('/api/get_history')
def get_history(): return jsonify(db["history"])

@app.route('/api/get_settings')
def get_settings(): return jsonify({"settings": db["settings"], "channels": db["join_channels"], "reaction_bots": db["reaction_bots"]})

@app.route('/api/update_settings', methods=['POST'])
def update_settings():
    db["settings"].update(request.json or {})
    save_db()
    return jsonify({"success": True})

@app.route('/api/add_channel', methods=['POST'])
def add_channel():
    data = request.json
    db["join_channels"].append({"name": data.get("name"), "link": data.get("link"), "type": data.get("type"), "chat_id": data.get("chat_id", "")})
    save_db()
    return jsonify({"success": True})

@app.route('/api/delete_channel', methods=['POST'])
def delete_channel():
    index = request.json.get("index")
    if 0 <= index < len(db["join_channels"]): db["join_channels"].pop(index)
    save_db()
    return jsonify({"success": True})

@app.route('/api/create_user', methods=['POST'])
def create_user():
    data = request.json
    uid, credits, key = str(data.get('user_id')), data.get('credits'), data.get('key') or gen_key()
    db["keys"][key] = {"user_id": uid, "credits": credits, "used": False}
    save_db()
    return jsonify({"success": True, "key": key})

@app.route('/api/edit_key', methods=['POST'])
def edit_key():
    data = request.json
    old_key, new_key, credits = data.get('old_key'), data.get('new_key'), int(data.get('credits'))
    if old_key in db["keys"]:
        if new_key and new_key != old_key: db["keys"][new_key] = db["keys"].pop(old_key)
        else: new_key = old_key
        db["keys"][new_key]["credits"] = credits
        save_db()
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/api/delete_key', methods=['POST'])
def delete_key():
    key = request.json.get('key')
    if key in db["keys"]: del db["keys"][key]
    save_db()
    return jsonify({"success": True})

# --- Reaction Bot API ---
@app.route('/api/add_reaction_bot', methods=['POST'])
def add_reaction_bot():
    data = request.json
    token = data.get('token')
    channel_id = data.get('channel_id')
    emojis = data.get('emojis') 
    
    if not token or not channel_id or not emojis:
        return jsonify({"success": False, "message": "All fields are required!"})
    
    try:
        res = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
        if res.status_code != 200 or not res.json().get("ok"):
            return jsonify({"success": False, "message": "Invalid Bot Token!"}), 400

        bot_user_id = res.json()["result"]["id"]
        chat_res = requests.get(f"https://api.telegram.org/bot{token}/getChat?chat_id={channel_id}", timeout=15)
        if chat_res.status_code != 200 or not chat_res.json().get("ok"):
            return jsonify({"success": False, "message": "Channel ID is wrong or the bot cannot access this channel."}), 400

        member_res = requests.get(
            f"https://api.telegram.org/bot{token}/getChatMember",
            params={"chat_id": channel_id, "user_id": bot_user_id},
            timeout=15
        )
        if member_res.status_code != 200 or not member_res.json().get("ok"):
            return jsonify({"success": False, "message": "Bot cannot read its channel membership. Add the bot as an administrator first."}), 400
        status = member_res.json()["result"].get("status")
        if status not in ("administrator", "creator"):
            return jsonify({"success": False, "message": "This bot must be an administrator of the channel."}), 400
    except Exception as e:
        logging.exception("Reaction bot verification failed")
        return jsonify({"success": False, "message": "Network error while verifying the bot/channel."}), 502

    for existing in db["reaction_bots"]:
        if str(existing.get("token")) == str(token) and str(existing.get("channel_id")) == str(channel_id):
            existing["emojis"] = emojis
            save_db()
            return jsonify({"success": True, "message": "Reaction bot updated."})

    db["reaction_bots"].append({"token": token, "channel_id": channel_id, "emojis": emojis})
    save_db()
    
    # নতুন বটটি সাথে সাথে চালু করা
    start_single_reaction_bot(token, channel_id, emojis)
    
    return jsonify({"success": True})

@app.route('/api/delete_reaction_bot', methods=['POST'])
def delete_reaction_bot():
    index = request.json.get("index")
    if 0 <= index < len(db["reaction_bots"]): 
        bot_data = db["reaction_bots"].pop(index)
        save_db()
        token = bot_data.get("token")
        # Keep a listener alive if the same token is still configured for another channel.
        token_still_used = any(str(x.get("token")) == str(token) for x in db["reaction_bots"])
        if not token_still_used and token in active_reaction_apps:
            try:
                active_reaction_apps[token]['stop_event'].set()
                del active_reaction_apps[token]
            except Exception as e:
                logging.error(f"Error stopping bot: {e}")
    return jsonify({"success": True})

def run_flask(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# ==================== REACTION BOT LOGIC ====================
async def auto_react(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = update.channel_post or update.edited_channel_post
    if not post:
        return

    channel_id = str(post.chat_id)
    message_id = post.message_id

    for rb in list(db.get("reaction_bots", [])):
        if str(rb.get("channel_id")) != channel_id:
            continue
        if context.bot.token != rb.get("token"):
            continue

        # Telegram allows a bot to set one reaction on a message.
        emojis = [e.strip() for e in str(rb.get("emojis", "")).split(",") if e.strip()]
        if not emojis:
            logging.warning(f"No emoji configured for reaction bot in {channel_id}")
            continue

        emoji = emojis[0]
        try:
            result = await asyncio.to_thread(
                set_telegram_reaction, rb["token"], channel_id, message_id, emoji
            )
            if not result.get("ok"):
                logging.error(
                    f"Reaction failed: channel={channel_id}, message={message_id}, "
                    f"emoji={emoji}, error={result.get('description')}"
                )
            else:
                logging.info(f"Reaction added: {emoji} -> {channel_id}/{message_id}")
        except Exception as e:
            logging.exception(f"Reaction exception for {channel_id}/{message_id}: {e}")

def set_telegram_reaction(token, channel_id, message_id, emoji):
    url = f"https://api.telegram.org/bot{token}/setMessageReaction"
    payload = {
        "chat_id": channel_id,
        "message_id": message_id,
        "reaction": [{"type": "emoji", "emoji": emoji}],
        "is_big": False,
    }
    try:
        response = requests.post(url, json=payload, timeout=15)
        return response.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}

def run_reaction_bot_sync(token, channel_id, emojis, stop_event):
    try:
        rb_app = Application.builder().token(token).build()
        # MessageHandler(filters.ALL) does not reliably receive channel_post updates.
        # TypeHandler receives the complete Telegram Update, including channel_post.
        rb_app.add_handler(TypeHandler(Update, auto_react))
        logging.info(f"Reaction listener online: channel={channel_id}, emojis={emojis}")
        rb_app.run_polling(drop_pending_updates=False, close_loop=False)
    except Exception as e:
        logging.exception(f"Error in reaction bot thread for {channel_id}: {e}")

def start_single_reaction_bot(token, channel_id, emojis):
    if token in active_reaction_apps:
        return
    try:
        stop_event = threading.Event()
        thread = threading.Thread(
            target=run_reaction_bot_sync,
            args=(token, channel_id, emojis, stop_event),
            daemon=True,
            name=f"reaction-{str(channel_id).replace('-', '_')}"
        )
        thread.start()
        active_reaction_apps[token] = {'thread': thread, 'stop_event': stop_event}
        logging.info(f"Reaction Bot started for channel: {channel_id}")
    except Exception as e:
        logging.exception(f"Failed to start Reaction Bot for {channel_id}: {e}")

# ==================== APK BOT LOGIC ====================
async def check_channels(user_id, context):
    not_joined = []
    for ch in db["join_channels"]:
        if ch.get("chat_id"):
            try:
                member = await context.bot.get_chat_member(chat_id=ch["chat_id"], user_id=user_id)
                if member.status in ['left', 'kicked']: not_joined.append(ch)
            except: not_joined.append(ch)
    return not_joined

async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user = db["users"].get(user_id)
    
    if user and user.get("is_logged_in") and user.get("credits", 0) > 0:
        await show_main_menu(update, context, user['credits']); return

    if user and user.get("trial_used"):
        keyboard = [[InlineKeyboardButton("🔑 Login with Key", callback_data='user_login')], [InlineKeyboardButton(db['settings']['premium_btn_text'], url=db['settings']['premium_link'])]]
        text = "👋 Welcome back!\n\nYou have already used your free trial. Please login or buy premium."
    else:
        keyboard = [[InlineKeyboardButton(db['settings']['trial_btn_text'], callback_data='free_trial')], [InlineKeyboardButton("🔑 Login with Key", callback_data='user_login')], [InlineKeyboardButton(db['settings']['premium_btn_text'], url=db['settings']['premium_link'])]]
        text = db['settings']['welcome_text']

    if update.callback_query: await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    not_joined = await check_channels(str(update.effective_user.id), context)
    if not_joined:
        buttons = [[InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["link"])] for ch in not_joined if ch.get("link")]
        buttons.append([InlineKeyboardButton("✅ Verify Joined", callback_data='verify_join')])
        await update.message.reply_text("⚠️ **Please join our channels to use this bot!**", reply_markup=InlineKeyboardMarkup(buttons))
        return
    await send_welcome(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, credits):
    keyboard = [[InlineKeyboardButton(f"🛡️ Protect APK (Credits: {credits})", callback_data='protect')]]
    text = f"✅ **Login Successful!**\n\n💳 **Your Credits:** {credits}"
    if update.callback_query: await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else: await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, text = str(update.effective_user.id), update.message.text.strip()
    if context.user_data.get('awaiting_key'):
        key_data = db["keys"].get(text)
        if key_data and str(key_data['user_id']) == user_id and not key_data['used']:
            db["users"][user_id] = {"key": text, "credits": key_data['credits'], "is_logged_in": True, "trial_used": db["users"].get(user_id, {}).get("trial_used", False)}
            db["keys"][text]["used"] = True
            save_db()
            context.user_data['awaiting_key'] = False
            await update.message.reply_text(f"🎉 **Login Successful!**\nYou have {key_data['credits']} credits.")
            await show_main_menu(update, context, key_data['credits'])
        else: await update.message.reply_text("❌ Invalid Key or already used.")

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    
    if query.data == 'verify_join':
        if not await check_channels(user_id, context):
            await query.edit_message_text("✅ **Verification Successful!**")
            await send_welcome(update, context)
        else: await query.edit_message_text("❌ You haven't joined all channels yet.")
    
    elif query.data == 'free_trial':
        user = db["users"].get(user_id, {})
        if user.get("trial_used"): return await query.edit_message_text("❌ You have already used your free trial.")
        db["users"][user_id] = {"credits": db["settings"]["trial_credits"], "is_logged_in": True, "trial_used": True, "last_protect_time": 0}
        save_db()
        await query.edit_message_text(f"🎁 **Free Trial Activated!**\n\nYou have {db['settings']['trial_credits']} credits.")
        await show_main_menu(update, context, db["settings"]["trial_credits"])
        
    elif query.data == 'user_login':
        context.user_data['awaiting_key'] = True
        await query.edit_message_text("🔑 **Please enter your Key to login:**\n\n(Example: `ABCD123456`)")
        
    elif query.data == 'protect':
        await query.edit_message_text("📤 **Please send the APK file** you want to protect.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, document = str(update.effective_user.id), update.message.document
    if not document.file_name.endswith('.apk'): return await update.message.reply_text("❌ Please send a valid APK file.")

    user = db["users"].get(user_id)
    if not user or user.get('credits', 0) <= 0: return await update.message.reply_text("❌ Not enough credits or not logged in.")

    if user.get("trial_used") and "last_protect_time" in user:
        rem = (db["settings"]["trial_wait_time"] * 60) - (time.time() - user["last_protect_time"])
        if rem > 0: return await update.message.reply_text(f"⏳ **Trial Limit:** Please wait **{int(rem//60)}m {int(rem%60)}s** before protecting another APK.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💎 Buy Premium", url=db['settings']['premium_link'])]]))
            
    context.user_data.update({'apk_id': document.file_id, 'apk_name': document.file_name})
    keyboard = [[InlineKeyboardButton("Google", callback_data='prot_google')], [InlineKeyboardButton("Tencent", callback_data='prot_tencent')], [InlineKeyboardButton("360", callback_data='prot_360')], [InlineKeyboardButton("Arm", callback_data='prot_arm')], [InlineKeyboardButton("Skip", callback_data='prot_skip')]]
    await update.message.reply_text("🛡️ **Which protection do you want to apply?**", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_protection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice, user_id = query.data, str(query.from_user.id)
    if choice == 'protect': return

    file_id, apk_name = context.user_data.get('apk_id'), context.user_data.get('apk_name')
    if not file_id: return await query.edit_message_text("❌ Session expired. Please send the APK again.")

    file = await context.bot.get_file(file_id)
    input_path = os.path.join(TEMP_DIR, apk_name)
    await file.download_to_drive(input_path)

    eta = "2-3 mins" if os.path.getsize(input_path)/(1024*1024) < 5 else "4-6 mins"
    progress_msg = await query.edit_message_text(f"⏳ **Processing APK...**\n\n[□□□□□□□□□□] 0%\n⏱️ **Target Time: {eta}**")

    executable_dir = os.path.join(BASE_DIR, "executable")
    if not os.path.exists(executable_dir):
        with zipfile.ZipFile(os.path.join(BASE_DIR, "dpt-shell-v2.21.1.zip"), 'r') as zip_ref: zip_ref.extractall(BASE_DIR)

    output_name = apk_name.replace(".apk", "_signed.apk")
    generated_file = os.path.join(executable_dir, output_name)
    
    try:
        await progress_msg.edit_text(f"⏳ **Processing APK...**\n\n[■■■□□□□□□□] 30%\n⏱️ **Target Time: {eta}**")
        subprocess.run(["java", "-Xmx512m", "-jar", os.path.join(executable_dir, "dpt.jar"), "-f", input_path], cwd=executable_dir, capture_output=True, text=True)
        
        if os.path.exists(generated_file):
            if choice in ['prot_google', 'prot_tencent', 'prot_360', 'prot_arm']:
                await progress_msg.edit_text(f"⏳ **Processing APK...**\n\n[■■■■■■□□□□] 60%\n⏱️ **Almost Done**")
                zip_map = {'prot_google': "google.zip", 'prot_tencent': "腾讯御安全.zip", 'prot_360': "360.zip", 'prot_arm': "arm.zip"}
                zip_path = os.path.join(BASE_DIR, zip_map[choice])
                if os.path.exists(zip_path):
                    temp_zip = generated_file + ".zip"
                    os.rename(generated_file, temp_zip)
                    extract_dir = os.path.join(TEMP_DIR, "inject_lib")
                    with zipfile.ZipFile(zip_path, 'r') as zf: zf.extractall(extract_dir)
                    for root, _, files in os.walk(extract_dir):
                        for f in files:
                            if f.endswith('.so'):
                                with zipfile.ZipFile(temp_zip, 'a', zipfile.ZIP_DEFLATED) as zf: zf.write(os.path.join(root, f), arcname=f"assets/{f}")
                                break
                    os.rename(temp_zip, generated_file)
                    shutil.rmtree(extract_dir, ignore_errors=True)

            await progress_msg.edit_text("✅ **Processing Complete!**\n\n[■■■■■■■■■■] 100%")
            await query.message.reply_document(document=open(generated_file, 'rb'), filename=output_name, caption=f"✅ **Protected Successfully!**\nType: {choice}")
            
            db["users"][user_id]["credits"] -= 1
            if db["users"][user_id].get("trial_used"): db["users"][user_id]["last_protect_time"] = time.time()
            db["history"].append({"tg_id": user_id, "apk_name": output_name, "type": choice})
            save_db()
            await query.message.reply_text(f"💳 Remaining Credits: {db['users'][user_id]['credits']}")
            
            os.remove(generated_file); os.remove(input_path); gc.collect()
        else: await progress_msg.edit_text("❌ Protection failed. Memory issue or unsupported APK.")
    except Exception as e:
        logging.error(e)
        await progress_msg.edit_text("❌ Error occurred during protection.")


def main():
    if not BOT_TOKEN: return print("ERROR: BOT_TOKEN missing!")
    
    # ফ্লাস্ক সার্ভার আলাদা থ্রেডে চালু
    threading.Thread(target=run_flask, daemon=True).start()
    
    # মেইন বট অ্যাপ্লিকেশন
    app_bot = Application.builder().token(BOT_TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(handle_callbacks, pattern='^(verify_join|free_trial|user_login|protect)$'))
    app_bot.add_handler(CallbackQueryHandler(handle_protection, pattern='^prot_'))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app_bot.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    # সার্ভার চালু হওয়ার সময় ডাটাবেসে থাকা রিঅ্যাকশন বটগুলো চালু করা
    for rb in db["reaction_bots"]:
        start_single_reaction_bot(rb["token"], rb["channel_id"], rb["emojis"])
    
    print("Main Bot and Web Server are running...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()