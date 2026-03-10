from pathlib import Path

from protocols import load_protocols_index, load_protocol, build_steps_preview

HERE = Path(__file__).resolve().parent
PROTOCOLS_ROOT = HERE / "farm_memory" / "protocols"

index = load_protocols_index(PROTOCOLS_ROOT)

print("Найдено протоколов:", len(index))

for name, path in index.items():
    print("-", name, "->", path)

print()

first = next(iter(index.values()))
protocol = load_protocol(first)

print(build_steps_preview(protocol, start_date="2026-02-10"))
