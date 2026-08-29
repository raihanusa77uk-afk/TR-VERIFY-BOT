import logging
import sqlite3
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

# ================= Configuration (100% Configured) =================
BOT_TOKEN = "8295039946:AAFgJ9yLjbLV69EN5HRjOW17_kmaYr8c82w"
ADMIN_ID = 7047896730
VIP_GROUP_ID = -1004424341978

REFERRAL_LINK = "https://broker-qx.pro/sign-up/?lid=2321846"
MUST_JOIN_CHANNEL = "@tradingwithraihan_22"          # আপডেট করা পাবলিক চ্যানেল ইউজারনেম
SUPPORT_USERNAME = "@TR_Support_and_Feedback"        # আপডেট করা সাপোর্ট ইউজারনেম
DATABASE_NAME = "master_vip_bot.db"
# ====================================================================

WAITING_FOR_ID, WAITING_FOR_SCREENSHOT = range(2)

# ----------------- Database Setup -----------------
def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            trader_id TEXT,
            status TEXT DEFAULT 'PENDING',
            is_blocked INTEGER DEFAULT 0,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trader_ids (
            trader_id TEXT PRIMARY KEY,
            used_by_user_id INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# DB Helpers
def save_user(user_id, username, full_name):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)", 
                   (user_id, username, full_name))
    conn.commit()
    conn.close()

def is_user_blocked(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] == 1 if row else False

def set_block_status(user_id, status_code):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (status_code, user_id))
    conn.commit()
    conn.close()

def update_user_status(user_id, trader_id, status):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET trader_id = ?, status = ? WHERE user_id = ?", (trader_id, status, user_id))
    if status == 'APPROVED':
        cursor.execute("INSERT OR REPLACE INTO trader_ids (trader_id, used_by_user_id) VALUES (?, ?)", (trader_id, user_id))
    conn.commit()
    conn.close()

def is_trader_id_used(trader_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT used_by_user_id FROM trader_ids WHERE trader_id = ?", (trader_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

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

# ----------------- Force Channel Join Checker -----------------
async def check_channel_membership(user_id, context: ContextTypes.DEFAULT_TYPE):
    try:
        member = await context.bot.get_chat_member(chat_id=MUST_JOIN_CHANNEL, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return False

# Keyboards
def get_main_menu_keyboard():
    keyboard = [
        [KeyboardButton("🚀 Join VIP Group"), KeyboardButton("🔗 Registration Link")],
        [KeyboardButton("📖 VIP Signal Rules"), KeyboardButton("📞 Help & Support")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ----------------- User Commands -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_blocked(user.id):
        await update.message.reply_text("🚫 আপনি এই বটটি ব্যবহার করা থেকে সাময়িকভাবে নিষিদ্ধ (Blocked)।")
        return

    save_user(user.id, user.username, user.full_name)
    
    # Force Join Check
    is_member = await check_channel_membership(user.id, context)
    if not is_member:
        join_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Public Channel", url=f"https://t.me/tradingwithraihan_22")]])
        await update.message.reply_text(
            f"⚠️ **বটটি ব্যবহার করতে আপনাকে প্রথমে আমাদের মূল চ্যানেলে যুক্ত হতে হবে!**\n\n"
            f"নিচের বাটনে ক্লিক করে {MUST_JOIN_CHANNEL} জয়েন করুন এবং পুনরায় `/start` টাইপ করুন।",
            reply_markup=join_btn, parse_mode="Markdown"
        )
        return

    welcome_msg = (
        f"👋 **হ্যালো {user.first_name}!**\n\n"
        f"আমাদের **Exclusive VIP Trading Bot**-এ আপনাকে স্বাগতম! 📈\n\n"
        f"প্রতিদিনের হাই-একুরেসি সিগন্যাল ও গাইড পেতে নিচের বাটন ব্যবহার করুন।"
    )
    await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

# Handle Menu Items
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if is_user_blocked(user.id):
        return

    text = update.message.text.strip()

    if text == "🚀 Join VIP Group":
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

    elif text == "🔗 Registration Link":
        reg_msg = f"📌 **Quotex Official Sign-Up Link:**\n\n👉 {REFERRAL_LINK}\n\n⚠️ *অবশ্যই এই লিংকের মাধ্যমে একাউন্ট খুলতে হবে।*"
        await update.message.reply_text(reg_msg, parse_mode="Markdown", disable_web_page_preview=True)

    elif text == "📖 VIP Signal Rules":
        rules_msg = (
            f"📊 **VIP Trading Rules:**\n\n"
            f"1️⃣ **Money Management:** প্রতি ট্রেডে ক্যাপিটালের ২%-৩% ব্যবহার করবেন।\n"
            f"2️⃣ **Martingale:** সর্বোচ্চ ১ স্টেপ MTG ফলো করবেন।\n"
            f"3️⃣ **Target:** দৈনিক প্রফিট টার্গেট পূরণ হলে ট্রেডিং অফ রাখুন।"
        )
        await update.message.reply_text(rules_msg, parse_mode="Markdown")

    elif text == "📞 Help & Support":
        support_msg = f"💬 **Customer Support:**\n\nযেকোনো প্রয়োজনে সরাসরি কথা বলুন:\n👨‍💻 Support: {SUPPORT_USERNAME}"
        await update.message.reply_text(support_msg, parse_mode="Markdown")

    else:
        await update.message.reply_text("অনুগ্রহ করে নিচের বাটন ব্যবহার করুন।", reply_markup=get_main_menu_keyboard())

async def get_trader_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if text in ["🚀 Join VIP Group", "🔗 Registration Link", "📖 VIP Signal Rules", "📞 Help & Support"]:
        return await handle_message(update, context)

    if not text.isdigit() or len(text) != 8:
        await update.message.reply_text("❌ অকার্যকর ID! একটি সঠিক ৮-ডিজিটের Quotex Trader ID টাইপ করুন (যেমন: 90177664):")
        return WAITING_FOR_ID

    if is_trader_id_used(text):
        await update.message.reply_text("⚠️ **Trader ID Already Registered!** এই আইডিটি দিয়ে পূর্বে VIP এক্সেস নেওয়া হয়ে গেছে।")
        return WAITING_FOR_ID

    context.user_data['trader_id'] = text
    await update.message.reply_text("✅ ID পাওয়া গেছে। এবার ডিপোজিটের (Min $50) একটি **Screenshot (ছবি)** পাঠান:")
    return WAITING_FOR_SCREENSHOT

async def get_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    trader_id = context.user_data.get('trader_id')
    photo_file_id = update.message.photo[-1].file_id

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"app_{user.id}_{trader_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"rej_{user.id}_{trader_id}")
        ],
        [InlineKeyboardButton("🚫 Block User", callback_data=f"blk_{user.id}_{trader_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    caption = (
        f"📩 **New Verification Request**\n\n"
        f"👤 **User:** {user.full_name} (@{user.username})\n"
        f"🆔 **Telegram ID:** `{user.id}`\n"
        f"🔢 **Trader ID:** `{trader_id}`"
    )
    
    await context.bot.send_photo(
        chat_id=ADMIN_ID,
        photo=photo_file_id,
        caption=caption,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

    await update.message.reply_text(
        "✅ আপনার ভেরিফিকেশন আবেদন অ্যাডমিনের কাছে জমা হয়েছে। যাচাইকরণের পর আপনাকে লিঙ্ক জানিয়ে দেওয়া হবে।",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# ----------------- Admin Callback Handler -----------------
async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    action = data[0]
    user_id = int(data[1])
    trader_id = data[2]

    if action == "app":
        try:
            invite_link_object = await context.bot.create_chat_invite_link(
                chat_id=VIP_GROUP_ID,
                member_limit=1,
                name=f"VIP Access for {user_id}"
            )
            single_use_link = invite_link_object.invite_link
            update_user_status(user_id, trader_id, 'APPROVED')

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

# ----------------- Advanced Admin Tools -----------------
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
        f"• `/broadcast <text>` - Send msg to all users\n"
        f"• `/search <trader_id>` - Find user by ID\n"
        f"• `/block <user_id>` - Ban user\n"
        f"• `/unblock <user_id>` - Unban user"
    )
    await update.message.reply_text(panel_text, parse_mode="Markdown")

async def search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or not context.args:
        return
    tid = context.args[0]
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, full_name, status FROM users WHERE trader_id = ?", (tid,))
    row = cursor.fetchone()
    conn.close()

    if row:
        msg = f"🔍 **User Found:**\n\nTelegram ID: `{row[0]}`\nName: {row[2]}\nUsername: @{row[1]}\nStatus: `{row[3]}`"
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
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🚀 Join VIP Group$"), handle_message)],
        states={
            WAITING_FOR_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_trader_id)],
            WAITING_FOR_SCREENSHOT: [MessageHandler(filters.PHOTO, get_screenshot)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('admin', admin_panel))
    app.add_handler(CommandHandler('search', search_user))
    app.add_handler(CommandHandler('block', block_user_cmd))
    app.add_handler(CommandHandler('unblock', unblock_user_cmd))
    app.add_handler(CommandHandler('broadcast', broadcast))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(admin_decision))

    print("Master VIP Bot Status: ONLINE and Ready!")
    app.run_polling()

if __name__ == '__main__':
    main()
