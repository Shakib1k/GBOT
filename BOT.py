import os
import zipfile
import subprocess
import logging
import sqlite3
import random
import string
import shutil
from flask import Flask, request, jsonify, render_template
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import threading
import asyncio

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE_DIR = os.getcwd()
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect('vip_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (tg_id TEXT PRIMARY KEY, key TEXT, credits INTEGER, is_logged_in INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS keys 
                 (key TEXT PRIMARY KEY, user_id TEXT, credits INTEGER, used INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, tg_id TEXT, apk_name TEXT, protection_type TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ==================== FLASK ADMIN API ====================
app = Flask(__name__, template_folder='templates')

@app.route('/admin')
def admin_panel():
    return render_template('admin.html')

@app.route('/generate_key', methods=['POST'])
def generate_key():
    data = request.json
    user_id = data.get('user_id')
    credits = data.get('credits')
    new_key = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
    
    conn = sqlite3.connect('vip_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO keys (key, user_id, credits) VALUES (?, ?, ?)", (new_key, user_id, credits))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "key": new_key})

@app.route('/get_keys')
def get_keys():
    conn = sqlite3.connect('vip_bot.db')
    c = conn.cursor()
    c.execute("SELECT key, user_id, credits FROM keys")
    keys = [{"key": row[0], "user_id": row[1], "credits": row[2]} for row in c.fetchall()]
    conn.close()
    return jsonify(keys)

def run_flask():
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))

# ==================== BOT LOGIC ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    conn = sqlite3.connect('vip_bot.db')
    c = conn.cursor()
    c.execute("SELECT is_logged_in, credits FROM users WHERE tg_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()

    if user and user[0] == 1:
        await show_main_menu(update, context, user[1])
    else:
        await update.message.reply_text("🔐 **Welcome! Please enter your Key to login.**\n\nExample: `ABCD123456`", parse_mode='Markdown')

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, credits):
    keyboard = [[InlineKeyboardButton(f"🛡️ Protect APK (Credits: {credits})", callback_data='protect')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("✅ **Login Successful!**\n\nClick below to protect your APK.", reply_markup=reply_markup)

async def handle_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    conn = sqlite3.connect('vip_bot.db')
    c = conn.cursor()
    
    c.execute("SELECT key, user_id, credits, used FROM keys WHERE key = ?", (text,))
    key_data = c.fetchone()
    
    if key_data and key_data[1] == user_id and key_data[3] == 0:
        credits = key_data[2]
        c.execute("INSERT OR REPLACE INTO users (tg_id, key, credits, is_logged_in) VALUES (?, ?, ?, 1)", (user_id, text, credits))
        c.execute("UPDATE keys SET used = 1 WHERE key = ?", (text,))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"🎉 **Login Successful!**\nYou have {credits} credits.")
        await show_main_menu(update, context, credits)
    else:
        conn.close()
        await update.message.reply_text("❌ Invalid Key, Key already used, or Key belongs to another user.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    user_id = str(update.effective_user.id)
    
    conn = sqlite3.connect('vip_bot.db')
    c = conn.cursor()
    c.execute("SELECT credits FROM users WHERE tg_id = ? AND is_logged_in = 1", (user_id,))
    user = c.fetchone()
    
    if not user or user[0] <= 0:
        conn.close()
        await update.message.reply_text("❌ You don't have enough credits or you are not logged in.")
        return

    if not document.file_name.endswith('.apk'):
        conn.close()
        await update.message.reply_text("❌ Please send a valid APK file.")
        return

    # Store the file for processing
    context.user_data['apk_id'] = document.file_id
    context.user_data['apk_name'] = document.file_name
    
    keyboard = [
        [InlineKeyboardButton("Google Protection", callback_data='prot_google')],
        [InlineKeyboardButton("Tencent (御安全) Protection", callback_data='prot_tencent')],
        [InlineKeyboardButton("⏭️ Skip Protection (Just Sign)", callback_data='prot_skip')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🛠️ **Select Protection Type:**", reply_markup=reply_markup)

async def handle_protection_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    choice = query.data
    user_id = str(query.from_user.id)
    
    if choice == 'protect':
        await query.edit_message_text("📤 Please send the APK file you want to protect.")
        return

    # Get APK
    file_id = context.user_data.get('apk_id')
    apk_name = context.user_data.get('apk_name')
    
    await query.edit_message_text("⏳ Processing... This may take 1-3 minutes.")

    file = await context.bot.get_file(file_id)
    input_path = os.path.join(TEMP_DIR, apk_name)
    await file.download_to_drive(input_path)

    # Setup DPT Shell
    executable_dir = os.path.join(BASE_DIR, "executable")
    if not os.path.exists(executable_dir):
        with zipfile.ZipFile(os.path.join(BASE_DIR, "dpt-shell-v2.21.1.zip"), 'r') as zip_ref:
            zip_ref.extractall(BASE_DIR)

    # Apply chosen protection logic
    # (Note: দপ্ত-শেল এর ভেতরে কাস্টম লিব বসানোর সিস্টেম পাইথন দিয়ে করা একটু কঠিন, তবে এখানে আমরা আলাদা ফোল্ডার থেকে ফাইল কপি করার সিমুলেশন করছি)
    if choice == 'prot_google':
        # এখানে আপনি চাইলে google প্রোটেকশন এর লজিক বসাতে পারেন
        pass 
    elif choice == 'prot_tencent':
        # এখানে আপনি চাইলে tencent প্রোটেকশন এর লজিক বসাতে পারেন
        pass
    # skip হলে কিছুই করবে না, শুধু সাইন করবে

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
            
            # Deduct Credit & Save History
            conn = sqlite3.connect('vip_bot.db')
            c = conn.cursor()
            c.execute("UPDATE users SET credits = credits - 1 WHERE tg_id = ?", (user_id,))
            c.execute("INSERT INTO history (tg_id, apk_name, protection_type) VALUES (?, ?, ?)", (user_id, output_name, choice))
            conn.commit()
            
            # Check remaining credits
            c.execute("SELECT credits FROM users WHERE tg_id = ?", (user_id,))
            rem_credits = c.fetchone()[0]
            conn.close()
            
            await query.message.reply_text(f"💳 Remaining Credits: {rem_credits}\n\nTo buy more credits, contact Admin.")
            
            os.remove(generated_file)
            os.remove(input_path)
        else:
            await query.message.reply_text("❌ Protection failed. Unsupported APK or memory issue.")
    except Exception as e:
        logging.error(e)
        await query.message.reply_text("❌ Error occurred during protection.")

# ==================== MAIN ====================
def main():
    # Start Web Server for Admin Panel
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Telegram Bot
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_login))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(CallbackQueryHandler(handle_protection_choice))
    
    print("Bot & Admin Panel are running...")
    application.run_polling()

if __name__ == '__main__':
    main()