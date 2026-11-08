import os
import zipfile
import subprocess
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# লগিং সেটআপ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ⚠️ এখানে আপনার বটের টোকেনটি বসান (Render-এ Environment Variable দিলে এটি এমনিই থাকবে)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# ⚠️ এখানে আপনার টেলিগ্রাম চ্যানেলের ইউজারনেম দিন
CHANNEL_USERNAME = "@YourChannelUsername" 

# ফোল্ডার সেটআপ
BASE_DIR = os.getcwd()
ZIP_FILE = os.path.join(BASE_DIR, "dpt-shell-v2.21.1.zip")
EXECUTABLE_DIR = os.path.join(BASE_DIR, "executable")
TEMP_DIR = os.path.join(BASE_DIR, "temp")

os.makedirs(TEMP_DIR, exist_ok=True)

# জিপ ফাইলটি এক্সট্রাক্ট করা (যদি আগে থেকে না করা থাকে)
if not os.path.exists(EXECUTABLE_DIR) and os.path.exists(ZIP_FILE):
    with zipfile.ZipFile(ZIP_FILE, 'r') as zip_ref:
        zip_ref.extractall(BASE_DIR)

# --- কমান্ড হ্যান্ডলার ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("ℹ️ View Protected APKs", callback_data='view')],
        [InlineKeyboardButton("🛡️ Protect New APK", callback_data='new'), InlineKeyboardButton("🗑️ Delete Data", callback_data='delete')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        "🌿⚠️ **Welcome to the APK Protector Bot!**\n\n"
        "We do not promote any illegal activities and strictly adhere to Telegram's new rules, "
        "ensuring that all discussions and resources are solely for improving Gaming skills.\n\n"
        "**What can this bot do?**\n"
        "I can protect your APK files using DPT-Shell to prevent reverse engineering."
    )
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# --- বাটন হ্যান্ডলার ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'view':
        await query.edit_message_text(text="📂 You haven't protected any APKs yet. Click 'Protect New APK' to start.")
        
    elif query.data == 'delete':
        for filename in os.listdir(TEMP_DIR):
            file_path = os.path.join(TEMP_DIR, filename)
            try:
                os.remove(file_path)
            except:
                pass
        await query.edit_message_text(text="🗑️ Your temporary data has been deleted successfully.")
        
    elif query.data == 'new':
        await query.edit_message_text(text="📤 Please send me the APK file you want to protect.")

# --- ফাইল রিসিভ এবং প্রোটেকশন লজিক ---
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    
    if not document.file_name.endswith('.apk'):
        await update.message.reply_text("❌ Please send a valid APK file (.apk).")
        return

    await update.message.reply_text("⏳ Processing your APK... Please wait a few moments.")
    
    # ফাইল ডাউনলোড করা
    file = await context.bot.get_file(document.file_id)
    input_apk_path = os.path.join(TEMP_DIR, document.file_name)
    await file.download_to_drive(input_apk_path)
    
    output_apk_name = document.file_name.replace(".apk", "_signed.apk")
    
    # জাভা কমান্ড রান করা (dpt.jar)
    try:
        command = [
            "java", "-jar", os.path.join(EXECUTABLE_DIR, "dpt.jar"), 
            "-f", input_apk_path
        ]
        
        result = subprocess.run(command, cwd=EXECUTABLE_DIR, capture_output=True, text=True)
        
        generated_file = os.path.join(EXECUTABLE_DIR, output_apk_name)
        
        if os.path.exists(generated_file):
            await update.message.reply_document(
                document=open(generated_file, 'rb'),
                filename=output_apk_name,
                caption="✅ **APK Protected Successfully!**\n\n🔹 DPT-Shell Protection Applied."
            )
            os.remove(generated_file)
            os.remove(input_apk_path)
        else:
            await update.message.reply_text("❌ Protection failed. The tool did not generate an output file. It might be an unsupported APK.")
            
    except Exception as e:
        logging.error(f"Error: {e}")
        await update.message.reply_text("❌ An error occurred during protection. Please try again later.")

# --- মেইন ফাংশন ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()