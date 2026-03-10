import asyncio
import time
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app_context import AppContext, safe_display
from weather.rules import load_weather_file, classify_weather, format_weather_message
from weather.subscribers import load_weather_subscribers


# Повторы alert 2 раза в сутки (GMT+5): 09:00 и 19:00
ALERT_REPEAT_TZ = timezone(timedelta(hours=5))
ALERT_REPEAT_MORNING_HOUR = 9
ALERT_REPEAT_EVENING_HOUR = 19


def start_weather_monitor(app: Any, ctx: AppContext) -> None:
    """
    Фоновый поток:
    - читает weather.json раз в N секунд
    - шлёт сообщения подписчикам
    Антиспам: сообщения только при смене состояния / stale / восстановлении.
    + Повтор alert 2 раза в сутки (09:00 и 19:00 GMT+5) по новому ts.
    """
    if ctx.weather.monitor_started:
        return

    ctx.weather.monitor_started = True

    interval = int(ctx.cfg.get("WEATHER_CHECK_EVERY_SEC", "300") or "300")
    stale_hours = int(ctx.cfg.get("WEATHER_STALE_HOURS", "6") or "6")
    warn_t12 = float(ctx.cfg.get("WEATHER_WARN_T12", "-12.0") or "-12.0")
    alert_t12 = float(ctx.cfg.get("WEATHER_ALERT_T12", "-18.0") or "-18.0")

    def _send(chat_id: int, text: str) -> None:
        """
        Безопасная отправка из фонового потока:
        планируем coroutine в event loop приложения.
        """
        if ctx.loop is None:
            ctx.logger.warning("No event loop in ctx; cannot send message")
            return

        async def _coro():
            await app.bot.send_message(
                chat_id=chat_id,
                text=safe_display(text),
                disable_web_page_preview=True,
            )

        try:
            asyncio.run_coroutine_threadsafe(_coro(), ctx.loop)
        except Exception:
            ctx.logger.exception("Failed to schedule send_message")

    def loop():
        ctx.logger.info(
            f"🌦 Weather monitor started: every {interval}s | stale {stale_hours}h | warn {warn_t12} | alert {alert_t12} | "
            f"repeat alert @ {ALERT_REPEAT_MORNING_HOUR}:00/{ALERT_REPEAT_EVENING_HOUR}:00 GMT+5"
        )

        while True:
            try:
                w = load_weather_file(ctx.paths.weather_file)
                ts = (w.get("ts") or "").strip()
                state = classify_weather(w, stale_hours=stale_hours, warn_t12=warn_t12, alert_t12=alert_t12)

                subs = load_weather_subscribers(ctx.paths.weather_subs_file, ctx.logger)
                if not subs:
                    ctx.weather.last_state = state
                    if ts:
                        ctx.weather.last_ts_seen = ts
                    time.sleep(interval)
                    continue

                # STALE: только при переходе в stale
                if state == "stale":
                    if ctx.weather.last_state != "stale":
                        msg = format_weather_message("stale", w, warn_t12, alert_t12)
                        for chat_id in subs:
                            _send(chat_id, msg)
                    ctx.weather.last_state = "stale"
                    time.sleep(interval)
                    continue

                # восстановление после stale
                if ctx.weather.last_state == "stale":
                    for chat_id in subs:
                        _send(chat_id, "✅ Погода: обновления восстановились.")

                # новый ts
                if ts and ts != ctx.weather.last_ts_seen:
                    now_local = datetime.now(ALERT_REPEAT_TZ)
                    today = now_local.strftime("%Y-%m-%d")
                    hour = now_local.hour

                    # если день сменился — сброс окон
                    if ctx.weather.last_repeat.get("date") != today:
                        ctx.weather.last_repeat = {"date": today, "morning_sent": False, "evening_sent": False}

                    # 1) обычное оповещение при смене состояния
                    if state != ctx.weather.last_state:
                        msg = format_weather_message(state, w, warn_t12, alert_t12)
                        for chat_id in subs:
                            _send(chat_id, msg)

                    # 2) повтор alert 2 раза
                    if state == "alert":
                        if hour >= ALERT_REPEAT_MORNING_HOUR and not ctx.weather.last_repeat.get("morning_sent", False):
                            msg = format_weather_message("alert", w, warn_t12, alert_t12)
                            for chat_id in subs:
                                _send(chat_id, msg)
                            ctx.weather.last_repeat["morning_sent"] = True

                        if hour >= ALERT_REPEAT_EVENING_HOUR and not ctx.weather.last_repeat.get("evening_sent", False):
                            msg = format_weather_message("alert", w, warn_t12, alert_t12)
                            for chat_id in subs:
                                _send(chat_id, msg)
                            ctx.weather.last_repeat["evening_sent"] = True

                    ctx.weather.last_ts_seen = ts
                    ctx.weather.last_state = state

            except Exception:
                ctx.logger.exception("Weather monitor loop error")

            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()
