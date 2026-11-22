"""Capture-queue consumer and single-file polling ingress."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from capture_queue import CaptureQueue, QueueFullError
from image_io import ImageInputError


def process_next_capture(captures, detector, session, timeout: float = 0.1) -> bool:
    """Consume one claimed event; invalid input never enters the retry machine."""
    event = captures.take(timeout)
    if event is None:
        return False
    try:
        data = event.path.read_bytes()
        if hashlib.sha256(data).hexdigest() != event.sha256:
            raise ImageInputError("queued capture changed after admission")
        result = detector.detect_bytes(data)
    except (OSError, ValueError) as exc:
        print(f"[INPUT FAILURE] capture {event.capture_id}: {type(exc).__name__}; no dispatch")
        captures.finish(event)
        return True
    if not result.input_ok:
        print(f"[INPUT FAILURE] capture {event.capture_id}: {result.input_error}; no dispatch")
        captures.finish(event)
        return True
    print(f"[LIVE] capture {event.capture_id}: bands={result.colors or '-'} -> {result.command}")
    # On dispatch/interruption errors leave the claim for manual review.
    session.on_recognition(result.command)
    captures.finish(event)
    return True


class LegacyFileIngress:
    """Poll a watched image file and publish observed updates into the capture queue."""

    def __init__(self, path: Path, captures: CaptureQueue, interval: float = 0.1) -> None:
        self.path = path
        self.captures = captures
        self.interval = interval
        self.stop_event = threading.Event()
        self.last = self._snapshot()
        self.last = None if self.last is None else self.last[0]
        self.thread = threading.Thread(target=self._run, name="legacy-file-ingress", daemon=True)

    def _snapshot(self):
        try:
            before = self.path.stat()
            data = self.path.read_bytes()
            after = self.path.stat()
        except OSError:
            return None
        if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
            return None
        identity = (after.st_mtime_ns, after.st_size, hashlib.sha256(data).hexdigest())
        return identity, data

    def poll_once(self) -> None:
        snapshot = self._snapshot()
        if snapshot is None or snapshot[0] == self.last:
            return
        identity, data = snapshot
        try:
            self.captures.publish(data, require_jpeg=False)
        except QueueFullError:
            print("[CAPTURE REJECTED] legacy file queue full; retaining latest observation for retry")
            return
        except ImageInputError as exc:
            print(f"[INPUT FAILURE] legacy file: {exc}; no dispatch")
        self.last = identity

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.poll_once()
            except OSError as exc:
                print(f"[INPUT FAILURE] legacy file access: {type(exc).__name__}")

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join()
