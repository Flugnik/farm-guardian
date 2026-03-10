from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ALERT_REPEAT_TZ = timezone(timedelta(hours=5))
ALERT_REPEAT_MORNING_HOUR = 9
ALERT_REPEAT_EVENING_HOUR = 19


def safe_display(text: str) -> str:
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


@dataclass
class Paths:
    here: Path
    weather_file: Path
    weather_subs_file: Path


@dataclass
class WeatherState:
    monitor_started: bool = False
    last_ts_seen: str = ""
    last_state: str = "unknown"  # ok | warn | alert | stale | unknown
    last_repeat: Dict[str, Any] = field(
        default_factory=lambda: {"date": "", "morning_sent": False, "evening_sent": False}
    )


@dataclass
class AppContext:
    cfg: Dict[str, str]
    paths: Paths
    logger: logging.Logger
    weather: WeatherState = field(default_factory=WeatherState)

    # event loop приложения (чтобы из thread безопасно планироват
