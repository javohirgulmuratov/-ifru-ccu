import os
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "clock_users.db")
PAYMENT_INFO = os.getenv(
    "PAYMENT_INFO",
    "To‘lov rekvizitlarini administrator bilan aniqlashtiring."
)

KEYBOARD = ReplyKeyboardMarkup(
    [
        ["🕒 Soatni yoqish", "⏹ Soatni o‘chirish"],
        ["👑 Premium", "💳 Chek yuborish"],
        ["⚙️ Sozlamalar", "ℹ️ Yordam"],
    ],
    resize_keyboard=True,
)


def connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                timezone TEXT NOT NULL DEFAULT 'Asia/Tashkent',
                premium_until TEXT,
                waiting_receipt INTEGER NOT NULL DEFAULT 0
            )
        """)

        columns = {
            row[1] for row in
            db.execute("PRAGMA table_info(users)").fetchall()
        }

        if "premium_until" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN premium_until TEXT")

        if "waiting_receipt" not in columns:
            db.execute(
                "ALTER TABLE users ADD COLUMN waiting_receipt "
                "INTEGER NOT NULL DEFAULT 0"
            )


def ensure_user(user_id):
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (user_id,),
        )


def get_user(user_id):
    ensure_user(user_id)
    with connect() as db:
        return db.execute(
            """SELECT enabled, timezone, premium_until,
                      waiting_receipt
               FROM users WHERE user_id = ?""",
            (user_id,),
        ).fetchone()


def is_premium(user_id):
    until = get_user(user_id)[2]
    if not until:
        return False

    try:
        expiry = datetime.fromisoformat(until)
        return expiry > datetime.now(timezone.utc)
    except ValueError:
        return False


def set_enabled(user_id, enabled):
    ensure_user(user_id)
    with connect() as db:
        db.execute(
            "UPDATE users SET enabled = ? WHERE user_id = ?",
            (enabled, user_id),
        )


def set_timezone(user_id, tz):
    ensure_user(user_id)
    with connect() as db:
        db.execute(
            "UPDATE users SET timezone = ? WHERE user_id = ?",
            (tz, user_id),
        )


def set_waiting(user_id, waiting):
    ensure_user(user_id)
    with connect() as db:
        db.execute(
            "UPDATE users SET waiting_receipt = ? WHERE user_id = ?",
            (waiting, user_id),
        )


async def send_ad(message, user_id):
    if not is_premium(user_id):
        await message.reply_text(
            "📢 Reklama: profilingiz uchun soat xizmati.\n"
            "Reklamasiz foydalanish uchun 👑 Premium — 5 000 so‘m/oy."
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ensure_user(user_id)

    await update.message.reply_text(
        "Salom! 🕒 Soat botiga xush kelibsiz.\n\n"
        "Tugmalardan foydalaning.\n"
        "Eslatma: ushbu versiya hali profilingizdagi ism yoki "
        "bio qismini avtomatik o‘zgartirmaydi.",
        reply_markup=KEYBOARD,
    )
    await send_ad(update.message, user_id)


async def show_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    until = get_user(user_id)[2]

    if is_premium(user_id):
        await update.message.reply_text(
            f"👑 Premium faol!\nAmal qilish muddati: {until}",
            reply_markup=KEYBOARD,
        )
        return

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "💳 To‘lov ma’lumotlari",
            callback_data="payment_info",
        )],
        [InlineKeyboardButton(
            "📨 Chek yuborish",
            callback_data="send_receipt",
        )],
    ])

    await update.message.reply_text(
        "👑 PREMIUM — 5 000 so‘m / 30 kun\n\n"
        "✅ Bot ichidagi reklama o‘chiriladi.\n"
        "✅ Premium muddati botda ko‘rsatiladi.\n"
        "ℹ️ Profil bio reklamasini olib tashlash uchun "
        "ko‘rsatma beriladi.\n\n"
        "To‘lov administrator tomonidan tekshiriladi.",
        reply_markup=buttons,
    )


async def show_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "payment_info":
        await query.message.reply_text(
            f"💳 To‘lov: 5 000 so‘m\n\n{PAYMENT_INFO}\n\n"
            "To‘lovni amalga oshirgach, «Chek yuborish» tugmasini bosing."
        )
    elif query.data == "send_receipt":
        set_waiting(query.from_user.id, 1)
        await query.message.reply_text(
            "To‘lov chekini rasm yoki fayl sifatida yuboring. "
            "Chekda karta raqamingiz yoki boshqa maxfiy ma’lumotlar "
            "keraksiz bo‘lsa, ularni berkitib qo‘ying."
        )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    enabled, tz, until, _ = get_user(user_id)
    now = datetime.now(ZoneInfo(tz)).strftime("%H:%M:%S")
    state = "Yoqilgan" if enabled else "O‘chirilgan"

    premium_text = (
        f"Premium muddati: {until}"
        if is_premium(user_id)
        else "Tarif: Bepul"
    )

    await update.message.reply_text(
        f"Soat funksiyasi: {state}\n"
        f"Hozirgi vaqt: {now}\n"
        f"Vaqt mintaqasi: {tz}\n"
        f"{premium_text}",
        reply_markup=KEYBOARD,
    )
    await send_ad(update.message, user_id)


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [InlineKeyboardButton(
            "🇺🇿 O‘zbekiston",
            callback_data="tz|Asia/Tashkent",
        )],
        [InlineKeyboardButton(
            "🇹🇷 Turkiya",
            callback_data="tz|Europe/Istanbul",
        )],
        [InlineKeyboardButton(
            "🇬🇧 London",
            callback_data="tz|Europe/London",
        )],
        [InlineKeyboardButton(
            "🇺🇸 Nyu-York",
            callback_data="tz|America/New_York",
        )],
    ]

    await update.message.reply_text(
        "Vaqt mintaqasini tanlang:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data in ("payment_info", "send_receipt"):
        await show_payment(update, context)
        return

    if data.startswith("tz|"):
        tz = data.split("|", 1)[1]
        try:
            ZoneInfo(tz)
            set_timezone(query.from_user.id, tz)
            await query.edit_message_text(
                f"Vaqt mintaqasi saqlandi: {tz} ✅"
            )
        except Exception:
            await query.edit_message_text("Vaqt mintaqasini tanlab bo‘lmadi.")
        return

    if data.startswith(("approve|", "reject|")):
        if query.from_user.id != ADMIN_ID or ADMIN_ID == 0:
            await query.answer("Bu amal faqat administrator uchun.", show_alert=True)
            return

        action, raw_id = data.split("|", 1)
        user_id = int(raw_id)

        if action == "approve":
            expiry = datetime.now(timezone.utc) + timedelta(days=30)
            with connect() as db:
                db.execute(
                    "UPDATE users SET premium_until = ?, waiting_receipt = 0 "
                    "WHERE user_id = ?",
                    (expiry.isoformat(), user_id),
                )

            try:
                await context.bot.send_message(
                    user_id,
                    "✅ To‘lov tasdiqlandi! Premium 30 kunga yoqildi.\n\n"
                    "Bot ichidagi reklama o‘chiriladi. Bio reklamasini "
                    "olib tashlash uchun profil sozlamalaridan o‘zingiz "
                    "tahrirlashingiz mumkin.",
                )
            except Exception:
                pass

            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"Premium tasdiqlandi: {user_id}"
            )

        else:
            set_waiting(user_id, 0)
            try:
                await context.bot.send_message(
                    user_id,
                    "❌ Chek tasdiqlanmadi. Iltimos, administrator "
                    "bilan bog‘lanib, to‘lovni aniqlashtiring.",
                )
            except Exception:
                pass

            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                f"Chek rad etildi: {user_id}"
            )


async def receive_receipt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_id = update.effective_user.id

    if not get_user(user_id)[3]:
        await handle_text(update, context)
        return

    if ADMIN_ID == 0:
        await update.message.reply_text(
            "Administrator hali sozlanmagan. Keyinroq urinib ko‘ring."
        )
        return

    set_waiting(user_id, 0)

    controls = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Tasdiqlash",
                callback_data=f"approve|{user_id}",
            ),
            InlineKeyboardButton(
                "❌ Rad etish",
                callback_data=f"reject|{user_id}",
            ),
        ]
    ])

    caption = (
        f"💳 Premium to‘lovi tekshirish uchun\n"
        f"Foydalanuvchi ID: {user_id}\n"
        f"Summa: 5 000 so‘m / 30 kun"
    )

    if update.message.photo:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=update.message.photo[-1].file_id,
            caption=caption,
            reply_markup=controls,
        )
    elif update.message.document:
        await context.bot.send_document(
            chat_id=ADMIN_ID,
            document=update.message.document.file_id,
            caption=caption,
            reply_markup=controls,
        )
    elif update.message.text:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=caption + "\n\nChek ma’lumoti:\n" + update.message.text,
            reply_markup=controls,
        )
    else:
        set_waiting(user_id, 1)
        await update.message.reply_text(
            "Chekni rasm, fayl yoki matn shaklida yuboring."
        )
        return

    await update.message.reply_text(
        "Chek administratorga yuborildi. Tekshiruv natijasini kuting.",
        reply_markup=KEYBOARD,
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    message = update.message.text

    if get_user(user_id)[3]:
        await receive_receipt(update, context)
        return

    if message == "🕒 Soatni yoqish":
        set_enabled(user_id, 1)
        await update.message.reply_text(
            "Soat funksiyasi yoqildi. Bu hozircha faqat bot ichidagi "
            "sozlamani saqlaydi.",
            reply_markup=KEYBOARD,
        )

    elif message == "⏹ Soatni o‘chirish":
        set_enabled(user_id, 0)
        await update.message.reply_text(
            "Soat funksiyasi o‘chirildi.",
            reply_markup=KEYBOARD,
        )

    elif message == "👑 Premium":
        await show_premium(update, context)

    elif message == "💳 Chek yuborish":
        set_waiting(user_id, 1)
        await update.message.reply_text(
            "To‘lov chekini rasm yoki fayl sifatida yuboring."
        )

    elif message == "⚙️ Sozlamalar":
        await settings(update, context)

    elif message == "ℹ️ Yordam":
        await update.message.reply_text(
            "/start — botni ochish\n"
            "/status — soat holati\n"
            "/premium — Premium tarifi\n"
            "/stop — soat funksiyasini o‘chirish",
            reply_markup=KEYBOARD,
        )

    else:
        await update.message.reply_text(
            "Iltimos, pastdagi tugmalardan foydalaning.",
            reply_markup=KEYBOARD,
        )

    await send_ad(update.message, user_id)


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    set_enabled(update.effective_user.id, 0)
    await update.message.reply_text(
        "Soat funksiyasi o‘chirildi.",
        reply_markup=KEYBOARD,
    )


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN Railway Variables bo‘limida yo‘q.")

    if ADMIN_ID == 0:
        print("DIQQAT: Railway Variables bo‘limiga ADMIN_ID qo‘shing.")

    init_db()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("premium", show_premium))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.ALL, receive_receipt)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    print("Bot ishga tushdi.")
    app.run_polling()


if __name__ == "__main__":
    main()
