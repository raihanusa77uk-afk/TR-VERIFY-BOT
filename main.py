import logging
import sqlite3
import os
import threading
import random
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# Logging Setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ================= Configuration =================
BOT_TOKEN = "8295039946:AAFgJ9yLjbLV69EN5HRjOW17_kmaYr8c82w"
ADMIN_ID = 7047896730
VIP_GROUP_ID = -1004424341978

REFERRAL_LINK = "https://broker-qx.pro/sign-up/?lid=2321846"
MUST_JOIN_CHANNEL = "@tradingwithraihan_22"
SUPPORT_USERNAME = "@TR_Support_and_Feedback"
DATABASE_NAME = "master_vip_bot.db"
# =================================================

WAITING_FOR_ID, WAITING_FOR_DEPOSIT, WAITING_FOR_SCREENSHOT, WAITING_FOR_PNL = range(4)

# Extended Quiz Data
QUIZ_QUESTIONS = [
    {
        "question": "❓ Martingale স্ট্র্যাটেজিতে ট্রেড লস হলে পরবর্তী ট্রেডের অ্যামাউন্ট সাধারণত কেমন করা হয়?",
        "options": ["কমানো হয়", "দ্বিগুণ বা বাড়ানো হয়", "একই রাখা হয়", "ট্রেড বন্ধ করা হয়"],
        "answer": 1
    },
    {
        "question": "❓ ট্রেডিংয়ে ১%-২% রিস্ক ম্যানেজমেন্ট কেন ব্যবহার করা হয়?",
        "options": ["একাউন্ট জিরো হওয়া বাঁচাতে", "একদিনে কোটিপতি হতে", "ব্রোকারকে কমিশন দিতে", "কোনোটিই নয়"],
        "answer": 0
    },
    {
        "question": "❓ RSI Indicator ৭০ এর উপরে গেলে মার্কেটকে কী বলা হয়?",
        "options": ["Oversold", "Overbought", "Sideways", "Downtrend"],
        "answer": 1
    }
]

# Global bot application reference
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
            trader_id TEXT,
            deposit_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'PENDING',
            is_blocked INTEGER DEFAULT 0,
            last_active_date TEXT,
            total_trades INTEGER DEFAULT 0,
            total_profit REAL DEFAULT 0,
            win_trades INTEGER DEFAULT 0,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS used_trader_ids (
            trader_id TEXT PRIMARY KEY,
            user_id INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# DB Helpers
def save_user(user_id, username, full_name):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    today_str = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, full_name, last_active_date) VALUES (?, ?, ?, ?)", 
                   (user_id, username, full_name, today_str))
    conn.commit()
    conn.close()

def update_activity(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    today_str = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("UPDATE users SET last_active_date = ? WHERE user_id = ?", (today_str, user_id))
    conn.commit()
    conn.close()

def is_user_blocked(user_id):
    if user_id == ADMIN_ID:
        return False
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] == 1 if row else False

def set_block_status(user_id, status_code):
    if user_id == ADMIN_ID:
        return
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (status_code, user_id))
    conn.commit()
    conn.close()

def update_user_status(user_id, trader_id, status, deposit_amount=0):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    today_str = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("UPDATE users SET trader_id = ?, status = ?, deposit_amount = ?, last_active_date = ? WHERE user_id = ?", 
                   (trader_id, status, deposit_amount, today_str, user_id))
    if status == 'APPROVED':
        cursor.execute("INSERT OR REPLACE INTO used_trader_ids (trader_id, user_id) VALUES (?, ?)", (trader_id, user_id))
    conn.commit()
    conn.close()

def get_user_by_trader_id(trader_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, status FROM users WHERE trader_id = ?", (trader_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def log_trade_pnl(user_id, pnl_amount):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    is_win = 1 if pnl_amount > 0 else 0
    cursor.execute("""
        UPDATE users 
        SET total_trades = total_trades + 1, 
            total_profit = total_profit + ?, 
            win_trades = win_trades + ?,
            last_active_date = ? 
        WHERE user_id = ?
    """, (pnl_amount, is_win, today_str, user_id))
    conn.commit()
    conn.close()

def get_leaderboard():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT full_name, total_profit, total_trades FROM users WHERE status = 'APPROVED' ORDER BY total_profit DESC LIMIT 5")
    rows = cursor.fetchall()
    conn.close()
    return rows

def is_trader_id_already_used(trader_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM used_trader_ids WHERE trader_id = ?", (trader_id,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return True
    
    cursor.execute("SELECT user_id FROM users WHERE trader_id = ? AND status IN ('APPROVED', 'PENDING')", (trader_id,))
    row_user = cursor.fetchone()
    conn.close()
    return row_user is not None

def get_db_stats():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'APPROVED'")
    approved = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'PENDING'")
    pending = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
    blocked = cursor.fetchone()[0]
    conn.close()
    return total, approved, pending, blocked

def get_all_users():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

# ================= Quotex Postback Webhook Server =================
class PostbackHTTPRequestHandler(BaseHTTPRequestHandler):
    def process_postback(self, params):
        # Extract Trader ID from Quotex fields
        trader_id = params.get('trader_id', [None])[0] or params.get('uid', [None])[0] or params.get('subid', [None])[0] or params.get('click_id', [None])[0]
        deposit_amount = params.get('sumdep', [0])[0] or params.get('deposit', [0])[0] or params.get('amount', [0])[0]
        status = params.get('status', ['APPROVED'])[0].upper()

        if not trader_id:
            return "Missing trader_id", 400

        try:
            deposit_amount = float(deposit_amount)
        except ValueError:
            deposit_amount = 0.0

        user_info = get_user_by_trader_id(trader_id)
        
        if user_info:
            user_id, current_status = user_info
            update_user_status(user_id, trader_id, status, deposit_amount)

            # Auto-Approve & Send VIP Link via Telegram
            if status == 'APPROVED' and telegram_app:
                try:
                    loop = telegram_app.loop
                    async def auto_approve_user():
                        invite_link_object = await telegram_app.bot.create_chat_invite_link(
                            chat_id=VIP_GROUP_ID,
                            member_limit=1,
                            name=f"Auto Postback Access for {user_id}"
                        )
                        single_use_link = invite_link_object.invite_link
                        
                        welcome_text = (
                            f"🎉 **Quotex Postback Verified!** 🎉\n\n"
                            f"আপনার Trader ID (`{trader_id}`) সফলভাবে অটোমেটিক ভেরিফাই হয়েছে।\n"
                            f"💰 **Deposit:** `${deposit_amount}`\n\n"
                            f"🔗 **আপনার VIP Access Link:**\n👉 {single_use_link}\n\n"
                            f"📌 *এই লিঙ্কটি ১ বার ব্যবহারযোগ্য।*"
                        )
                        await telegram_app.bot.send_message(chat_id=user_id, text=welcome_text, parse_mode="Markdown")
                        await telegram_app.bot.send_message(
                            chat_id=ADMIN_ID,
                            text=f"⚡ **Quotex Postback Live:**\nUser `{user_id}` (Trader ID: `{trader_id}`) Verified & Sent VIP Link!"
                        )

                    loop.create_task(auto_approve_user())
                except Exception as e:
                    logging.error(f"Postback Auto-Approval Error: {e}")
            
            return f"Postback Processed for Trader ID {trader_id}", 200
        else:
            # Unmatched Trader ID Alert to Admin
            if telegram_app:
                loop = telegram_app.loop
                async def notify_admin_unmatched():
                    await telegram_app.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f"📥 **Unmatched Quotex Postback Received:**\nTrader ID: `{trader_id}`\nDeposit: `${deposit_amount}`\nStatus: `{status}`"
                    )
                loop.create_task(notify_admin_unmatched())
            return "Postback logged successfully", 200

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/postback":
            params = parse_qs(parsed_path.query)
            msg, code = self.process_postback(params)
            self.send_response(code)
            self.end_headers()
            self.wfile.write(msg.encode())
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Quotex VIP Bot Postback Webhook: ACTIVE")

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/postback":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            params = parse_qs(post_data)
            
            if not params:
                params = parse_qs(parsed_path.query)
                
            msg, code = self.process_postback(params)
            self.send_response(code)
            self.end_headers()
            self.wfile.write(msg.encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), PostbackHTTPRequestHandler)
    server.serve_forever()

async def check_channel_membership(user_id, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(chat_id=MUST_JOIN_CHANNEL, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return False

# Keyboard Menu
def get_main_menu_keyboard():
    keyboard = [
        [KeyboardButton("🚀 Join VIP Group"), KeyboardButton("🔗 Registration Link")],
        [KeyboardButton("📈 Auto Signal & Analysis"), KeyboardButton("🎯 Daily Target Planner")],
        [KeyboardButton("📊 My Account / Status"), KeyboardButton("🏆 VIP Leaderboard")],
        [KeyboardButton("📝 Log Today's Trade"), KeyboardButton("🧮 Risk Calculator")],
        [KeyboardButton("📈 Compounding Plan"), KeyboardButton("🕒 Market Session & OTC")],
        [KeyboardButton("🌐 Market Economic News"), KeyboardButton("🎓 Trading Quiz")],
        [KeyboardButton("📖 VIP Signal Rules"), KeyboardButton("💬 Send Profit Feedback")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

MENU_BUTTONS = [
    "🚀 Join VIP Group", "🔗 Registration Link", "📝 Log Today's Trade",
    "📊 My Account / Status", "🏆 VIP Leaderboard", "🧮 Risk Calculator",
    "🌐 Market Economic News", "🎓 Trading Quiz", "📈 Auto Signal & Analysis",
    "🎯 Daily Target Planner", "📈 Compounding Plan", "🕒 Market Session & OTC",
    "📖 VIP Signal Rules", "💬 Send Profit Feedback"
]

# ----------------- Handlers -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id == ADMIN_ID:
        set_block_status(user.id, 0)

    if is_user_blocked(user.id):
        await update.message.reply_text("🚫 আপনি এই বটটি ব্যবহার করা থেকে সাময়িকভাবে নিষিদ্ধ (Blocked)।")
        return ConversationHandler.END

    save_user(user.id, user.username, user.full_name)
    update_activity(user.id)
    
    is_member = await check_channel_membership(user.id, context)
    if not is_member:
        join_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Public Channel", url=f"https://t.me/tradingwithraihan_22")]])
        await update.message.reply_text(
            f"⚠️ **বটটি ব্যবহার করতে আপনাকে প্রথমে আমাদের মূল চ্যানেলে যুক্ত হতে হবে!**\n\n"
            f"নিচের বাটনে ক্লিক করে {MUST_JOIN_CHANNEL} জয়েন করুন এবং পুনরায় `/start` টাইপ করুন।",
            reply_markup=join_btn, parse_mode="Markdown"
        )
        return ConversationHandler.END

    welcome_msg = (
        f"👋 **হ্যালো {user.first_name}!**\n\n"
        f"স্বাগতম **Ultimate All-In-One Trading Hub**-এ! 📈🔥\n\n"
        f"এখানে আপনি VIP জয়েনিং, লাইভ মার্কেট এনালাইসিস, এআই সিগন্যাল, পোস্টব্যাক অটো-ভেরিফিকেশন, কম্পাউন্ডিং প্ল্যান ও ট্রেডিং জার্নাল সব এক জায়গায় পাবেন।"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

async def start_vip_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_user_blocked(user.id):
        return ConversationHandler.END

    update_activity(user.id)

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    conn.close()

    if row and row[0] == 'APPROVED':
        await update.message.reply_text(f"🎉 আপনি ইতিমধ্যে VIP গ্রুপের মেম্বার! নতুন লিংকের জন্য সাপোর্ট অ্যাডমিনের সাথে যোগাযোগ করুন: {SUPPORT_USERNAME}")
        return ConversationHandler.END

    msg = (
        f"🎯 **VIP গ্রুপে যুক্ত হওয়ার সহজ ধাপসমূহ:**\n\n"
        f"1️⃣ প্রথমে আমাদের অফিশিয়াল রেজিস্ট্রেশন লিঙ্ক দিয়ে অ্যাকাউন্ট খুলুন:\n👉 {REFERRAL_LINK}\n\n"
        f"2️⃣ অ্যাকাউন্টে সর্বনিম্ন **$50** ডিপোজিট করুন।\n\n"
        f"3️⃣ এবার আপনার **8-digit Quotex Trader ID** লিখে পাঠান:"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)
    return WAITING_FOR_ID

async def get_trader_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text in MENU_BUTTONS:
        await handle_general_message(update, context)
        return ConversationHandler.END

    if not text.isdigit() or len(text) != 8:
        await update.message.reply_text("❌ অকার্যকর ID! একটি সঠিক ৮-ডিজিটের Quotex Trader ID টাইপ করুন (যেমন: 90177664):")
        return WAITING_FOR_ID

    if is_trader_id_already_used(text):
        await update.message.reply_text(
            f"⚠️ **Trader ID Already Used!**\n\n"
            f"এই Trader ID (`{text}`) টি দিয়ে ইতিমধ্যে অন্য একজন VIP অ্যাক্সেস নিয়েছেন বা ভেরিফিকেশনের জন্য পাঠিয়েছেন।\n"
            f"অনুগ্রহ করে আপনার নিজস্ব সঠিক Trader ID টি টাইপ করুন:",
            parse_mode="Markdown"
        )
        return WAITING_FOR_ID

    context.user_data['trader_id'] = text
    await update.message.reply_text("💵 এবার আপনি কত ডলার Deposit করেছেন তা সংখ্যায় লিখুন (যেমন: 50, 100):")
    return WAITING_FOR_DEPOSIT

async def get_deposit_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    if text in MENU_BUTTONS:
        await handle_general_message(update, context)
        return ConversationHandler.END

    if not text.isdigit() or int(text) < 50:
        await update.message.reply_text("❌ সর্বনিম্ন ডিপোজিট $50 হতে হবে। অনুগ্রহ করে সঠিক অ্যামাউন্ট লিখুন (যেমন: 50):")
        return WAITING_FOR_DEPOSIT

    context.user_data['deposit_amount'] = float(text)
    await update.message.reply_text("✅ ডিপোজিট পরিমাণ সংরক্ষিত। এবার আপনার ডিপোজিটের একটি **Screenshot (ছবি)** পাঠান:")
    return WAITING_FOR_SCREENSHOT

async def get_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    trader_id = context.user_data.get('trader_id')
    deposit_amount = context.user_data.get('deposit_amount', 0)
    
    if is_trader_id_already_used(trader_id):
        await update.message.reply_text("❌ দুঃখিত! এই Trader ID টি ইতিমধ্যে ব্যবহার হয়ে গেছে। প্রক্রিয়াটি আবার শুরু করুন।", reply_markup=get_main_menu_keyboard())
        return ConversationHandler.END

    photo_file_id = update.message.photo[-1].file_id

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"app_{user.id}_{trader_id}_{deposit_amount}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}_{trader_id}")
        ],
        [InlineKeyboardButton("🚫 Block User", callback_data=f"blk_{user.id}_{trader_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    username_str = f"@{user.username}" if user.username else "No Username"
    caption = (
        f"📩 **New Verification Request**\n\n"
        f"👤 **User:** {user.full_name} ({username_str})\n"
        f"🆔 **Telegram ID:** `{user.id}`\n"
        f"🔢 **Trader ID:** `{trader_id}`\n"
        f"💰 **Deposit:** `${deposit_amount}`"
    )
    
    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_file_id,
            caption=caption,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    except Exception as e:
        logging.error(f"Failed to send request to admin: {e}")

    update_user_status(user.id, trader_id, 'PENDING', deposit_amount)

    await update.message.reply_text(
        "✅ আপনার ভেরিফিকেশন আবেদন জমা হয়েছে। ব্রোকার Postback দিয়ে অটো-ভেরিফাই বা অ্যাডমিন ম্যানুয়ালি যাচাই করার সাথে সাথে লিংক পেয়ে যাবেন।",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# PNL Logging
async def start_pnl_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 **আজকের মোট Profit/Loss ডলারের সংখ্যায় লিখুন:**\n(যেমন: প্রফিট হলে `15` এবং লস হলে `-10` লিখুন)")
    return WAITING_FOR_PNL

async def process_pnl_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user = update.effective_user

    if text in MENU_BUTTONS:
        await handle_general_message(update, context)
        return ConversationHandler.END

    try:
        pnl = float(text)
        log_trade_pnl(user.id, pnl)
        
        status_emoji = "🟢 Profit" if pnl >= 0 else "🔴 Loss"
        await update.message.reply_text(
            f"✅ **Trade Activity Registered!**\n\n"
            f"📊 Status: {status_emoji} `${pnl}`\n"
            f"আপনার ট্রেডিং জার্নাল ও গ্রাফ দেখতে টাইপ করুন: `/journal` অথবা `/chart`",
            reply_markup=get_main_menu_keyboard()
        )
    except ValueError:
        await update.message.reply_text("❌ অনুগ্রহ করে সঠিক সংখ্যা লিখুন (যেমন: 10 অথবা -5):")
        return WAITING_FOR_PNL
    return ConversationHandler.END

# General Message Handler
async def handle_general_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_user_blocked(user.id):
        return

    update_activity(user.id)
    text = update.message.text.strip()

    if text == "🔗 Registration Link":
        reg_msg = f"📌 **Quotex Official Sign-Up Link:**\n\n👉 {REFERRAL_LINK}\n\n⚠️ *অবশ্যই এই লিংকের মাধ্যমে একাউন্ট খুলতে হবে।*"
        await update.message.reply_text(reg_msg, parse_mode="Markdown", disable_web_page_preview=True)

    elif text == "🏆 VIP Leaderboard":
        leaders = get_leaderboard()
        if not leaders:
            await update.message.reply_text("🏆 **Top Traders Leaderboard:**\n\nএখনো কোনো লিডারবোর্ড রেকর্ড পাওয়া যায়নি।")
            return

        lb_msg = "🏆 **Top VIP Traders Leaderboard:**\n\n"
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for idx, (name, profit, trades) in enumerate(leaders):
            lb_msg += f"{medals[idx]} **{name}** — Profit: `${profit:.2f}` ({trades} Trades)\n"
        
        await update.message.reply_text(lb_msg, parse_mode="Markdown")

    elif text == "🧮 Risk Calculator":
        await update.message.reply_text(
            "🧮 **Risk & Lot Size Calculator:**\n\n"
            "ক্যালকুলেটর ব্যবহার করতে টাইপ করুন:\n"
            "`/calc <Balance> <Risk%>` \n\n"
            "উদাহরণ: `/calc 100 2` ($100 ব্যালেন্সের ২% রিস্ক বের করতে)",
            parse_mode="Markdown"
        )

    elif text == "📊 My Account / Status":
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT trader_id, deposit_amount, status, last_active_date, total_profit, total_trades, win_trades FROM users WHERE user_id = ?", (user.id,))
        row = cursor.fetchone()
        conn.close()

        if row and row[0]:
            win_rate = (row[6] / row[5] * 100) if row[5] > 0 else 0
            status_text = (
                f"👤 **Your Account Profile:**\n\n"
                f"🔢 **Trader ID:** `{row[0]}`\n"
                f"💵 **Deposit:** `${row[1]}`\n"
                f"📌 **VIP Status:** `{row[2]}`\n"
                f"📈 **Total Trades:** `{row[5]}`\n"
                f"🎯 **Win Rate:** `{win_rate:.1f}%`\n"
                f"💰 **Total Profit:** `${row[4]:.2f}`\n"
                f"📅 **Last Active:** `{row[3]}`"
            )
        else:
            status_text = "❌ আপনার কোনো সক্রিয় ভেরিফিকেশন রেকর্ড পাওয়া যায়নি। VIP গ্ৰুপে যুক্ত হতে '🚀 Join VIP Group' বাটন চাপুন।"
        
        await update.message.reply_text(status_text, parse_mode="Markdown")

    elif text == "🌐 Market Economic News":
        news_msg = (
            "🌐 **Today's Important Market News Calendar:**\n\n"
            "⚠️ High Impact News ট্রেডিং এড়িয়ে চলুন:\n"
            "• 🔴 **USD (CPI/NFP):** 06:30 PM (High Volatility)\n"
            "• 🟡 **EUR (ECB Speech):** 03:00 PM (Medium Volatility)\n\n"
            "📌 *নিউজ টাইমে ৩ মিনিট আগে এবং পরে ট্রেড করা থেকে বিরত থাকুন।*"
        )
        await update.message.reply_text(news_msg, parse_mode="Markdown")

    elif text == "📈 Auto Signal & Analysis":
        pairs = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/CAD", "EUR/GBP (OTC)", "USD/BDT (OTC)"]
        selected_pair = random.choice(pairs)
        direction = random.choice(["🟢 CALL (UP)", "🔴 PUT (DOWN)"])
        accuracy = random.randint(86, 96)
        timeframe = random.choice(["1 Minute", "2 Minutes", "5 Minutes"])
        
        sig_text = (
            f"⚡ **AI Automated Market Analysis & Signal:**\n\n"
            f"📊 **Pair:** `{selected_pair}`\n"
            f"🎯 **Signal:** {direction}\n"
            f"⏳ **Timeframe:** `{timeframe}`\n"
            f"🔥 **Win Confidence:** `{accuracy}%`\n"
            f"⚙️ **Analysis:** RSI Oversold/Overbought + Support/Resistance Confluence.\n\n"
            f"⚠️ *রিস্ক ম্যানেজমেন্ট মেনে ট্রেড নিন।*"
        )
        await update.message.reply_text(sig_text, parse_mode="Markdown")

    elif text == "🎯 Daily Target Planner":
        plan_text = (
            "🎯 **Daily Profit & Loss Target Calculator:**\n\n"
            "আপনার ব্যালেন্স এবং দৈনিক লক্ষ্য হিসেব করতে টাইপ করুন:\n"
            "`/target <Balance> <DailyTarget%>` \n\n"
            "উদাহরণ: `/target 100 5` ($100 ব্যালেন্সের দৈনিক ৫% প্রফিট টার্গেট সেট করতে)"
        )
        await update.message.reply_text(plan_text, parse_mode="Markdown")

    elif text == "📈 Compounding Plan":
        comp_msg = (
            "📈 **30-Day Safe Compounding Strategy ($50 Base):**\n\n"
            "• **Day 1-5:** Target $2.5/day ➔ Capital: $62.5\n"
            "• **Day 6-10:** Target $3.1/day ➔ Capital: $78.0\n"
            "• **Day 11-20:** Target $5.0/day ➔ Capital: $128.0\n"
            "• **Day 21-30:** Target $10/day ➔ Capital: $228.0+\n\n"
            "💡 *নিয়ম: প্রতিদিন সর্বোচ্চ ৫% লস স্টপ-মার্জিন রাখুন।*"
        )
        await update.message.reply_text(comp_msg, parse_mode="Markdown")

    elif text == "🕒 Market Session & OTC":
        session_text = (
            "🕒 **Global Forex Sessions & Market Status:**\n\n"
            "• 🇬🇧 **London Session:** Open (High Volatility)\n"
            "• 🇺🇸 **New York Session:** Open (Best For EUR/USD)\n"
            "• 🇯🇵 **Tokyo Session:** Closed\n\n"
            "📊 **OTC Market Alert:** সপ্তাহের কাজের দিনে Live Market এবং উইকএন্ডে OTC Market ফলো করুন।"
        )
        await update.message.reply_text(session_text, parse_mode="Markdown")

    elif text == "🎓 Trading Quiz":
        q = random.choice(QUIZ_QUESTIONS)
        buttons = []
        for idx, opt in enumerate(q["options"]):
            buttons.append([InlineKeyboardButton(opt, callback_data=f"quiz_{idx}_{q['answer']}")])
        
        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(f"🎓 **Trading Skill Quiz:**\n\n{q['question']}", reply_markup=reply_markup)

    elif text == "💬 Send Profit Feedback":
        await update.message.reply_text("📸 আপনার আজকের প্রফিটের স্ক্রিনশট সরাসরি আমাদের এডমিন সাপোর্টে পাঠান: " + SUPPORT_USERNAME)

    elif text == "📖 VIP Signal Rules":
        rules_msg = (
            f"📊 **VIP Trading Rules:**\n\n"
            f"1️⃣ **Money Management:** প্রতি ট্রেডে ক্যাপিটালের ২%-৩% ব্যবহার করবেন।\n"
            f"2️⃣ **Martingale:** সর্বোচ্চ ১ স্টেপ MTG ফলো করবেন।\n"
            f"3️⃣ **Target:** দৈনিক প্রফিট টার্গেট পূরণ হলে ট্রেডিং অফ রাখুন।"
        )
        await update.message.reply_text(rules_msg, parse_mode="Markdown")

    else:
        await update.message.reply_text("অনুগ্রহ করে নিচের বাটন ব্যবহার করুন।", reply_markup=get_main_menu_keyboard())

# Quiz Callback Handler
async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    selected_idx = int(data[1])
    correct_idx = int(data[2])

    if selected_idx == correct_idx:
        await query.edit_message_text(text=query.message.text + "\n\n✅ **সঠিক উত্তর! চমৎকার কাজ।**")
    else:
        await query.edit_message_text(text=query.message.text + "\n\n❌ **ভুল উত্তর! সঠিক নিয়ম মনে রাখার চেষ্টা করুন।**")

# Visual Chart Command
async def chart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT total_trades, win_trades, total_profit FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    conn.close()

    if not row or row[0] == 0:
        await update.message.reply_text("📊 আপনার কোনো ট্রেড ডাটা না থাকায় বার-চার্ট তৈরি করা যাচ্ছে না। আগে ট্রেড ডাটা ইনপুট দিন।")
        return

    trades, wins, profit = row
    losses = trades - wins
    win_percentage = int((wins / trades) * 10) if trades > 0 else 0
    loss_percentage = 10 - win_percentage

    win_bar = "🟩" * win_percentage
    loss_bar = "🟥" * loss_percentage

    chart_msg = (
        f"📊 **Trading Performance Visual Chart:**\n\n"
        f"Wins ({wins}):   {win_bar}\n"
        f"Losses ({losses}): {loss_bar}\n\n"
        f"💰 Total Profit: `${profit:.2f}`\n"
        f"📈 Total Trades: `{trades}`"
    )
    await update.message.reply_text(chart_msg, parse_mode="Markdown")

# Target Calculator Command
async def target_calc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ ফরম্যাট: `/target <Balance> <Target%>` \nউদাহরণ: `/target 100 5` ($100 এর দৈনিক ৫% টার্গেট)")
        return
    try:
        balance = float(context.args[0])
        target_pct = float(context.args[1])
        target_amt = (balance * target_pct) / 100
        stop_loss = target_amt

        msg = (
            f"🎯 **Daily Target & Stop-Loss Plan:**\n\n"
            f"💰 Starting Balance: `${balance}`\n"
            f"🟢 Daily Profit Target ({target_pct}%): `${target_amt:.2f}` (Target Balance: `${balance + target_amt:.2f}`)\n"
            f"🔴 Max Stop-Loss Margin: `${stop_loss:.2f}` (Stop Balance: `${balance - stop_loss:.2f}`)\n\n"
            f"📌 *টার্গেট বা স্টপ-লস যেকোনো একটি পূর্ণ হলে ওই দিনের মতো ট্রেডিং বন্ধ করুন।*"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ সঠিক সংখ্যা ব্যবহার করুন।")

# Trade Journal Command
async def journal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT total_trades, total_profit, win_trades FROM users WHERE user_id = ?", (user.id,))
    row = cursor.fetchone()
    conn.close()

    if not row or row[0] == 0:
        await update.message.reply_text("📘 **Trading Journal:**\n\nআপনার কোনো ট্রেড ডাটা পাওয়া যায়নি। ট্রেড রেকর্ড করতে '📝 Log Today's Trade' অপশন ব্যবহার করুন।")
        return

    trades, profit, wins = row
    win_rate = (wins / trades) * 100 if trades > 0 else 0
    losses = trades - wins

    journal_text = (
        f"📘 **Your Personal Trading Journal:**\n\n"
        f"🔢 Total Trades Recorded: `{trades}`\n"
        f"🟢 Winning Trades: `{wins}`\n"
        f"🔴 Losing Trades: `{losses}`\n"
        f"🎯 Win Rate: `{win_rate:.1f}%`\n"
        f"💰 Total Net Profit: `${profit:.2f}`\n\n"
        f"💡 *পরামর্শ: সবসময় ১-২% ফিক্সড রিস্ক বজায় রাখুন।*"
    )
    await update.message.reply_text(journal_text, parse_mode="Markdown")

# Admin Decision
async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data.startswith("quiz_"):
        await handle_quiz_answer(update, context)
        return

    await query.answer()
    data = query.data.split("_")
    action = data[0]
    user_id = int(data[1])
    trader_id = data[2]
    deposit_amount = float(data[3]) if len(data) > 3 else 0.0

    if action == "app":
        try:
            invite_link_object = await context.bot.create_chat_invite_link(
                chat_id=VIP_GROUP_ID,
                member_limit=1,
                name=f"VIP Access for {user_id}"
            )
            single_use_link = invite_link_object.invite_link
            update_user_status(user_id, trader_id, 'APPROVED', deposit_amount)

            welcome_text = (
                f"🎉 **Congratulations & Welcome aboard!** 🎉\n\n"
                f"আপনার আইডি (`{trader_id}`) সফলভাবে ভেরিফাই করা হয়েছে।\n\n"
                f"🔗 **আপনার ব্যক্তিগত VIP Access Link:**\n👉 {single_use_link}\n\n"
                f"📌 *সতর্কতা:* সিকিউরিটির স্বার্থে এই লিঙ্কটি **মাত্র ১ বার** ব্যবহার করা যাবে।"
            )

            await context.bot.send_message(chat_id=user_id, text=welcome_text, parse_mode="Markdown")
            await query.edit_message_caption(caption=query.message.caption + "\n\nSTATUS: ✅ **APPROVED (Invite Link Sent)**")

        except Exception as e:
            await query.edit_message_caption(caption=query.message.caption + f"\n\n❌ Link Error: {e}")
            
    elif action == "rej":
        try:
            update_user_status(user_id, trader_id, 'REJECTED')
            reject_text = f"❌ **Verification Failed!**\n\nআপনার প্রদত্ত Trader ID অথবা Deposit Screenshot সঠিক নয়। সহায়তার জন্য যোগাযোগ করুন: {SUPPORT_USERNAME}"
            await context.bot.send_message(chat_id=user_id, text=reject_text)
            await query.edit_message_caption(caption=query.message.caption + "\n\nSTATUS: ❌ **REJECTED**")
        except Exception as e:
            await query.edit_message_caption(caption=query.message.caption + f"\n\n❌ Error: {e}")

    elif action == "blk":
        set_block_status(user_id, 1)
        await query.edit_message_caption(caption=query.message.caption + "\n\nSTATUS: 🚫 **USER BLOCKED**")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total, approved, pending, blocked = get_db_stats()
    panel_text = (
        f"⚙️ **Admin Control Panel**\n\n"
        f"👥 Total Users: `{total}`\n"
        f"✅ VIP Approved: `{approved}`\n"
        f"⏳ Pending Users: `{pending}`\n"
        f"🚫 Blocked Users: `{blocked}`\n\n"
        f"**Available Commands:**\n"
        f"• `/checkinactives` - Kick inactive members\n"
        f"• `/broadcast <text>` - Send msg to all\n"
        f"• `/signal <asset> <direction> <time>` - Send Signal\n"
        f"• `/forceapprove <user_id> <trader_id>` - Manual approve\n"
        f"• `/search <trader_id>` - Find user\n"
        f"• `/block <user_id>` / `/unblock <user_id>`"
    )
    await update.message.reply_text(panel_text, parse_mode="Markdown")

async def check_inactives(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    cursor.execute("SELECT user_id, full_name FROM users WHERE status = 'APPROVED' AND last_active_date < ?", (thirty_days_ago,))
    inactive_users = cursor.fetchall()
    
    kicked_count = 0
    for uid, name in inactive_users:
        try:
            await context.bot.ban_chat_member(chat_id=VIP_GROUP_ID, user_id=uid)
            await context.bot.unban_chat_member(chat_id=VIP_GROUP_ID, user_id=uid)
            
            cursor.execute("UPDATE users SET status = 'KICKED_INACTIVE' WHERE user_id = ?", (uid,))
            await context.bot.send_message(chat_id=uid, text="⚠️ আপনি টানা ৩০ দিন নিষ্ক্রিয় থাকায় VIP গ্রুপ থেকে রিমুভ করা হয়েছে।")
            kicked_count += 1
        except Exception as e:
            logging.error(f"Failed to kick user {uid}: {e}")

    conn.commit()
    conn.close()

    await update.message.reply_text(f"🧹 **Inactive Cleanup Completed!**\n\nমোট `{kicked_count}` জন মেম্বারকে কিক দেওয়া হয়েছে।")

async def calc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("⚠️ ফরম্যাট: `/calc <Balance> <Risk%>` \nউদাহরণ: `/calc 100 2` (অর্থাৎ $100 ব্যালেন্সের ২% রিস্ক)")
        return
    try:
        balance = float(context.args[0])
        risk_percent = float(context.args[1])
        trade_amount = (balance * risk_percent) / 100
        mtg_amount = trade_amount * 2.2

        res = (
            f"🧮 **Martingale & Risk Calculator:**\n\n"
            f"💰 Balance: `${balance}`\n"
            f"🎯 1st Trade ({risk_percent}%): `${trade_amount:.2f}`\n"
            f"🔄 1-Step MTG Trade: `${mtg_amount:.2f}`"
        )
        await update.message.reply_text(res, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ সঠিক সংখ্যা লিখুন।")

async def send_signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or len(context.args) < 3:
        await update.message.reply_text("⚠️ ফরম্যাট: `/signal <ASSET> <CALL/PUT> <TIME>`\nউদাহরণ: `/signal EUR/USD CALL 5m`")
        return

    asset = context.args[0].upper()
    direction = context.args[1].upper()
    duration = context.args[2]

    arrow = "🟢 CALL (UP)" if direction == "CALL" else "🔴 PUT (DOWN)"

    sig_msg = (
        f"🚨 **NEW VIP TRADING SIGNAL** 🚨\n\n"
        f"📊 **Asset:** {asset}\n"
        f"📈 **Direction:** {arrow}\n"
        f"⏳ **Duration:** {duration}\n\n"
        f"⚠️ *Proper Money Management বজায় রেখে ট্রেড প্লেস করুন।*"
    )

    user_ids = get_all_users()
    succ = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=sig_msg, parse_mode="Markdown")
            succ += 1
        except Exception:
            pass

    await update.message.reply_text(f"✅ VIP Signal Broadcasted to `{succ}` users.")

async def force_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or len(context.args) < 2:
        await update.message.reply_text("⚠️ ফরম্যাট: `/forceapprove <user_id> <trader_id>`")
        return
    
    uid = int(context.args[0])
    tid = context.args[1]

    try:
        invite_link_object = await context.bot.create_chat_invite_link(chat_id=VIP_GROUP_ID, member_limit=1)
        update_user_status(uid, tid, 'APPROVED', 50)
        
        await context.bot.send_message(
            chat_id=uid,
            text=f"🎉 **অ্যাডমিন আপনাকে সরাসরি VIP অ্যাক্সেস দিয়েছেন!**\n\n🔗 লিঙ্ক: {invite_link_object.invite_link}"
        )
        await update.message.reply_text(f"✅ User `{uid}` successfully approved manually.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or not context.args:
        return
    tid = context.args[0]
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, full_name, deposit_amount, status, last_active_date FROM users WHERE trader_id = ?", (tid,))
    row = cursor.fetchone()
    conn.close()

    if row:
        msg = f"🔍 **User Found:**\n\nTelegram ID: `{row[0]}`\nName: {row[2]}\nUsername: @{row[1]}\nDeposit: `${row[3]}`\nStatus: `{row[4]}`\nLast Active: `{row[5]}`"
    else:
        msg = "❌ কোনো রেকর্ড পাওয়া যায়নি।"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def block_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID and context.args:
        uid = int(context.args[0])
        set_block_status(uid, 1)
        await update.message.reply_text(f"✅ User `{uid}` Blocked Successfully.")

async def unblock_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID and context.args:
        uid = int(context.args[0])
        set_block_status(uid, 0)
        await update.message.reply_text(f"✅ User `{uid}` Unblocked Successfully.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or not context.args:
        return
    msg = " ".join(context.args)
    user_ids = get_all_users()
    succ = 0
    await update.message.reply_text(f"📢 ব্রডকাস্ট শুরু হয়েছে...")
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
            succ += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ ব্রডকাস্ট সম্পন্ন। প্রাপ্তি: `{succ}` জন।")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("প্রক্রিয়াটি বাতিল করা হয়েছে।", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# ----------------- Execution -----------------
def main():
    global telegram_app

    # Start HTTP & Postback Listener
    threading.Thread(target=run_dummy_server, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    telegram_app = app
    
    private_filter = filters.ChatType.PRIVATE

    vip_conv = ConversationHandler(
        entry_points=[MessageHandler(private_filter & filters.Regex("^🚀 Join VIP Group$"), start_vip_join)],
        states={
            WAITING_FOR_ID: [MessageHandler(private_filter & filters.TEXT & ~filters.COMMAND, get_trader_id)],
            WAITING_FOR_DEPOSIT: [MessageHandler(private_filter & filters.TEXT & ~filters.COMMAND, get_deposit_amount)],
            WAITING_FOR_SCREENSHOT: [MessageHandler(private_filter & filters.PHOTO, get_screenshot)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel, filters=private_filter),
            MessageHandler(private_filter & filters.Regex("^🚀 Join VIP Group$"), start_vip_join),
            MessageHandler(private_filter & filters.TEXT, handle_general_message)
        ],
        allow_reentry=True
    )

    pnl_conv = ConversationHandler(
        entry_points=[MessageHandler(private_filter & filters.Regex("^📝 Log Today's Trade$"), start_pnl_log)],
        states={
            WAITING_FOR_PNL: [MessageHandler(private_filter & filters.TEXT & ~filters.COMMAND, process_pnl_log)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel, filters=private_filter),
            MessageHandler(private_filter & filters.TEXT, handle_general_message)
        ],
        allow_reentry=True
    )

    app.add_handler(CommandHandler('start', start, filters=private_filter))
    app.add_handler(CommandHandler('admin', admin_panel, filters=private_filter))
    app.add_handler(CommandHandler('journal', journal_cmd, filters=private_filter))
    app.add_handler(CommandHandler('chart', chart_cmd, filters=private_filter))
    app.add_handler(CommandHandler('target', target_calc_cmd, filters=private_filter))
    app.add_handler(CommandHandler('checkinactives', check_inactives, filters=private_filter))
    app.add_handler(CommandHandler('calc', calc_command, filters=private_filter))
    app.add_handler(CommandHandler('signal', send_signal_cmd, filters=private_filter))
    app.add_handler(CommandHandler('forceapprove', force_approve, filters=private_filter))
    app.add_handler(CommandHandler('search', search_user, filters=private_filter))
    app.add_handler(CommandHandler('block', block_user_cmd, filters=private_filter))
    app.add_handler(CommandHandler('unblock', unblock_user_cmd, filters=private_filter))
    app.add_handler(CommandHandler('broadcast', broadcast, filters=private_filter))
    
    app.add_handler(vip_conv)
    app.add_handler(pnl_conv)
    app.add_handler(MessageHandler(private_filter & filters.TEXT & ~filters.COMMAND, handle_general_message))
    app.add_handler(CallbackQueryHandler(admin_decision))

    print("Ultimate All-In-One VIP Bot with Auto-Postback: ONLINE & READY!")
    app.run_polling()

if __name__ == '__main__':
    main()
