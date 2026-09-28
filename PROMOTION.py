import os
import logging
import sqlite3
from contextlib import closing

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, ContextTypes, filters,
)

TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("BOT_TOKEN not set!")

SUPER_ADMIN = int(os.environ.get("SUPER_ADMIN", "8955272657"))
DB_NAME = "/tmp/bot.db"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

COLOR_EMOJI = {"green": "🟢", "red": "🔴", "blue": "🔵", "yellow": "🟡", "purple": "🟣", "orange": "🟠"}

(WAITING_CHANNEL_NAME, WAITING_CHANNEL_LINK, WAITING_CHANNEL_COLOR,
 WAITING_BUTTON_NAME, WAITING_WELCOME_TEXT, WAITING_WELCOME_MEDIA,
 WAITING_BROADCAST, WAITING_ADMIN_ID) = range(8)


def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    with closing(db()) as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, link TEXT NOT NULL,
            button_color TEXT DEFAULT 'green', button_name TEXT)""")
        cur.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_blocked INTEGER DEFAULT 0)""")
        cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
    logger.info("✅ DB initialized")


def add_admin(uid):
    with closing(db()) as conn:
        conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (uid,))
        conn.commit()


def remove_admin(uid):
    if uid == SUPER_ADMIN:
        return False
    with closing(db()) as conn:
        conn.execute("DELETE FROM admins WHERE user_id = ?", (uid,))
        conn.commit()
    return True


def is_admin(uid):
    if uid == SUPER_ADMIN:
        return True
    with closing(db()) as conn:
        return conn.execute("SELECT 1 FROM admins WHERE user_id = ?", (uid,)).fetchone() is not None


def get_admins():
    with closing(db()) as conn:
        return conn.execute("SELECT user_id FROM admins ORDER BY user_id").fetchall()


def save_user(user):
    with closing(db()) as conn:
        conn.execute("""INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name""",
            (user.id, user.username or "", user.first_name or ""))
        conn.commit()


def get_user_ids():
    with closing(db()) as conn:
        return [r[0] for r in conn.execute("SELECT user_id FROM users WHERE is_blocked = 0").fetchall()]


def mark_blocked(uid):
    with closing(db()) as conn:
        conn.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (uid,))
        conn.commit()


def add_channel(name, link, color, btn_name):
    with closing(db()) as conn:
        conn.execute("INSERT INTO channels (name, link, button_color, button_name) VALUES (?, ?, ?, ?)",
                     (name, link, color, btn_name))
        conn.commit()


def remove_channel(cid):
    with closing(db()) as conn:
        conn.execute("DELETE FROM channels WHERE id = ?", (cid,))
        conn.commit()


def get_all_channels():
    with closing(db()) as conn:
        return conn.execute("SELECT id, name, link, button_color, button_name FROM channels ORDER BY id").fetchall()


def set_setting(key, value):
    with closing(db()) as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, value))
        conn.commit()


def get_setting(key, default=None):
    with closing(db()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def count_users():
    with closing(db()) as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def admin_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Channel", callback_data="add_channel"),
         InlineKeyboardButton("➖ Remove Channel", callback_data="remove_channel")],
        [InlineKeyboardButton("📋 Channel List", callback_data="channel_list"),
         InlineKeyboardButton("✏️ Button Name", callback_data="button_name")],
        [InlineKeyboardButton("📝 Welcome Text", callback_data="welcome_text"),
         InlineKeyboardButton("🎬 Welcome Media", callback_data="welcome_media")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="broadcast"),
         InlineKeyboardButton("📊 Statistics", callback_data="stats")],
        [InlineKeyboardButton("👮 Add Admin", callback_data="add_admin"),
         InlineKeyboardButton("🚫 Remove Admin", callback_data="remove_admin")],
        [InlineKeyboardButton("👮 Admin List", callback_data="admin_list"),
         InlineKeyboardButton("⚙️ Maintenance", callback_data="maintenance")],
        [InlineKeyboardButton("🗑️ Remove Welcome Media", callback_data="delete_media")],
    ])


def back_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_home")]])


def channel_keyboard():
    keyboard = []
    for cid, name, link, color, bn in get_all_channels():
        emoji = COLOR_EMOJI.get(color, "🟢")
        keyboard.append([InlineKeyboardButton(f"{emoji} {bn or name}", url=link)])
    return InlineKeyboardMarkup(keyboard) if keyboard else None


async def send_welcome(target, context):
    count = len(get_all_channels())
    text = get_setting("welcome_text",
        "WELCOME TO RED LUCKY XYZ FAMILY\n\nPlease join all {count} channels below to continue."
    ).replace("{count}", str(count))
    markup = channel_keyboard()
    media_id = get_setting("welcome_media", "")
    media_type = get_setting("welcome_media_type", "")

    if media_id and media_type == "video":
        try:
            await target.reply_video(video=media_id, caption=text, reply_markup=markup)
            return
        except Exception:
            pass
    if media_id and media_type == "photo":
        try:
            await target.reply_photo(photo=media_id, caption=text, reply_markup=markup)
            return
        except Exception:
            pass
    await target.reply_text(text, reply_markup=markup)


async def start(update, context):
    save_user(update.effective_user)
    if get_setting("maintenance", "off") == "on" and not is_admin(update.effective_user.id):
        await update.message.reply_text("🔧 Bot maintenance mode mein hai.")
        return
    await send_welcome(update.message, context)


async def promo(update, context):
    save_user(update.effective_user)
    markup = channel_keyboard()
    if not markup:
        await update.message.reply_text("📭 Koi channel nahi.")
        return
    await update.message.reply_text("🔥 Hamare Channels 🔥", reply_markup=markup)


async def admin_command(update, context):
    save_user(update.effective_user)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin nahi.")
        return ConversationHandler.END
    await update.message.reply_text("🛡️ ADMIN PANEL", reply_markup=admin_keyboard())
    return ConversationHandler.END


async def admin_buttons(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ Admin nahi.")
        return ConversationHandler.END
    data = query.data

    if data == "admin_home":
        await query.edit_message_text("🛡️ ADMIN PANEL", reply_markup=admin_keyboard())
        return ConversationHandler.END
    if data == "add_channel":
        context.user_data.clear()
        await query.edit_message_text("1️⃣ Channel ka naam bhejein.\n\n/cancel")
        return WAITING_CHANNEL_NAME
    if data == "remove_channel":
        channels = get_all_channels()
        if not channels:
            await query.edit_message_text("📭 Koi channel nahi.", reply_markup=back_keyboard())
            return ConversationHandler.END
        kb = [[InlineKeyboardButton(f"❌ {bn or n}", callback_data=f"delete_channel:{cid}")] for cid, n, l, c, bn in channels]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="admin_home")])
        await query.edit_message_text("Kaunsa remove?", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END
    if data.startswith("delete_channel:"):
        remove_channel(int(data.split(":", 1)[1]))
        await query.edit_message_text("✅ Remove.", reply_markup=back_keyboard())
        return ConversationHandler.END
    if data == "channel_list":
        channels = get_all_channels()
        text = "📭 Koi nahi." if not channels else "📋 LIST\n\n" + "\n".join(
            f"🆔 {cid}\n📌 {n}\n🔘 {bn or n}\n🎨 {c}\n🔗 {l}\n" for cid, n, l, c, bn in channels)
        await query.edit_message_text(text, reply_markup=back_keyboard())
        return ConversationHandler.END
    if data == "button_name":
        channels = get_all_channels()
        if not channels:
            await query.edit_message_text("📭 Pehle add.", reply_markup=back_keyboard())
            return ConversationHandler.END
        kb = [[InlineKeyboardButton(f"🔘 {bn or n}", callback_data=f"choose_button:{cid}")] for cid, n, l, c, bn in channels]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="admin_home")])
        await query.edit_message_text("Kis channel ka?", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END
    if data.startswith("choose_button:"):
        context.user_data["edit_channel_id"] = int(data.split(":", 1)[1])
        await query.edit_message_text("Naya button name bhejein.")
        return WAITING_BUTTON_NAME
    if data == "welcome_text":
        current = get_setting("welcome_text", "WELCOME\n\nJoin all {count} channels.")
        await query.edit_message_text(f"📝 Naya welcome text:\n\nCurrent:\n{current}")
        return WAITING_WELCOME_TEXT
    if data == "welcome_media":
        await query.edit_message_text("🎬 Photo ya video bhejein.")
        return WAITING_WELCOME_MEDIA
    if data == "delete_media":
        set_setting("welcome_media", "")
        set_setting("welcome_media_type", "")
        await query.edit_message_text("✅ Remove.", reply_markup=back_keyboard())
        return ConversationHandler.END
    if data == "broadcast":
        await query.edit_message_text("📢 Broadcast message bhejein.")
        return WAITING_BROADCAST
    if data == "stats":
        await query.edit_message_text(
            f"📊 STATS\n\n👥 Users: {count_users()}\n📢 Channels: {len(get_all_channels())}\n"
            f"👮 Admins: {len(get_admins()) + 1}\n🔧 Maintenance: {get_setting('maintenance', 'off')}",
            reply_markup=back_keyboard())
        return ConversationHandler.END
    if data == "add_admin":
        await query.edit_message_text("👮 User ka numeric ID bhejein.")
        return WAITING_ADMIN_ID
    if data == "remove_admin":
        admins = get_admins()
        if not admins:
            await query.edit_message_text("📭 Koi admin nahi.", reply_markup=back_keyboard())
            return ConversationHandler.END
        kb = [[InlineKeyboardButton(f"❌ {uid}", callback_data=f"remove_admin_id:{uid}")] for (uid,) in admins]
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="admin_home")])
        await query.edit_message_text("Kis admin ko?", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END
    if data.startswith("remove_admin_id:"):
        uid = int(data.split(":", 1)[1])
        msg = f"✅ Admin {uid} remove." if remove_admin(uid) else "❌ Super admin remove nahi."
        await query.edit_message_text(msg, reply_markup=back_keyboard())
        return ConversationHandler.END
    if data == "admin_list":
        admins = [SUPER_ADMIN] + [r[0] for r in get_admins() if r[0] != SUPER_ADMIN]
        await query.edit_message_text("👮 ADMINS\n\n" + "\n".join(f"• {uid}" for uid in admins), reply_markup=back_keyboard())
        return ConversationHandler.END
    if data == "maintenance":
        nv = "off" if get_setting("maintenance", "off") == "on" else "on"
        set_setting("maintenance", nv)
        await query.edit_message_text(f"🔧 Maintenance: {nv.upper()}", reply_markup=back_keyboard())
        return ConversationHandler.END
    return ConversationHandler.END


async def receive_channel_name(update, context):
    context.user_data["channel_name"] = update.message.text.strip()
    await update.message.reply_text("2️⃣ Channel ka URL:")
    return WAITING_CHANNEL_LINK


async def receive_channel_link(update, context):
    link = update.message.text.strip()
    if not (link.startswith("https://t.me/") or link.startswith("http://t.me/") or link.startswith("https://telegram.me/")):
        await update.message.reply_text("❌ Valid Telegram link.")
        return WAITING_CHANNEL_LINK
    context.user_data["channel_link"] = link
    kb = [
        [InlineKeyboardButton("🟢 Green", callback_data="color:green"),
         InlineKeyboardButton("🔴 Red", callback_data="color:red")],
        [InlineKeyboardButton("🔵 Blue", callback_data="color:blue"),
         InlineKeyboardButton("🟡 Yellow", callback_data="color:yellow")],
        [InlineKeyboardButton("🟣 Purple", callback_data="color:purple"),
         InlineKeyboardButton("🟠 Orange", callback_data="color:orange")],
    ]
    await update.message.reply_text("3️⃣ Color:", reply_markup=InlineKeyboardMarkup(kb))
    return WAITING_CHANNEL_COLOR


async def receive_channel_color(update, context):
    query = update.callback_query
    await query.answer()
    color = query.data.split(":", 1)[1]
    name = context.user_data.get("channel_name", "Channel")
    link = context.user_data.get("channel_link", "")
    add_channel(name, link, color, name)
    await query.edit_message_text(f"✅ Added!\n\n📌 {name}\n🔗 {link}\n🎨 {color}", reply_markup=back_keyboard())
    return ConversationHandler.END


async def receive_button_name(update, context):
    new_name = update.message.text.strip()
    cid = context.user_data.get("edit_channel_id")
    if cid:
        with closing(db()) as conn:
            conn.execute("UPDATE channels SET button_name = ? WHERE id = ?", (new_name, cid))
            conn.commit()
    await update.message.reply_text("✅ Updated!", reply_markup=back_keyboard())
    return ConversationHandler.END


async def receive_welcome_text(update, context):
    set_setting("welcome_text", update.message.text.strip())
    await update.message.reply_text("✅ Updated!", reply_markup=back_keyboard())
    return ConversationHandler.END


async def receive_welcome_media(update, context):
    msg = update.message
    if msg.photo:
        set_setting("welcome_media", msg.photo[-1].file_id)
        set_setting("welcome_media_type", "photo")
        await msg.reply_text("✅ Photo saved!", reply_markup=back_keyboard())
    elif msg.video:
        set_setting("welcome_media", msg.video.file_id)
        set_setting("welcome_media_type", "video")
        await msg.reply_text("✅ Video saved!", reply_markup=back_keyboard())
    else:
        await msg.reply_text("❌ Photo ya video bhejein.")
        return WAITING_WELCOME_MEDIA
    return ConversationHandler.END


async def receive_broadcast(update, context):
    msg = update.message
    uids = get_user_ids()
    sent = failed = 0
    for uid in uids:
        try:
            if msg.text:
                await context.bot.send_message(uid, msg.text)
            elif msg.photo:
                await context.bot.send_photo(uid, msg.photo[-1].file_id, caption=msg.caption or "")
            elif msg.video:
                await context.bot.send_video(uid, msg.video.file_id, caption=msg.caption or "")
            elif msg.document:
                await context.bot.send_document(uid, msg.document.file_id, caption=msg.caption or "")
            sent += 1
        except Exception:
            failed += 1
            mark_blocked(uid)
    await msg.reply_text(f"✅ Done!\n\n👥 {len(uids)}\n✅ {sent}\n❌ {failed}", reply_markup=back_keyboard())
    return ConversationHandler.END


async def receive_admin_id(update, context):
    try:
        uid = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Valid numeric ID.")
        return WAITING_ADMIN_ID
    add_admin(uid)
    await update.message.reply_text(f"✅ Admin {uid} added!", reply_markup=back_keyboard())
    return ConversationHandler.END


async def cancel(update, context):
    await update.message.reply_text("❌ Cancelled.", reply_markup=back_keyboard())
    return ConversationHandler.END


def main():
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("admin", admin_command),
            CallbackQueryHandler(admin_buttons),
        ],
        states={
            WAITING_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_channel_name)],
            WAITING_CHANNEL_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_channel_link)],
            WAITING_CHANNEL_COLOR: [CallbackQueryHandler(receive_channel_color, pattern=r"^color:")],
            WAITING_BUTTON_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_button_name)],
            WAITING_WELCOME_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_welcome_text)],
            WAITING_WELCOME_MEDIA: [MessageHandler(filters.PHOTO | filters.VIDEO, receive_welcome_media)],
            WAITING_BROADCAST: [MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL, receive_broadcast)],
            WAITING_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_id)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(conv)

    logger.info("🚀 Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
