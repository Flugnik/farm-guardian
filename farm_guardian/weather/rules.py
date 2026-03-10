import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


def load_weather_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def hours_since_ts(ts: str) -> float:
    if not ts:
        return 9999.0
    try:
        dt = datetime.fromisoformat(ts)
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        return (now - dt).total_seconds() / 3600.0
    except Exception:
        return 9999.0


# -------------------- НОВОЕ --------------------

def _age_hours_from_dt(dt: datetime) -> float:
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    return (now - dt).total_seconds() / 3600.0


def _age_hours_from_iso(ts: str) -> Optional[float]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return _age_hours_from_dt(dt)
    except Exception:
        return None


def diagnose_weather_file(path: Path, stale_hours: int) -> Dict[str, Any]:
    diag: Dict[str, Any] = {
        "file": str(path),
        "exists": path.exists(),
        "mtime": "",
        "json_ts": "",
        "json_source": "",
        "age_h_by_ts": None,
        "age_h_by_mtime": None,
        "status": "unknown",
        "hint": "",
    }

    if not path.exists():
        diag["status"] = "missing"
        diag["hint"] = (
            "Файл не найден. Проверь запуск weather_collector.py и путь "
            "farm_memory/sensors/weather.json."
        )
        return diag

    try:
        mdt = datetime.fromtimestamp(path.stat().st_mtime)
        diag["mtime"] = mdt.isoformat(sep=" ", timespec="seconds")
        diag["age_h_by_mtime"] = round(_age_hours_from_dt(mdt), 2)
    except Exception:
        pass

    try:
        raw = path.read_text(encoding="utf-8") or "{}"
        w = json.loads(raw)
        if not isinstance(w, dict):
            raise ValueError("not a dict")
    except Exception:
        diag["status"] = "broken"
        diag["hint"] = (
            "Файл есть, но JSON битый или не читается. "
            "Проверь логи weather_collector.py и права записи."
        )
        return diag

    ts = (w.get("ts") or "").strip()
    diag["json_ts"] = ts
    diag["json_source"] = (w.get("source") or "").strip()

    age_ts = _age_hours_from_iso(ts)
    if age_ts is not None:
        diag["age_h_by_ts"] = round(age_ts, 2)

    if "t_min_next_12h" not in w or "t_min_next_24h" not in w:
        diag["status"] = "bad_fields"
        diag["hint"] = (
            "В weather.json нет полей t_min_next_12h / t_min_next_24h. "
            "Проверь формат, который пишет collector."
        )
        return diag

    age_for_stale = diag["age_h_by_ts"]
    if age_for_stale is None:
        age_for_stale = diag["age_h_by_mtime"]

    if age_for_stale is None:
        diag["status"] = "stale"
        diag["hint"] = "Не удалось определить возраст данных (нет ts и mtime)."
        return diag

    if age_for_stale >= float(stale_hours):
        diag["status"] = "stale"
        diag["hint"] = (
            f"Данные старше порога ({stale_hours} ч). "
            "Проверь расписание запуска weather_collector.py."
        )
        return diag

    diag["status"] = "ok"
    return diag


def format_weather_diagnostic_block(diag: Dict[str, Any]) -> str:
    lines = ["Диагностика источника погоды:"]

    lines.append(f"- файл: {diag.get('file')}")
    lines.append(f"- существует: {diag.get('exists')}")

    if diag.get("mtime"):
        lines.append(f"- mtime: {diag.get('mtime')}")

    if diag.get("json_ts"):
        src = diag.get("json_source", "")
        lines.append(f"- ts в JSON: {diag.get('json_ts')} ({src})")

    if diag.get("age_h_by_ts") is not None:
        lines.append(f"- возраст по ts: {diag.get('age_h_by_ts')} ч")

    if diag.get("age_h_by_mtime") is not None:
        lines.append(f"- возраст по mtime: {diag.get('age_h_by_mtime')} ч")

    if diag.get("hint"):
        lines.append(f"- что проверить: {diag.get('hint')}")

    return "\n".join(lines)


# -------------------- ТВОЯ ЛОГИКА --------------------

def classify_weather(w: Dict[str, Any], stale_hours: int, warn_t12: float, alert_t12: float) -> str:
    if not w:
        return "stale"

    ts = (w.get("ts") or "").strip()
    if hours_since_ts(ts) >= stale_hours:
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


def format_weather_message(state: str, w: Dict[str, Any], warn_t12: float, alert_t12: float) -> str:
    if state == "stale":
        return (
            "⚠️ Погода: нет свежих данных.\n"
            "Источник не обновляется."
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
