import asyncio
import logging
from pathlib import Path

from telegram import BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler

from app_context import AppContext, Paths
from config import load_config
from weather.monitor import start_weather_monitor

from handlers.core import start as h_start, ping as h_ping
from handlers.confirm import yes as h_yes, no as h_no
from handlers.farm import note as h_note, observe as h_observe
from handlers.weather import (
    weather_on as h_weather_on,
    weather_off as h_weather_off,
    weather_now as h_weather_now,
)

# -------------------- ЛОГИ --------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")

# Чтобы не печатались полные URL (и, не дай бог, токен) в логах http-клиента
logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    here = Path(__file__).resolve().parent
    cfg = load_config(here)

    weather_file = here / "farm_memory" / "sensors" / "weather.json"
    weather_subs_file = here / "storage" / "weather_subscribers.json"
    weather_subs_file.parent.mkdir(parents=True, exist_ok=True)

    ctx = AppContext(
        cfg=cfg,
        paths=Paths(here=here, weather_file=weather_file, weather_subs_file=weather_subs_file),
        logger=logger,
    )

    async def _post_init(app):
        # тут гарантированно есть running event loop
        ctx.loop = asyncio.get_running_loop()
        start_weather_monitor(app, ctx)

        # Чистим/задаём команды бота (убираем хвосты OpenClaw)
        await app.bot.set_my_commands(
            [
                BotCommand("start", "старт"),
                BotCommand("ping", "проверка"),
                BotCommand("weather_now", "погода сейчас"),
                BotCommand("weather_on", "вкл уведомления погоды"),
                BotCommand("weather_off", "выкл уведомления погоды"),
                BotCommand("note", "запись в журнал"),
                BotCommand("observe", "наблюдение по животному"),
                BotCommand("yes", "подтвердить запись"),
                BotCommand("no", "отменить запись"),
            ]
        )

    app = ApplicationBuilder().token(cfg["TELEGRAM_TOKEN"]).post_init(_post_init).build()

    # handlers with ctx binding
    app.add_handler(CommandHandler("start", lambda u, c: h_start(u, c, ctx)))
    app.add_handler(CommandHandler("ping", lambda u, c: h_ping(u, c, ctx)))
    app.add_handler(CommandHandler("yes", lambda u, c: h_yes(u, c, ctx)))
    app.add_handler(CommandHandler("no", lambda u, c: h_no(u, c, ctx)))
    app.add_handler(CommandHandler("note", lambda u, c: h_note(u, c, ctx)))
    app.add_handler(CommandHandler("observe", lambda u, c: h_observe(u, c, ctx)))

    app.add_handler(CommandHandler("weather_on", lambda u, c: h_weather_on(u, c, ctx)))
    app.add_handler(CommandHandler("weather_off", lambda u, c: h_weather_off(u, c, ctx)))
    app.add_handler(CommandHandler("weather_now", lambda u, c: h_weather_now(u, c, ctx)))

    logger.info("🐂 Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
