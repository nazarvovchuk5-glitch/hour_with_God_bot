import logging
import os
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ── Налаштування ─────────────────────────────────────────────────────────────
BOT_TOKEN         = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
CHAT_ID           = int(os.environ.get("CHAT_ID", -5164276463))  # ID групи
TIMEZONE          = "Europe/Kiev"
CHECK_HOUR        = 16
CHECK_MIN         = 0
REMIND_HOUR       = 18
REMIND_MIN        = 0
WINDOW_START_HOUR = 18

# ── Учасники ──────────────────────────────────────────────────────────────────
MEMBERS: dict[int, dict] = {
    653369664: {"name": "Міла",         "username": "mlllana"},
    542909091: {"name": "Назар Вовчук", "username": "vovchuk_n"},
    # додавайте учасників сюди
}

# ── Логування ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Стан ─────────────────────────────────────────────────────────────────────
checked_in: set[int] = set()  # set of user_id які поставили + у поточному вікні

tz = pytz.timezone(TIMEZONE)


# ── Допоміжні функції ─────────────────────────────────────────────────────────

def window_bounds() -> tuple[datetime, datetime]:
    now   = datetime.now(tz)
    end   = now.replace(hour=CHECK_HOUR, minute=CHECK_MIN, second=0, microsecond=0)
    start = (end - timedelta(days=1)).replace(
        hour=WINDOW_START_HOUR, minute=0, second=0, microsecond=0
    )
    return start, end


def is_within_window() -> bool:
    now = datetime.now(tz)
    start, end = window_bounds()
    return start <= now <= end


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

    user_id = update.effective_user.id
    logger.info("Повідомлення '+' від user_id=%d", user_id)

    if user_id not in MEMBERS:
        return

    if not is_within_window():
        start, end = window_bounds()
        await msg.reply_text(
            f"⏰ Реєстрація можлива лише з "
            f"{start.strftime('%d.%m %H:%M')} до {end.strftime('%d.%m %H:%M')}."
        )
        return

    if user_id in checked_in:
        await msg.reply_text("Ти вже відмітився ✅")
    else:
        checked_in.add(user_id)
        await msg.reply_text(f"✅ {update.effective_user.first_name}, відмічено!")


# ── Команда /check ────────────────────────────────────────────────────────────

async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await run_check(ctx.bot)


# ── Нагадування о 18:00 ───────────────────────────────────────────────────────

async def send_reminder(app: Application) -> None:
    global checked_in
    checked_in = set()  # скидаємо — починається нове вікно
    try:
        await app.bot.send_message(
            CHAT_ID,
            "🙏 <b>Як ваша година з Богом?</b>\n\nНапишіть <b>+</b> якщо провели час з Богом сьогодні.",
            parse_mode="HTML",
        )
        logger.info("Reminder sent to chat %d", CHAT_ID)
    except Exception as e:
        logger.error("Error sending reminder: %s", e)


# ── Перевірка явки о 16:00 ────────────────────────────────────────────────────

async def run_check(bot) -> None:
    absent = {uid: info for uid, info in MEMBERS.items() if uid not in checked_in}

    if not absent:
        await bot.send_message(CHAT_ID, "🎉 Всі відмітились! Молодці 👏", parse_mode="HTML")
    else:
        mentions = "\n".join(
            f"• {user_mention(uid, info)}" for uid, info in absent.items()
        )
        await bot.send_message(
            CHAT_ID,
            f"❌ <b>Не відмітились:</b>\n{mentions}",
            parse_mode="HTML",
        )

    global checked_in
    checked_in = set()


async def scheduled_check(app: Application) -> None:
    logger.info("Running scheduled check for chat %d", CHAT_ID)
    try:
        await run_check(app.bot)
    except Exception as e:
        logger.error("Error in scheduled check: %s", e)


# ── Запуск ────────────────────────────────────────────────────────────────────

def main() -> None:
    if not CHAT_ID:
        raise ValueError("CHAT_ID не встановлено! Додайте змінну середовища CHAT_ID.")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("check", cmd_check))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = AsyncIOScheduler(timezone=tz)

    scheduler.add_job(
        scheduled_check,
        id="daily_check",
        trigger="cron",
        hour=CHECK_HOUR,
        minute=CHECK_MIN,
        kwargs={"app": app},
    )

    scheduler.add_job(
        send_reminder,
        id="daily_reminder",
        trigger="cron",
        hour=REMIND_HOUR,
        minute=REMIND_MIN,
        kwargs={"app": app},
    )

    async def post_init(application: Application) -> None:
        scheduler.start()
        logger.info(
            "Bot started. CHAT_ID=%d | Check at %02d:%02d | Reminder at %02d:%02d",
            CHAT_ID, CHECK_HOUR, CHECK_MIN, REMIND_HOUR, REMIND_MIN,
        )

    app.post_init = post_init

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
