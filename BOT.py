import os
import zipfile
import subprocess
import logging
import json
import base64
import requests
import random
import string
import threading
from flask import Flask, request, jsonify, render_template
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# ⚠️ আপনার GitLab টোকেন সরাসরি এখানে বসানো হলো
GITLAB_TOKEN = "glpat-6HhMaa8p9Q84RAncGnbLCGM6MQpvOjEKdTpvODlveA8.01.17007rkbm"
GITLAB_PROJECT_ID = "Shakib1k%2Fsk-bd"
GITLAB_FILE_PATH = "db.json"

BASE_DIR = os.getcwd()
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# ==================== GITLAB DATABASE ====================
def read_db():
    url = f"https://gitlab.com/api/v4/projects/{GITLAB_PROJECT_ID}/repository/files/{GITLAB_FILE_PATH}?ref=main"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            content = base64.b64decode(response.json()['content']).decode('utf-8')
            # যদি ডাটাবেস ফাঁকা থাকে, তবে ডিফল্ট স্ট্রাকচার দেবে
            return json.loads(content) if content else {"users": {}, "keys": {}, "history": []}
    except Exception as e:
        logging.error(f"GitLab Read Error: {e}")
    return {"users": {}, "keys": {}, "history": []}

def write_db(data):
    url = f"https://gitlab.com/api/v4/projects/{GITLAB_PROJECT_ID}/repository/files/{GITLAB_FILE_PATH}"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    try:
        check_res = requests.get(f"{url}?ref=main", headers=headers)
        content = json.dumps(data, indent=4)
        encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        payload = {"branch": "main", "content": encoded_content, "commit_message": "Bot DB Updated"}
        if check_res.status_code == 200:
            requests.put(url, headers=headers, json=payload)
        else:
            requests.post(url, headers=headers, json=payload)
    except Exception as e:
        logging.error(f"GitLab Write Error: {e}")

def gen_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

# ==================== FLASK WEB API (For Admin Panel) ====================
app = Flask(__name__, template_folder='.')

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/api/get_users')
def get_users():
    db = read_db()
    keys = db.get("keys", {})
    users = []
    for k, v in keys.items():
        users.append({
            "user_id": v.get("user_id"), 
            "key": k, 
            "credits": v.get("credits"), 
            "used": v.get("used", False)
        })
    return jsonify(users)

@app.route('/api/get_history')
def get_history():
    db = read_db()
    return jsonify(db.get("history", []))

@app.route('/api/create_user', methods=['POST'])
def create_user():
    data = request.json
    uid = str(data.get('user_id'))
    credits = data.get('credits')
    key = data.get('key') or gen_key()
    
    db = read_db()
    if "keys" not in db: db["keys"] = {}
    db["keys"][key] = {"user_id": uid, "credits": credits, "used": False}
    write_db(db)
    return jsonify({"success": True, "key": key})

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# ==================== BOT LOGIC ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    context.user_data.clear() 
    
    db = read_db()
    user = db.get("users", {}).get(user_id)
    
    if user and user.get("is_logged_in"):
        await show_main_menu(update, context, user['credits'])
    else:
        await update.message.reply_text("🔐 **Welcome! Please enter your Key to login.**\n\nExample: `ABCD123456`", parse_mode='Markdown')

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, credits):
    keyboard = [[InlineKeyboardButton(f"🛡️ Protect APK (Credits: {credits})", callback_data='protect')]]
    await update.message.reply_text("✅ **Login Successful!**\n\nClick below to protect your APK.", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    db = read_db()
    key_data = db.get("keys", {}).get(text)
    
    if key_data and str(key_data['user_id']) == user_id and not key_data['used']:
        credits = key_data['credits']
        if "users" not in db: db["users"] = {}
        db["users"][user_id] = {"key": text, "credits": credits, "is_logged_in": True}
        db["keys"][text]["used"] = True
        write_db(db)
        
        await update.message.reply_text(f"🎉 **Login Successful!**\nYou have {credits} credits.")
        await show_main_menu(update, context, credits)
    else:
        await update.message.reply_text("❌ Invalid Key or already used.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    document = update.message.document
    
    if not document.file_name.endswith('.apk'):
        await update.message.reply_text("❌ Please send a valid APK file.")
        return

    db = read_db()
    user = db.get("users", {}).get(user_id)
    if not user or user['credits'] <= 0:
        await update.message.reply_text("❌ Not enough credits or not logged in.")
        return

    context.user_data['apk_id'] = document.file_id
    context.user_data['apk_name'] = document.file_name
    
    keyboard = [
        [InlineKeyboardButton("Google Protection", callback_data='prot_google')],
        [InlineKeyboardButton("Tencent Protection", callback_data='prot_tencent')],
        [InlineKeyboardButton("⏭️ Skip Protection", callback_data='prot_skip')]
    ]
    await update.message.reply_text("🛠️ **Select Protection Type:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_protection_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    user_id = str(query.from_user.id)
    
    if choice == 'protect':
        await query.edit_message_text("📤 Please send the APK file you want to protect.")
        return

    file_id = context.user_data.get('apk_id')
    apk_name = context.user_data.get('apk_name')
    if not file_id:
        await query.edit_message_text("❌ Session expired. Please send the APK again.")
        return

    await query.edit_message_text("⏳ Processing APK... Please wait a few moments.")
    file = await context.bot.get_file(file_id)
    input_path = os.path.join(TEMP_DIR, apk_name)
    await file.download_to_drive(input_path)

    executable_dir = os.path.join(BASE_DIR, "executable")
    if not os.path.exists(executable_dir):
        with zipfile.ZipFile(os.path.join(BASE_DIR, "dpt-shell-v2.21.1.zip"), 'r') as zip_ref:
            zip_ref.extractall(BASE_DIR)

    output_name = apk_name.replace(".apk", "_signed.apk")
    
    try:
        command = ["java", "-jar", os.path.join(executable_dir, "dpt.jar"), "-f", input_path]
        subprocess.run(command, cwd=executable_dir, capture_output=True, text=True)
        generated_file = os.path.join(executable_dir, output_name)
        
        if os.path.exists(generated_file):
            await query.message.reply_document(document=open(generated_file, 'rb'), filename=output_name, caption=f"✅ **Protected Successfully!**\nType: {choice}")
            
            # ডাটাবেস আপডেট (ক্রেডিট মাইনাস এবং হিস্ট্রি সেভ)
            db = read_db()
            db["users"][user_id]["credits"] -= 1
            if "history" not in db: db["history"] = []
            db["history"].append({"tg_id": user_id, "apk_name": output_name, "type": choice})
            write_db(db)
            
            await query.message.reply_text(f"💳 Remaining Credits: {db['users'][user_id]['credits']}")
            os.remove(generated_file)
            os.remove(input_path)
        else:
            await query.message.reply_text("❌ Protection failed. Memory issue or unsupported APK.")
    except Exception as e:
        logging.error(e)
        await query.message.reply_text("❌ Error occurred during protection.")

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN missing!")
        return

    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_protection_choice, pattern='^prot_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print("Bot and Web Server are running...")
    application.run_polling()

if __name__ == '__main__':
    main()