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

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Environment Variables
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 7058712225 

BASE_DIR = os.getcwd()
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# ==================== DATABASE ====================
db = {
    "users": {},
    "keys": {},
    "history": [],
    "settings": {
        "premium_link": "https://t.me/YourAdminUsername", 
        "trial_credits": 15 
    }
}

def gen_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

# ==================== FLASK WEB API ====================
app = Flask(__name__, template_folder='.')
CORS(app)

@app.route('/admin')
def admin_page():
    return render_template('admin.html')

@app.route('/api/get_users')
def get_users():
    users = []
    for k, v in db["keys"].items():
        users.append({"user_id": v.get("user_id"), "key": k, "credits": v.get("credits"), "used": v.get("used", False)})
    return jsonify(users)

@app.route('/api/get_history')
def get_history():
    return jsonify(db["history"])

@app.route('/api/get_settings')
def get_settings():
    return jsonify(db["settings"])

@app.route('/api/update_settings', methods=['POST'])
def update_settings():
    data = request.json
    db["settings"]["premium_link"] = data.get("premium_link", db["settings"]["premium_link"])
    db["settings"]["trial_credits"] = int(data.get("trial_credits", db["settings"]["trial_credits"]))
    return jsonify({"success": True})

@app.route('/api/create_user', methods=['POST'])
def create_user():
    data = request.json
    uid = str(data.get('user_id'))
    credits = data.get('credits')
    key = data.get('key') or gen_key()
    
    db["keys"][key] = {"user_id": uid, "credits": credits, "used": False}
    return jsonify({"success": True, "key": key})

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# ==================== BOT LOGIC ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    context.user_data.clear() 
    
    user = db["users"].get(user_id)
    if user and user.get("is_logged_in"):
        await show_main_menu(update, context, user['credits'])
    else:
        premium_link = db["settings"]["premium_link"]
        keyboard = [
            [InlineKeyboardButton(f"🎁 Try Free Trial ({db['settings']['trial_credits']} Credits)", callback_data='free_trial')],
            [InlineKeyboardButton("💎 Buy Premium", url=premium_link)]
        ]
        await update.message.reply_text(
            "👋 **Welcome to the APK Protector Bot!**\n\n"
            "🔹 **Free Trial:** Get limited credits for 1 day (1 APK per 30 mins).\n"
            "🔹 **Premium:** Unlimited access (Contact Admin).\n\n"
            "Please choose an option below:",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, credits):
    keyboard = [[InlineKeyboardButton(f"🛡️ Protect APK (Credits: {credits})", callback_data='protect')]]
    await update.message.reply_text(f"✅ **Login Successful!**\n\n💳 **Your Credits:** {credits}\n\nClick below to protect your APK.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    key_data = db["keys"].get(text)
    
    if key_data and str(key_data['user_id']) == user_id and not key_data['used']:
        credits = key_data['credits']
        db["users"][user_id] = {"key": text, "credits": credits, "is_logged_in": True}
        db["keys"][text]["used"] = True
        await update.message.reply_text(f"🎉 **Login Successful!**\nYou have {credits} credits.")
        await show_main_menu(update, context, credits)
    else:
        await update.message.reply_text("❌ Invalid Key or already used.")

async def handle_user_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    
    if query.data == 'free_trial':
        user = db["users"].get(user_id)
        if user and user.get("trial_used"):
            await query.edit_message_text("❌ You have already used your free trial.")
            return
        
        trial_credits = db["settings"]["trial_credits"]
        db["users"][user_id] = {
            "credits": trial_credits, 
            "is_logged_in": True, 
            "trial_used": True,
            "last_protect_time": 0
        }
        await query.edit_message_text(f"🎁 **Free Trial Activated!**\n\nYou have {trial_credits} credits.\n⚠️ Note: You can protect 1 APK every 30 minutes.", parse_mode='Markdown')
        await show_main_menu(update, context, trial_credits)
        
async def handle_protect_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == 'protect':
        await query.edit_message_text("📤 **Please send the APK file** you want to protect.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    document = update.message.document
    
    if not document.file_name.endswith('.apk'):
        await update.message.reply_text("❌ Please send a valid APK file.")
        return

    user = db["users"].get(user_id)
    if not user or user['credits'] <= 0:
        await update.message.reply_text("❌ Not enough credits or not logged in.")
        return

    if user.get("trial_used"):
        current_time = time.time()
        last_time = user.get("last_protect_time", 0)
        if current_time - last_time < 1800:
            remaining = 1800 - (current_time - last_time)
            await update.message.reply_text(f"⏳ **Trial Limit:** Please wait {int(remaining//60)} minutes before protecting another APK.")
            return

    context.user_data['apk_id'] = document.file_id
    context.user_data['apk_name'] = document.file_name
    
    # ৪টি প্রোটেকশন অপশন
    keyboard = [
        [InlineKeyboardButton("Google Protection", callback_data='prot_google')],
        [InlineKeyboardButton("Tencent Protection", callback_data='prot_tencent')],
        [InlineKeyboardButton("360 Protection", callback_data='prot_360')],
        [InlineKeyboardButton("Arm Protection", callback_data='prot_arm')],
        [InlineKeyboardButton("⏭️ Skip Protection", callback_data='prot_skip')]
    ]
    
    # উপরে টেক্সট সহ মেসেজ
    await update.message.reply_text(
        "🛡️ **Which protection do you want to apply to your APK?**\n\nSelect an option below:", 
        reply_markup=InlineKeyboardMarkup(keyboard), 
        parse_mode='Markdown'
    )

# --- ফাইল ইনজেক্টর এবং প্রোটেকশন লজিক ---
async def handle_protection_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data
    user_id = str(query.from_user.id)
    
    if choice == 'protect':
        return

    file_id = context.user_data.get('apk_id')
    apk_name = context.user_data.get('apk_name')
    if not file_id:
        await query.edit_message_text("❌ Session expired. Please send the APK again.")
        return

    progress_msg = await query.edit_message_text("⏳ **Processing APK...**\n\n[□□□□□□□□□□] 0%")
    
    gc.collect()
    file = await context.bot.get_file(file_id)
    input_path = os.path.join(TEMP_DIR, apk_name)
    await file.download_to_drive(input_path)

    executable_dir = os.path.join(BASE_DIR, "executable")
    if not os.path.exists(executable_dir):
        with zipfile.ZipFile(os.path.join(BASE_DIR, "dpt-shell-v2.21.1.zip"), 'r') as zip_ref:
            zip_ref.extractall(BASE_DIR)

    output_name = apk_name.replace(".apk", "_signed.apk")
    generated_file = os.path.join(executable_dir, output_name)
    
    try:
        await progress_msg.edit_text("⏳ **Processing APK...**\n\n[■■■□□□□□□□] 30%")
        command = ["java", "-jar", os.path.join(executable_dir, "dpt.jar"), "-f", input_path]
        subprocess.run(command, cwd=executable_dir, capture_output=True, text=True)
        
        if os.path.exists(generated_file):
            # ৪টি প্রোটেকশনের জন্য জিপ ফাইল ম্যাপিং
            zip_mapping = {
                'prot_google': "google.zip",
                'prot_tencent': "腾讯御安全.zip",
                'prot_360': "360.zip",
                'prot_arm': "arm.zip"
            }

            if choice in zip_mapping:
                await progress_msg.edit_text("⏳ **Processing APK...**\n\n[■■■■■■□□□□] 60%")
                
                zip_to_extract = zip_mapping[choice]
                zip_path = os.path.join(BASE_DIR, zip_to_extract)
                
                if os.path.exists(zip_path):
                    temp_zip_path = generated_file + ".zip"
                    os.rename(generated_file, temp_zip_path)
                    
                    extract_dir = os.path.join(TEMP_DIR, "inject_lib")
                    os.makedirs(extract_dir, exist_ok=True)
                    with zipfile.ZipFile(zip_path, 'r') as zf:
                        zf.extractall(extract_dir)
                    
                    so_file = None
                    for root, dirs, files in os.walk(extract_dir):
                        for f in files:
                            if f.endswith('.so'):
                                so_file = os.path.join(root, f)
                                break
                    
                    if so_file:
                        with zipfile.ZipFile(temp_zip_path, 'a', zipfile.ZIP_DEFLATED) as zf:
                            zf.write(so_file, arcname=f"assets/{os.path.basename(so_file)}")
                    
                    os.rename(temp_zip_path, generated_file)
                    shutil.rmtree(extract_dir, ignore_errors=True)
                else:
                    await query.message.reply_text(f"⚠️ Warning: {zip_to_extract} not found in server. Skipping injection.")

            await progress_msg.edit_text("✅ **Processing Complete!**\n\n[■■■■■■■■■■] 100%")
            await query.message.reply_document(
                document=open(generated_file, 'rb'), 
                filename=output_name, 
                caption=f"✅ **Protected Successfully!**\nType: {choice}"
            )
            
            db["users"][user_id]["credits"] -= 1
            if db["users"][user_id].get("trial_used"):
                db["users"][user_id]["last_protect_time"] = time.time()
                
            db["history"].append({"tg_id": user_id, "apk_name": output_name, "type": choice})
            await query.message.reply_text(f"💳 Remaining Credits: {db['users'][user_id]['credits']}")
            
            os.remove(generated_file)
            os.remove(input_path)
            gc.collect()
        else:
            await progress_msg.edit_text("❌ Protection failed. Memory issue or unsupported APK.")
    except Exception as e:
        logging.error(f"Error during protection: {e}")
        await progress_msg.edit_text("❌ Error occurred during protection.")

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN missing!")
        return

    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_user_callbacks, pattern='^free_trial$'))
    application.add_handler(CallbackQueryHandler(handle_protect_button, pattern='^protect$'))
    application.add_handler(CallbackQueryHandler(handle_protection_choice, pattern='^prot_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    
    print("Bot and Web Server are running...")
    application.run_polling()

if __name__ == '__main__':
    main()