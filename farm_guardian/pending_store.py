import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_TTL_SECONDS = 15 * 60  # 15 минут


def _store_path() -> Path:
    # farm_guardian/storage/pending.json
    here = Path(__file__).resolve().parent
    p = here / "storage" / "pending.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_all() -> Dict[str, Any]:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        # если файл битый — не падаем, начинаем заново
        return {}


def _save_all(data: Dict[str, Any]) -> None:
    p = _store_path()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup(ttl_seconds: int = DEFAULT_TTL_SECONDS) -> int:
    """
    Удаляет протухшие планы. Возвращает количество удалённых.
    """
    all_data = _load_all()
    now = datetime.now()
    removed = 0

    for chat_id in list(all_data.keys()):
        item = all_data.get(chat_id) or {}
        ts = item.get("ts")
        try:
            created = datetime.fromisoformat(ts) if ts else None
        except Exception:
            created = None

        if not created or (now - created) > timedelta(seconds=ttl_seconds):
            all_data.pop(chat_id, None)
            removed += 1

    if removed:
        _save_all(all_data)
    return removed


def set_plan(chat_id: int, plan: Dict[str, Any]) -> None:
    all_data = _load_all()
    all_data[str(chat_id)] = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "plan": plan,
    }
    _save_all(all_data)


def get_plan(chat_id: int, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Optional[Dict[str, Any]]:
    cleanup(ttl_seconds=ttl_seconds)
    all_data = _load_all()
    item = all_data.get(str(chat_id))
    if not item:
        return None
    return item.get("plan")


def clear_plan(chat_id: int) -> None:
    all_data = _load_all()
    if str(chat_id) in all_data:
        all_data.pop(str(chat_id), None)
        _save_all(all_data)
