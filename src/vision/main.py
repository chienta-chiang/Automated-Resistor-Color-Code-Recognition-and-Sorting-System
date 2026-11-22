"""Entry point of the vision side: ``--mock`` (offline demo) and ``--live`` (real hardware).

Examples::

    python src/vision/main.py --mock                       # no hardware needed
    python src/vision/main.py --mock --input-dir some/dir  # use your own images
    python src/vision/main.py --live --serve-upload        # ESP32-CAM -> HTTP -> OpenCV -> Arduino
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np
import yaml

from detector import DetectionResult, DetectorParams, HsvThresholds, ResistorDetector
from serial_bridge import ArduinoSerial, MockSerial, SortingSession
from configuration import validate_settings
from capture_queue import CaptureQueue
from live_capture import LegacyFileIngress, process_next_capture

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def resolve(path_like: str | Path) -> Path:
    """Resolve a path from the settings file against the repository root."""
    path = Path(path_like)
    return path if path.is_absolute() else REPO_ROOT / path


def load_settings(explicit: str | None) -> Dict[str, Any]:
    """Load ``--config`` if given, else ``config/settings.yaml``, else ``config/settings.example.yaml``."""
    candidates = [Path(explicit)] if explicit else [
        REPO_ROOT / "config" / "settings.yaml",
        REPO_ROOT / "config" / "settings.example.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            print(f"[CONFIG] {candidate}")
            settings = yaml.safe_load(candidate.read_text(encoding="utf-8"))
            settings = {} if settings is None else settings
            validate_settings(settings)
            vision = settings.get("vision", {})
            DetectorParams.from_settings(vision)
            HsvThresholds.from_json(resolve(vision.get("hsv_thresholds", "config/hsv_thresholds.json")))
            return settings
    raise FileNotFoundError(f"No settings file found (tried: {', '.join(map(str, candidates))})")


def build_detector(settings: Dict[str, Any]) -> ResistorDetector:
    """Create the detector from ``settings['vision']`` and the HSV JSON it points to."""
    vision_cfg = settings.get("vision", {})
    thresholds = HsvThresholds.from_json(resolve(vision_cfg.get("hsv_thresholds", "config/hsv_thresholds.json")))
    return ResistorDetector(thresholds, DetectorParams.from_settings(vision_cfg),
                            max_pixels=settings.get("upload_server", {}).get("max_pixels", 16_000_000))


def natural_key(path: Path) -> List[Any]:
    """Sort key that orders ``photo (2).jpg`` before ``photo (10).jpg``."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def list_images(directory: Path) -> List[Path]:
    """All image files directly inside ``directory`` in natural order."""
    if not directory.is_dir():
        return []
    return sorted((p for p in directory.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES), key=natural_key)


def save_image(path: Path, image: np.ndarray) -> None:
    """Write an image with ``imencode`` so non-ASCII file names work on Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise OSError(f"Could not encode {path}")
    path.write_bytes(buffer.tobytes())


def annotate(result: DetectionResult, name: str, sent: str) -> np.ndarray:
    """Add a caption bar (file name, bands read, command sent) above the detector's drawing."""
    assert result.annotated is not None
    body = result.annotated
    bar = np.full((52, body.shape[1], 3), 32, dtype=np.uint8)
    bands = ", ".join(result.colors) if result.colors else "-"
    cv2.putText(bar, f"{name[:60]}  |  bands: {bands}  |  found: {result.bands_found}", (8, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    verdict = f"TX: {sent}" + ("  (-> unknown bin)" if sent == "NONE" else " ohm")
    color = (0, 200, 255) if sent == "NONE" else (80, 255, 80)
    cv2.putText(bar, verdict, (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)
    return np.vstack([bar, body])


# --------------------------------------------------------------------------- mock
def run_mock(settings: Dict[str, Any], input_dir: Path | None, output_dir: Path | None) -> int:
    """Offline demo: detect each image, simulate the serial traffic, save annotated results."""
    mock_cfg = settings.get("mock", {})
    in_dir = input_dir or resolve(mock_cfg.get("input_dir", "assets/sample_resistors"))
    out_dir = output_dir or resolve(mock_cfg.get("output_dir", "output/mock_results"))
    wait_s = float(mock_cfg.get("adjust_wait_s", 0.3))

    images = list_images(in_dir)
    if not images:
        from synthetic import write_synthetic_samples

        synth_dir = REPO_ROOT / "output" / "mock_inputs"
        print(f"[MOCK] No images in {in_dir} - generating synthetic test pictures in {synth_dir}")
        images = write_synthetic_samples(synth_dir)
    else:
        print(f"[MOCK] {len(images)} image(s) from {in_dir}")

    detector = build_detector(settings)
    link = MockSerial()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: List[List[Any]] = []

    for index, path in enumerate(images, 1):
        print(f"\n[{index}/{len(images)}] {path.name}")
        session = SortingSession(link, adjust_wait_s=wait_s)
        frame = 0
        while True:
            frame += 1
            try:
                result = detector.detect_file(path)
            except ValueError as exc:
                print(f"  ! skipped: {exc}")
                break
            if not result.input_ok:
                print(f"  ! input failure: {result.input_error}; no dispatch")
                break
            tag = "frame 1" if frame == 1 else f"frame {frame} (next frame, mock re-uses the same picture)"
            detail = f"{result.command}" if result.value is not None else f"NONE ({result.reason})"
            print(f"  {tag}: bands={result.colors or '-'} reversed={result.reversed_direction} -> {detail}")
            sent = session.on_recognition(result.command)
            if sent is not None:
                save_image(out_dir / f"{index:03d}_{re.sub(r'[^0-9A-Za-z_.-]+', '_', path.stem)}.png",
                           annotate(result, path.name, sent))
                rows.append([path.name, " ".join(result.colors), result.bands_found, sent, frame])
                break

    # If every real sample succeeded on the first frame, run one synthetic incomplete-band frame
    # so the two-stage MOTOR_ADJUST -> next-frame -> NONE state machine is always exercised in --mock.
    if rows and not any(r[4] > 1 for r in rows):
        from synthetic import make_synthetic_resistor

        demo_name = "synthetic_retry_demo.png"
        demo_idx = len(images) + 1
        print(f"\n[{demo_idx}/{demo_idx}] {demo_name} (synthetic fault-tolerance state-machine demo)")
        demo_bgr = make_synthetic_resistor(bands=("orange",), angle_deg=-8.0)
        session = SortingSession(link, adjust_wait_s=wait_s)
        frame = 0
        while True:
            frame += 1
            result = detector.detect(demo_bgr)
            if not result.input_ok:
                print(f"  ! input failure: {result.input_error}; no dispatch")
                break
            tag = "frame 1" if frame == 1 else f"frame {frame} (next frame after MOTOR_ADJUST)"
            detail = f"{result.command}" if result.value is not None else f"NONE ({result.reason})"
            print(f"  {tag}: bands={result.colors or '-'} reversed={result.reversed_direction} -> {detail}")
            sent = session.on_recognition(result.command)
            if sent is not None:
                save_image(out_dir / f"{demo_idx:03d}_synthetic_retry_demo.png",
                           annotate(result, demo_name, sent))
                rows.append([demo_name, " ".join(result.colors), result.bands_found, sent, frame])
                break

    with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["image", "bands_read", "bands_found", "command_sent", "frames_used"])
        writer.writerows(rows)

    recognised = sum(1 for r in rows if r[3] != "NONE")
    print(f"\n[MOCK] Done: {len(rows)} image(s) processed, {recognised} read as a value, "
          f"{len(rows) - recognised} sent as NONE (unknown bin).")
    print(f"[MOCK] Annotated results: {out_dir}")
    return 0


# --------------------------------------------------------------------------- live
def run_live(settings: Dict[str, Any], serve_upload: bool, port_override: str | None) -> int:
    """Consume immutable queued events; hardware only opens in this entry point."""
    validate_settings(settings)
    serial_cfg = settings.get("serial", {})
    capture_cfg = settings.get("capture", {})
    upload_cfg = settings.get("upload_server", {})
    detector = build_detector(settings)
    captures = CaptureQueue(resolve(capture_cfg.get("queue_dir", "uploads/captures")),
                            capture_cfg.get("queue_capacity", 32),
                            upload_cfg.get("max_pixels", 16_000_000))
    link = server = server_thread = legacy = None
    try:
        if captures.quarantined:
            raise RuntimeError("Uncertain in-flight captures require manual review before motion")
        if captures.recovered_count and not capture_cfg.get("resume_pending", False):
            raise RuntimeError("Pending captures recovered; review and explicitly set capture.resume_pending")
        link = ArduinoSerial(port_override or serial_cfg.get("port", "COM3"),
                             serial_cfg.get("baudrate", 9600), serial_cfg.get("timeout_s", 1))
        session = SortingSession(link, adjust_wait_s=settings.get("retry", {}).get("adjust_wait_s", 4))
        watch_file = resolve(capture_cfg.get("watch_file", "uploads/photo.jpg"))
        if serve_upload:
            from upload_server import create_server, serve_in_background
            server = create_server(upload_cfg.get("host", "127.0.0.1"),
                                   upload_cfg.get("port", 8080), watch_file,
                                   upload_cfg.get("upload_path", "/upload/upload.php"),
                                   upload_cfg.get("max_bytes", 5 * 1024 * 1024), captures=captures)
            server_thread = serve_in_background(server)
            print("[LIVE] Integrated capture FIFO ready; each accepted upload has a unique ID")
        else:
            print("[LIVE] Legacy file polling is best effort; overwritten frames cannot be recovered")
            legacy = LegacyFileIngress(watch_file, captures, capture_cfg.get("poll_interval_s", 0.1))
            legacy.start()
        while True:
            process_next_capture(captures, detector, session)
    except KeyboardInterrupt:
        print("[LIVE] Stopped; unprocessed accepted captures remain on disk")
    finally:
        if legacy is not None:
            legacy.close()
        if server is not None:
            server.shutdown()
            server.server_close()
            server_thread.join()
        captures.close()
        if link is not None:
            link.close()
    return 0


def main(argv: List[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Resistor colour-code recognition (vision side).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="offline demo: images in, simulated serial out")
    mode.add_argument("--live", action="store_true", help="real ESP32-CAM frames and Arduino serial port")
    parser.add_argument("--config", help="settings YAML (default: config/settings.yaml or settings.example.yaml)")
    parser.add_argument("--input-dir", type=Path, help="[mock] folder of images to process")
    parser.add_argument("--output-dir", type=Path, help="[mock] where annotated images are written")
    parser.add_argument("--serve-upload", action="store_true", help="[live] also run the HTTP upload receiver")
    parser.add_argument("--port", help="[live] serial port override, e.g. COM5 or /dev/ttyACM0")
    args = parser.parse_args(argv)

    settings = load_settings(args.config)
    if args.mock:
        return run_mock(settings, args.input_dir, args.output_dir)
    return run_live(settings, args.serve_upload, args.port)


if __name__ == "__main__":
    sys.exit(main())
