"""Synthetic resistor image generator for offline demos and tests.

Used by ``main.py --mock`` when ``assets/sample_resistors/`` contains no images. The picture
imitates the real capture setup (800x600 frame, light-blue background, tan body, three colour
bands plus an olive tolerance band at one end, silver leads) and can be tilted so the Affine
rotation step is exercised. It is a *drawing*, not a photograph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

import cv2
import numpy as np

_BAND_HSV = {
    "orange": (17, 160, 170),
    "green": (50, 140, 110),
    "purple": (140, 40, 110),
    "red": (10, 170, 130),
    "brown": (18, 190, 80),
}
_BACKGROUND_HSV = (90, 55, 200)
_BODY_HSV = (28, 110, 175)
_TOLERANCE_HSV = (30, 120, 110)  # olive / gold-ish, not one of the 10 value colours
_LEAD_HSV = (0, 0, 150)


def _bgr(hsv: Tuple[int, int, int]) -> Tuple[int, int, int]:
    pixel = cv2.cvtColor(np.uint8([[hsv]]), cv2.COLOR_HSV2BGR)[0, 0]
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def make_synthetic_resistor(bands: Sequence[str] = ("orange", "green", "purple"), angle_deg: float = -10.0,
                            size: Tuple[int, int] = (800, 600)) -> np.ndarray:
    """Draw a resistor and tilt it by ``angle_deg``.

    The three ``bands`` are drawn left to right close to the *right* end and an olive tolerance
    band apart at the left end, so the default drawing reads right to left as
    ``purple, green, orange`` = 75 kΩ (same as the real ``photo.jpg`` sample). Rotating by ~180°
    flips the layout, which exercises the end-distance direction logic.
    """
    width, height = size
    image = np.full((height, width, 3), _bgr(_BACKGROUND_HSV), dtype=np.uint8)
    cx, cy = width // 2, height // 2
    body_w, body_h = 190, 62

    cv2.line(image, (cx - 330, cy), (cx - body_w // 2, cy), _bgr(_LEAD_HSV), 6)
    cv2.line(image, (cx + body_w // 2, cy), (cx + 330, cy), _bgr(_LEAD_HSV), 6)
    cv2.rectangle(image, (cx - body_w // 2, cy - body_h // 2), (cx + body_w // 2, cy + body_h // 2), _bgr(_BODY_HSV), -1)

    x0 = cx - body_w // 2
    # Like a real resistor: the value bands are grouped near one end, the tolerance band sits apart
    # at the other end. The reader must therefore start from the end the value bands are closest to.
    cv2.rectangle(image, (x0 + 18, cy - body_h // 2), (x0 + 30, cy + body_h // 2), _bgr(_TOLERANCE_HSV), -1)
    for i, name in enumerate(bands):
        bx = x0 + 85 + i * 34
        cv2.rectangle(image, (bx, cy - body_h // 2), (bx + 14, cy + body_h // 2), _bgr(_BAND_HSV[name]), -1)

    rot = cv2.getRotationMatrix2D((cx, cy), angle_deg, 1.0)
    return cv2.warpAffine(image, rot, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def write_synthetic_samples(out_dir: Path) -> list[Path]:
    """Write a couple of synthetic frames (different tilts / orientations) into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        ("synthetic_orange_green_purple_tilt-10.png", ("orange", "green", "purple"), -10.0),
        ("synthetic_orange_green_purple_tilt+14.png", ("orange", "green", "purple"), 14.0),
        ("synthetic_orange_green_purple_flipped.png", ("orange", "green", "purple"), 180.0 - 6.0),
        ("synthetic_incomplete_bands_retry_demo.png", ("orange",), -8.0),
    ]
    paths = []
    for name, bands, angle in specs:
        path = out_dir / name
        cv2.imwrite(str(path), make_synthetic_resistor(bands, angle))
        paths.append(path)
    return paths
