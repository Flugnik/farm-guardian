import json
import os
from pathlib import Path
from typing import Any, Dict

WEATHER_CHECK_EVERY_SEC_DEFAULT = 300   # 5 минут
WEATHER_STALE_HOURS_DEFAULT = 6         # если старше 6 часов — "погода упала"
WEATHER_WARN_T12_DEFAULT = -12.0        # предупредить: ≤ -12
WEATHER_ALERT_T12_DEFAULT = -18.0       # тревога: ≤ -18


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


def load_config(here: Path) -> Dict[str, str]:
    """
    Приоритет:
    1) config/secrets.json
    2) переменные окружения (перекрывают secrets)
    """
    secrets_path = here / "config" / "secrets.json"
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

        # Weather knobs
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
