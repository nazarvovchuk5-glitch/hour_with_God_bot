import logging
import os
from datetime import datetime, time as datetime_time

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
CHAT_ID           = int(os.environ.get("CHAT_ID", -1003753828565))
TIMEZONE          = "Europe/Kiev"
CHECK_HOUR        = 16
CHECK_MIN         = 0
REMIND_HOUR       = 18
REMIND_MIN        = 0
WINDOW_START_HOUR = 18

# ── Учасники ──────────────────────────────────────────────────────────────────
MEMBERS: dict[int, dict] = {
    542909091:  {"name": "Назар Вовчук",     "username": "vovchuk_n",        "checked": False},
    600916975:  {"name": "Віталік Шегда",    "username": "v_shehda",         "checked": False},
    683631390:  {"name": "Павло Скіцко",     "username": "pavlo_skitsko",    "checked": False},
    410711173:  {"name": "Павло Веляник",    "username": "poulVel",          "checked": False},
    439061132:  {"name": "Володя Веляник",   "username": "sound_volodya",    "checked": False},
    1313242876: {"name": "Тереза Федорук",   "username": "Defkanvi",         "checked": False},
    1270762844: {"name": "Діана Паркулаб",   "username": "di_parker1",       "checked": False},
    554304091:  {"name": "Діана Черняк",     "username": "cherniak_diana",   "checked": False},
    426703270:  {"name": "Юра Чигур",        "username": "yurii_chygur",     "checked": False},
    1032761760: {"name": "Надія Пушкар",     "username": "Nadiya_psh",       "checked": False},
    1113982047: {"name": "Христя",           "username": "kristparl",        "checked": False},
    1039513473: {"name": "Влад Гайдей",      "username": "vladislav_gaydey", "checked": False},
    531725686:  {"name": "Каріна Пуйда",     "username": "karina_puida",     "checked": False},
    6332427398: {"name": "Влад Севостьянов", "username": "JohnDeer102",      "checked": False},
    761640440:  {"name": "Настя Чигур",      "username": "chygurkaa",        "checked": False},
    380071501:  {"name": "Юра Бурчак",       "username": "burchak1",         "checked": False},
    1496062214: {"name": "Тимофій Строіч",   "username": "t_stroich",        "checked": False},
    627457986:  {"name": "Марко Черняк",     "username": "cherniak_marko",   "checked": False},
    393415671:  {"name": "Юля Бурчак",       "username": "jburchak",         "checked": False},
    1182319849: {"name": "Влад Жмудовський",                                 "checked": False},
    788031811: {"name": "Андрій Мельничук",  "username": "melnichhuk",      "checked": False},
    788031811: {"name": "Софія Черняк",  "username": "sofia_cherniak",      "checked": False},
}

# ── Логування ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

tz = pytz.timezone(TIMEZONE)


# ── Допоміжні функції ─────────────────────────────────────────────────────────

def is_within_window() -> bool:
    """Вікно відкрите з 18:00 до 16:00. Мертва зона: 16:00–18:00."""
    hour = datetime.now(tz).hour
    return not (CHECK_HOUR <= hour < WINDOW_START_HOUR)


def reset_all() -> None:
    """Скидає checked = False для всіх учасників."""
    for info in MEMBERS.values():
        info["checked"] = False


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

    if not MEMBERS[user_id]["checked"]:
        MEMBERS[user_id]["checked"] = True
        logger.info("User %d відмічено.", user_id)


# ── Команди ───────────────────────────────────────────────────────────────────

async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await run_check(ctx.bot)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує хто вже відмітився без закриття циклу."""
    present = {uid: info for uid, info in MEMBERS.items() if info["checked"]}
    absent  = {uid: info for uid, info in MEMBERS.items() if not info["checked"]}

    lines = [f"📊 <b>Статус (вікно {WINDOW_START_HOUR:02d}:00 – {CHECK_HOUR:02d}:00)</b>\n"]

    if present:
        lines.append("✅ <b>Відмітились:</b>")
        for uid, info in present.items():
            lines.append(f"  • {user_mention(uid, info)}")

    if absent:
        lines.append("\n❌ <b>Ще не відмітились:</b>")
        for uid, info in absent.items():
            lines.append(f"  • {user_mention(uid, info)}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── Нагадування о 18:00 ───────────────────────────────────────────────────────

async def send_reminder(app: Application) -> None:
    reset_all()  # скидаємо всі checked → False
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
    absent = {uid: info for uid, info in MEMBERS.items() if not info["checked"]}
    logger.info("run_check: absent=%d", len(absent))

    if not absent:
        await bot.send_message(CHAT_ID, "🎉 Всі відмітились! Молодці 👏", parse_mode="HTML")
    else:
        mentions = "\n".join(
            f"• {user_mention(uid, info)}" for uid, info in absent.items()
        )
        await bot.send_message(
            CHAT_ID,
            f"❌ <b>А ви провели годину з Богом?:</b>\n{mentions}"
            f"\n\n<b>Якщо ні, то ось номер карти, скиньте 200 грн штрафу</b>\n"
            f"<b>5375 4112 1882 3420</b>\n"
            f'<a href="https://send.monobank.ua/jar/Zc7jQS4v7">💳 Посилання моно</a>',
            parse_mode="HTML",
        )


async def scheduled_check(app: Application) -> None:
    logger.info("Running scheduled check for chat %d", CHAT_ID)
    try:
        await run_check(app.bot)
    except Exception as e:
        logger.error("Error in scheduled check: %s", e)


# ── Запуск ────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("check",  cmd_check))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = AsyncIOScheduler(timezone=tz)

    scheduler.add_job(
        scheduled_check,
        id="scheduled_check",
        trigger="cron",
        hour=CHECK_HOUR,
        minute=CHECK_MIN,
        kwargs={"app": app},
    )

    scheduler.add_job(
        send_reminder,
        id="send_reminder",
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
