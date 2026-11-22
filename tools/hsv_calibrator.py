"""Interactive OpenCV Trackbar tool for calibrating resistor body and colour-band HSV thresholds.

This utility reproduces the manual lighting and HSV threshold calibration workflow used during
hardware integration. It loads a sample resistor image (default: the first image in
``assets/sample_resistors/`` or a synthetic test image if none is present) together with
``config/hsv_thresholds.json``, and opens an OpenCV window with 7 trackbars:

* ``Target`` : selects which HSV entry to tune (``0 = body``, ``1..10 = black..white``)
* ``H min``, ``S min``, ``V min`` : lower HSV bound ``[0..179, 0..255, 0..255]``
* ``H max``, ``S max``, ``V max`` : upper HSV bound ``[0..179, 0..255, 0..255]``

Keyboard shortcuts in the preview window:

* ``n`` / ``b`` : next / previous target class (body, black, brown, ..., white)
* ``]`` / ``[`` : next / previous image in ``assets/sample_resistors/``
* ``p``         : print the current target's JSON snippet to the terminal
* ``s``         : save all thresholds to ``--output`` (default: ``config/hsv_thresholds.json``)
* ``r``         : reset the current target back to the values loaded from disk
* ``q`` / ``ESC``: quit

Examples::

    python tools/hsv_calibrator.py
    python tools/hsv_calibrator.py --image assets/sample_resistors/resistor_08.jpg --target purple
    python tools/hsv_calibrator.py --self-test
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
VISION_DIR = REPO_ROOT / "src" / "vision"
if str(VISION_DIR) not in sys.path:
    sys.path.insert(0, str(VISION_DIR))

from detector import COLOR_CODE, HsvRange, HsvThresholds, ResistorDetector  # noqa: E402
from synthetic import make_synthetic_resistor  # noqa: E402

WINDOW_NAME = "HSV Calibrator (s: save | p: print | n/b: target | [/]: image | q: quit)"
TARGETS: List[str] = ["body", *COLOR_CODE.keys()]


def load_raw_json(path: Path) -> Dict[str, Any]:
    """Read the HSV threshold JSON file while preserving its ``_notes`` metadata."""
    return json.loads(path.read_text(encoding="utf-8"))


def get_bounds(raw: Dict[str, Any], target: str) -> Tuple[List[int], List[int]]:
    """Return ``(lower, upper)`` lists for ``target`` (``'body'`` or a colour name)."""
    entry = raw["body"] if target == "body" else raw["bands"][target]
    return list(entry["lower"]), list(entry["upper"])


def set_bounds(raw: Dict[str, Any], target: str, lower: List[int], upper: List[int]) -> None:
    """Update ``(lower, upper)`` in ``raw`` for ``target``."""
    entry = {"lower": [int(x) for x in lower], "upper": [int(x) for x in upper]}
    if target == "body":
        raw["body"] = entry
    else:
        raw["bands"][target] = entry


def raw_to_thresholds(raw: Dict[str, Any]) -> HsvThresholds:
    """Convert the in-memory JSON dict into an :class:`HsvThresholds` instance."""
    body = HsvRange(tuple(raw["body"]["lower"]), tuple(raw["body"]["upper"]))  # type: ignore[arg-type]
    bands = {
        name: HsvRange(tuple(rng["lower"]), tuple(rng["upper"]))  # type: ignore[arg-type]
        for name, rng in raw["bands"].items()
    }
    return HsvThresholds(body=body, bands=bands)


def collect_images(explicit_image: Path | None) -> List[Path]:
    """Return a list of images to browse in the calibrator."""
    if explicit_image is not None:
        if not explicit_image.is_file():
            raise FileNotFoundError(f"Image not found: {explicit_image}")
        return [explicit_image]
    sample_dir = REPO_ROOT / "assets" / "sample_resistors"
    if sample_dir.is_dir():
        imgs = sorted(
            p for p in sample_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
        )
        if imgs:
            return imgs
    return []


def read_bgr(path: Path | None, resize_factor: float = 0.5) -> Tuple[np.ndarray, str]:
    """Read and resize an image from ``path`` (or generate a synthetic resistor if ``None``)."""
    if path is None:
        img = make_synthetic_resistor()
        label = "synthetic_sample.png"
    else:
        buf = np.fromfile(str(path), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Cannot decode image: {path}")
        label = path.name
    scaled = cv2.resize(img, None, fx=resize_factor, fy=resize_factor)
    return scaled, label


def render_composite(
    image_bgr: np.ndarray,
    raw: Dict[str, Any],
    target: str,
    image_label: str,
) -> np.ndarray:
    """Build a 3-panel preview: original + detection, binary mask for ``target``, masked BGR."""
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    lower, upper = get_bounds(raw, target)
    mask = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))
    mask_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    isolated = cv2.bitwise_and(image_bgr, image_bgr, mask=mask)

    detector = ResistorDetector(raw_to_thresholds(raw))
    full_res = cv2.resize(image_bgr, None, fx=2.0, fy=2.0)
    det_res = detector.detect(full_res)

    panels = np.hstack([image_bgr, mask_bgr, isolated])
    header = np.full((64, panels.shape[1], 3), 28, dtype=np.uint8)
    line1 = (
        f"Image: {image_label}  |  Target: [{target}]  "
        f"lower={lower}  upper={upper}  (matching px: {int(np.count_nonzero(mask))})"
    )
    bands_str = ", ".join(det_res.colors) if det_res.colors else "-"
    line2 = (
        f"Live detector -> bands: [{bands_str}]  command: {det_res.command}  "
        f"|  Keys: [n/b] target  [[/]] image  [p] print  [s] save  [r] reset  [q] quit"
    )
    cv2.putText(header, line1, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(header, line2, (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (120, 240, 120), 1, cv2.LINE_AA)
    return np.vstack([header, panels])


def run_self_test(config_path: Path, explicit_image: Path | None) -> int:
    """Headless check that loads the JSON, renders one composite frame for every target, and exits."""
    raw = load_raw_json(config_path)
    images = collect_images(explicit_image)
    image_bgr, label = read_bgr(images[0] if images else None)
    for target in TARGETS:
        frame = render_composite(image_bgr, raw, target, label)
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise RuntimeError(f"Unexpected composite shape for {target}: {frame.shape}")
    print(f"[SELF-TEST OK] Rendered {len(TARGETS)} targets ({', '.join(TARGETS)}) on '{label}' -> shape={frame.shape}")
    return 0


def run_interactive(
    config_path: Path,
    output_path: Path,
    explicit_image: Path | None,
    initial_target: str,
) -> int:
    """Open the OpenCV Trackbar window and run the interactive event loop."""
    saved_raw = load_raw_json(config_path)
    working_raw = copy.deepcopy(saved_raw)
    images = collect_images(explicit_image)
    img_idx = 0
    target_idx = TARGETS.index(initial_target)

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_AUTOSIZE)
    syncing = False

    def _noop(_val: int) -> None:
        pass

    cv2.createTrackbar("Target", WINDOW_NAME, target_idx, len(TARGETS) - 1, _noop)
    cv2.createTrackbar("H min", WINDOW_NAME, 0, 179, _noop)
    cv2.createTrackbar("S min", WINDOW_NAME, 0, 255, _noop)
    cv2.createTrackbar("V min", WINDOW_NAME, 0, 255, _noop)
    cv2.createTrackbar("H max", WINDOW_NAME, 179, 179, _noop)
    cv2.createTrackbar("S max", WINDOW_NAME, 255, 255, _noop)
    cv2.createTrackbar("V max", WINDOW_NAME, 255, 255, _noop)

    def push_bounds_to_trackbars(target: str) -> None:
        nonlocal syncing
        syncing = True
        lower, upper = get_bounds(working_raw, target)
        cv2.setTrackbarPos("Target", WINDOW_NAME, TARGETS.index(target))
        cv2.setTrackbarPos("H min", WINDOW_NAME, int(lower[0]))
        cv2.setTrackbarPos("S min", WINDOW_NAME, int(lower[1]))
        cv2.setTrackbarPos("V min", WINDOW_NAME, int(lower[2]))
        cv2.setTrackbarPos("H max", WINDOW_NAME, int(upper[0]))
        cv2.setTrackbarPos("S max", WINDOW_NAME, int(upper[1]))
        cv2.setTrackbarPos("V max", WINDOW_NAME, int(upper[2]))
        syncing = False

    push_bounds_to_trackbars(TARGETS[target_idx])
    image_bgr, label = read_bgr(images[img_idx] if images else None)

    try:
        while True:
            tb_target_idx = cv2.getTrackbarPos("Target", WINDOW_NAME)
            if tb_target_idx != target_idx:
                target_idx = tb_target_idx
                push_bounds_to_trackbars(TARGETS[target_idx])

            target = TARGETS[target_idx]
            if not syncing:
                lower = [
                    cv2.getTrackbarPos("H min", WINDOW_NAME),
                    cv2.getTrackbarPos("S min", WINDOW_NAME),
                    cv2.getTrackbarPos("V min", WINDOW_NAME),
                ]
                upper = [
                    cv2.getTrackbarPos("H max", WINDOW_NAME),
                    cv2.getTrackbarPos("S max", WINDOW_NAME),
                    cv2.getTrackbarPos("V max", WINDOW_NAME),
                ]
                set_bounds(working_raw, target, lower, upper)

            frame = render_composite(image_bgr, working_raw, target, label)
            cv2.imshow(WINDOW_NAME, frame)

            key = cv2.waitKey(30) & 0xFF
            if key in (27, ord("q")):
                break
            if key == ord("n"):
                target_idx = (target_idx + 1) % len(TARGETS)
                push_bounds_to_trackbars(TARGETS[target_idx])
            elif key == ord("b"):
                target_idx = (target_idx - 1) % len(TARGETS)
                push_bounds_to_trackbars(TARGETS[target_idx])
            elif key == ord("]") and images:
                img_idx = (img_idx + 1) % len(images)
                image_bgr, label = read_bgr(images[img_idx])
            elif key == ord("[") and images:
                img_idx = (img_idx - 1) % len(images)
                image_bgr, label = read_bgr(images[img_idx])
            elif key == ord("r"):
                orig_l, orig_u = get_bounds(saved_raw, target)
                set_bounds(working_raw, target, orig_l, orig_u)
                push_bounds_to_trackbars(target)
                print(f"[RESET] {target}: lower={orig_l}, upper={orig_u}")
            elif key == ord("p"):
                cur_l, cur_u = get_bounds(working_raw, target)
                print(f'"{target}": {{ "lower": {cur_l}, "upper": {cur_u} }}')
            elif key == ord("s"):
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(working_raw, indent=2) + "\n", encoding="utf-8")
                saved_raw = copy.deepcopy(working_raw)
                print(f"[SAVED] Wrote thresholds to {output_path}")
    finally:
        cv2.destroyAllWindows()
    return 0


def main(argv: List[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Interactive OpenCV Trackbar HSV calibrator.")
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "hsv_thresholds.json",
        help="Path to hsv_thresholds.json (default: config/hsv_thresholds.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Where 's' writes updated JSON (default: overwrite --config)",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="Image file to load (default: first image in assets/sample_resistors/)",
    )
    parser.add_argument(
        "--target",
        choices=TARGETS,
        default="body",
        help="Initial target to tune (default: body)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a headless check of threshold loading and composite rendering, then exit",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test(args.config, args.image)
    out_path = args.output or args.config
    return run_interactive(args.config, out_path, args.image, args.target)


if __name__ == "__main__":
    sys.exit(main())
