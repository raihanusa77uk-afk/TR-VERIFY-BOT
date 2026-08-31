import logging
import sqlite3
import os
import threading
from urllib.parse import parse_qs, urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ================= Configuration =================
BOT_TOKEN = "8295039946:AAF9Tz23T5vsm0RRS5VVb_c46Ydt8m7-Otc"
ADMIN_ID = 7047896730
VIP_GROUP_ID = -1004424341978

REFERRAL_LINK = "https://broker-qx.pro/sign-up/?lid=2321846"
PUBLIC_CHANNEL_LINK = "https://t.me/tradingwithraihan_22"
SUPPORT_USERNAME = "@TR_Support_and_Feedback"
DATABASE_NAME = "clean_vip_bot.db"
# =================================================

WAITING_FOR_ID, WAITING_FOR_FEEDBACK = range(2)
telegram_app = None

# Database Setup
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            trader_id TEXT UNIQUE,
            deposit_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'PENDING',
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_user(user_id, username, full_name):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)", 
                   (user_id, username, full_name))
    conn.commit()
    conn.close()

def set_trader_id(user_id, trader_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET trader_id = ? WHERE user_id = ?", (trader_id, user_id))
    conn.commit()
    conn.close()

def process_broker_postback(trader_id, deposit_amount):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE trader_id = ?", (trader_id,))
    row = cursor.fetchone()
    
    if row:
        user_id = row[0]
        cursor.execute("UPDATE users SET deposit_amount = deposit_amount + ?, status = 'APPROVED' WHERE trader_id = ?", 
                       (deposit_amount, trader_id))
        conn.commit()
        conn.close()
        return user_id
    conn.close()
    return None

# ================= Automatic Postback Engine =================
class PostbackHTTPRequestHandler(BaseHTTPRequestHandler):
    def process_request(self, params):
        trader_id = params.get('trader_id', [None])[0] or params.get('subid', [None])[0] or params.get('uid', [None])[0]
        deposit_amount = params.get('sumdep', [0])[0] or params.get('deposit', [0])[0]

        if not trader_id:
            return "Missing trader_id", 400

        try:
            deposit_amount = float(deposit_amount)
        except ValueError:
            deposit_amount = 0.0

        user_id = process_broker_postback(trader_id, deposit_amount)

        if user_id and telegram_app:
            loop = telegram_app.loop
            async def send_vip_access():
                if deposit_amount >= 50:
                    invite = await telegram_app.bot.create_chat_invite_link(
                        chat_id=VIP_GROUP_ID,
                        member_limit=1
                    )
                    
                    user_msg = (
                        f"🎉 **স্বয়ংক্রিয় ভেরিফিকেশন সফল!** 🎉\n\n"
                        f"আপনার ডিপোজিট (${deposit_amount}) নিশ্চিত হয়েছে।\n\n"
                        f"🔗 **VIP Group Invite Link:**\n👉 {invite.invite_link}\n\n"
                        f"📌 *লিঙ্কটি ১ বার ব্যবহারযোগ্য।*"
                    )
                    await telegram_app.bot.send_message(chat_id=user_id, text=user_msg, parse_mode="Markdown")
                    
                    admin_log = f"⚡ **[Auto VIP Approval]**\nUser: `{user_id}` | Trader ID: `{trader_id}` | Deposit: `${deposit_amount}`"
                    await telegram_app.bot.send_message(chat_id=ADMIN_ID, text=admin_log, parse_mode="Markdown")
                else:
                    await telegram_app.bot.send_message(
                        chat_id=user_id,
                        text=f"📥 পোস্টব্যাক ডিপোজিট এসেছে `${deposit_amount}`, কিন্তু VIP-র জন্য নূন্যতম $50 প্রয়োজন।"
                    )

            loop.create_task(send_vip_access())
            return "OK", 200
        return "Logged", 200

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/postback":
            msg, code = self.process_request(parse_qs(parsed.query))
            self.send_response(code)
            self.end_headers()
            self.wfile.write(msg.encode())
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Server Active")

def start_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), PostbackHTTPRequestHandler)
    server.serve_forever()

# ================= Telegram UI & Logic =================
def get_clean_keyboard():
    keyboard = [
        [KeyboardButton("🚀 Join VIP Group"), KeyboardButton("🔗 Registration Link")],
        [KeyboardButton("📢 Public Channel Link"), KeyboardButton("💬 Send Profit Feedback")],
        [KeyboardButton("🆘 Help & Support")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

MENU_BUTTONS = ["🚀 Join VIP Group", "🔗 Registration Link", "📢 Public Channel Link", "💬 Send Profit Feedback", "🆘 Help & Support"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user.id, user.username, user.full_name)
    await update.message.reply_text(
        f"👋 **হ্যালো {user.first_name}!**\n\n"
        f"স্বাগতম **TRADING BY RAIHAN** অফিসিয়াল বটে। নিচের মেনু থেকে আপনার প্রয়োজনীয় অপশনটি বেছে নিন:",
        parse_mode="Markdown",
        reply_markup=get_clean_keyboard()
    )
    return ConversationHandler.END

# VIP Process
async def start_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        f"🎯 **VIP গ্রুপে যুক্ত হওয়ার নিয়ম:**\n\n"
        f"1️⃣ নিচের অফিশিয়াল লিঙ্ক দিয়ে অ্যাকাউন্ট খুলুন:\n👉 {REFERRAL_LINK}\n\n"
        f"2️⃣ অ্যাকাউন্টে সর্বনিম্ন **$50** ডিপোজিট করুন।\n\n"
        f"3️⃣ এবার আপনার **8-digit Quotex Trader ID** টি নিচে লিখে পাঠান:"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)
    return WAITING_FOR_ID

async def receive_trader_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user

    if text in MENU_BUTTONS:
        await handle_clean_menu(update, context)
        return ConversationHandler.END

    if not text.isdigit() or len(text) != 8:
        await update.message.reply_text("❌ অকার্যকর ID! সঠিক ৮-ডিজিটের Trader ID লিখুন (যেমন: 46123489):")
        return WAITING_FOR_ID

    set_trader_id(user.id, text)

    reply_msg = (
        f"✅ **Trader ID ({text}) সেভ করা হয়েছে!**\n\n"
        f"⏳ ব্রোকারে আপনার ডিপোজিট সম্পন্ন হওয়া মাত্রই অটোমেটিক পোস্টব্যাকের মাধ্যমে বট আপনাকে এই চ্যাটে VIP লিঙ্ক পাঠিয়ে দেবে।"
    )
    await update.message.reply_text(reply_msg, parse_mode="Markdown", reply_markup=get_clean_keyboard())
    return ConversationHandler.END

# Feedback Process
async def start_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💬 **আপনার প্রফিটের ফিডব্যাক, স্ক্রিনশট বা মেসেজটি লিখুন:**\n\n(এডমিন সরাসরি এটি দেখতে পাবেন)")
    return WAITING_FOR_FEEDBACK

async def receive_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip() if update.message.text else ""

    if text in MENU_BUTTONS:
        await handle_clean_menu(update, context)
        return ConversationHandler.END

    username_str = f"@{user.username}" if user.username else "No Username"
    admin_msg = f"📩 **New User Feedback!**\n\n👤 **From:** {user.full_name} ({username_str})\n🆔 **User ID:** `{user.id}`\n\n💬 **Message:**\n{text}"

    if update.message.photo:
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, caption=admin_msg, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")

    await update.message.reply_text("✅ আপনার ফিডব্যাক সফলভাবে এডমিনের কাছে পাঠানো হয়েছে। ধন্যবাদ!", reply_markup=get_clean_keyboard())
    return ConversationHandler.END

# Menu Buttons Handler
async def handle_clean_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text == "🔗 Registration Link":
        msg = f"📌 **Quotex Official Sign-Up Link:**\n\n👉 {REFERRAL_LINK}\n\n⚠️ *অবশ্যই এই লিংকের মাধ্যমে অ্যাকাউন্ট তৈরি করতে হবে।*"
        await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)

    elif text == "📢 Public Channel Link":
        msg = f"📢 **আমাদের অফিশিয়াল পাবলিক টেলিগ্রাম চ্যানেল:**\n\n👉 {PUBLIC_CHANNEL_LINK}"
        await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)

    elif text == "🆘 Help & Support":
        msg = f"🆘 **যে কোনো সমস্যায় বা সহায়তার জন্য যোগাযোগ করুন:**\n\n👨‍💻 Admin Support: {SUPPORT_USERNAME}"
        await update.message.reply_text(msg, parse_mode="Markdown")

    else:
        await update.message.reply_text("নিচের মেনু বাটন ব্যবহার করুন।", reply_markup=get_clean_keyboard())

def main():
    global telegram_app
    threading.Thread(target=start_server, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    telegram_app = app

    private_filter = filters.ChatType.PRIVATE

    vip_conv = ConversationHandler(
        entry_points=[MessageHandler(private_filter & filters.Regex("^🚀 Join VIP Group$"), start_vip)],
        states={
            WAITING_FOR_ID: [MessageHandler(private_filter & filters.TEXT & ~filters.COMMAND, receive_trader_id)]
        },
        fallbacks=[],
        allow_reentry=True
    )

    feedback_conv = ConversationHandler(
        entry_points=[MessageHandler(private_filter & filters.Regex("^💬 Send Profit Feedback$"), start_feedback)],
        states={
            WAITING_FOR_FEEDBACK: [MessageHandler(private_filter & (filters.TEXT | filters.PHOTO) & ~filters.COMMAND, receive_feedback)]
        },
        fallbacks=[],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start, filters=private_filter))
    app.add_handler(vip_conv)
    app.add_handler(feedback_conv)
    app.add_handler(MessageHandler(private_filter & filters.TEXT & ~filters.COMMAND, handle_clean_menu))

    print("Clean VIP Bot with 5 Key Features: ONLINE!")
    app.run_polling()

if __name__ == '__main__':
    main()
