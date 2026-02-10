import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from file_executor import execute, FileExecutorError


class ControllerError(Exception):
    pass


# Путь стабилен независимо от того, откуда запущен бот
HERE = Path(__file__).resolve().parent
ALIASES_FILE = HERE / "farm_memory" / "resources" / "animals.json"


def _normalize_text(text: str) -> str:
    text = (text or "").lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


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

    lines.append("")
    lines.append("Текст записи:")
    lines.append(plan.get("entry", ""))
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
