import os
import urllib.parse
import datetime
from pathlib import Path
from typing import Tuple, Dict, Any


class FileExecutorError(Exception):
    pass


def _now_stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _normalize_path_for_windows(path_raw: str) -> Tuple[str, str]:
    """Возвращает (decoded_path, clean_path_with_os_sep)."""
    decoded_path = urllib.parse.unquote((path_raw or "").strip())

    clean = decoded_path.replace("farm_memory/", "").replace("farm_memory\\", "")
    clean = clean.replace("/", os.sep).replace("\\", os.sep)

    while clean.startswith(os.sep):
        clean = clean[1:]

    return decoded_path, clean


def _block_heading(block_id: str) -> str:
    b = (block_id or "").strip().lower()
    mapping = {
        "inventory": "## Текущие запасы",
        "log": "## Лог",
        "observations": "## Наблюдения",
        "notes": "## Записи",
        "weight": "## Вес",
    }
    return mapping.get(b, "")


def _ensure_section(lines: list[str], heading: str) -> int:
    for i, line in enumerate(lines):
        if line.strip() == heading:
            return i

    if lines and lines[-1].strip() != "":
        lines.append("\n")
    lines.append(heading + "\n")
    lines.append("\n")
    return len(lines) - 2


def _append_entry_to_section(lines: list[str], heading_index: int, content: str) -> int:
    stamp_line = f"- [{_now_stamp()}] {content}\n"
    insert_at = heading_index + 1
    while insert_at < len(lines) and lines[insert_at].strip() == "":
        insert_at += 1
    lines.insert(insert_at, stamp_line)
    return insert_at


def _default_template_for(path_lower: str, name: str) -> str:
    if "/resources/" in path_lower or "/system/" in path_lower:
        return (
            "# Склад: Учет кормов и добавок\n\n"
            "Здесь хранится информация о запасах, закупках и расходе кормов.\n\n"
            "## Текущие запасы\n\n"
            "- Пока склад пуст.\n\n"
            "## Лог\n\n"
            "- [{date}] Файл учета создан.\n".format(date=datetime.datetime.now().strftime("%Y-%m-%d"))
        )
    if "/animals/" in path_lower:
        return (
            f"# Карточка животного: {name}\n\n"
            "## Наблюдения\n\n"
        )
    return (
        "# Журнал\n\n"
        "## Записи\n\n"
    )


def _ensure_file_exists(full_path: str):
    if os.path.exists(full_path):
        return
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    name = os.path.splitext(os.path.basename(full_path))[0]
    lower = full_path.lower().replace("\\", "/")
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(_default_template_for(lower, name))


def _base_dir() -> str:
    """
    ВАЖНО: больше никаких жёстких путей типа C:\\Users\\...
    Всегда пишем в farm_guardian/farm_memory рядом со скриптами.
    """
    here = Path(__file__).resolve().parent
    mem = here / "farm_memory"
    mem.mkdir(parents=True, exist_ok=True)
    return str(mem)


def execute(data: dict) -> Dict[str, Any]:
    """
    Выполняет действие над файлами и возвращает dict для отчёта:
    {
      status, action, mode, path, file, block_id, block_heading, summary
    }
    """
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

    # ---- write: дописать в конец ----
    if action == "write":
        with open(full_path, "a", encoding="utf-8") as f:
            if content:
                if not content.startswith("\n"):
                    f.write("\n")
                f.write(content)
                f.write("\n")

        return {
            "status": "ok",
            "action": "write",
            "mode": mode or "append",
            "path": rel_path,
            "file": file_name,
            "block_id": None,
            "block_heading": None,
            "summary": f"дописано в {file_name}",
        }

    # ---- modify ----
    if action == "modify":
        _ensure_file_exists(full_path)

        if mode == "replace_block":
            heading = _block_heading(str(block_id or ""))

            if not heading:
                lower = full_path.lower().replace("\\", "/")
                if "/resources/" in lower or "/system/" in lower:
                    heading = "## Текущие запасы"
                    block_id = block_id or "inventory"
                elif "/animals/" in lower:
                    heading = "## Наблюдения"
                    block_id = block_id or "observations"
                else:
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

        # fallback
        with open(full_path, "a", encoding="utf-8") as f:
            f.write(f"\n- [{_now_stamp()}] {content}\n")

        return {
            "status": "ok",
            "action": "modify",
            "mode": mode or "append_fallback",
            "path": rel_path,
            "file": file_name,
            "block_id": block_id,
            "block_heading": None,
            "summary": f"добавлено в конец: {file_name} (fallback)",
        }

    raise FileExecutorError(f"Неизвестное действие: {action}")
