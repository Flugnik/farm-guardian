import datetime
import os
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Tuple


class FileExecutorError(Exception):
    pass


def _now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _normalize_path_for_windows(path_raw: str) -> Tuple[str, str]:
    decoded_path = urllib.parse.unquote((path_raw or "").strip())
    clean = decoded_path.replace("farm_memory/", "").replace("farm_memory\\", "")
    clean = clean.replace("/", os.sep).replace("\\", os.sep)
    while clean.startswith(os.sep):
        clean = clean[1:]
    return decoded_path, clean


def _block_heading(block_id: str) -> str:
    mapping = {
        "inventory": "## Текущие запасы",
        "log": "## Лог",
        "observations": "## Наблюдения",
        "notes": "## Записи",
        "weight": "## Вес",
        "chronicle": "## Хроника",
    }
    return mapping.get((block_id or "").strip().lower(), "")


def _ensure_section(lines: list[str], heading: str) -> int:
    for i, line in enumerate(lines):
        if line.strip() == heading:
            return i
    if lines and lines[-1].strip() != "":
        lines.append("\n")
    lines.append(heading + "\n")
    lines.append("\n")
    return len(lines) - 2


def _append_entry_to_section(lines: list[str], heading_index: int, content: str) -> None:
    stamp_line = f"- [{_now_stamp()}] {content}\n"
    insert_at = heading_index + 1
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    lines.insert(insert_at, stamp_line)


def _default_template_for(path: str, name: str) -> str:
    p = path.replace("\\", "/").lower()
    if p.startswith("resources/journal/"):
        return "# Дневной журнал\n\n## Записи\n\n"
    if p.startswith("resources/animals/"):
        return f"# Карточка животного: {name}\n\n## Хроника\n\n"
    if "/resources/" in p or "/system/" in p:
        return (
            "# Склад: Учет кормов и добавок\n\n"
            "## Текущие запасы\n\n"
            "- Пока склад пуст.\n\n"
            "## Лог\n\n"
        )
    if "/animals/" in p:
        return f"# Карточка животного: {name}\n\n## Наблюдения\n\n"
    return "# Журнал\n\n## Записи\n\n"


def _ensure_file_exists(full_path: str, rel_path: str) -> None:
    if os.path.exists(full_path):
        return
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    name = os.path.splitext(os.path.basename(full_path))[0]
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(_default_template_for(rel_path, name))


def _base_dir() -> str:
    here = Path(__file__).resolve().parent
    mem = here / "farm_memory"
    mem.mkdir(parents=True, exist_ok=True)
    return str(mem)


def execute(data: dict) -> Dict[str, Any]:
    base_dir = _base_dir()

    action = str(data.get("action", "")).strip().lower()
    mode = str(data.get("mode", "")).strip().lower()
    content = str(data.get("content", "")).strip()
    block_id = data.get("block_id")

    path_raw = str(data.get("path", "")).strip()
    decoded_path, clean_path = _normalize_path_for_windows(path_raw)

    allowed_dirs = ["journal", "animals", "resources", "system"]
    path_parts = [p for p in clean_path.split(os.sep) if p]
    first_dir = path_parts[0] if path_parts else ""

    if first_dir not in allowed_dirs:
        raise FileExecutorError(f"Недопустимый путь: {decoded_path}. Разрешены: {allowed_dirs}")

    full_path = os.path.join(base_dir, clean_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    rel_path = decoded_path.replace("\\", "/")
    file_name = os.path.basename(full_path)

    if action == "modify":
        _ensure_file_exists(full_path, rel_path)

        if mode == "replace_block":
            heading = _block_heading(str(block_id or ""))
            if not heading:
                heading = "## Записи"
                block_id = block_id or "notes"

            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            h_idx = _ensure_section(lines, heading)
            _append_entry_to_section(lines, h_idx, content)

            with open(full_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

            return {
                "status": "ok",
                "action": "modify",
                "mode": "replace_block",
                "path": rel_path,
                "file": file_name,
                "block_id": block_id,
                "block_heading": heading,
                "summary": f"обновлено: {file_name}",
            }

    raise FileExecutorError(f"Неизвестное действие: {action}/{mode}")
