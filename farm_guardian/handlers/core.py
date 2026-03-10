from telegram import Update
from telegram.ext import ContextTypes

from app_context import AppContext, safe_display
from weather.subscribers import subscribe_chat, load_weather_subscribers


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx: AppContext):
    # авто-подписка на погодные уведомления
    try:
        subscribe_chat(ctx.paths.weather_subs_file, update.effective_chat.id, ctx.logger)
    except Exception:
        ctx.logger.exception("Failed to auto-subscribe chat to weather")

    await update.message.reply_text(
        safe_display(
            "🐄 Дух Фермы на связи.\n\n"
            "Команды:\n"
            "• /note <текст> — запись в память (с подтверждением /yes)\n"
            "• /observe <Имя> <текст> — наблюдение по животному (с подтверждением /yes)\n\n"
            "Подтверждение:\n"
            "• /yes — выполнить предложенную запись\n"
            "• /no — отменить\n\n"
            "Погода (авто-алерты):\n"
            "• /weather_on — включить авто-уведомления\n"
            "• /weather_off — выключить авто-уведомления\n"
            "• /weather_now — проверить прямо сейчас\n\n"
            "Сервис:\n"
            "• /ping — проверка связи\n"
        ),
        disable_web_page_preview=True,
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE, ctx: AppContext):
    subs = load_weather_subscribers(ctx.paths.weather_subs_file, ctx.logger)
    await update.message.reply_text(
        safe_display(
            "✅ На связи.\n"
            f"Secrets: {ctx.cfg.get('SECRETS_PATH')}\n"
            f"Pending TTL: {ctx.cfg.get('PENDING_TTL_SECONDS')} sec\n"
            f"Weather subs: {len(subs)}\n"
            f"Weather file: {ctx.paths.weather_file}\n"
            f"Warn/Alert: {ctx.cfg.get('WEATHER_WARN_T12')} / {ctx.cfg.get('WEATHER_ALERT_T12')}\n"
            f"Last seen weather ts: {ctx.weather.last_ts_seen or '(none)'}\n"
            f"Last weather state: {ctx.weather.last_state}"
        ),
        disable_web_page_preview=True,
    )
