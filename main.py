"""
Telegram Bot — відмічає людей, які не поставили + за вікно часу:
від 18:00 попереднього дня до 16:00 поточного дня.

Бот сам веде базу учасників групи — через три джерела:
  1. Адміністратори — завжди підтягуються через API
  2. Вхід/вихід — відстежуються через ChatMemberHandler
  3. Будь-яке повідомлення — автор додається в базу

Залежності:
    pip install python-telegram-bot==20.* apscheduler pytz

Налаштування:
    1. Створіть бота через @BotFather → отримайте BOT_TOKEN
    2. Замініть BOT_TOKEN нижче
    3. Запустіть бота: python attendance_bot.py
    4. Додайте бота в групу та дайте права адміністратора
    5. Напишіть /setchat у потрібній групі
"""

import logging
from datetime import datetime, timedelta
import os

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, ChatMember
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# ── Налаштування ─────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
TIMEZONE          = "Europe/Kiev"
CHECK_HOUR        = 16
CHECK_MIN         = 0
WINDOW_START_HOUR = 18

# ── Логування ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Сховище стану ─────────────────────────────────────────────────────────────
# chat_id → set of user_id, які поставили + у поточному вікні
checked_in: dict[int, set[int]] = {}

# зареєстровані чати для авто-перевірки
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


def user_mention(user_id: int, full_name: str, username: str | None) -> str:
    if username:
        return f"@{username}"
    return f'<a href="tg://user?id={user_id}">{full_name}</a>'


def get_db(bot_data: dict, chat_id: int) -> dict[int, dict]:
    """Повертає базу учасників для конкретного чату."""
    if chat_id not in bot_data:
        bot_data[chat_id] = {}
    return bot_data[chat_id]


def add_to_db(bot_data: dict, chat_id: int, user) -> None:
    """Додає або оновлює учасника в базі."""
    if user.is_bot:
        return
    db = get_db(bot_data, chat_id)
    db[user.id] = {
        "name":     user.full_name,
        "username": user.username,
    }


# ── Хендлер подій учасників (вхід / вихід) ───────────────────────────────────

async def track_chat_member(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.chat_member
    if not result:
        return

    chat_id = result.chat.id
    user    = result.new_chat_member.user
    status  = result.new_chat_member.status

    if user.is_bot:
        return

    if status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER):
        add_to_db(ctx.bot_data, chat_id, user)
        logger.info("➕ Додано учасника: %s (chat %d)", user.full_name, chat_id)

    elif status in (ChatMember.LEFT, ChatMember.BANNED):
        get_db(ctx.bot_data, chat_id).pop(user.id, None)
        checked_in.get(chat_id, set()).discard(user.id)
        logger.info("➖ Видалено учасника: %s (chat %d)", user.full_name, chat_id)


# ── Хендлер повідомлень ───────────────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    if not msg or not msg.text:
        return

    chat_id = update.effective_chat.id
    user    = msg.from_user

    if user.is_bot:
        return

    # Кожне повідомлення — шанс поповнити базу
    add_to_db(ctx.bot_data, chat_id, user)

    if msg.text.strip() != "+":
        return

    # Обробка "+"
    if not is_within_window():
        start, end = window_bounds()
        await msg.reply_text(
            f"⏰ Реєстрація можлива лише з "
            f"{start.strftime('%d.%m %H:%M')} до {end.strftime('%d.%m %H:%M')}."
        )
        return

    if chat_id not in checked_in:
        checked_in[chat_id] = set()

    if user.id in checked_in[chat_id]:
        await msg.reply_text("Ти вже відмітився ✅")
    else:
        checked_in[chat_id].add(user.id)
        await msg.reply_text(f"✅ {user.first_name}, відмічено!")


# ── Команди ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привіт! Команди:\n"
        "/setchat — зареєструвати цей чат\n"
        "/check   — перевірити прямо зараз\n"
        "/who     — хто вже відмітився\n"
        "/members — показати всіх у базі\n"
        "/reset   — скинути відмітки (тест)\n\n"
        "Щоб відмітитись — напишіть <b>+</b> у чаті.",
        parse_mode="HTML",
    )


async def cmd_setchat(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    registered_chats.add(chat_id)

    if chat_id not in checked_in:
        checked_in[chat_id] = set()

    # Підтягуємо адмінів як початкову базу
    try:
        admins = await ctx.bot.get_chat_administrators(chat_id)
        for member in admins:
            add_to_db(ctx.bot_data, chat_id, member.user)
        admin_count = len([m for m in admins if not m.user.is_bot])
    except Exception as e:
        admin_count = 0
        logger.warning("Не вдалось отримати адмінів: %s", e)

    db = get_db(ctx.bot_data, chat_id)
    await update.message.reply_text(
        f"✅ Чат зареєстровано!\n"
        f"👥 Адмінів додано в базу: {admin_count}\n"
        f"📊 Всього в базі зараз: {len(db)}\n"
        f"⏰ Авто-перевірка щодня о {CHECK_HOUR:02d}:{CHECK_MIN:02d}\n\n"
        f"ℹ️ Решта учасників додаються автоматично, "
        f"коли пишуть у чаті або входять до групи.",
        parse_mode="HTML",
    )


async def cmd_check(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await run_check(ctx.bot, update.effective_chat.id, ctx.bot_data)


async def cmd_who(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    present = checked_in.get(chat_id, set())
    db      = get_db(ctx.bot_data, chat_id)

    if not present:
        await update.message.reply_text("😶 Ще ніхто не поставив +.")
        return

    lines = [
        f"• {user_mention(uid, db.get(uid, {}).get('name', str(uid)), db.get(uid, {}).get('username'))}"
        for uid in present
    ]
    start, end = window_bounds()
    await update.message.reply_text(
        f"✅ <b>Відмітились ({len(lines)}):</b>\n"
        + "\n".join(lines)
        + f"\n\n🕐 Вікно: {start.strftime('%d.%m %H:%M')} – {end.strftime('%d.%m %H:%M')}",
        parse_mode="HTML",
    )


async def cmd_members(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    db      = get_db(ctx.bot_data, chat_id)

    if not db:
        await update.message.reply_text(
            "📭 База порожня.\n"
            "Учасники додаються коли:\n"
            "• пишуть будь-що в чаті\n"
            "• входять у групу\n"
            "• є адміністраторами (при /setchat)"
        )
        return

    present = checked_in.get(chat_id, set())
    lines = [
        f"{'✅' if uid in present else '❌'} "
        f"{user_mention(uid, info['name'], info.get('username'))}"
        for uid, info in db.items()
    ]
    await update.message.reply_text(
        f"👥 <b>База учасників ({len(lines)}):</b>\n" + "\n".join(lines),
        parse_mode="HTML",
    )


async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    checked_in[update.effective_chat.id] = set()
    await update.message.reply_text("🔄 Відмітки скинуто.")


# ── Основна логіка перевірки ──────────────────────────────────────────────────

async def run_check(bot, chat_id: int, bot_data: dict) -> None:
    # Оновлюємо адмінів перед кожною перевіркою
    try:
        admins = await bot.get_chat_administrators(chat_id)
        for member in admins:
            add_to_db(bot_data, chat_id, member.user)
    except Exception as e:
        logger.warning("Не вдалось оновити адмінів: %s", e)

    db      = get_db(bot_data, chat_id)
    present = checked_in.get(chat_id, set())

    if not db:
        await bot.send_message(
            chat_id,
            "ℹ️ База учасників порожня. Учасники додаються автоматично при написанні в чат.",
        )
        return

    absent = {uid: info for uid, info in db.items() if uid not in present}

    start, end = window_bounds()
    header = (
        f"📋 <b>Перевірка явки</b>\n"
        f"🕐 {start.strftime('%d.%m %H:%M')} – {end.strftime('%d.%m %H:%M')}\n"
        f"👥 В базі: {len(db)} | ✅ Відмітились: {len(present)} | ❌ Відсутні: {len(absent)}\n\n"
    )

    if not absent:
        await bot.send_message(chat_id, header + "🎉 Всі відмітились! Молодці 👏", parse_mode="HTML")
    else:
        mentions = "\n".join(
            f"• {user_mention(uid, info['name'], info.get('username'))}"
            for uid, info in absent.items()
        )
        await bot.send_message(
            chat_id,
            header + f"❌ <b>Не відмітились:</b>\n{mentions}",
            parse_mode="HTML",
        )

    # Скидаємо після перевірки — починається нове вікно
    checked_in[chat_id] = set()


async def scheduled_check(app: Application) -> None:
    logger.info("Scheduled check for %d chats", len(registered_chats))
    for chat_id in list(registered_chats):
        try:
            await run_check(app.bot, chat_id, app.bot_data)
        except Exception as e:
            logger.error("Error in chat %d: %s", chat_id, e)


# ── Запуск ────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("setchat", cmd_setchat))
    app.add_handler(CommandHandler("check",   cmd_check))
    app.add_handler(CommandHandler("who",     cmd_who))
    app.add_handler(CommandHandler("members", cmd_members))
    app.add_handler(CommandHandler("reset",   cmd_reset))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ВАЖЛИВО: відстеження входу/виходу учасників
    app.add_handler(ChatMemberHandler(track_chat_member, ChatMemberHandler.CHAT_MEMBER))

    # Планувальник стартує всередині async-loop через post_init
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
        logger.info("Scheduler started. Daily check at %02d:%02d %s", CHECK_HOUR, CHECK_MIN, TIMEZONE)

    app.post_init = post_init

    logger.info("Bot started.")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "chat_member"],
    )


if __name__ == "__main__":
    main()
