import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from file_executor import execute, FileExecutorError

logger = logging.getLogger("Controller")

# Разрешённые корни (относительно farm_memory/)
ALLOWED_ROOTS = ("journal/", "animals/", "resources/", "system/")


class ControllerError(Exception):
    pass


# -------------------- PATH NORMALIZATION --------------------

def _normalize_rel_path(path: str) -> str:
    """Нормализует относительный путь от модели к виду folder/file.md (слеши вперёд)."""
    p = (path or "").strip()
    p = p.replace("\\", "/")

    while p.startswith("./"):
        p = p[2:]
    while p.startswith("/"):
        p = p[1:]

    if p.lower().startswith("farm_memory/"):
        p = p[len("farm_memory/"):]

    parts = [seg for seg in p.split("/") if seg]
    if not parts:
        return ""

    first = parts[0].lower()
    aliases = {
        "resource": "resources",
        "resourse": "resources",
        "resourses": "resources",
        "resouces": "resources",
        "journel": "journal",
        "journals": "journal",
        "animal": "animals",
    }
    parts[0] = aliases.get(first, parts[0])
    return "/".join(parts)


def _is_allowed_root(path: str) -> bool:
    return any(path.startswith(root) for root in ALLOWED_ROOTS)


def _try_remap_root(path: str) -> Optional[str]:
    """
    Если корень не разрешён — пробуем безопасный ремап (resources <-> system).
    """
    if _is_allowed_root(path):
        return path

    parts = path.split("/", 1)
    first = parts[0]
    tail = parts[1] if len(parts) > 1 else ""

    remap = {
        "resources": "system",
        "system": "resources",
    }
    cand_first = remap.get(first)
    if not cand_first:
        return None

    candidate = f"{cand_first}/{tail}" if tail else f"{cand_first}/"
    return candidate if _is_allowed_root(candidate) else None


def _validate_path(path: str):
    if not _is_allowed_root(path):
        raise ControllerError(f"Недопустимый путь: {path}")


# -------------------- ROUTING (HARD RULES) --------------------

_FEED_KEYWORDS = (
    "сено", "рулон", "тюк",
    "зерно", "ячмень", "овёс", "овес", "пшениц", "кукуруз",
    "комбикорм", "корм",
    "мешок", "мешка", "мешков",
    "кг", "килограмм", "тонн", "литр"
)

_PLAN_KEYWORDS = (
    "завтра", "послезавтра", "сегодня",
    "торгов", "рынок", "ярмарк",
    "развоз", "доставка", "выдача",
    "заказ", "заказы", "клиент",
    "упаков", "вакуум", "заваккум", "завакуум",
    "маршрут", "поедем", "выезжаем"
)


def _today_journal_relpath() -> str:
    return f"journal/{datetime.now():%Y-%m-%d}.md"


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    t = (text or "").lower()
    return any(k in t for k in keywords)


def _route_by_content_rules(data: Dict[str, Any]) -> None:
    """
    Детерминированно исправляем маршрут, если модель ошиблась.
    Основание: content и path из JSON модели.
    """
    content = str(data.get("content", "") or "")
    path = str(data.get("path", "") or "")
    mode = str(data.get("mode", "") or "")
    block_id = str(data.get("block_id", "") or "")

    # планы/торговля в resources -> journal
    if path.startswith("resources/") and _contains_any(content, _PLAN_KEYWORDS):
        old = path
        data["path"] = _today_journal_relpath()
        data["action"] = "write"
        data["mode"] = "append"
        data.pop("block_id", None)
        data["_path_routed_from"] = old
        logger.warning("Route fix (plans->journal): %s -> %s", old, data["path"])
        return

    # корм/запасы не туда -> resources/feed.md
    if (path.startswith("journal/") or path.startswith("system/")) and _contains_any(content, _FEED_KEYWORDS):
        old = path
        data["path"] = "resources/feed.md"
        data["action"] = "modify"
        data["mode"] = "replace_block" if mode != "append" else "replace_block"
        if not block_id:
            data["block_id"] = "log"
        data["_path_routed_from"] = old
        logger.warning("Route fix (feed->resources): %s -> %s", old, data["path"])
        return


# -------------------- CONTENT SAFETY (meaning/time) --------------------

def _normalize_content_keep_time(data: Dict[str, Any]) -> None:
    """Лёгкая нормализация пробелов без переписывания смысла."""
    content = str(data.get("content", "") or "")
    content = re.sub(r"[ \t]+", " ", content).strip()
    data["content"] = content


# -------------------- VALIDATION --------------------

def _validate_action(data: Dict[str, Any]):
    required = {"action", "path", "mode", "content"}
    if not required.issubset(data.keys()):
        raise ControllerError("Неполный JSON от модели")

    original = data.get("path", "")
    normalized = _normalize_rel_path(original)

    remapped = _try_remap_root(normalized)
    if remapped and remapped != normalized:
        logger.warning("Path remap: %s -> %s", normalized, remapped)
        data["path"] = remapped
        data["_path_remapped_from"] = original
    else:
        data["path"] = normalized

    _normalize_content_keep_time(data)
    _route_by_content_rules(data)

    _validate_path(str(data["path"]))


# -------------------- REPORT / PREVIEW --------------------

def _format_report(exec_result: Dict[str, Any], data: Dict[str, Any]) -> str:
    status = exec_result.get("status", "ok")
    if status != "ok":
        return f"❌ Ошибка: {exec_result.get('error', 'Unknown error')}"

    action = exec_result.get("action", "")
    mode = exec_result.get("mode", "")
    rel_path = exec_result.get("path", "")
    file_name = exec_result.get("file", "")

    block_id = exec_result.get("block_id")
    block_heading = exec_result.get("block_heading")
    summary = exec_result.get("summary", "")

    pieces = ["✅ Выполнено"]

    op = f"{action}"
    if mode:
        op += f" / {mode}"
    pieces.append(op)

    if rel_path:
        pieces.append(f"→ {rel_path}")

    if block_id or block_heading:
        b = block_id if block_id else ""
        h = block_heading if block_heading else ""
        if b and h:
            pieces.append(f"(блок: {b} / {h})")
        elif b:
            pieces.append(f"(блок: {b})")
        elif h:
            pieces.append(f"(секция: {h})")

    if summary:
        pieces.append(f"| {summary}")

    remapped_from = data.get("_path_remapped_from")
    if remapped_from and remapped_from != rel_path:
        pieces.append(f"(исправил путь: {remapped_from} → {rel_path})")

    routed_from = data.get("_path_routed_from")
    if routed_from and routed_from != rel_path:
        pieces.append(f"(перенаправил: {routed_from} → {rel_path})")

    if file_name and (not rel_path or not rel_path.endswith(file_name)):
        pieces.append(f"(файл: {file_name})")

    return " ".join(pieces).strip()


def format_plan_preview(data: Dict[str, Any]) -> str:
    """
    Короткое понятное описание того, ЧТО будет сделано (до выполнения).
    """
    action = str(data.get("action", ""))
    mode = str(data.get("mode", ""))
    path = str(data.get("path", ""))
    block_id = str(data.get("block_id", "") or "")
    content = str(data.get("content", "") or "")

    lines = []
    lines.append("🧾 План записи (нужен /yes или /no):")
    lines.append(f"• action: {action}")
    if mode:
        lines.append(f"• mode: {mode}")
    lines.append(f"• path: {path}")
    if block_id:
        lines.append(f"• block_id: {block_id}")
    if content:
        short = content if len(content) <= 220 else content[:220] + "…"
        lines.append(f"• content: {short}")
    return "\n".join(lines)


# -------------------- PUBLIC API --------------------

def parse_llm_json(raw_text: str) -> Dict[str, Any]:
    """
    Достаём JSON из ответа модели, нормализуем/маршрутизируем/валидируем.
    НИЧЕГО НЕ ПИШЕМ в файлы.
    """
    try:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start == -1 or end <= 0:
            raise ControllerError("В ответе модели не найден JSON")
        data = json.loads(raw_text[start:end])
    except json.JSONDecodeError:
        raise ControllerError("Ответ модели не является валидным JSON")

    if not isinstance(data, dict):
        raise ControllerError("JSON должен быть объектом (dict)")

    _validate_action(data)
    return data


def execute_action(data: Dict[str, Any]) -> str:
    """
    Выполняем запись (в файлы) и возвращаем человеко-читаемый отчёт.
    """
    try:
        exec_result = execute(data)
    except FileExecutorError as e:
        raise ControllerError(str(e))

    return _format_report(exec_result, data)


def process_llm_response(raw_text: str) -> str:
    """
    Старый интерфейс: сразу парсим и выполняем.
    """
    data = parse_llm_json(raw_text)
    return execute_action(data)


def build_today_journal_path() -> str:
    journal_dir = Path("farm_memory/journal")
    journal_dir.mkdir(parents=True, exist_ok=True)
    today_file = journal_dir / f"{datetime.now():%Y-%m-%d}.md"
    return str(today_file)
