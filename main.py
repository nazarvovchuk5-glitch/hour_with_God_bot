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
BOT_TOKEN         = os.environ.get("BOT_TOKEN", "8710025600:AAGkDZQPR3ZgVJVYzQeVerjBLpuqtTQiWvQ")
TIMEZONE          = "Europe/Kiev"
CHECK_HOUR        = 16
CHECK_MIN         = 0
WINDOW_START_HOUR = 18

# ── Учасники (вносьте вручну) ─────────────────────────────────────────────────
MEMBERS: dict[int, dict] = {
    653369664: {"name": "НАйкрасивіша дівчинка",  "username": "mlllana"},
    542909091: {"name": "Назар Вовчук",  "username": "vovchuk_n"},
    # додавайте учасників сюди
}

# ── Логування ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Стан ─────────────────────────────────────────────────────────────────────
checked_in: dict[int, set[int]] = {}
registered_chats: set[int] = set()

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

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if user_id not in MEMBERS:
        return  # ігноруємо тих, кого немає в списку

    if not is_within_window():
        start, end = window_bounds()
        await msg.reply_text(
            f"⏰ Реєстрація можлива лише з "
            f"{start.strftime('%d.%m %H:%M')} до {end.strftime('%d.%m %H:%M')}."
        )
        return

    if chat_id not in checked_in:
        checked_in[chat_id] = set()

    if not user_id in checked_in[chat_id]:
        checked_in[chat_id].add(user_id)



# ── Команди ───────────────────────────────────────────────────────────────────

async def cmd_setchat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    registered_chats.add(chat_id)
    if chat_id not in checked_in:
        checked_in[chat_id] = set()

    await update.message.reply_text(
        f"✅ Чат зареєстровано!\n"
        f"👥 Учасників у базі: {len(MEMBERS)}\n"
        f"⏰ Авто-перевірка щодня о {CHECK_HOUR:02d}:{CHECK_MIN:02d}",
        parse_mode="HTML",
    )


async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await run_check(ctx.bot, update.effective_chat.id)


# ── Перевірка явки ────────────────────────────────────────────────────────────

async def run_check(bot, chat_id: int) -> None:
    present = checked_in.get(chat_id, set())
    absent  = {uid: info for uid, info in MEMBERS.items() if uid not in present}

    start, end = window_bounds()

    if not absent:
        await bot.send_message(chat_id, "🎉 Всі відмітились! Молодці 👏", parse_mode="HTML")
    else:
        mentions = "\n".join(
            f"• {user_mention(uid, info)}" for uid, info in absent.items()
        )
        await bot.send_message(
            chat_id,
            f"❌ <b>Як година з Богом? </b>\n{mentions}",
            parse_mode="HTML",
        )

    # Скидаємо після перевірки
    checked_in[chat_id] = set()


async def scheduled_check(app: Application) -> None:
    for chat_id in list(registered_chats):
        try:
            await run_check(app.bot, chat_id)
        except Exception as e:
            logger.error("Error in chat %d: %s", chat_id, e)


# ── Запуск ────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("setchat", cmd_setchat))
    app.add_handler(CommandHandler("check",   cmd_check))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        scheduled_check,
        trigger="cron",
        hour=CHECK_HOUR,
        minute=CHECK_MIN,
        kwargs={"app": app},
    )

    async def post_init(application: Application) -> None:
        scheduler.start()
        logger.info("Scheduler started. Daily check at %02d:%02d", CHECK_HOUR, CHECK_MIN)

    app.post_init = post_init

    logger.info("Bot started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
