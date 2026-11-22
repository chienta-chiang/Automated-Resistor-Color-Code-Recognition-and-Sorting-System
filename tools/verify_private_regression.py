"""Compare current detector outputs against an external historical capture archive.

Extracts the legacy recognition function via AST so module-level serial and
file-watching code is not executed during comparison.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "src/vision"))

import cv2
import numpy as np
import yaml

from detector import DetectorParams, HsvRange, HsvThresholds, ResistorDetector
from routing import classify_command, load_routes


def contained(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValueError("Fixture path must stay inside the supplied private source root")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--report", type=Path, help="Optional path for the JSON comparison report (outside the repository and source root)")
    args = parser.parse_args()
    source = args.source_root.resolve()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    if args.report:
        report_path = args.report.resolve()
        if ROOT == report_path or ROOT in report_path.parents or source == report_path or source in report_path.parents:
            parser.error("Report path must be outside the repository and source root")
    settings = yaml.safe_load((ROOT / "config/settings.example.yaml").read_text())
    thresholds = HsvThresholds.from_json(ROOT / "config/hsv_thresholds.json")
    params = DetectorParams.from_settings(settings["vision"])
    detector = ResistorDetector(thresholds, params)
    old_bands = dict(thresholds.bands)
    # Construct legacy inverted gray/white bounds for historical comparison only.
    def historical_range(lower, upper):
        result = object.__new__(HsvRange)
        object.__setattr__(result, "lower", lower)
        object.__setattr__(result, "upper", upper)
        return result
    old_bands["gray"] = historical_range((32, 71, 94), (4, 9, 1))
    old_bands["white"] = historical_range((34, 60, 168), (4, 9, 2))
    legacy_bounds = ResistorDetector(HsvThresholds(thresholds.body, old_bands), params)
    tree = ast.parse(contained(source, baseline["legacy_python"]).read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "read_resistance_value")
    namespace = {"cv2": cv2, "np": np}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<private-legacy-function>", "exec"), namespace)
    routes = load_routes()
    failures = []
    observations = []
    original_imread = cv2.imread
    try:
        for fixture in baseline["images"]:
            path = contained(source, fixture["source_relative_path"])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != fixture["sha256"]:
                failures.append({"fixture": fixture["source_relative_path"], "failure": "image_hash_changed"})
                continue
            result = detector.detect_file(path)
            expected = fixture["current"]
            actual = {
                "command": result.command, "colors": result.colors,
                "bands_found": result.bands_found, "reversed_direction": result.reversed_direction,
                "routing_eligible": classify_command(result.command, routes)["routing_eligible"],
            }
            if any(actual[key] != expected[key] for key in actual):
                failures.append({"fixture": fixture["source_relative_path"], "failure": "current_changed", "actual": actual})
            frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
            cv2.imread = lambda *a, _frame=frame, **kw: _frame.copy()
            try:
                legacy = {"command": str(namespace["read_resistance_value"]())}
            except Exception as exc:
                legacy = {"error": type(exc).__name__}
            old_bounds_command = legacy_bounds.detect_file(path).command
            if legacy != fixture["legacy"]:
                failures.append({"fixture": fixture["source_relative_path"], "failure": "legacy_changed"})
            if old_bounds_command != fixture["current_with_legacy_gray_white"]:
                failures.append({"fixture": fixture["source_relative_path"], "failure": "legacy_bounds_changed"})
            observations.append({"fixture_sha256": digest, **actual, "legacy": legacy,
                                 "legacy_bounds_command": old_bounds_command})
    finally:
        cv2.imread = original_imread
    text = re.sub(r"//[^\n]*", "", contained(source, baseline["legacy_firmware"]).read_text(encoding="utf-8"))
    archived = {value: (int(a), int(b), int(c)) for value, a, b, c in re.findall(
        r'(?:if|else if) \(command == "(\d+)"\)\s*\{\s*angle1 = (\d+);\s*angle2 = (\d+);\s*angle3 = (\d+);', text)}
    current = {value: tuple(route["angle_deg"] if i == route["layer"] else 0 for i in (1, 2, 3))
               for value, route in routes.items()}
    table_matches = len(archived) == len(current) == 26 and archived == current
    if not table_matches:
        failures.append({"failure": "archived_routing_table_differs"})
    environment = {"python": platform.python_version(), **{name: importlib.metadata.version(name)
                   for name in ("opencv-python", "numpy", "pyserial", "PyYAML")}}
    report = {
        "description": "historical_capture_regression_comparison",
        "environment": environment,
        "baseline_environment_matches": environment == baseline["environment"],
        "images_checked": len(observations),
        "legacy_command_differences": sum(r["command"] != r["legacy"].get("command") for r in observations),
        "gray_white_only_command_differences": sum(r["command"] != r["legacy_bounds_command"] for r in observations),
        "numeric_predictions": sum(r["command"] != "NONE" for r in observations),
        "none_predictions": sum(r["command"] == "NONE" for r in observations),
        "routing_eligible": sum(r["routing_eligible"] for r in observations),
        "archived_routing_table_matches": table_matches,
        "failures": failures,
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
