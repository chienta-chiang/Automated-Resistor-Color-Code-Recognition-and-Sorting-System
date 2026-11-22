"""Single-owner bounded persistent FIFO of accepted capture events.

Each admission gets an independent sequence/UUID even for identical bytes.
Pending captures survive clean shutdown. In-flight captures are quarantined on
restart, never automatically replayed into physical actuation.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from configuration import integer
from image_io import DEFAULT_MAX_PIXELS, decode_image_bytes


class QueueFullError(RuntimeError):
    """Admission rejected without discarding any previously accepted event."""


@dataclass(frozen=True)
class CaptureEvent:
    capture_id: str
    path: Path
    sha256: str


class CaptureQueue:
    def __init__(self, directory: Path, capacity: int = 32,
                 max_pixels: int = DEFAULT_MAX_PIXELS) -> None:
        self.directory = Path(directory).resolve()
        self.capacity = integer(capacity, "capture.queue_capacity")
        self.max_pixels = integer(max_pixels, "upload_server.max_pixels")
        self.directory.mkdir(parents=True, exist_ok=True)
        self._condition = threading.Condition()
        self._closed = False
        self._active: dict[str, CaptureEvent] = {}
        self._owner = self.directory / ".owner"
        self._token = f"{os.getpid()}:{uuid.uuid4().hex}".encode("ascii")
        try:
            with self._owner.open("xb") as stream:
                stream.write(self._token)
        except FileExistsError as exc:
            raise RuntimeError("Capture spool already owned or stale .owner; review before restarting") from exc
        self.quarantined = []
        try:
            for path in sorted(self.directory.glob("*.processing")):
                destination = path.with_suffix(".uncertain")
                os.replace(path, destination)
                self.quarantined.append(destination.name)
            self.quarantined = sorted(path.name for path in self.directory.glob("*.uncertain"))
            # Leftover incomplete writes were never accepted. Do not process them.
            for path in self.directory.glob("*.part"):
                path.unlink()
            paths = sorted(self.directory.glob("*.jpg"))
            self._pending = deque(
                CaptureEvent(path.stem, path, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in paths
            )
            self.recovered_count = len(self._pending)
            sequences = [int(path.name.split("_", 1)[0]) for path in self.directory.iterdir()
                         if path.name.split("_", 1)[0].isdigit()]
            self._sequence = max(sequences, default=0)
        except BaseException:
            self._owner.unlink(missing_ok=True)
            raise

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending) + len(self._active)

    def publish(self, data: bytes, *, require_jpeg: bool = True) -> CaptureEvent:
        decode_image_bytes(data, require_jpeg=require_jpeg, max_pixels=self.max_pixels)
        with self._condition:
            if self._closed:
                raise RuntimeError("Capture queue is closed")
            if len(self._pending) + len(self._active) >= self.capacity:
                raise QueueFullError("Capture queue full; no capture accepted")
            self._sequence += 1
            capture_id = f"{self._sequence:020d}_{uuid.uuid4().hex}"
            destination = self.directory / f"{capture_id}.jpg"
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.directory, suffix=".part", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
                event = CaptureEvent(capture_id, destination, hashlib.sha256(data).hexdigest())
                self._pending.append(event)
                self._condition.notify()
                return event
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)

    def take(self, timeout: float = 0.1) -> CaptureEvent | None:
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._pending and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if not self._pending:
                return None
            original = self._pending[0]
            claimed = original.path.with_suffix(".processing")
            os.replace(original.path, claimed)
            self._pending.popleft()
            event = CaptureEvent(original.capture_id, claimed, original.sha256)
            self._active[event.capture_id] = event
            return event

    def finish(self, event: CaptureEvent) -> None:
        with self._condition:
            if self._active.get(event.capture_id) != event:
                raise ValueError("Capture was not claimed by this queue")
            event.path.unlink()
            del self._active[event.capture_id]

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
            if self._owner.exists() and self._owner.read_bytes() == self._token:
                self._owner.unlink()


def publish_preview(path: Path, data: bytes) -> None:
    """Best-effort legacy latest-file view; never used as the integrated queue."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
