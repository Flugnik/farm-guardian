import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from file_executor import execute, FileExecutorError
from protocols import load_protocols_index, load_protocol, build_steps_preview, ProtocolError


class ControllerError(Exception):
    pass


# Путь стабилен независимо от того, откуда запущен бот
HERE = Path(__file__).resolve().parent
ALIASES_FILE = HERE / "farm_memory" / "resources" / "animals.json"
PROTOCOLS_ROOT = HERE / "farm_memory" / "protocols"
WEATHER_FILE = HERE / "farm_memory" / "sensors" / "weather.json"

# Пороговая логика под твою задачу (можно позже вынести в settings.json)
WEATHER_STALE_HOURS = 6     # если данные старше N часов — считаем "погода упала"
WEATHER_WARN_T12 = -12.0    # предупреждение, если t_min_next_12h <= -12
WEATHER_ALERT_T12 = -18.0   # тревога, если t_min_next_12h <= -18

COLD_CHECKLIST_ALERT = [
    "АКБ/пуск (если утром нужен запуск техники/машины)",
    "Телята: проверить/включить подогрев, убрать сквозняки",
    "Вода/скважина: второй контур/обогрев узла",
    "Коровник: проверить режим тепла по ситуации",
]

COLD_CHECKLIST_WARN = [
    "Телята: подогрев/сквозняки по ситуации",
    "Вода/скважина: убедиться, что не прихватит",
]


def _normalize_text(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def extract_protocol_name(text: str) -> str:
    """
    Ищет строку вида:
      Протокол: Беременность свиноматки
    (регистр и пробелы не важны)
    """
    m = re.search(r"(?im)^\s*протокол\s*:\s*(.+?)\s*$", text or "")
    return (m.group(1).strip() if m else "")


def wants_weather(text: str) -> bool:
    """
    Явный триггер, чтобы не срабатывало случайно:
      - отдельной строкой: "Погода"
      - или командой: "/weather"
    """
    return bool(re.search(r"(?im)^\s*(/weather|погода)\s*$", text or ""))


def load_weather() -> Dict[str, Any]:
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


def format_weather_brief(w: Dict[str, Any]) -> str:
    if not w:
        return "ПОГОДА: данных нет (farm_memory/sensors/weather.json не найден или битый)"

    t12 = w.get("t_min_next_12h")
    t24 = w.get("t_min_next_24h")
    ts = w.get("ts", "")
    src = w.get("source", "")

    return (
        "ПОГОДА (минимум):\n"
        f"- ближайшие 12ч: {t12}°C\n"
        f"- ближайшие 24ч: {t24}°C\n"
        f"- обновлено: {ts} ({src})"
    )


def format_weather_alert(w: Dict[str, Any]) -> str:
    """
    Алерт-блок под пороги:
      - stale: если данных нет или они устарели
      - warn: t12 <= -12
      - alert: t12 <= -18
      - ok: иначе
    """
    if not w:
        return "⚠️ АЛЕРТ ПО ПОГОДЕ: данных нет (weather.json не найден/битый)"

    ts = (w.get("ts") or "").strip()
    age_h = _hours_since_ts(ts)
    if age_h >= WEATHER_STALE_HOURS:
        return (
            f"⚠️ АЛЕРТ ПО ПОГОДЕ: нет свежих данных ({age_h:.1f} ч назад).\n"
            "Проверь, что weather_collector.py запускается по расписанию."
        )

    t12 = w.get("t_min_next_12h")
    t24 = w.get("t_min_next_24h")

    try:
        t12f = float(t12)
    except Exception:
        return "⚠️ АЛЕРТ ПО ПОГОДЕ: поле t_min_next_12h отсутствует/некорректно"

    if t12f <= WEATHER_ALERT_T12:
        checklist = "\n".join([f"- [ ] {x}" for x in COLD_CHECKLIST_ALERT])
        return (
            f"🟥 МОРОЗ: минимум ближайшие 12ч = {t12}°C (24ч = {t24}°C)\n"
            f"Порог тревоги: {WEATHER_ALERT_T12}°C\n"
            "Чек-лист:\n"
            f"{checklist}"
        )

    if t12f <= WEATHER_WARN_T12:
        checklist = "\n".join([f"- [ ] {x}" for x in COLD_CHECKLIST_WARN])
        return (
            f"🟧 РИСК МОРОЗА: минимум ближайшие 12ч = {t12}°C (24ч = {t24}°C)\n"
            f"Порог предупреждения: {WEATHER_WARN_T12}°C\n"
            "Чек-лист:\n"
            f"{checklist}"
        )

    return f"🟩 Погода ок: минимум ближайшие 12ч = {t12}°C (24ч = {t24}°C)."


def _today_journal_relpath() -> str:
    return f"resources/journal/{datetime.now():%Y-%m}/{datetime.now():%Y-%m-%d}.md"


def _load_aliases() -> Dict[str, List[str]]:
    if not ALIASES_FILE.exists():
        return {}
    try:
        data = json.loads(ALIASES_FILE.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as e:
        raise ControllerError(f"Битый animals.json: {e}")

    aliases: Dict[str, List[str]] = {}
    for slug, words in data.items():
        if isinstance(words, list):
            aliases[str(slug)] = [_normalize_text(str(w)) for w in words if str(w).strip()]
    return aliases


def extract_animal_slugs(text: str) -> List[str]:
    normalized = f" {_normalize_text(text)} "
    if not normalized.strip():
        return []

    aliases = _load_aliases()
    found: List[str] = []

    for slug, words in aliases.items():
        for alias in words:
            if not alias:
                continue
            pattern = rf"(?<!\w){re.escape(alias)}(?!\w)"
            if re.search(pattern, normalized):
                found.append(slug)
                break

    # дедуп с сохранением порядка
    uniq: List[str] = []
    seen = set()
    for s in found:
        if s not in seen:
            uniq.append(s)
            seen.add(s)

    return uniq


def _build_write(path: str, block_id: str, content: str) -> Dict[str, Any]:
    return {
        "action": "modify",
        "path": path,
        "mode": "replace_block",
        "block_id": block_id,
        "content": content,
    }


def build_plan_from_text(text: str) -> Dict[str, Any]:
    content = (text or "").strip()
    if not content:
        raise ControllerError("Пустой текст записи")

    journal_path = _today_journal_relpath()
    slugs = extract_animal_slugs(content)

    # --- протоколы (опционально) ---
    protocol_name = extract_protocol_name(content)
    protocol_preview = ""
    protocol_file = ""

    if protocol_name:
        try:
            index = load_protocols_index(PROTOCOLS_ROOT)
            key = _normalize_text(protocol_name)
            path = index.get(key)

            if path:
                protocol = load_protocol(path)
                protocol_preview = build_steps_preview(
                    protocol,
                    start_date=f"{datetime.now():%Y-%m-%d}",
                )
                protocol_file = str(path.relative_to(HERE))
            else:
                protocol_preview = f"Протокол не найден: {protocol_name}"
        except ProtocolError as e:
            protocol_preview = f"Ошибка протоколов: {e}"

    # --- погода (опционально) ---
    weather_requested = wants_weather(content)
    weather_data = load_weather() if weather_requested else {}
    weather_brief = format_weather_brief(weather_data) if weather_requested else ""
    weather_alert = format_weather_alert(weather_data) if weather_requested else ""

    writes = [_build_write(journal_path, "notes", content)]
    animal_paths: List[str] = []

    for slug in slugs:
        card_path = f"resources/animals/{slug}.md"
        animal_paths.append(card_path)
        writes.append(_build_write(card_path, "chronicle", content))

    return {
        "kind": "multi_write",
        "entry": content,
        "journal_path": journal_path,
        "animal_paths": animal_paths,
        "animal_slugs": slugs,
        "writes": writes,
        "protocol_name": protocol_name,
        "protocol_file": protocol_file,
        "protocol_preview": protocol_preview,
        "weather_requested": weather_requested,
        "weather_brief": weather_brief,
        "weather_alert": weather_alert,
    }


def format_plan_preview(plan: Dict[str, Any]) -> str:
    lines = ["ПЛАН ЗАПИСИ", f"- Journal: {plan.get('journal_path', '')}"]

    animal_paths = plan.get("animal_paths") or []
    if animal_paths:
        lines.append("- Animal card(s):")
        for path in animal_paths:
            lines.append(f"  - {path}")
    else:
        lines.append("- Животное не распознано — только журнал")

    if plan.get("protocol_name"):
        lines.append(f"- Протокол: {plan.get('protocol_name', '')}")
        if plan.get("protocol_file"):
            lines.append(f"  (file: {plan.get('protocol_file', '')})")

    if plan.get("weather_requested"):
        lines.append("- Погода: включена в предпросмотр")

    lines.append("")
    lines.append("Текст записи:")
    lines.append(plan.get("entry", ""))

    if plan.get("protocol_preview"):
        lines.append("")
        lines.append(plan["protocol_preview"])

    if plan.get("weather_brief"):
        lines.append("")
        lines.append(plan["weather_brief"])

    if plan.get("weather_alert"):
        lines.append("")
        lines.append(plan["weather_alert"])

    return "\n".join(lines)


def execute_action(plan: Dict[str, Any]) -> str:
    writes = plan.get("writes")
    if not isinstance(writes, list) or not writes:
        raise ControllerError("План пустой или некорректный")

    report_lines = ["ВЫПОЛНЕНО"]
    for item in writes:
        try:
            result = execute(item)
        except FileExecutorError as e:
            raise ControllerError(str(e))

        op = f"{result.get('action', '')}/{result.get('mode', '')}".strip("/")
        report_lines.append(f"- wrote: {result.get('path', '')} ({op})")

    return "\n".join(report_lines)
