import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class WeatherMonitorConfig:
    weather_file: Path
    check_every_sec: int = 300          # каждые 5 минут
    stale_hours: int = 6                # если старше — считаем, что сборщик упал
    warn_t12_c: float = -5.0
    alert_t12_c: float = -10.0


class WeatherMonitor:
    """
    Вызывает callback(message) только когда:
    - пришли новые данные и есть превышение порога (или снятие тревоги)
    - данные перестали обновляться (stale)
    """

    def __init__(self, cfg: WeatherMonitorConfig):
        self.cfg = cfg
        self._last_ts_seen: str = ""
        self._last_state: str = "unknown"  # ok | warn | alert | stale | unknown

    def _load_weather(self) -> Dict[str, Any]:
        p = self.cfg.weather_file
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def _hours_since(self, ts: str) -> float:
        if not ts:
            return 9999.0
        try:
            dt = datetime.fromisoformat(ts)
            now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
            return (now - dt).total_seconds() / 3600.0
        except Exception:
            return 9999.0

    def _classify(self, w: Dict[str, Any]) -> str:
        if not w:
            return "stale"
        ts = w.get("ts", "")
        if self._hours_since(ts) >= self.cfg.stale_hours:
            return "stale"
        t12 = w.get("t_min_next_12h")
        if t12 is None:
            return "stale"
        if t12 <= self.cfg.alert_t12_c:
            return "alert"
        if t12 <= self.cfg.warn_t12_c:
            return "warn"
        return "ok"

    def _format_message(self, state: str, w: Dict[str, Any]) -> str:
        if state == "stale":
            return "⚠️ Погода: нет свежих данных. Проверь, что weather_collector запускается по расписанию."
        t12 = w.get("t_min_next_12h")
        t24 = w.get("t_min_next_24h")
        ts = w.get("ts", "")
        if state == "alert":
            return (
                f"🟥 ХОЛОДНО: минимум ближайшие 12ч = {t12}°C (24ч = {t24}°C)\n"
                f"Обновлено: {ts}\n"
                "Чек-лист:\n"
                "- АКБ/пуск\n"
                "- телята: подогрев\n"
                "- вода/скважина: контур\n"
                "- коровник: сквозняки/тепло"
            )
        if state == "warn":
            return (
                f"🟧 РИСК ХОЛОДА: минимум ближайшие 12ч = {t12}°C (24ч = {t24}°C)\n"
                f"Обновлено: {ts}\n"
                "Проверь подогрев телят/воду по ситуации."
            )
        # ok
        return f"🟩 Погода ок: минимум ближайшие 12ч = {t12}°C (24ч = {t24}°C). Обновлено: {ts}"

    def run_forever(self, notify_callback):
        while True:
            w = self._load_weather()
            ts = (w.get("ts") or "").strip()
            state = self._classify(w)

            # 1) Если данные стали stale — шлём только при смене состояния на stale
            if state == "stale":
                if self._last_state != "stale":
                    notify_callback(self._format_message("stale", w))
                self._last_state = "stale"
                time.sleep(self.cfg.check_every_sec)
                continue

            # 2) Данные свежие: если ts новый — анализируем и шлём при смене уровня (ok/warn/alert)
            if ts and ts != self._last_ts_seen:
                if state != self._last_state:
                    notify_callback(self._format_message(state, w))
                self._last_ts_seen = ts
                self._last_state = state

            time.sleep(self.cfg.check_every_sec)
