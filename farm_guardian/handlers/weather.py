from telegram import Update
from telegram.ext import ContextTypes

from app_context import AppContext, safe_display
from weather.subscribers import subscribe_chat, unsubscribe_chat
from weather.rules import (
    load_weather_file,
    classify_weather,
    format_weather_message,
    diagnose_weather_file,
    format_weather_diagnostic_block,
)


async def weather_on(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx: AppContext):
    chat_id = update.effective_chat.id
    added = subscribe_chat(ctx.paths.weather_subs_file, chat_id, ctx.logger)
    if added:
        await update.message.reply_text("✅ Уведомления по погоде включены.", disable_web_page_preview=True)
    else:
        await update.message.reply_text("Уведомления по погоде уже включены.", disable_web_page_preview=True)


async def weather_off(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx: AppContext):
    chat_id = update.effective_chat.id
    removed = unsubscribe_chat(ctx.paths.weather_subs_file, chat_id, ctx.logger)
    if removed:
        await update.message.reply_text("🛑 Уведомления по погоде выключены.", disable_web_page_preview=True)
    else:
        await update.message.reply_text("Уведомления по погоде и так были выключены.", disable_web_page_preview=True)


async def weather_now(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx: AppContext):
    stale_hours = int(ctx.cfg.get("WEATHER_STALE_HOURS", "6") or "6")
    warn_t12 = float(ctx.cfg.get("WEATHER_WARN_T12", "-12.0") or "-12.0")
    alert_t12 = float(ctx.cfg.get("WEATHER_ALERT_T12", "-18.0") or "-18.0")

    w = load_weather_file(ctx.paths.weather_file)
    state = classify_weather(w, stale_hours=stale_hours, warn_t12=warn_t12, alert_t12=alert_t12)

    msg = format_weather_message(state, w, warn_t12, alert_t12)

    # 👉 главное новое: объясняем, ПОЧЕМУ нет данных
    if state == "stale":
        diag = diagnose_weather_file(ctx.paths.weather_file, stale_hours=stale_hours)
        msg = msg + "\n\n" + format_weather_diagnostic_block(diag)

    await update.message.reply_text(safe_display(msg), disable_web_page_preview=True)
