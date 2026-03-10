from __future__ import annotations

from pathlib import Path
from typing import Dict, Any
import re

import yaml


class ProtocolError(Exception):
    pass


def _norm(s: str) -> str:
    s = (s or "").lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def load_protocols_index(protocols_root: Path) -> Dict[str, Path]:
    index: Dict[str, Path] = {}

    if not protocols_root.exists():
        return index

    for p in protocols_root.rglob("*.yaml"):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception as e:
            raise ProtocolError(f"Ошибка чтения {p}: {e}")

        name = data.get("name") or p.stem
        index[_norm(str(name))] = p

    return index


def load_protocol(path: Path) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise ProtocolError(f"Ошибка чтения {path}: {e}")

    if not isinstance(data, dict) or "steps" not in data:
        raise ProtocolError(f"Битый протокол: {path}")

    return data


def build_steps_preview(protocol: Dict[str, Any], start_date: str) -> str:
    name = protocol.get("name", "")
    steps = protocol.get("steps") or []

    lines = [
        f"ПРОТОКОЛ: {name}",
        f"Старт: {start_date}",
        "",
        "Шаги:"
    ]

    for s in steps:
        day = s.get("day", 0)
        title = s.get("title", "")
        crit = "‼️ " if s.get("critical") else ""
        note = s.get("note")

        line = f"- День {day}: {crit}{title}"
        if note:
            line += f" — {note}"

        lines.append(line)

    return "\n".join(lines)
