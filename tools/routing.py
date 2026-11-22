"""Map decoded resistance commands to configured Arduino sorting destinations."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "src" / "firmware" / "resistor_sorter" / "stepper_control.h"


def load_routes(path: Path = HEADER) -> dict[str, dict[str, int]]:
    text = path.read_text(encoding="utf-8")
    block = text.split("const SortEntry SORT_TABLE[] = {", 1)[1].split("};", 1)[0]
    rows = re.findall(r'\{"(\d+)",\s*(\d+),\s*(\d+)\}', block)
    routes = {value: {"layer": int(layer), "angle_deg": int(angle)}
              for value, layer, angle in rows}
    if len(rows) != len(routes) or len(routes) != 26:
        raise ValueError("Expected 26 unique firmware routing entries")
    return routes


def classify_command(command: str, routes: dict | None = None) -> dict:
    routes = load_routes() if routes is None else routes
    if command in routes:
        return {"routing_eligible": True, "category": "configured", **routes[command]}
    return {
        "routing_eligible": False,
        "category": "recognition_failed" if command == "NONE" else "outside_table",
        "layer": 1,
        "angle_deg": 324,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Report decoded commands separately from firmware routing.")
    parser.add_argument("summary", type=Path, help="Existing offline summary.csv; read only")
    args = parser.parse_args()
    routes = load_routes()
    print("image,command_sent,routing_eligible,category,layer,angle_deg")
    with args.summary.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            route = classify_command(row["command_sent"], routes)
            print(f'{row["image"]},{row["command_sent"]},{route["routing_eligible"]},'
                  f'{route["category"]},{route["layer"]},{route["angle_deg"]}')


if __name__ == "__main__":
    main()
