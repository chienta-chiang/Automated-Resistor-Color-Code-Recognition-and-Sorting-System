"""HSV-based resistor color-band detector.

Pipeline: resize, HSV masks, morphological filtering, largest-contour bounding
box, affine deskew rotation, candidate band filtering (position, area, aspect
ratio), reading-direction estimation from band-to-body-edge distances, and
three-band resistance decoding (two significant digits plus decimal multiplier).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from numbers import Integral
from configuration import mapping, integer, number
from image_io import DEFAULT_MAX_PIXELS, ImageInputError, decode_image_bytes
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

#: Resistor colour code (digit / multiplier exponent) for the 10 supported colours.
COLOR_CODE: Dict[str, int] = {
    "black": 0,
    "brown": 1,
    "red": 2,
    "orange": 3,
    "yellow": 4,
    "green": 5,
    "blue": 6,
    "purple": 7,
    "gray": 8,
    "white": 9,
}

NONE_COMMAND = "NONE"


@dataclass(frozen=True)
class HsvRange:
    """Inclusive HSV lower / upper bound as used by ``cv2.inRange``."""

    lower: Tuple[int, int, int]
    upper: Tuple[int, int, int]

    def __post_init__(self) -> None:
        for name, bound in (("lower", self.lower), ("upper", self.upper)):
            if not isinstance(bound, (tuple, list)) or len(bound) != 3:
                raise ValueError(f"HSV {name} must contain three integer channels")
            for index, value in enumerate(bound):
                maximum = 179 if index == 0 else 255
                if isinstance(value, bool) or not isinstance(value, Integral) or not 0 <= value <= maximum:
                    raise ValueError(f"HSV {name} channel {index} must be an integer in 0..{maximum}")
        if any(low > high for low, high in zip(self.lower, self.upper)):
            raise ValueError("HSV lower bounds must not exceed upper bounds")

    def mask(self, hsv: np.ndarray) -> np.ndarray:
        """Return the binary mask of pixels inside this range."""
        return cv2.inRange(hsv, np.array(self.lower, dtype=np.uint8), np.array(self.upper, dtype=np.uint8))


@dataclass(frozen=True)
class HsvThresholds:
    """HSV ranges of the resistor body and the colour bands (insertion order matters)."""

    body: HsvRange
    bands: Dict[str, HsvRange]

    @classmethod
    def from_json(cls, path: Path | str) -> "HsvThresholds":
        """Load thresholds from ``config/hsv_thresholds.json``."""
        data = mapping(json.loads(Path(path).read_text(encoding="utf-8")), "HSV config")

        def parse(entry: dict) -> HsvRange:
            mapping(entry, "HSV range")
            if "lower" not in entry or "upper" not in entry:
                raise ValueError("HSV range requires lower and upper")
            return HsvRange(entry["lower"], entry["upper"])

        if "body" not in data or "bands" not in data:
            raise ValueError("HSV config requires body and bands")
        band_data = mapping(data["bands"], "HSV bands")
        if not band_data:
            raise ValueError("HSV bands must not be empty")
        bands = {name: parse(rng) for name, rng in band_data.items()}
        unknown = set(bands) - set(COLOR_CODE)
        if unknown:
            raise ValueError(f"Unsupported colour names in HSV config: {sorted(unknown)}")
        return cls(body=parse(data["body"]), bands=bands)


@dataclass(frozen=True)
class DetectorParams:
    """Image-processing parameters (defaults match the capstone detector's values)."""

    resize_factor: float = 0.5
    mask_dilate: int = 5
    band_erode: int = 3
    band_dilate: int = 9
    final_erode: int = 4
    black_blob_area: float = 500
    band_min_area: float = 100
    band_min_aspect: float = 1.0
    band_dedup_px: float = 6

    def __post_init__(self) -> None:
        number(self.resize_factor, "vision.resize_factor")
        for name in ("mask_dilate", "band_erode", "band_dilate", "final_erode"):
            integer(getattr(self, name), f"vision.morphology.{name}")
        for name in ("black_blob_area", "band_min_area", "band_min_aspect", "band_dedup_px"):
            number(getattr(self, name), f"vision.filters.{name}", allow_zero=True)

    @classmethod
    def from_settings(cls, vision_cfg: dict) -> "DetectorParams":
        """Build from the ``vision`` section of ``settings.yaml`` (missing keys use defaults)."""
        mapping(vision_cfg, "vision")
        morph = mapping(vision_cfg.get("morphology", {}), "vision.morphology")
        filt = mapping(vision_cfg.get("filters", {}), "vision.filters")
        base = cls()
        return cls(
            resize_factor=vision_cfg.get("resize_factor", base.resize_factor),
            mask_dilate=morph.get("mask_dilate", base.mask_dilate),
            band_erode=morph.get("band_erode", base.band_erode),
            band_dilate=morph.get("band_dilate", base.band_dilate),
            final_erode=morph.get("final_erode", base.final_erode),
            black_blob_area=filt.get("black_blob_area", base.black_blob_area),
            band_min_area=filt.get("band_min_area", base.band_min_area),
            band_min_aspect=filt.get("band_min_aspect", base.band_min_aspect),
            band_dedup_px=filt.get("band_dedup_px", base.band_dedup_px),
        )


@dataclass
class DetectionResult:
    """Outcome of one detection run."""

    value: Optional[int] = None
    colors: List[str] = field(default_factory=list)  # bands in reading order (up to 3)
    bands_found: int = 0
    reversed_direction: bool = False
    angle_deg: float = 0.0
    reason: str = ""  # why the result is NONE (empty when recognised)
    annotated: Optional[np.ndarray] = None  # original | rotated, with boxes drawn

    input_error: Optional[str] = None  # separate input failure from valid-image NONE

    @property
    def input_ok(self) -> bool:
        return self.input_error is None

    @property
    def command(self) -> str:
        """Serial payload: the resistance in ohms as text, or ``"NONE"``."""
        return NONE_COMMAND if self.value is None else str(self.value)


def _kernel(size: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))


def _long_axis_angle_deg(rect: Tuple[Tuple[float, float], Tuple[float, float], float]) -> float:
    """Tilt of the rectangle's long side from the x axis, normalised to [-90, 90).

    ``cv2.minAreaRect`` changed its angle convention in OpenCV 4.5.1 (range (0, 90] instead
    of [-90, 0)). Using the long-side direction makes the result independent of that.
    Positive values mean clockwise tilt on screen (y axis points down).
    """
    (_, _), (w, h), angle = rect
    if w < h:
        angle += 90.0
    return (angle + 90.0) % 180.0 - 90.0


class ResistorDetector:
    """Reads a 3-band resistance value from a close-up BGR image."""

    def __init__(self, thresholds: HsvThresholds, params: Optional[DetectorParams] = None,
                 *, max_pixels: int = DEFAULT_MAX_PIXELS) -> None:
        self.max_pixels = integer(max_pixels, "upload_server.max_pixels")
        self.th = thresholds
        self.p = params or DetectorParams()
        self._k_mask_dilate = _kernel(self.p.mask_dilate)
        self._k_erode = _kernel(self.p.band_erode)
        self._k_dilate = _kernel(self.p.band_dilate)
        self._k_final_erode = _kernel(self.p.final_erode)

    # ------------------------------------------------------------------ masks
    def _band_mask(self, hsv: np.ndarray, color: str) -> np.ndarray:
        """Mask of one colour band after noise suppression."""
        mask = self.th.bands[color].mask(hsv)
        if color == "black":
            # Large black blobs are shadow / background, not a thin band: blank them out.
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                if cv2.contourArea(contour) > self.p.black_blob_area:
                    cv2.drawContours(mask, [contour], -1, 0, thickness=cv2.FILLED)
        if color != "purple":  # purple bands are thin and faint: do not erode them
            mask = cv2.erode(mask, self._k_erode)
        return cv2.dilate(mask, self._k_dilate)

    def _first_pass_mask(self, hsv: np.ndarray) -> np.ndarray:
        """Union of body + all band masks, used to find the resistor's tilt."""
        mask = self.th.body.mask(hsv)
        for color in self.th.bands:
            band = self._band_mask(hsv, color)
            mask = cv2.dilate(mask, self._k_mask_dilate)
            mask = cv2.bitwise_or(mask, band)
        return mask

    def _rotated_pass_mask(self, hsv: np.ndarray) -> np.ndarray:
        """Union mask on the deskewed frame, used to find the resistor's left/right ends."""
        body = self.th.body.mask(hsv)
        body = cv2.erode(body, self._k_mask_dilate)
        body = cv2.dilate(body, self._k_mask_dilate)
        mask = body
        for color in self.th.bands:
            mask = cv2.bitwise_or(mask, self._band_mask(hsv, color))
        return cv2.erode(mask, self._k_final_erode)

    # -------------------------------------------------------------- detection
    @staticmethod
    def input_failure(reason: str) -> DetectionResult:
        return DetectionResult(reason=f"input failure: {reason}", input_error=reason,
                               annotated=np.zeros((64, 128, 3), dtype=np.uint8))

    def detect_file(self, path: Path | str) -> DetectionResult:
        """Raise ValueError for a missing path; return an input_failure DetectionResult for unreadable or invalid image bytes."""
        try:
            data = Path(path).read_bytes()
        except FileNotFoundError as exc:
            raise ValueError(f"Cannot read image: {path}") from exc
        except OSError as exc:
            return self.input_failure(type(exc).__name__)
        return self.detect_bytes(data)

    def detect_bytes(self, data: bytes) -> DetectionResult:
        try:
            image = decode_image_bytes(data, max_pixels=self.max_pixels)
        except ImageInputError as exc:
            return self.input_failure(str(exc))
        return self.detect(image)

    def detect(self, image_bgr: np.ndarray) -> DetectionResult:
        if (not isinstance(image_bgr, np.ndarray) or image_bgr.dtype != np.uint8
                or image_bgr.ndim != 3 or image_bgr.shape[2] != 3 or image_bgr.size == 0):
            return self.input_failure("expected nonempty uint8 BGR image")
        height, width = image_bgr.shape[:2]
        scaled = (width * self.p.resize_factor, height * self.p.resize_factor)
        if (not all(math.isfinite(value) for value in scaled)
                or any(round(value) <= 0 for value in scaled)
                or round(scaled[0]) * round(scaled[1]) > self.max_pixels):
            return self.input_failure("scaled dimensions invalid or pixel limit exceeded")
        try:
            return self._detect_valid(image_bgr)
        except cv2.error as exc:
            return self.input_failure(f"OpenCV processing failed: {exc.code}")

    def _detect_valid(self, image_bgr: np.ndarray) -> DetectionResult:
        """Run the full pipeline on one BGR frame.

        Never raises for "nothing found": it returns a result whose ``value`` is ``None``
        (``command == "NONE"``) and whose ``reason`` explains why.
        """
        image = cv2.resize(image_bgr, None, fx=self.p.resize_factor, fy=self.p.resize_factor)
        result = DetectionResult(annotated=image.copy())
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        # --- 1. locate the resistor and measure its tilt -----------------------------
        contours, _ = cv2.findContours(self._first_pass_mask(hsv), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            result.reason = "no resistor contour found"
            return result
        rect = cv2.minAreaRect(max(contours, key=cv2.contourArea))
        box = np.int32(cv2.boxPoints(rect))
        left_view = image.copy()
        cv2.drawContours(left_view, [box], 0, (0, 255, 0), 2)

        # --- 2. Affine rotation to horizontal ----------------------------------------
        angle = _long_axis_angle_deg(rect)
        result.angle_deg = angle
        h, w = image.shape[:2]
        rot = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rotated = cv2.warpAffine(image, rot, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        hsv = cv2.cvtColor(rotated, cv2.COLOR_BGR2HSV)
        right_view = rotated.copy()
        result.annotated = np.hstack([left_view, right_view])

        # --- 3. resistor extent on the rotated frame ---------------------------------
        contours_r, _ = cv2.findContours(self._rotated_pass_mask(hsv), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours_r:
            result.reason = "no resistor contour after rotation"
            return result
        x, y, bw, bh = cv2.boundingRect(max(contours_r, key=cv2.contourArea))
        min_x, max_x, min_y, max_y = x, x + bw, y, y + bh
        cv2.rectangle(right_view, (x, y), (x + bw, y + bh), (0, 0, 255), 2)

        # --- 4. colour-band candidates -----------------------------------------------
        positions: List[Tuple[str, float]] = []
        for color in self.th.bands:
            band_contours, _ = cv2.findContours(self._band_mask(hsv, color), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in band_contours:
                bx, by, cw, ch = cv2.boundingRect(contour)
                if cv2.contourArea(contour) <= self.p.band_min_area or ch / cw <= self.p.band_min_aspect:
                    continue
                cx, cy = bx + cw / 2, by + ch / 2
                if not (min_x <= cx <= max_x and min_y <= cy <= max_y):
                    continue
                if any(abs(cx - pos_x) < self.p.band_dedup_px for _, pos_x in positions):
                    continue
                positions.append((color, cx))
                cv2.rectangle(right_view, (bx, by), (bx + cw, by + ch), (255, 0, 0), 2)
        positions.sort(key=lambda item: item[1])
        result.bands_found = len(positions)

        # --- 5. reading direction from distance to the resistor ends -----------------
        if positions:
            distance_left = positions[0][1] - min_x
            distance_right = max_x - positions[-1][1]
            if distance_left > distance_right:
                positions.reverse()
                result.reversed_direction = True

        # --- 6. value from the first three bands -------------------------------------
        result.colors = [name for name, _ in positions[:3]]
        if len(result.colors) == 3:
            digits = COLOR_CODE[result.colors[0]] * 10 + COLOR_CODE[result.colors[1]]
            result.value = digits * 10 ** COLOR_CODE[result.colors[2]]
        else:
            result.reason = f"only {len(result.colors)} colour band(s) found"
        result.annotated = np.hstack([left_view, right_view])
        return result
