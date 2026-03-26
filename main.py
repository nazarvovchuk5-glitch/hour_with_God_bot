import json
import logging
import os
from datetime import datetime, time as datetime_time

import pytz
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ── Налаштування ─────────────────────────────────────────────────────────────
BOT_TOKEN         = os.environ.get("BOT_TOKEN", "8710025600:AAGkDZQPR3ZgVJVYzQeVerjBLpuqtTQiWvQ")
TIMEZONE          = "Europe/Kiev"
CHECK_HOUR        = 16
CHECK_MIN         = 0
REMIND_HOUR       = 18
REMIND_MIN        = 0
WINDOW_START_HOUR = 18
CHATS_FILE        = "registered_chats.json"

# ── Учасники ──────────────────────────────────────────────────────────────────
MEMBERS: dict[int, dict] = {
    653369664: {"name": "Міла",         "username": "mlllana"},
    542909091: {"name": "Назар Вовчук", "username": "vovchuk_n"},
}

# ── Логування ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Стан ─────────────────────────────────────────────────────────────────────
checked_in: dict[int, set[int]] = {}
tz = pytz.timezone(TIMEZONE)


# ── Збереження/завантаження чатів ─────────────────────────────────────────────

def load_chats() -> set[int]:
    if os.path.exists(CHATS_FILE):
        with open(CHATS_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_chats(chats: set[int]) -> None:
    with open(CHATS_FILE, "w") as f:
        json.dump(list(chats), f)


registered_chats: set[int] = load_chats()


# ── Допоміжні функції ─────────────────────────────────────────────────────────

def is_within_window() -> bool:
    """Вікно відкрите з 18:00 до 16:00 наступного дня. Мертва зона: 16:00–18:00."""
    hour = datetime.now(tz).hour
    return not (CHECK_HOUR <= hour < WINDOW_START_HOUR)


def user_mention(user_id: int, info: dict) -> str:
    username = info.get("username")
    name     = info.get("name", str(user_id))
    if username:
        return f"@{username}"
    return f'<a href="tg://user?id={user_id}">{name}</a>'


# ── Хендлер "+" ───────────────────────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.text or msg.text.strip() != "+":
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if user_id not in MEMBERS:
        return

    if not is_within_window():
        await msg.reply_text(
            f"⏰ Реєстрація можлива лише з {WINDOW_START_HOUR:02d}:00 до {CHECK_HOUR:02d}:00."
        )
        return

    if chat_id not in checked_in:
        checked_in[chat_id] = set()

    if user_id in checked_in[chat_id]:
        await msg.reply_text("Ти вже відмітився ✅")
    else:
        checked_in[chat_id].add(user_id)
        await msg.reply_text(f"✅ {update.effective_user.first_name}, відмічено!")


# ── Команди ───────────────────────────────────────────────────────────────────

async def cmd_setchat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    registered_chats.add(chat_id)
    save_chats(registered_chats)

    if chat_id not in checked_in:
        checked_in[chat_id] = set()

    await update.message.reply_text(
        f"✅ Чат зареєстровано!\n"
        f"👥 Учасників у базі: {len(MEMBERS)}\n"
        f"🔔 Нагадування щодня о {REMIND_HOUR:02d}:{REMIND_MIN:02d}\n"
        f"⏰ Перевірка щодня о {CHECK_HOUR:02d}:{CHECK_MIN:02d}",
        parse_mode="HTML",
    )


async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await run_check(ctx.bot, update.effective_chat.id)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    present = checked_in.get(chat_id, set())
    absent  = {uid: info for uid, info in MEMBERS.items() if uid not in present}

    lines = [f"📊 <b>Статус (вікно {WINDOW_START_HOUR:02d}:00 – {CHECK_HOUR:02d}:00)</b>\n"]

    if present:
        lines.append("✅ <b>Відмітились:</b>")
        for uid in present:
            if uid in MEMBERS:
                lines.append(f"  • {user_mention(uid, MEMBERS[uid])}")

    if absent:
        lines.append("\n❌ <b>Ще не відмітились:</b>")
        for uid, info in absent.items():
            lines.append(f"  • {user_mention(uid, info)}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── JobQueue колбеки ──────────────────────────────────────────────────────────

async def job_send_reminder(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Щодня о 18:00 — скидає стан і надсилає нагадування."""
    for chat_id in list(registered_chats):
        try:
            checked_in[chat_id] = set()
            await ctx.bot.send_message(
                chat_id,
                "🙏 <b>Як ваша година з Богом?</b>\n\nНапишіть <b>+</b> якщо провели час з Богом сьогодні.",
                parse_mode="HTML",
            )
            logger.info("Reminder sent to chat %d", chat_id)
        except Exception as e:
            logger.error("Error sending reminder to chat %d: %s", chat_id, e)


async def job_scheduled_check(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Щодня о 16:00 — підраховує хто відмітився."""
    for chat_id in list(registered_chats):
        try:
            await run_check(ctx.bot, chat_id)
            logger.info("Check completed for chat %d", chat_id)
        except Exception as e:
            logger.error("Error in scheduled check for chat %d: %s", chat_id, e)


async def run_check(bot, chat_id: int) -> None:
    present = checked_in.get(chat_id, set())
    absent  = {uid: info for uid, info in MEMBERS.items() if uid not in present}

    if not absent:
        await bot.send_message(chat_id, "🎉 Всі відмітились! Молодці 👏", parse_mode="HTML")
    else:
        mentions = "\n".join(
            f"• {user_mention(uid, info)}" for uid, info in absent.items()
        )
        await bot.send_message(
            chat_id,
            f"❌ <b>Не відмітились:</b>\n{mentions}",
            parse_mode="HTML",
        )

    checked_in[chat_id] = set()


# ── Запуск ────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("setchat", cmd_setchat))
    app.add_handler(CommandHandler("check",   cmd_check))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Вбудований JobQueue — надійніше за APScheduler
    app.job_queue.run_daily(
        job_scheduled_check,
        time=datetime_time(hour=CHECK_HOUR, minute=CHECK_MIN, tzinfo=tz),
        name="daily_check",
    )
    app.job_queue.run_daily(
        job_send_reminder,
        time=datetime_time(hour=REMIND_HOUR, minute=REMIND_MIN, tzinfo=tz),
        name="daily_reminder",
    )

    logger.info(
        "Bot started. Loaded %d registered chats. Check at %02d:%02d, Reminder at %02d:%02d",
        len(registered_chats), CHECK_HOUR, CHECK_MIN, REMIND_HOUR, REMIND_MIN,
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
