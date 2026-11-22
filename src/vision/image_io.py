"""Validate encoded inputs before recognition or queue admission.

Pillow verifies structure and loads pixels; OpenCV remains the BGR decoder used
by recognition. Valid captures are not re-encoded or color-corrected.
"""

from __future__ import annotations

import io
import warnings

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

DEFAULT_MAX_PIXELS = 16_000_000


class ImageInputError(ValueError):
    """Encoded data cannot be treated as a complete supported image."""


def decode_image_bytes(data: bytes, *, require_jpeg: bool = False,
                       max_pixels: int = DEFAULT_MAX_PIXELS) -> np.ndarray:
    if not data:
        raise ImageInputError("empty image")
    if require_jpeg and (not data.startswith(b"\xff\xd8") or not data.rstrip().endswith(b"\xff\xd9")):
        raise ImageInputError("expected a complete JPEG")
    # OpenCV can recover partially truncated JPEGs. Require the end marker for
    # local JPEG inputs too, rather than accepting a recovered partial picture.
    if data.startswith(b"\xff\xd8") and not data.rstrip().endswith(b"\xff\xd9"):
        raise ImageInputError("truncated JPEG")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if require_jpeg and image.format != "JPEG":
                    raise ImageInputError("multipart image must be JPEG")
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise ImageInputError("invalid dimensions or pixel limit exceeded")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
        decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if decoded is None or decoded.ndim != 3 or decoded.shape[2] != 3 or decoded.size == 0:
            raise ImageInputError("OpenCV could not decode image")
        return decoded
    except (cv2.error, OSError, ValueError, SyntaxError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        if isinstance(exc, ImageInputError):
            raise
        raise ImageInputError(f"image decoding failed: {type(exc).__name__}") from exc
