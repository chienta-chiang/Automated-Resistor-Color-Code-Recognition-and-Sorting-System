"""Configuration validation shared by CLI and detector; no hardware effects."""

from __future__ import annotations

import math
from numbers import Integral, Real


def mapping(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return value


def integer(value, name: str, *, minimum: int = 1, maximum: int = 2**31 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return int(value)


def number(value, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < 0 or (not allow_zero and value == 0):
        raise ValueError(f"{name} must be {'nonnegative' if allow_zero else 'positive'}")
    return float(value)


def validate_settings(settings: dict) -> dict:
    mapping(settings, "settings")
    for section in ("serial", "capture", "upload_server", "vision", "retry", "mock"):
        if section in settings:
            mapping(settings[section], section)
    serial = settings.get("serial", {})
    if "baudrate" in serial and integer(serial["baudrate"], "serial.baudrate") != 9600:
        raise ValueError("serial.baudrate must remain 9600")
    if "timeout_s" in serial:
        number(serial["timeout_s"], "serial.timeout_s", allow_zero=True)
    if "port" in serial and (not isinstance(serial["port"], str) or not serial["port"].strip()):
        raise ValueError("serial.port must be a nonempty string")
    capture = settings.get("capture", {})
    for key in ("poll_interval_s",):
        if key in capture:
            number(capture[key], f"capture.{key}")
    if "queue_capacity" in capture:
        integer(capture["queue_capacity"], "capture.queue_capacity")
    if "resume_pending" in capture and not isinstance(capture["resume_pending"], bool):
        raise ValueError("capture.resume_pending must be boolean")
    upload = settings.get("upload_server", {})
    for key in ("port", "max_bytes", "max_pixels"):
        if key in upload:
            integer(upload[key], f"upload_server.{key}", maximum=65535 if key == "port" else 2**31 - 1)
    for section in ("retry", "mock"):
        if "adjust_wait_s" in settings.get(section, {}):
            number(settings[section]["adjust_wait_s"], f"{section}.adjust_wait_s", allow_zero=True)
    for section, keys in {
        "capture": ("watch_file", "queue_dir"),
        "upload_server": ("host", "upload_path"),
        "vision": ("hsv_thresholds",),
        "mock": ("input_dir", "output_dir"),
    }.items():
        for key in keys:
            if key in settings.get(section, {}):
                value = settings[section][key]
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{section}.{key} must be a nonempty string")
    path = upload.get("upload_path", "/upload/upload.php")
    if not path.startswith("/"):
        raise ValueError("upload_server.upload_path must start with /")
    return settings
