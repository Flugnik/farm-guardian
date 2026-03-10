import json
from datetime import datetime
from pathlib import Path
import urllib.request

# Координаты твоего хозяйства (поставь свои!)
LAT = 55.44
LON = 65.34

OUT = Path("farm_memory/sensors/weather.json")
OUT.parent.mkdir(parents=True, exist_ok=True)


def fetch():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&hourly=temperature_2m"
        "&forecast_days=2"
        "&timezone=auto"
    )

    with urllib.request.urlopen(url, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))

    times = data["hourly"]["time"]
    temps = data["hourly"]["temperature_2m"]

    # Для вычислений используем "naive" локальное время,
    # потому что open-meteo (timezone=auto) отдаёт time без offset.
    now = datetime.now()  # naive local time
    now_tz = datetime.now().astimezone()  # для лога с таймзоной

    t12 = []
    t24 = []

    for t, temp in zip(times, temps):
        dt = datetime.fromisoformat(t)  # naive local time
        delta_h = (dt - now).total_seconds() / 3600

        if 0 <= delta_h <= 12:
            t12.append(temp)
        if 0 <= delta_h <= 24:
            t24.append(temp)

    payload = {
        "ts": now_tz.isoformat(timespec="seconds"),
        "t_min_next_12h": min(t12) if t12 else None,
        "t_min_next_24h": min(t24) if t24 else None,
        "source": "open-meteo",
        "lat": LAT,
        "lon": LON,
    }

    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("OK:", payload)


if __name__ == "__main__":
    fetch()
