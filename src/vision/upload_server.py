"""HTTP multipart upload receiver for ESP32-CAM JPEG captures.

Accepts multipart POST requests on the configured endpoint (`/upload/upload.php`),
validates image data, and publishes each capture into the bounded FIFO queue while
updating a latest-image preview file for compatibility.
"""

from __future__ import annotations

import argparse
import socket
import threading
from email.parser import BytesParser
from email.policy import default as default_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from capture_queue import CaptureQueue, QueueFullError, publish_preview
from image_io import DEFAULT_MAX_PIXELS, ImageInputError

DEFAULT_UPLOAD_PATH = "/upload/upload.php"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
JPEG_MAGIC = b"\xff\xd8"


def extract_image_part(content_type: str, body: bytes, field: str = "image") -> Optional[bytes]:
    raw = b"Content-Type: " + content_type.encode("latin-1") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    message = BytesParser(policy=default_policy).parsebytes(raw)
    if not message.is_multipart() or message.defects:
        return None
    matches = [part for part in message.iter_parts()
               if part.get_param("name", header="content-disposition") == field]
    if len(matches) != 1 or matches[0].defects:
        return None
    return matches[0].get_payload(decode=True)


def make_handler(save_path: Path, upload_path: str, max_bytes: int,
                 captures: CaptureQueue) -> type[BaseHTTPRequestHandler]:
    class UploadHandler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10.0)

        def _reply(self, code: int, text: str, capture_id: str | None = None) -> None:
            payload = text.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            if capture_id:
                self.send_header("X-Capture-ID", capture_id)
            if code == 503:
                self.send_header("Retry-After", "1")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(payload)

        def do_POST(self) -> None:
            if self.path != upload_path:
                self._reply(404, "Not found")
                return
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
                self._reply(400, "Exactly one Content-Length is required")
                return
            raw_length = lengths[0]
            if not raw_length.isascii() or not raw_length.isdigit():
                self._reply(400, "Malformed Content-Length")
                return
            try:
                length = int(raw_length)
            except ValueError:
                self._reply(400, "Malformed Content-Length")
                return
            if length > max_bytes:
                self._reply(413, "Body too large")
                return
            if length <= 0:
                self._reply(400, "Empty body")
                return
            try:
                body = self.rfile.read(length)
            except (socket.timeout, TimeoutError):
                self._reply(400, "Incomplete request body")
                return
            if len(body) != length:
                self._reply(400, "Incomplete request body")
                return
            try:
                image = extract_image_part(self.headers.get("Content-Type", ""), body)
                if image is None:
                    raise ImageInputError("Missing or malformed multipart image")
                event = captures.publish(image)
            except (ImageInputError, UnicodeError, ValueError):
                self._reply(400, "Invalid or incomplete JPEG image")
                return
            except QueueFullError:
                self._reply(503, "Capture queue full; upload not accepted")
                return
            except OSError:
                self._reply(500, "Capture storage failed; upload not accepted")
                return
            # Acceptance belongs to the immutable queued event, not this preview.
            try:
                publish_preview(save_path, image)
            except OSError:
                self.log_message("Capture queued; compatibility preview unavailable")
            self._reply(200, f"Upload successful ({len(image)} bytes; capture {event.capture_id})",
                        event.capture_id)

        def log_message(self, fmt: str, *args: object) -> None:
            print(f"[UPLOAD] {self.address_string()} - {fmt % args}")

    return UploadHandler


def create_server(host: str, port: int, save_path: Path, upload_path: str = DEFAULT_UPLOAD_PATH,
                  max_bytes: int = DEFAULT_MAX_BYTES, *, captures: CaptureQueue | None = None,
                  queue_dir: Path | None = None, queue_capacity: int = 32,
                  max_pixels: int = DEFAULT_MAX_PIXELS) -> ThreadingHTTPServer:
    owns_queue = captures is None
    if captures is None:
        captures = CaptureQueue(queue_dir or Path(save_path).parent / "captures",
                                queue_capacity, max_pixels)

    class UploadServer(ThreadingHTTPServer):
        daemon_threads = False  # graceful close waits for accepted request handlers

        def server_close(self) -> None:
            try:
                super().server_close()
            finally:
                if owns_queue:
                    captures.close()

    try:
        server = UploadServer((host, port), make_handler(save_path, upload_path, max_bytes, captures))
    except BaseException:
        if owns_queue:
            captures.close()
        raise
    server.captures = captures
    return server


def serve_in_background(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, name="upload-server", daemon=True)
    thread.start()
    return thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Receive ESP32-CAM captures into a bounded FIFO.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--path", default=DEFAULT_UPLOAD_PATH)
    parser.add_argument("--save", type=Path, default=Path("uploads/photo.jpg"))
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--queue-dir", type=Path, default=Path("uploads/captures"))
    parser.add_argument("--queue-capacity", type=int, default=32)
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.save, args.path, args.max_bytes,
                           queue_dir=args.queue_dir, queue_capacity=args.queue_capacity)
    print("Upload receiver ready; use integrated --live --serve-upload for a consuming worker")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
