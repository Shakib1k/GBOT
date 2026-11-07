import os
import zipfile
import subprocess
import logging
import random
import string
import threading
import json
import requests
import base64
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# লগিং সেটআপ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Environment Variables (Render-এ সেট করবেন)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN", "YOUR_GITLAB_TOKEN")
GITLAB_PROJECT_ID = "Shakib1k%2Fsk-bd" # আপনার GitLab Project ID (URL Encoded)
GITLAB_FILE_PATH = "db.json"
ADMIN_PASS = "Shakib.12"

BASE_DIR = os.getcwd()
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# ==================== GITLAB DATABASE LOGIC ====================
def get_gitlab_file():
    url = f"https://gitlab.com/api/v4/projects/{GITLAB_PROJECT_ID}/repository/files/{GITLAB_FILE_PATH}?ref=main"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        content = base64.b64decode(response.json()['content']).decode('utf-8')
        return json.loads(content) if content else {}
    return {"users": {}, "keys": {}, "history": []}

def save_gitlab_file(data):
    url = f"https://gitlab.com/api/v4/projects/{GITLAB_PROJECT_ID}/repository/files/{GITLAB_FILE_PATH}"
    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN}
    
    # ফাইলটি আগে থেকে আছে কিনা চেক করা
    check_url = f"{url}?ref=main"
    check_res = requests.get(check_url, headers=headers)
    
    content = json.dumps(data, indent=4)
    encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    
    payload = {
        "branch": "main",
        "content": encoded_content,
        "commit_message": "Database updated by Bot"
    }
    
    if check_res.status_code == 200:
        # ফাইল আপডেট করা
        requests.put(url, headers=headers, json=payload)
    else:
        # নতুন ফাইল তৈরি করা
        requests.post(url, headers=headers, json=payload)

def read_db():
    return get_gitlab_file()

def write_db(data):
    save_gitlab_file(data)

# ==================== FLASK ADMIN PANEL ====================
app = Flask(__name__, template_folder='.')
app.secret_key = 'super_secret_key_123'

@app.route('/admin', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASS:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        return render_template('login.html', error="Invalid Password!")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'): return redirect(url_for('login'))
    db = read_db()
    total_users = len(db.get("users", {}))
    return render_template('dashboard.html', total_users=total_users)

@app.route('/manage_users')
def manage_users():
    if not session.get('logged_in'): return redirect(url_for('login'))
    db = read_db()
    all_keys = [{"key": k, **v} for k, v in db.get("keys", {}).items()]
    return render_template('manage_users.html', keys=all_keys)

@app.route('/api/generate_key', methods=['POST'])
def generate_key():
    if not session.get('logged_in'): return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    user_id = data.get('user_id')
    credits = int(data.get('credits'))
    new_key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    
    db = read_db()
    if "keys" not in db: db["keys"] = {}
    db["keys"][new_key] = {"user_id": user_id, "credits": credits, "used": False}
    write_db(db)
    return jsonify({"success": True, "key": new_key})

# ==================== BOT LOGIC ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    db = read_db()
    user = db.get("users", {}).get(user_id)
    
    if user and user.get("is_logged_in"):
        await show_main_menu(update, context, user['credits'])
    else:
        await update.message.reply_text("🔐 **Welcome! Please enter your Key to login.**\n\nExample: `ABCD123456`", parse_mode='Markdown')

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, credits):
    keyboard = [[InlineKeyboardButton(f"🛡️ Protect APK (Credits: {credits})", callback_data='protect')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("✅ **Login Successful!**\n\nClick below to protect your APK.", reply_markup=reply_markup)

async def handle_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("❌ Invalid Key, Key already used, or Key belongs to another user.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    user_id = str(update.effective_user.id)
    
    db = read_db()
    user = db.get("users", {}).get(user_id)
    
    if not user or user['credits'] <= 0:
        await update.message.reply_text("❌ You don't have enough credits or you are not logged in.")
        return

    if not document.file_name.endswith('.apk'):
        await update.message.reply_text("❌ Please send a valid APK file.")
        return

    context.user_data['apk_id'] = document.file_id
    context.user_data['apk_name'] = document.file_name
    
    keyboard = [
        [InlineKeyboardButton("Google Protection", callback_data='prot_google')],
        [InlineKeyboardButton("Tencent (御安全) Protection", callback_data='prot_tencent')],
        [InlineKeyboardButton("⏭️ Skip Protection (Just Sign)", callback_data='prot_skip')]
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
    await query.edit_message_text("⏳ Processing... This may take 1-3 minutes.")

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
            await query.message.reply_document(
                document=open(generated_file, 'rb'),
                filename=output_name,
                caption=f"✅ **Protected Successfully!**\nType: {choice}\n\nDo not share this file illegally."
            )
            
            # ডাটাবেস আপডেট
            db = read_db()
            db["users"][user_id]["credits"] -= 1
            if "history" not in db: db["history"] = []
            db["history"].append({"tg_id": user_id, "apk_name": output_name, "type": choice})
            write_db(db)
            
            rem_credits = db["users"][user_id]["credits"]
            await query.message.reply_text(f"💳 Remaining Credits: {rem_credits}\n\nTo buy more, contact Admin.")
            
            os.remove(generated_file)
            os.remove(input_path)
        else:
            await query.message.reply_text("❌ Protection failed. Unsupported APK or memory issue.")
    except Exception as e:
        logging.error(e)
        await query.message.reply_text("❌ Error occurred during protection.")

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# ==================== MAIN ====================
def main():
    threading.Thread(target=run_flask, daemon=True).start()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_login))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(handle_protection_choice))
    application.run_polling()

if __name__ == '__main__':
    main()