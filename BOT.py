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
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 7058712225 
BASE_DIR = os.getcwd()
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

db = {
    "users": {},
    "keys": {},
    "history": [],
    "join_channels": [],
    "settings": {
        "premium_link": "https://t.me/YourAdminUsername",
        "trial_credits": 15,
        "trial_wait_time": 30,
        "welcome_text": "👋 **Welcome to the APK Protector Bot!**\n\nPlease login or start a free trial to continue.",
        "trial_btn_text": "🎁 Free Trial",
        "premium_btn_text": "💎 Buy Premium"
    }
}

def gen_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

app = Flask(__name__, template_folder='.')
CORS(app)

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/api/get_users')
def get_users():
    users = []
    for k, v in db["keys"].items():
        users.append({"key": k, "user_id": v.get("user_id"), "credits": v.get("credits"), "used": v.get("used", False)})
    return jsonify(users)

@app.route('/api/get_trial_users')
def get_trial_users():
    return jsonify([{"user_id": uid, "credits": d.get("credits")} for uid, d in db["users"].items() if d.get("trial_used")])

@app.route('/api/get_history')
def get_history():
    return jsonify(db["history"])

@app.route('/api/get_settings')
def get_settings():
    return jsonify({"settings": db["settings"], "channels": db["join_channels"]})

@app.route('/api/update_settings', methods=['POST'])
def update_settings():
    data = request.json
    db["settings"].update(data)
    return jsonify({"success": True})

@app.route('/api/add_channel', methods=['POST'])
def add_channel():
    data = request.json
    db["join_channels"].append({"name": data.get("name"), "link": data.get("link"), "type": data.get("type"), "chat_id": data.get("chat_id", "")})
    return jsonify({"success": True})

@app.route('/api/delete_channel', methods=['POST'])
def delete_channel():
    index = request.json.get("index")
    if 0 <= index < len(db["join_channels"]): db["join_channels"].pop(index)
    return jsonify({"success": True})

@app.route('/api/create_user', methods=['POST'])
def create_user():
    data = request.json
    uid, credits, key = str(data.get('user_id')), data.get('credits'), data.get('key') or gen_key()
    db["keys"][key] = {"user_id": uid, "credits": credits, "used": False}
    return jsonify({"success": True, "key": key})

@app.route('/api/edit_key', methods=['POST'])
def edit_key():
    data = request.json
    old_key, new_key, credits = data.get('old_key'), data.get('new_key'), int(data.get('credits'))
    if old_key in db["keys"]:
        if new_key and new_key != old_key:
            db["keys"][new_key] = db["keys"].pop(old_key)
        else:
            new_key = old_key
        db["keys"][new_key]["credits"] = credits
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/api/delete_key', methods=['POST'])
def delete_key():
    key = request.json.get('key')
    if key in db["keys"]: del db["keys"][key]
    return jsonify({"success": True})

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# ==================== BOT LOGIC ====================
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
    
    # ১. যদি ইউজার লগইন থাকে
    if user and user.get("is_logged_in") and user.get("credits", 0) > 0:
        await show_main_menu(update, context, user['credits'])
        return

    # ২. যদি ট্রায়াল আগে নেওয়া থাকে (শুধু লগইন এবং প্রিমিয়াম দেখাবে)
    if user and user.get("trial_used"):
        keyboard = [
            [InlineKeyboardButton("🔑 Login with Key", callback_data='user_login')],
            [InlineKeyboardButton(db['settings']['premium_btn_text'], url=db['settings']['premium_link'])]
        ]
        text = "👋 Welcome back!\n\nYou have already used your free trial. Please login or buy premium."
    else:
        # ৩. নতুন ইউজার (ট্রায়াল, লগইন, প্রিমিয়াম)
        keyboard = [
            [InlineKeyboardButton(db['settings']['trial_btn_text'], callback_data='free_trial')],
            [InlineKeyboardButton("🔑 Login with Key", callback_data='user_login')],
            [InlineKeyboardButton(db['settings']['premium_btn_text'], url=db['settings']['premium_link'])]
        ]
        text = db['settings']['welcome_text']

    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    context.user_data.clear()
    
    not_joined = await check_channels(user_id, context)
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
            await send_welcome(update, context) # এখানে send_welcome কল করা হলো
        else: await query.edit_message_text("❌ You haven't joined all channels yet.")
    
    elif query.data == 'free_trial':
        user = db["users"].get(user_id, {})
        if user.get("trial_used"):
            await query.edit_message_text("❌ You have already used your free trial.")
            return
        db["users"][user_id] = {"credits": db["settings"]["trial_credits"], "is_logged_in": True, "trial_used": True, "last_protect_time": 0}
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
            await query.message.reply_text(f"💳 Remaining Credits: {db['users'][user_id]['credits']}")
            
            os.remove(generated_file); os.remove(input_path); gc.collect()
        else: await progress_msg.edit_text("❌ Protection failed. Memory issue or unsupported APK.")
    except Exception as e:
        logging.error(e)
        await progress_msg.edit_text("❌ Error occurred during protection.")

def main():
    if not BOT_TOKEN: return print("ERROR: BOT_TOKEN missing!")
    threading.Thread(target=run_flask, daemon=True).start()
    app_bot = Application.builder().token(BOT_TOKEN).build()
    
    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CallbackQueryHandler(handle_callbacks, pattern='^(verify_join|free_trial|user_login|protect)$'))
    app_bot.add_handler(CallbackQueryHandler(handle_protection, pattern='^prot_'))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app_bot.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print("Bot and Web Server are running...")
    app_bot.run_polling()

if __name__ == '__main__':
    main()