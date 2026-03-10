import json
from pathlib import Path
from typing import List
import logging


def load_weather_subscribers(path: Path, logger: logging.Logger) -> List[int]:
    try:
        raw = path.read_text(encoding="utf-8")
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


def save_weather_subscribers(path: Path, subs: List[int]) -> None:
    payload = {"subscribers": subs}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def subscribe_chat(path: Path, chat_id: int, logger: logging.Logger) -> bool:
    subs = load_weather_subscribers(path, logger)
    if chat_id in subs:
        return False
    subs.append(chat_id)
    save_weather_subscribers(path, subs)
    return True


def unsubscribe_chat(path: Path, chat_id: int, logger: logging.Logger) -> bool:
    subs = load_weather_subscribers(path, logger)
    if chat_id not in subs:
        return False
    subs = [x for x in subs if x != chat_id]
    save_weather_subscribers(path, subs)
    return True
