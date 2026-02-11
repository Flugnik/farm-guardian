import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from controller import (
    build_plan_from_text,
    execute_action,
    format_plan_preview,
    ControllerError,
)

from pending_store import get_plan, set_plan, clear_plan, cleanup


# -------------------- ЛОГИ --------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")


# -------------------- PATHS --------------------
HERE = Path(__file__).resolve().parent
WEATHER_FILE = HERE / "farm_memory" / "sensors" / "weather.json"
WEATHER_SUBS_FILE = HERE / "storage" / "weather_subscribers.json"
WEATHER_SUBS_FILE.parent.mkdir(parents=True, exist_ok=True)


# -------------------- WEATHER DEFAULTS (под -18°C) --------------------
WEATHER_CHECK_EVERY_SEC_DEFAULT = 300   # 5 минут
WEATHER_STALE_HOURS_DEFAULT = 6         # если старше 6 часов — "погода упала"
WEATHER_WARN_T12_DEFAULT = -12.0        # предупредить: ≤ -12
WEATHER_ALERT_T12_DEFAULT = -18.0       # тревога: ≤ -18

# Повторы alert (GMT+5): 09:00 и 19:00
ALERT_REPEAT_TZ = timezone(timedelta(hours=5))
ALERT_REPEAT_MORNING_HOUR = 9
ALERT_REPEAT_EVENING_HOUR = 19


# -------------------- CONFIG (secrets.json) --------------------
def _read_json(path: Path) -> Dict[str, Any]:
    """
    utf-8-sig съедает BOM.
    """
    try:
        raw = path.read_text(encoding="utf-8-sig")
        return json.loads(raw) if raw.strip() else {}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"secrets.json битый JSON: {path} | {e}")


def load_config() -> Dict[str, str]:
    """
    Приоритет:
    1) config/secrets.json
    2) переменные окружения (перекрывают secrets)
    """
    secrets_path = HERE / "config" / "secrets.json"
    secrets = _read_json(secrets_path)

    def pick(key: str, default: str = "") -> str:
        env = os.environ.get(key, "").strip()
        if env:
            return env
        v = str(secrets.get(key, default) or "").strip()
        return v

    cfg = {
        "TELEGRAM_TOKEN": pick("TELEGRAM_TOKEN"),
        "PENDING_TTL_SECONDS": pick("PENDING_TTL_SECONDS", "900"),  # 15 минут
        "SECRETS_PATH": str(secrets_path),

        # Weather knobs (можно переопределять из secrets/env)
        "WEATHER_CHECK_EVERY_SEC": pick("WEATHER_CHECK_EVERY_SEC", str(WEATHER_CHECK_EVERY_SEC_DEFAULT)),
        "WEATHER_STALE_HOURS": pick("WEATHER_STALE_HOURS", str(WEATHER_STALE_HOURS_DEFAULT)),
        "WEATHER_WARN_T12": pick("WEATHER_WARN_T12", str(WEATHER_WARN_T12_DEFAULT)),
        "WEATHER_ALERT_T12": pick("WEATHER_ALERT_T12", str(WEATHER_ALERT_T12_DEFAULT)),
    }

    if not cfg["TELEGRAM_TOKEN"]:
        raise RuntimeError(
            "Не хватает ключа TELEGRAM_TOKEN.\n"
            f"Проверь файл: {cfg['SECRETS_PATH']}\n"
            "Он должен содержать TELEGRAM_TOKEN."
        )

    return cfg


# -------------------- Telegram anti-URL --------------------
def _safe_display(text: str) -> str:
    """
    Telegram иногда распознаёт куски как URL (feed.md, resources/...).
    Ломаем отображение, НЕ ломая реальные пути в файлах.
    """
    if not text:
        return text

    text = re.sub(r"\.md\b", "·md", text)  # feed.md -> feed·md
    text = text.replace("resources/", "resources／")
    text = text.replace("system/", "system／")
    text = text.replace("animals/", "animals／")
    text = text.replace("journal/", "journal／")
    text = text.replace("http://", "hxxp://").replace("https://", "hxxps://")
    return text


CFG: Dict[str, str] = {}

# Чтобы монитор можно было остановить/не плодить потоки
WEATHER_MONITOR_STARTED = False


async def _edit_status(msg, text: str):
    await msg.edit_text(_safe_display(text), disable_web_page_preview=True)


# -------------------- Weather subscribers --------------------
def _load_weather_subscribers() -> List[int]:
    try:
        raw = WEATHER_SUBS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        subs = data.get("subscribers") or []
        out: List[int] = []
        seen = set()
        for x in subs:
            try:
                cid = int(x)
            except Exception:
                continue
            if cid not in seen:
                out.append(cid)
                seen.add(cid)
        return out
    except FileNotFoundError:
        return []
    except Exception:
        logger.exception("Failed to read weather_subscribers.json")
        return []


def _save_weather_subscribers(subs: List[int]) -> None:
    payload = {"subscribers": subs}
    WEATHER_SUBS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def subscribe_chat(chat_id: int) -> bool:
    subs = _load_weather_subscribers()
    if chat_id in subs:
        return False
    subs.append(chat_id)
    _save_weather_subscribers(subs)
    return True


def unsubscribe_chat(chat_id: int) -> bool:
    subs = _load_weather_subscribers()
    if chat_id not in subs:
        return False
    subs = [x for x in subs if x != chat_id]
    _save_weather_subscribers(subs)
    return True


# -------------------- Weather monitor helpers --------------------
WEATHER_LAST_TS_SEEN: str = ""
WEATHER_LAST_STATE: str = "unknown"  # ok | warn | alert | stale | unknown

# Повторы alert 2 раза в сутки (GMT+5), антиспам по окнам
WEATHER_LAST_REPEAT = {"date": "", "morning_sent": False, "evening_sent": False}


def _load_weather_file() -> Dict[str, Any]:
    if not WEATHER_FILE.exists():
        return {}
    try:
        return json.loads(WEATHER_FILE.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def _hours_since_ts(ts: str) -> float:
    if not ts:
        return 9999.0
    try:
        dt = datetime.fromisoformat(ts)
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return (now - dt).total_seconds() / 3600.0
    except Exception:
        return 9999.0


def _classify_weather(w: Dict[str, Any], stale_hours: int, warn_t12: float, alert_t12: float) -> str:
    if not w:
        return "stale"

    ts = (w.get("ts") or "").strip()
    if _hours_since_ts(ts) >= stale_hours:
        return "stale"

    t12 = w.get("t_min_next_12h")
    if t12 is None:
        return "stale"

    try:
        t12f = float(t12)
    except Exception:
        return "stale"

    if t12f <= alert_t12:
        return "alert"
    if t12f <= warn_t12:
        return "warn"
    return "ok"


def _format_weather_message(state: str, w: Dict[str, Any], warn_t12: float, alert_t12: float) -> str:
    if state == "stale":
        return (
            "⚠️ Погода: нет свежих данных.\n"
            "Проверь, что weather_collector.py запускается по расписанию и пишет farm_memory/sensors/weather.json."
        )

    t12 = w.get("t_min_next_12h")
    t24 = w.get("t_min_next_24h")
    ts = w.get("ts", "")
    src = w.get("source", "")

    if state == "alert":
        return (
            f"🟥 МОРОЗ: минимум ближайшие 12ч = {t12}°C (24ч = {t24}°C)\n"
            f"Порог тревоги: {alert_t12}°C\n"
            f"Обновлено: {ts} ({src})\n\n"
            "Чек-лист:\n"
            "- АКБ/пуск (если актуально)\n"
            "- телята: подогрев/сквозняки\n"
            "- вода/скважина: контур/узел\n"
            "- коровник: режим тепла по ситуации"
        )

    if state == "warn":
        return (
            f"🟧 РИСК МОРОЗА: минимум ближайшие 12ч = {t12}°C (24ч = {t24}°C)\n"
            f"Порог предупреждения: {warn_t12}°C\n"
            f"Обновлено: {ts} ({src})\n\n"
            "Проверь телят/воду по ситуации."
        )

    return (
        f"🟩 Погода ок: минимум ближайшие 12ч = {t12}°C (24ч = {t24}°C)\n"
        f"Обновлено: {ts} ({src})"
    )


def start_weather_monitor(app):
    """
    Запускает фоновый поток, который:
    - читает weather.json раз в N секунд
    - шлёт сообщения подписчикам через Telegram bot API
    Антиспам: сообщения только при изменении состояния / переходе в stale / восстановлении.
    + Повтор alert 2 раза в сутки (09:00 и 19:00 GMT+5) при новом ts.
    """
    global WEATHER_MONITOR_STARTED
    if WEATHER_MONITOR_STARTED:
        return

    WEATHER_MONITOR_STARTED = True

    interval = int(CFG.get("WEATHER_CHECK_EVERY_SEC", str(WEATHER_CHECK_EVERY_SEC_DEFAULT)) or str(WEATHER_CHECK_EVERY_SEC_DEFAULT))
    stale_hours = int(CFG.get("WEATHER_STALE_HOURS", str(WEATHER_STALE_HOURS_DEFAULT)) or str(WEATHER_STALE_HOURS_DEFAULT))
    warn_t12 = float(CFG.get("WEATHER_WARN_T12", str(WEATHER_WARN_T12_DEFAULT)) or str(WEATHER_WARN_T12_DEFAULT))
    alert_t12 = float(CFG.get("WEATHER_ALERT_T12", str(WEATHER_ALERT_T12_DEFAULT)) or str(WEATHER_ALERT_T12_DEFAULT))

    def loop():
        global WEATHER_LAST_TS_SEEN, WEATHER_LAST_STATE, WEATHER_LAST_REPEAT

        logger.info(
            f"🌦 Weather monitor started: every {interval}s | stale {stale_hours}h | warn {warn_t12} | alert {alert_t12} | "
            f"repeat alert @ {ALERT_REPEAT_MORNING_HOUR}:00/{ALERT_REPEAT_EVENING_HOUR}:00 GMT+5"
        )

        while True:
            try:
                w = _load_weather_file()
                ts = (w.get("ts") or "").strip()
                state = _classify_weather(w, stale_hours=stale_hours, warn_t12=warn_t12, alert_t12=alert_t12)

                subs = _load_weather_subscribers()
                if not subs:
                    WEATHER_LAST_STATE = state
                    if ts:
                        WEATHER_LAST_TS_SEEN = ts
                    time.sleep(interval)
                    continue

                # STALE: только при переходе в stale
                if state == "stale":
                    if WEATHER_LAST_STATE != "stale":
                        msg = _format_weather_message("stale", w, warn_t12, alert_t12)
                        for chat_id in subs:
                            try:
                                app.bot.send_message(chat_id=chat_id, text=_safe_display(msg), disable_web_page_preview=True)
                            except Exception:
                                logger.exception("Failed to send stale weather message")
                    WEATHER_LAST_STATE = "stale"
                    time.sleep(interval)
                    continue

                # восстановление после stale
                if WEATHER_LAST_STATE == "stale":
                    for chat_id in subs:
                        try:
                            app.bot.send_message(
                                chat_id=chat_id,
                                text=_safe_display("✅ Погода: обновления восстановились."),
                                disable_web_page_preview=True,
                            )
                        except Exception:
                            logger.exception("Failed to send recovery message")

                # новый ts
                if ts and ts != WEATHER_LAST_TS_SEEN:
                    # локальная дата/время в GMT+5 (не зависит от таймзоны ПК)
                    now_local = datetime.now(ALERT_REPEAT_TZ)
                    today = now_local.strftime("%Y-%m-%d")
                    hour = now_local.hour

                    # если день сменился — сброс окон
                    if WEATHER_LAST_REPEAT.get("date") != today:
                        WEATHER_LAST_REPEAT = {"date": today, "morning_sent": False, "evening_sent": False}

                    # 1) обычное оповещение при смене состояния
                    if state != WEATHER_LAST_STATE:
                        msg = _format_weather_message(state, w, warn_t12, alert_t12)
                        for chat_id in subs:
                            try:
                                app.bot.send_message(chat_id=chat_id, text=_safe_display(msg), disable_web_page_preview=True)
                            except Exception:
                                logger.exception("Failed to send weather alert message")

                    # 2) повтор alert в 09:00 и 19:00 (по новому ts), даже если state не менялся
                    if state == "alert":
                        # утро
                        if hour >= ALERT_REPEAT_MORNING_HOUR and not WEATHER_LAST_REPEAT.get("morning_sent", False):
                            msg = _format_weather_message("alert", w, warn_t12, alert_t12)
                            for chat_id in subs:
                                try:
                                    app.bot.send_message(chat_id=chat_id, text=_safe_display(msg), disable_web_page_preview=True)
                                except Exception:
                                    logger.exception("Failed to send morning alert repeat")
                            WEATHER_LAST_REPEAT["morning_sent"] = True

                        # вечер
                        if hour >= ALERT_REPEAT_EVENING_HOUR and not WEATHER_LAST_REPEAT.get("evening_sent", False):
                            msg = _format_weather_message("alert", w, warn_t12, alert_t12)
                            for chat_id in subs:
                                try:
                                    app.bot.send_message(chat_id=chat_id, text=_safe_display(msg), disable_web_page_preview=True)
                                except Exception:
                                    logger.exception("Failed to send evening alert repeat")
                            WEATHER_LAST_REPEAT["evening_sent"] = True

                    WEATHER_LAST_TS_SEEN = ts
                    WEATHER_LAST_STATE = state

            except Exception:
                logger.exception("Weather monitor loop error")

            time.sleep(interval)

    t = threading.Thread(target=loop, daemon=True)
    t.start()


# -------------------- HANDLERS --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # авто-подписка на погодные уведомления
    try:
        subscribe_chat(update.effective_chat.id)
    except Exception:
        logger.exception("Failed to auto-subscribe chat to weather")

    await update.message.reply_text(
        _safe_display(
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


async def weather_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    added = subscribe_chat(chat_id)
    if added:
        await update.message.reply_text("✅ Уведомления по погоде включены.", disable_web_page_preview=True)
    else:
        await update.message.reply_text("Уведомления по погоде уже включены.", disable_web_page_preview=True)


async def weather_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    removed = unsubscribe_chat(chat_id)
    if removed:
        await update.message.reply_text("🛑 Уведомления по погоде выключены.", disable_web_page_preview=True)
    else:
        await update.message.reply_text("Уведомления по погоде и так были выключены.", disable_web_page_preview=True)


async def weather_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ручная диагностика: читает weather.json и отвечает текущим статусом.
    Никакого антиспама — всегда отвечает.
    """
    stale_hours = int(CFG.get("WEATHER_STALE_HOURS", str(WEATHER_STALE_HOURS_DEFAULT)) or str(WEATHER_STALE_HOURS_DEFAULT))
    warn_t12 = float(CFG.get("WEATHER_WARN_T12", str(WEATHER_WARN_T12_DEFAULT)) or str(WEATHER_WARN_T12_DEFAULT))
    alert_t12 = float(CFG.get("WEATHER_ALERT_T12", str(WEATHER_ALERT_T12_DEFAULT)) or str(WEATHER_ALERT_T12_DEFAULT))

    w = _load_weather_file()
    state = _classify_weather(w, stale_hours=stale_hours, warn_t12=warn_t12, alert_t12=alert_t12)
    msg = _format_weather_message(state, w, warn_t12, alert_t12)

    await update.message.reply_text(_safe_display(msg), disable_web_page_preview=True)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = _load_weather_subscribers()
    await update.message.reply_text(
        _safe_display(
            "✅ На связи.\n"
            f"Secrets: {CFG.get('SECRETS_PATH')}\n"
            f"Pending TTL: {CFG.get('PENDING_TTL_SECONDS')} sec\n"
            f"Weather subs: {len(subs)}\n"
            f"Weather file: {WEATHER_FILE}\n"
            f"Warn/Alert: {CFG.get('WEATHER_WARN_T12', str(WEATHER_WARN_T12_DEFAULT))} / "
            f"{CFG.get('WEATHER_ALERT_T12', str(WEATHER_ALERT_T12_DEFAULT))}\n"
            f"Last seen weather ts: {WEATHER_LAST_TS_SEEN or '(none)'}\n"
            f"Last weather state: {WEATHER_LAST_STATE}"
        ),
        disable_web_page_preview=True,
    )


async def yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    ttl = int(CFG.get("PENDING_TTL_SECONDS", "900") or "900")

    plan = get_plan(chat_id, ttl_seconds=ttl)
    if not plan:
        await update.message.reply_text(
            "Нет ожидающей записи (или протухла). Сначала /note или /observe.",
            disable_web_page_preview=True,
        )
        return

    try:
        report = execute_action(plan)
        clear_plan(chat_id)
        await update.message.reply_text(_safe_display(report), disable_web_page_preview=True)
    except ControllerError as e:
        clear_plan(chat_id)
        await update.message.reply_text(f"❌ Ошибка выполнения: {e}", disable_web_page_preview=True)


async def no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    clear_plan(chat_id)
    await update.message.reply_text("ОТМЕНЕНО", disable_web_page_preview=True)


async def handle_farm_request(update: Update, prompt: str):
    status_msg = await update.message.reply_text("⏳ Дух вникает...")

    try:
        ttl = int(CFG.get("PENDING_TTL_SECONDS", "900") or "900")
        cleanup(ttl_seconds=ttl)

        data = build_plan_from_text(prompt)

        chat_id = update.effective_chat.id
        set_plan(chat_id, data)

        preview = format_plan_preview(data) + "\n\nПодтвердить: /yes\nОтменить: /no"
        await _edit_status(status_msg, preview)

    except ControllerError as e:
        logger.exception("Handled error")
        await _edit_status(status_msg, f"❌ Ошибка: {e}")
    except Exception as e:
        logger.exception("Unexpected error")
        await _edit_status(status_msg, f"❌ Ошибка: {e}")


async def note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Формат: /note текст", disable_web_page_preview=True)
        return
    await handle_farm_request(update, " ".join(context.args))


async def observe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /observe Имя текст", disable_web_page_preview=True)
        return
    animal = context.args[0]
    text = " ".join(context.args[1:])
    await handle_farm_request(update, f"{animal}: {text}")


# -------------------- MAIN --------------------
def main():
    global CFG
    CFG = load_config()

    app = ApplicationBuilder().token(CFG["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("yes", yes))
    app.add_handler(CommandHandler("no", no))
    app.add_handler(CommandHandler("note", note))
    app.add_handler(CommandHandler("observe", observe))

    # Погода: управление подпиской
    app.add_handler(CommandHandler("weather_on", weather_on))
    app.add_handler(CommandHandler("weather_off", weather_off))
    app.add_handler(CommandHandler("weather_now", weather_now))

    # Монитор погоды (без JobQueue)
    start_weather_monitor(app)

    logger.info("🐂 Бот запущен")
    app.run_polling()


if __name__ == "__main__":
    main()
