import os
import zipfile
import subprocess
import logging
import json
import base64
import requests
import random
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# লগিং সেটআপ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Environment Variables (Render-এ সেট করবেন)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN", "YOUR_GITLAB_TOKEN")
GITLAB_PROJECT_ID = "Shakib1k%2Fsk-bd" # আপনার GitLab Project ID (URL Encoded)
GITLAB_FILE_PATH = "db.json"

# ⚠️ আপনার অ্যাডমিন আইডি এখানে বসান
ADMIN_ID = 7058712225 

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
            return json.loads(content) if content else {"users": {}, "keys": {}}
    except Exception:
        pass
    return {"users": {}, "keys": {}}

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

# ==================== KEY GENERATORS ====================
def gen_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

# ==================== ADMIN PANEL ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = read_db()
    total_users = len(db.get("users", {}))
    total_keys = len(db.get("keys", {}))
    
    text = (
        f"👑 **Admin Control Panel**\n\n"
        f"👥 **Total Users:** {total_users}\n"
        f"🔑 **Total Keys:** {total_keys}\n\n"
        f"নিচের অপশনগুলো থেকে কাজ নির্বাচন করুন:"
    )
    
    keyboard = [
        [InlineKeyboardButton("➕ Create User Key", callback_data='admin_create')],
        [InlineKeyboardButton("👥 View All Users", callback_data='admin_view_users')],
        [InlineKeyboardButton("🔑 View All Keys", callback_data='admin_view_keys')]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# ==================== USER PANEL ====================
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, credits):
    keyboard = [[InlineKeyboardButton(f"🛡️ Protect APK (Credits: {credits})", callback_data='protect')]]
    await update.message.reply_text("✅ **Login Successful!**\n\nClick below to protect your APK.", reply_markup=InlineKeyboardMarkup(keyboard))

# ==================== START COMMAND ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if user_id == ADMIN_ID:
        await admin_panel(update, context)
        return

    user_id_str = str(user_id)
    db = read_db()
    user = db.get("users", {}).get(user_id_str)
    
    if user and user.get("is_logged_in"):
        await show_main_menu(update, context, user['credits'])
    else:
        await update.message.reply_text("🔐 **Welcome! Please enter your Key to login.**\n\nExample: `ABCD123456`", parse_mode='Markdown')

# ==================== ADMIN CALLBACKS ====================
async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("❌ You are not authorized to use this.")
        return

    if query.data == 'admin_create':
        await query.edit_message_text("📝 **Please send the Telegram User ID** you want to create a key for.\n\nFormat: `ID Credits` (Example: `123456789 10`)")
        context.user_data['admin_action'] = 'create_key'

    elif query.data == 'admin_view_users':
        db = read_db()
        users = db.get("users", {})
        if not users:
            await query.edit_message_text("👥 No users found.")
            return
        
        text = "👥 **Registered Users:**\n\n"
        for uid, info in users.items():
            text += f"🆔 ID: `{uid}` | 💳 Credits: {info.get('credits', 0)}\n"
        await query.edit_message_text(text, parse_mode='Markdown')

    elif query.data == 'admin_view_keys':
        db = read_db()
        keys = db.get("keys", {})
        if not keys:
            await query.edit_message_text("🔑 No keys found.")
            return
            
        text = "🔑 **Generated Keys:**\n\n"
        for k, info in keys.items():
            status = "Used" if info.get('used') else "Active"
            text += f"`{k}` | 👤 {info.get('user_id')} | 💳 {info.get('credits')} | {status}\n"
        await query.edit_message_text(text, parse_mode='Markdown')

# ==================== TEXT HANDLER (LOGIN & ADMIN CREATE) ====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # অ্যাডমিন কী তৈরি করছে
    if user_id == ADMIN_ID and context.user_data.get('admin_action') == 'create_key':
        try:
            uid, credits = text.split()
            new_key = gen_key()
            db = read_db()
            if "keys" not in db: db["keys"] = {}
            db["keys"][new_key] = {"user_id": uid, "credits": int(credits), "used": False}
            write_db(db)
            
            await update.message.reply_text(f"✅ **Key Generated Successfully!**\n\n🔑 Key: `{new_key}`\n👤 User ID: `{uid}`\n💳 Credits: {credits}", parse_mode='Markdown')
            context.user_data['admin_action'] = None
            await admin_panel(update, context)
        except ValueError:
            await update.message.reply_text("❌ Invalid format. Please send: `ID Credits` (Example: `123456789 10`)")
        return

    # ইউজার লগইন করছে
    if user_id != ADMIN_ID:
        db = read_db()
        key_data = db.get("keys", {}).get(text)
        
        if key_data and str(key_data['user_id']) == str(user_id) and not key_data['used']:
            credits = key_data['credits']
            if "users" not in db: db["users"] = {}
            db["users"][str(user_id)] = {"key": text, "credits": credits, "is_logged_in": True}
            db["keys"][text]["used"] = True
            write_db(db)
            
            await update.message.reply_text(f"🎉 **Login Successful!**\nYou have {credits} credits.")
            await show_main_menu(update, context, credits)
        else:
            await update.message.reply_text("❌ Invalid Key or already used.")

# ==================== USER APK HANDLING ====================
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id == str(ADMIN_ID):
        await update.message.reply_text("👑 অ্যাডমিন, আপনার কাছে APK প্রোটেকশন ফিচারটি এখনো যুক্ত করা হয়নি।")
        return

    document = update.message.document
    db = read_db()
    user = db.get("users", {}).get(user_id)
    
    if not user or user['credits'] <= 0:
        await update.message.reply_text("❌ Not enough credits or not logged in.")
        return
    if not document.file_name.endswith('.apk'):
        await update.message.reply_text("❌ Please send a valid APK file.")
        return

    context.user_data['apk_id'] = document.file_id
    context.user_data['apk_name'] = document.file_name
    
    keyboard = [[InlineKeyboardButton("Google Protection", callback_data='prot_google')],
                [InlineKeyboardButton("Tencent Protection", callback_data='prot_tencent')],
                [InlineKeyboardButton("⏭️ Skip Protection", callback_data='prot_skip')]]
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
    await query.edit_message_text("⏳ Processing... Please wait.")

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
            db = read_db()
            db["users"][user_id]["credits"] -= 1
            write_db(db)
            await query.message.reply_text(f"💳 Remaining Credits: {db['users'][user_id]['credits']}")
            os.remove(generated_file)
            os.remove(input_path)
        else:
            await query.message.reply_text("❌ Protection failed. Memory issue or unsupported APK.")
    except Exception as e:
        logging.error(e)
        await query.message.reply_text("❌ Error occurred during protection.")

# ==================== MAIN ====================
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(admin_callbacks, pattern='^admin_'))
    application.add_handler(CallbackQueryHandler(handle_protection_choice, pattern='^prot_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()