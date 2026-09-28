import os
import logging
import sqlite3
from contextlib import closing

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# CONFIG — Environment variables se load hoga (safe)
# ============================================================
TOKEN = os.environ.get("BOT_TOKEN", "").strip()
if not TOKEN:8894431922:AAE_9QbqKARdUAXOJLOcZJspD5Twu0wgIjk
    raise RuntimeError("❌ BOT_TOKEN environment variable set nahi hai! Render > Environment mein add karo.")

SUPER_ADMIN = int(os.environ.get("SUPER_ADMIN", "8955272657"))

# Render free tier mein sirf /tmp writable hai
DB_NAME = "/tmp/bot.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

COLOR_EMOJI = {
    "green": "🟢",
    "red": "🔴",
    "blue": "🔵",
    "yellow": "🟡",
    "purple": "🟣",
    "orange": "🟠",
}

(
    WAITING_CHANNEL_NAME,
    WAITING_CHANNEL_LINK,
    WAITING_CHANNEL_COLOR,
    WAITING_BUTTON_NAME,
    WAITING_WELCOME_TEXT,
    WAITING_WELCOME_MEDIA,
    WAITING_BROADCAST,
    WAITING_ADMIN_ID,
) = range(8)


# ============================================================
# DATABASE
# ============================================================
def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    with closing(db()) as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                link TEXT NOT NULL,
                button_color TEXT DEFAULT 'green',
                button_name TEXT
            )
        """)

        try:
            cur.execute("ALTER TABLE channels ADD COLUMN button_name TEXT")
        except sqlite3.OperationalError:
            pass

        cur.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_blocked INTEGER DEFAULT 0
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        conn.commit()
    logger.info("✅ Database initialized at %s", DB_NAME)


def add_admin(user_id: int):
    with closing(db()) as conn:
        conn.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        conn.commit()


def remove_admin(user_id: int):
    if user_id == SUPER_ADMIN:
        return False
    with closing(db()) as conn:
        conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        conn.commit()
    return True


def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN:
        return True
    with closing(db()) as conn:
        row = conn.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)).fetchone()
    return row is not None


def get_admins():
    with closing(db()) as conn:
        return conn.execute("SELECT user_id FROM admins ORDER BY user_id").fetchall()


def save_user(user):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name
        """, (user.id, user.username or "", user.first_name or ""))
        conn.commit()


def get_user_ids():
    with closing(db()) as conn:
        rows = conn.execute("SELECT user_id FROM users WHERE is_blocked = 0").fetchall()
    return [r[0] for r in rows]


def mark_blocked(user_id):
    with closing(db()) as conn:
        conn.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user_id,))
        conn.commit()


def add_channel(name, link, color, button_name):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO channels (name, link, button_color, button_name)
            VALUES (?, ?, ?, ?)
        """, (name, link, color, button_name))
        conn.commit()


def remove_channel(channel_id):
    with closing(db()) as conn:
        conn.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
        conn.commit()


def get_all_channels():
    with closing(db()) as conn:
        return conn.execute("""
            SELECT id, name, link, button_color, button_name
            FROM channels ORDER BY id
        """).fetchall()


def set_setting(key, value):
    with closing(db()) as conn:
        conn.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        conn.commit()


def get_setting(key, default=None):
    with closing(db()) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def count_users():
    with closing(db()) as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


# ============================================================
# COMMON HELPERS
# ============================================================
def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add Channel", callback_data="add_channel"),
            InlineKeyboardButton("➖ Remove Channel", callback_data="remove_channel"),
        ],
        [
            InlineKeyboardButton("📋 Channel List", callback_data="channel_list"),
            InlineKeyboardButton("✏️ Button Name", callback_data="button_name"),
        ],
        [
            InlineKeyboardButton("📝 Welcome Text", callback_data="welcome_text"),
            InlineKeyboardButton("🎬 Welcome Media", callback_data="welcome_media"),
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="broadcast"),
            InlineKeyboardButton("📊 Statistics", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("👮 Add Admin", callback_data="add_admin"),
            InlineKeyboardButton("🚫 Remove Admin", callback_data="remove_admin"),
        ],
        [
            InlineKeyboardButton("👮 Admin List", callback_data="admin_list"),
            InlineKeyboardButton("⚙️ Maintenance", callback_data="maintenance"),
        ],
        [
            InlineKeyboardButton("🗑️ Remove Welcome Media", callback_data="delete_media"),
        ],
    ])


def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_home")]
    ])


def channel_keyboard():
    keyboard = []
    for ch_id, name, link, color, button_name in get_all_channels():
        emoji = COLOR_EMOJI.get(color, "🟢")
        label = button_name or name
        keyboard.append([InlineKeyboardButton(f"{emoji} {label}", url=link)])
    return InlineKeyboardMarkup(keyboard) if keyboard else None


async def send_welcome(target, context):
    channels = get_all_channels()
    count = len(channels)

    text = get_setting(
        "welcome_text",
        "WELCOME TO RED LUCKY XYZ FAMILY\n\n"
        "Please join all {count} channels below to continue."
    ).replace("{count}", str(count))

    markup = channel_keyboard()
    media_id = get_setting("welcome_media", "")
    media_type = get_setting("welcome_media_type", "")

    if media_id and media_type == "video":
        try:
            await target.reply_video(video=media_id, caption=text, reply_markup=markup)
            return
        except Exception:
            logger.exception("Could not send welcome video")

    if media_id and media_type == "photo":
        try:
            await target.reply_photo(photo=media_id, caption=text, reply_markup=markup)
            return
        except Exception:
            logger.exception("Could not send welcome photo")

    await target.reply_text(text, reply_markup=markup)


# ============================================================
# USER COMMANDS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)

    if get_setting("maintenance", "off") == "on" and not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "🔧 Bot abhi maintenance mode mein hai.\nPlease baad mein try karein."
        )
        return

    await send_welcome(update.message, context)


async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)

    markup = channel_keyboard()
    if not markup:
        await update.message.reply_text("📭 Abhi koi channel add nahi hai.")
        return

    await update.message.reply_text("🔥 Hamare Channels 🔥", reply_markup=markup)


# ============================================================
# ADMIN ENTRY
# ============================================================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)

    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Aap admin nahi hain.")
        return ConversationHandler.END

    await update.message.reply_text(
        "🛡️ ADMIN PANEL\n\nNeeche se option select karein:",
        reply_markup=admin_keyboard(),
    )
    return ConversationHandler.END


# ============================================================
# ADMIN CALLBACKS
# ============================================================
async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("❌ Aap admin nahi hain.")
        return ConversationHandler.END

    data = query.data

    if data == "admin_home":
        await query.edit_message_text(
            "🛡️ ADMIN PANEL\n\nNeeche se option select karein:",
            reply_markup=admin_keyboard(),
        )
        return ConversationHandler.END

    if data == "add_channel":
        context.user_data.clear()
        await query.edit_message_text(
            "1️⃣ Channel ka naam bhejein.\n\n/cancel se cancel kar sakte hain."
        )
        return WAITING_CHANNEL_NAME

    if data == "remove_channel":
        channels = get_all_channels()
        if not channels:
            await query.edit_message_text("📭 Koi channel nahi hai.", reply_markup=back_keyboard())
            return ConversationHandler.END

        keyboard = []
        for ch_id, name, link, color, button_name in channels:
            keyboard.append([
                InlineKeyboardButton(f"❌ {button_name or name}", callback_data=f"delete_channel:{ch_id}")
            ])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_home")])

        await query.edit_message_text(
            "Kaunsa channel remove karna hai?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    if data.startswith("delete_channel:"):
        channel_id = int(data.split(":", 1)[1])
        remove_channel(channel_id)
        await query.edit_message_text("✅ Channel remove ho gaya.", reply_markup=back_keyboard())
        return ConversationHandler.END

    if data == "channel_list":
        channels = get_all_channels()
        if not channels:
            text = "📭 Koi channel add nahi hai."
        else:
            lines = ["📋 CHANNEL LIST\n"]
            for ch_id, name, link, color, button_name in channels:
                lines.append(
                    f"🆔 {ch_id}\n"
                    f"📌 Name: {name}\n"
                    f"🔘 Button: {button_name or name}\n"
                    f"🎨 Color: {color}\n"
                    f"🔗 {link}\n"
                )
            text = "\n".join(lines)
        await query.edit_message_text(text, reply_markup=back_keyboard())
        return ConversationHandler.END

    if data == "button_name":
        channels = get_all_channels()
        if not channels:
            await query.edit_message_text("📭 Pehle channel add karein.", reply_markup=back_keyboard())
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton(
                f"🔘 {button_name or name}",
                callback_data=f"choose_button:{ch_id}",
            )]
            for ch_id, name, link, color, button_name in channels
        ]
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_home")])

        await query.edit_message_text(
            "Kis channel ka button name change karna hai?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    if data.startswith("choose_button:"):
        channel_id = int(data.split(":", 1)[1])
        context.user_data["edit_channel_id"] = channel_id
        await query.edit_message_text(
            "Naya button name bhejein.\n\nExample: 🟢 JOIN NOW\n\n/cancel = cancel"
        )
        return WAITING_BUTTON_NAME

    if data == "welcome_text":
        current = get_setting(
            "welcome_text",
            "WELCOME TO RED LUCKY XYZ FAMILY\n\nPlease join all {count} channels below to continue.",
        )
        await query.edit_message_text(
            "📝 Naya welcome text bhejein.\n\n"
            f"Current:\n{current}\n\n"
            "Tip: {count} use karke channel count dikha sakte hain."
        )
        return WAITING_WELCOME_TEXT

    if data == "welcome_media":
        await query.edit_message_text("🎬 Welcome photo ya video bhejein.\n\n/cancel = cancel")
        return WAITING_WELCOME_MEDIA

    if data == "delete_media":
        set_setting("welcome_media", "")
        set_setting("welcome_media_type", "")
        await query.edit_message_text("✅ Welcome media remove ho gaya.", reply_markup=back_keyboard())
        return ConversationHandler.END

    if data == "broadcast":
        await query.edit_message_text(
            "📢 Broadcast message bhejein.\n\n"
            "Text, photo, video ya document bhej sakte hain.\n"
            "/cancel = cancel"
        )
        return WAITING_BROADCAST

    if data == "stats":
        users = count_users()
        channels = len(get_all_channels())
        admins = len(get_admins()) + 1

        await query.edit_message_text(
            "📊 BOT STATISTICS\n\n"
            f"👥 Users: {users}\n"
            f"📢 Channels: {channels}\n"
            f"👮 Admins: {admins}\n"
            f"🔧 Maintenance: {get_setting('maintenance', 'off')}",
            reply_markup=back_keyboard(),
        )
        return ConversationHandler.END

    if data == "add_admin":
        await query.edit_message_text(
            "👮 Jis user ko admin banana hai uska numeric Telegram ID bhejein."
        )
        return WAITING_ADMIN_ID

    if data == "remove_admin":
        admins = get_admins()
        if not admins:
            await query.edit_message_text("📭 Koi extra admin nahi hai.", reply_markup=back_keyboard())
            return ConversationHandler.END

        keyboard = []
        for (uid,) in admins:
            keyboard.append([InlineKeyboardButton(f"❌ {uid}", callback_data=f"remove_admin_id:{uid}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_home")])

        await query.edit_message_text(
            "Kis admin ko remove karna hai?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return ConversationHandler.END

    if data.startswith("remove_admin_id:"):
        uid = int(data.split(":", 1)[1])
        if remove_admin(uid):
            msg = f"✅ Admin {uid} remove ho gaya."
        else:
            msg = "❌ Super admin ko remove nahi kiya ja sakta."
        await query.edit_message_text(msg, reply_markup=back_keyboard())
        return ConversationHandler.END

    if data == "admin_list":
        admins = [SUPER_ADMIN] + [row[0] for row in get_admins() if row[0] != SUPER_ADMIN]
        text = "👮 ADMIN LIST\n\n" + "\n".join(f"• {uid}" for uid in admins)
        await query.edit_message_text(text, reply_markup=back_keyboard())
        return ConversationHandler.END

    if data == "maintenance":
        current = get_setting("maintenance", "off")
        new_value = "off" if current == "on" else "on"
        set_setting("maintenance", new_value)
        await query.edit_message_text(
            f"🔧 Maintenance mode: {new_value.upper()}",
            reply_markup=back_keyboard(),
        )
        return ConversationHandler.END

    return ConversationHandler.END


# ============================================================
# CONVERSATION HANDLERS
# ============================================================
async def receive_channel_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["channel_name"] = update.message.text.strip()
    await update.message.reply_text(
        "2️⃣ Channel ka URL bhejein.\nExample: https://t.me/example"
    )
    return WAITING_CHANNEL_LINK


async def receive_channel_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()

    if not (
        link.startswith("https://t.me/")
        or link.startswith("http://t.me/")
        or link.startswith("https://telegram.me/")
    ):
        await update.message.reply_text(
            "❌ Valid Telegram link dein.\nExample: https://t.me/example"
        )
        return WAITING_CHANNEL_LINK

    context.user_data["channel_link"] = link

    keyboard = [
        [
            InlineKeyboardButton("🟢 Green", callback_data="color:green"),
            InlineKeyboardButton("🔴 Red", callback_data="color:red"),
        ],
        [
            InlineKeyboardButton("🔵 Blue", callback_data="color:blue"),
            InlineKeyboardButton("🟡 Yellow", callback_data="color:yellow"),
        ],
        [
            InlineKeyboardButton("🟣 Purple", callback_data="color:purple"),
            InlineKeyboardButton("🟠 Orange", callback_data="color:orange"),
        ],
    ]

    await update.message.reply_text(
        "3️⃣ Button color choose karein:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_CHANNEL_COLOR


async def receive_channel_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    color = query.data.split(":", 1)[1]
    name = context.user_data.get("channel_name", "Channel")
    link = context.user_data.get("channel_link", "")

    add_channel(name, link, color, name)
    await query.edit_message_text(
        f"✅ Channel add ho gaya!\n\n"
        f"📌 Name: {name}\n"
        f"🔗 Link: {link}\n"
        f"🎨 Color: {color}",
        reply_markup=back_keyboard(),
    )
    return ConversationHandler.END


async def receive_button_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_name = update.message.text.strip()
    channel_id = context.user_data.get("edit_channel_id")

    if channel_id:
        with closing(db()) as conn:
            conn.execute(
                "UPDATE channels SET button_name = ? WHERE id = ?",
                (new_name, channel_id),
            )
            conn.commit()

    await update.message.reply_text(
        "✅ Button name update ho gaya!",
        reply_markup=back_keyboard(),
    )
    return ConversationHandler.END


async def receive_welcome_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_se
