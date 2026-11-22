"""Automated regression and reliability test suite for the vision and dispatch pipeline."""

from __future__ import annotations

import contextlib
import csv
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "vision"))
sys.path.insert(0, str(ROOT / "tools"))

import cv2
import numpy as np

from detector import HsvThresholds, ResistorDetector
from routing import classify_command, load_routes
from serial_bridge import ArduinoSerial, MockSerial, SortingSession
from synthetic import make_synthetic_resistor
from upload_server import extract_image_part


class DetectorRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = ResistorDetector(HsvThresholds.from_json(ROOT / "config/hsv_thresholds.json"))
        cls.baseline = json.loads((ROOT / "tests/baselines/approved_samples.json").read_text(encoding="utf-8"))

    def test_approved_sample_predictions(self):
        import hashlib

        for expected in self.baseline["samples"]:
            with self.subTest(image=expected["image"]):
                path = ROOT / "assets/sample_resistors" / expected["image"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected["sha256"])
                actual = self.detector.detect_file(path)
                self.assertEqual(actual.command, expected["command"])
                self.assertEqual(actual.colors, expected["colors"])
                self.assertEqual(actual.bands_found, expected["bands_found"])
                self.assertEqual(actual.reversed_direction, expected["reversed_direction"])
                self.assertEqual(classify_command(actual.command)["routing_eligible"], expected["routing_eligible"])
                self.assertIsNone(expected["ground_truth_ohms"])

    def test_blank_frames_are_not_values(self):
        for level in (0, 255):
            with self.subTest(level=level):
                result = self.detector.detect(np.full((600, 800, 3), level, dtype=np.uint8))
                self.assertEqual(result.command, "NONE")
                self.assertTrue(result.reason)

    def test_synthetic_incomplete_frame(self):
        frame = make_synthetic_resistor(("orange",), -8.0)
        self.assertEqual(self.detector.detect(frame).command, "NONE")

    def test_extra_candidates_are_recorded_not_hidden(self):
        sample = ROOT / "assets/sample_resistors/resistor_05.jpg"
        result = self.detector.detect_file(sample)
        self.assertEqual(result.bands_found, 5)
        self.assertEqual(result.command, "750")

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                self.detector.detect_file(Path(directory) / "absent.jpg")


class DispatchRegression(unittest.TestCase):
    def session(self):
        link = MockSerial()
        waits = []
        return link, waits, SortingSession(link, sleep=waits.append)

    def test_valid_first_frame(self):
        link, waits, session = self.session()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(session.on_recognition("4700"), "4700")
        self.assertEqual(link.sent, ["4700"])
        self.assertEqual(waits, [])
        self.assertFalse(session.awaiting_retry)

    def test_failure_then_success(self):
        link, waits, session = self.session()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(session.on_recognition("NONE"))
            self.assertTrue(session.awaiting_retry)
            self.assertEqual(session.on_recognition("4700"), "4700")
        self.assertEqual(link.sent, ["MOTOR_ADJUST", "4700"])
        self.assertEqual(waits, [4.0])
        self.assertFalse(session.awaiting_retry)

    def test_two_failures_then_new_session(self):
        link, waits, session = self.session()
        with contextlib.redirect_stdout(io.StringIO()):
            for command in ("NONE", "NONE", "NONE", "4700"):
                session.on_recognition(command)
        self.assertEqual(link.sent, ["MOTOR_ADJUST", "NONE", "MOTOR_ADJUST", "4700"])
        self.assertEqual(waits, [4.0, 4.0])
        self.assertFalse(session.awaiting_retry)

    def test_unsupported_value_is_transmitted_unchanged(self):
        link, _, session = self.session()
        with contextlib.redirect_stdout(io.StringIO()):
            session.on_recognition("12345")
        self.assertEqual(link.sent, ["12345"])
        self.assertEqual(classify_command("12345")["category"], "outside_table")

    def test_serial_framing_without_opening_a_device(self):
        with patch("serial.Serial") as factory:
            link = ArduinoSerial("DUMMY_PORT")
            with contextlib.redirect_stdout(io.StringIO()):
                link.send("4700")
                link.send("MOTOR_ADJUST")
                link.send("NONE")
            factory.assert_called_once_with("DUMMY_PORT", 9600, timeout=1.0)
            self.assertEqual([call.args[0] for call in factory.return_value.write.call_args_list],
                             [b"4700\n", b"MOTOR_ADJUST\n", b"NONE\n"])
            link.close()

    def test_wrong_baud_rejected_before_open(self):
        with patch("serial.Serial") as factory:
            with self.assertRaises(ValueError):
                ArduinoSerial("DUMMY_PORT", 115200)
            factory.assert_not_called()


class RoutingRegression(unittest.TestCase):
    def test_all_26_entries_match_routing_baseline(self):
        baseline = json.loads((ROOT / "tests/baselines/routing_table.json").read_text())
        expected = {r["command"]: {"layer": r["layer"], "angle_deg": r["angle_deg"]}
                    for r in baseline["entries"]}
        self.assertEqual(load_routes(), expected)
        self.assertEqual(len(expected), 26)
        self.assertEqual(len({(r["layer"], r["angle_deg"]) for r in expected.values()}), 26)

    def test_unknown_mapping(self):
        for command in ("NONE", "12345"):
            with self.subTest(command=command):
                route = classify_command(command)
                self.assertFalse(route["routing_eligible"])
                self.assertEqual((route["layer"], route["angle_deg"]), (1, 324))


class UploadParsingRegression(unittest.TestCase):
    def test_binary_payload_preserved_without_service(self):
        jpeg = (ROOT / "assets/sample_resistors/resistor_01.jpg").read_bytes()
        body = (b'--ESP32CAM\r\nContent-Disposition: form-data; name="image"; filename="photo.jpg"\r\n'
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n--ESP32CAM--\r\n")
        self.assertIn(b"\x00", jpeg)
        self.assertEqual(extract_image_part("multipart/form-data; boundary=ESP32CAM", body), jpeg)

    def test_missing_part(self):
        self.assertIsNone(extract_image_part("text/plain", b"not multipart"))


class OfflineCLIRegression(unittest.TestCase):
    def test_documented_mock_command(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", str(ROOT / "src/vision/main.py"), "--mock",
                 "--output-dir", directory],
                cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("[MOCK] Done:", result.stdout)
            self.assertNotIn("[SERIAL TX]", result.stdout)
            with (Path(directory) / "summary.csv").open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 9)
            self.assertEqual([r["command_sent"] for r in rows[:8]],
                             ["12", "300", "510", "560", "750", "4700", "5600", "75000"])
            self.assertEqual(rows[-1]["command_sent"], "NONE")
            self.assertEqual(rows[-1]["frames_used"], "2")
            self.assertEqual(len(list(Path(directory).glob("*.png"))), 9)



# Capture delivery, configuration validation, and input-failure isolation tests.
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from http.client import HTTPConnection

import main as vision_main
from capture_queue import CaptureQueue, QueueFullError
from configuration import validate_settings
from detector import DetectorParams, HsvRange
from image_io import ImageInputError
from live_capture import LegacyFileIngress, process_next_capture
from upload_server import create_server, make_handler


class InputFailureReliability(unittest.TestCase):
    def setUp(self):
        self.detector = ResistorDetector(HsvThresholds.from_json(ROOT / "config/hsv_thresholds.json"))
        self.valid = (ROOT / "assets/sample_resistors/resistor_01.jpg").read_bytes()

    def test_empty_corrupt_and_truncated_files_return_flagged_none(self):
        payloads = [b"", b"not an image", b"\xff\xd8broken",
                    self.valid[:-40], b"\xff\xd8garbage\xff\xd9"]
        with tempfile.TemporaryDirectory() as directory:
            for index, payload in enumerate(payloads):
                with self.subTest(case=index):
                    path = Path(directory) / f"capture_{index}.jpg"
                    path.write_bytes(payload)
                    result = self.detector.detect_file(path)
                    self.assertEqual(result.command, "NONE")
                    self.assertFalse(result.input_ok)
                    self.assertTrue(result.input_error)

    def test_opencv_decode_error_is_contained(self):
        with patch("image_io.cv2.imdecode", side_effect=cv2.error("decode failure")):
            result = self.detector.detect_bytes(self.valid)
        self.assertEqual(result.command, "NONE")
        self.assertFalse(result.input_ok)

    def test_invalid_array_is_input_failure_but_blank_photo_is_recognition_failure(self):
        for invalid in (None, np.empty((0, 0, 3), np.uint8), np.zeros((20, 20), np.uint8),
                        np.zeros((20, 20, 3), np.float32)):
            with self.subTest(shape=getattr(invalid, "shape", None)):
                self.assertFalse(self.detector.detect(invalid).input_ok)
        result = self.detector.detect(np.zeros((600, 800, 3), np.uint8))
        self.assertTrue(result.input_ok)
        self.assertEqual(result.command, "NONE")

    def test_corrupt_spool_cannot_trigger_or_advance_retry(self):
        for already_waiting in (False, True):
            with self.subTest(already_waiting=already_waiting), tempfile.TemporaryDirectory() as directory:
                queue = CaptureQueue(Path(directory) / "queue")
                try:
                    queued = queue.publish(self.valid)
                    queued.path.write_bytes(b"")
                    link = MockSerial()
                    session = SortingSession(link, sleep=lambda _: None)
                    with contextlib.redirect_stdout(io.StringIO()):
                        if already_waiting:
                            session.on_recognition("NONE")
                        before = list(link.sent)
                        process_next_capture(queue, self.detector, session, 0)
                    self.assertEqual(link.sent, before)
                    self.assertEqual(session.awaiting_retry, already_waiting)
                    self.assertEqual(queue.pending_count, 0)
                finally:
                    queue.close()

    def test_decode_failure_after_admission_never_dispatches_none(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = CaptureQueue(Path(directory))
            try:
                queue.publish(self.valid)
                link = MockSerial()
                session = SortingSession(link, sleep=lambda _: None)
                with patch.object(self.detector, "detect_bytes",
                                  return_value=self.detector.input_failure("injected decode error")):
                    with contextlib.redirect_stdout(io.StringIO()):
                        process_next_capture(queue, self.detector, session, 0)
                self.assertEqual(link.sent, [])
                self.assertFalse(session.awaiting_retry)
            finally:
                queue.close()

    def test_mock_invalid_capture_has_no_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            inputs = base / "inputs"
            inputs.mkdir()
            (inputs / "broken.jpg").write_bytes(b"")
            result = subprocess.run(
                [sys.executable, "-X", "utf8", "-B", str(ROOT / "src/vision/main.py"),
                 "--mock", "--input-dir", str(inputs), "--output-dir", str(base / "output")],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("input failure", result.stdout)
            self.assertNotIn("[MOCK SERIAL TX]", result.stdout)


class ConfigurationReliability(unittest.TestCase):
    def test_hsv_dimensions_types_channel_limits_and_order(self):
        invalid = [
            ((0, 0), (179, 255, 255)), ((0, 0, 0), (180, 255, 255)),
            ((0, -1, 0), (179, 255, 255)), ((0, 0, 0), (179, 256, 255)),
            ((20, 0, 0), (10, 255, 255)), ((True, 0, 0), (179, 255, 255)),
            ((0.0, 0, 0), (179, 255, 255)), (("0", 0, 0), (179, 255, 255)),
        ]
        for lower, upper in invalid:
            with self.subTest(lower=lower, upper=upper), self.assertRaises(ValueError):
                HsvRange(lower, upper)

    def test_even_morphology_kernel_remains_supported(self):
        params = DetectorParams.from_settings({"morphology": {"final_erode": 4, "band_erode": 2}})
        detector = ResistorDetector(HsvThresholds.from_json(ROOT / "config/hsv_thresholds.json"), params)
        self.assertEqual(detector._k_final_erode.shape, (4, 4))
        self.assertEqual(detector._k_erode.shape, (2, 2))

    def test_invalid_numeric_parameters_are_rejected(self):
        for value in (0, -1, float("nan"), float("inf"), True, "0.5"):
            with self.subTest(scale=value), self.assertRaises(ValueError):
                DetectorParams.from_settings({"resize_factor": value})
        for value in (0, -1, 2.5, True, "3"):
            with self.subTest(kernel=value), self.assertRaises(ValueError):
                DetectorParams.from_settings({"morphology": {"final_erode": value}})
        for value in (-1, float("nan"), float("inf"), False, "100"):
            with self.subTest(filter=value), self.assertRaises(ValueError):
                DetectorParams.from_settings({"filters": {"band_min_area": value}})

    def test_load_settings_rejects_invalid_root_and_hsv_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            settings = base / "settings.yaml"
            settings.write_text("[]\n")
            with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
                vision_main.load_settings(str(settings))
            hsv = base / "hsv.json"
            raw = json.loads((ROOT / "config/hsv_thresholds.json").read_text())
            raw["body"]["lower"] = [180, 0, 0]
            hsv.write_text(json.dumps(raw))
            settings.write_text("vision:\n  hsv_thresholds: " + hsv.as_posix() + "\n")
            with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
                vision_main.load_settings(str(settings))

    def test_invalid_settings_fail_before_hardware(self):
        for settings in ({"serial": {"baudrate": 115200}},
                         {"capture": {"queue_capacity": 0}},
                         {"capture": {"resume_pending": "yes"}},
                         {"retry": {"adjust_wait_s": float("nan")}}):
            with self.subTest(settings=settings), patch.object(vision_main, "ArduinoSerial") as serial:
                with self.assertRaises(ValueError):
                    vision_main.run_live(settings, False, None)
                serial.assert_not_called()


class CaptureQueueReliability(unittest.TestCase):
    def setUp(self):
        self.valid = (ROOT / "assets/sample_resistors/resistor_01.jpg").read_bytes()

    def test_identical_images_are_distinct_fifo_events(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = CaptureQueue(Path(directory))
            try:
                first = queue.publish(self.valid)
                second = queue.publish(self.valid)
                self.assertNotEqual(first.capture_id, second.capture_id)
                self.assertEqual(first.sha256, second.sha256)
                a = queue.take(0)
                b = queue.take(0)
                self.assertEqual([a.capture_id, b.capture_id], [first.capture_id, second.capture_id])
                queue.finish(a)
                queue.finish(b)
                self.assertEqual(queue.pending_count, 0)
            finally:
                queue.close()

    def test_capacity_includes_processing_and_rejection_preserves_event(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = CaptureQueue(Path(directory), 1)
            try:
                queue.publish(self.valid)
                active = queue.take(0)
                with self.assertRaises(QueueFullError):
                    queue.publish(self.valid)
                self.assertEqual(queue.pending_count, 1)
                self.assertTrue(active.path.exists())
                self.assertFalse(list(Path(directory).glob("*.part")))
                queue.finish(active)
                queue.publish(self.valid)
            finally:
                queue.close()

    def test_invalid_admission_creates_no_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = CaptureQueue(Path(directory))
            try:
                with self.assertRaises(ImageInputError):
                    queue.publish(b"\xff\xd8bad")
                self.assertEqual(queue.pending_count, 0)
                self.assertEqual(list(Path(directory).glob("*.jpg")), [])
            finally:
                queue.close()

    def test_pending_survives_and_processing_is_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            queue = CaptureQueue(base)
            first = queue.publish(self.valid)
            second = queue.publish(self.valid)
            queue.take(0)
            queue.close()
            recovered = CaptureQueue(base)
            try:
                self.assertEqual(recovered.recovered_count, 1)
                self.assertEqual(len(recovered.quarantined), 1)
                event = recovered.take(0)
                self.assertEqual(event.capture_id, second.capture_id)
                self.assertNotEqual(event.capture_id, first.capture_id)
                recovered.finish(event)
            finally:
                recovered.close()
            again = CaptureQueue(base)
            try:
                self.assertEqual(len(again.quarantined), 1)
            finally:
                again.close()

    def test_spool_has_single_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = CaptureQueue(Path(directory))
            try:
                with self.assertRaises(RuntimeError):
                    CaptureQueue(Path(directory))
                self.assertTrue((Path(directory) / ".owner").exists())
            finally:
                queue.close()

    def test_startup_pending_requires_review_before_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = CaptureQueue(Path(directory))
            queue.publish(self.valid)
            queue.close()
            settings = {"capture": {"queue_dir": directory}}
            with patch.object(vision_main, "ArduinoSerial") as serial:
                with self.assertRaisesRegex(RuntimeError, "Pending captures recovered"):
                    vision_main.run_live(settings, False, None)
                serial.assert_not_called()


class LocalUploadReliability(unittest.TestCase):
    """Real HTTP tests bind only to 127.0.0.1 and an ephemeral port."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.queue = CaptureQueue(self.base / "queue", capacity=8)
        self.server = create_server("127.0.0.1", 0, self.base / "preview.jpg",
                                    max_bytes=100000, captures=self.queue)
        self.thread = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.jpeg = (ROOT / "assets/sample_resistors/resistor_01.jpg").read_bytes()
        self.detector = ResistorDetector(HsvThresholds.from_json(ROOT / "config/hsv_thresholds.json"))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.queue.close()
        self.directory.cleanup()

    def request(self, body, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request("POST", "/upload/upload.php", body=body, headers=headers or {})
            response = connection.getresponse()
            data = response.read()
            return response.status, response.getheader("X-Capture-ID"), data
        finally:
            connection.close()

    def post(self, image, field="image"):
        body = (f'--ESP32CAM\r\nContent-Disposition: form-data; name="{field}"; filename="photo.jpg"\r\n'
                "Content-Type: image/jpeg\r\n\r\n").encode() + image + b"\r\n--ESP32CAM--\r\n"
        return self.request(body, {"Content-Type": "multipart/form-data; boundary=ESP32CAM"})

    def test_concurrent_identical_and_distinct_uploads_keep_every_event(self):
        other = (ROOT / "assets/sample_resistors/resistor_02.jpg").read_bytes()
        payloads = [self.jpeg, self.jpeg, other, self.jpeg, other, self.jpeg]
        with ThreadPoolExecutor(max_workers=6) as pool:
            replies = list(pool.map(self.post, payloads))
        self.assertTrue(all(reply[0] == 200 for reply in replies))
        ids = [reply[1] for reply in replies]
        self.assertEqual(len(set(ids)), 6)
        self.assertEqual(self.queue.pending_count, 6)
        events = [self.queue.take(0) for _ in replies]
        self.assertEqual([event.capture_id for event in events], sorted(ids))
        expected = sorted(hashlib.sha256(payload).hexdigest() for payload in payloads)
        self.assertEqual(sorted(event.sha256 for event in events), expected)
        for event in events:
            self.assertEqual(hashlib.sha256(event.path.read_bytes()).hexdigest(), event.sha256)
            self.queue.finish(event)
        self.assertEqual(list((self.base / "queue").glob("*.part")), [])
        self.assertEqual(list(self.base.glob("*.part")), [])

    def test_invalid_images_missing_parts_and_malformed_multipart_are_400(self):
        ok, png = cv2.imencode(".png", np.zeros((20, 20, 3), np.uint8))
        self.assertTrue(ok)
        for payload in (b"", b"garbage", b"\xff\xd8bad", self.jpeg[:-50], png.tobytes()):
            with self.subTest(bytes=len(payload)):
                self.assertEqual(self.post(payload)[0], 400)
        self.assertEqual(self.post(self.jpeg, field="wrong")[0], 400)
        self.assertEqual(self.request(b"--broken", {"Content-Type": "multipart/form-data; boundary=missing"})[0], 400)
        self.assertEqual(self.queue.pending_count, 0)
        self.assertFalse((self.base / "preview.jpg").exists())

    def test_oversized_actual_upload_is_rejected(self):
        self.assertEqual(self.post(self.jpeg + b"x" * 100001)[0], 413)
        self.assertEqual(self.queue.pending_count, 0)

    def test_bad_length_and_oversized_body_have_explicit_rejection(self):
        for length in ("bad", "-1", "0"):
            with self.subTest(length=length):
                self.assertEqual(self.request(b"", {"Content-Length": length})[0], 400)
        self.assertEqual(self.request(b"", {"Content-Length": "100001"})[0], 413)
        self.assertEqual(self.queue.pending_count, 0)

    def test_incomplete_body_and_duplicate_headers_without_a_socket(self):
        handler_type = make_handler(self.base / "fake.jpg", "/upload/upload.php", 100000, self.queue)
        for lengths, body in ((["20"], b"short"), (["1", "1"], b"x")):
            handler = object.__new__(handler_type)
            handler.path = "/upload/upload.php"
            handler.headers = Message()
            for value in lengths:
                handler.headers["Content-Length"] = value
            handler.rfile = io.BytesIO(body)
            replies = []
            handler._reply = lambda status, text, capture_id=None: replies.append(status)
            handler.do_POST()
            self.assertEqual(replies, [400])
        self.assertEqual(self.queue.pending_count, 0)

    def test_queue_full_is_503_without_overwriting_prior_uploads(self):
        accepted = [self.post(self.jpeg) for _ in range(8)]
        self.assertTrue(all(reply[0] == 200 for reply in accepted))
        self.assertEqual(self.post(self.jpeg)[0], 503)
        self.assertEqual(self.queue.pending_count, 8)
        self.assertEqual(len(list((self.base / "queue").glob("*.jpg"))), 8)

    def test_capture_arriving_during_recognition_is_processed_next(self):
        self.assertEqual(self.post(self.jpeg)[0], 200)
        entered, release = threading.Event(), threading.Event()
        calls = []
        original = self.detector.detect_bytes
        errors = []

        def slow_decode(data):
            calls.append(True)
            result = original(data)
            if len(calls) == 1:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("Test release not signaled")
            return result

        link = MockSerial()
        session = SortingSession(link, sleep=lambda _: None)

        def worker():
            try:
                process_next_capture(self.queue, self.detector, session, 0)
            except BaseException as exc:
                errors.append(exc)

        with patch.object(self.detector, "detect_bytes", side_effect=slow_decode):
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                # Identical pixels must still be a new event.
                self.assertEqual(self.post(self.jpeg)[0], 200)
                self.assertEqual(self.queue.pending_count, 2)
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            process_next_capture(self.queue, self.detector, session, 0)
        self.assertEqual(link.sent, ["12", "12"])
        self.assertEqual(self.queue.pending_count, 0)

    def test_capture_arriving_during_motor_adjust_is_not_skipped(self):
        frame = make_synthetic_resistor(("orange",), -8.0)
        ok, buffer = cv2.imencode(".jpg", frame)
        self.assertTrue(ok)
        incomplete = buffer.tobytes()
        self.assertEqual(self.detector.detect_bytes(incomplete).command, "NONE")
        self.assertEqual(self.post(incomplete)[0], 200)
        entered, release = threading.Event(), threading.Event()
        errors = []

        def wait_for_adjust(_):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("Test release not signaled")

        link = MockSerial()
        session = SortingSession(link, sleep=wait_for_adjust)

        def worker():
            try:
                process_next_capture(self.queue, self.detector, session, 0)
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertTrue(session.awaiting_retry)
            self.assertEqual(self.post(b"\xff\xd8invalid")[0], 400)
            self.assertTrue(session.awaiting_retry)
            self.assertEqual(self.post(self.jpeg)[0], 200)
            self.assertEqual(self.queue.pending_count, 2)
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        process_next_capture(self.queue, self.detector, session, 0)
        self.assertEqual(link.sent, ["MOTOR_ADJUST", "12"])
        self.assertFalse(session.awaiting_retry)

    def test_actual_live_loop_consumes_queue_with_mocked_hardware(self):
        self.post(self.jpeg)
        self.post(self.jpeg)
        link = MockSerial()
        count = []
        real_consumer = process_next_capture

        def consume_then_stop(captures, detector, session):
            result = real_consumer(captures, detector, session, 0)
            count.append(result)
            if len(count) == 2:
                raise KeyboardInterrupt
            return result

        with patch.object(vision_main, "ArduinoSerial", return_value=link), \
                patch.object(vision_main, "CaptureQueue", return_value=self.queue), \
                patch.object(vision_main, "LegacyFileIngress"), \
                patch.object(vision_main, "process_next_capture", side_effect=consume_then_stop):
            self.assertEqual(vision_main.run_live({}, False, None), 0)
        self.assertEqual(link.sent, ["12", "12"])
        self.assertEqual(count, [True, True])


class LegacyIngressReliability(unittest.TestCase):
    def test_observed_identical_file_replacements_are_separate_events(self):
        import os

        jpeg = (ROOT / "assets/sample_resistors/resistor_01.jpg").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            path = base / "latest.jpg"
            path.write_bytes(jpeg)
            queue = CaptureQueue(base / "queue")
            try:
                ingress = LegacyFileIngress(path, queue)
                for _ in range(2):
                    previous = path.stat().st_mtime_ns
                    path.write_bytes(jpeg)
                    os.utime(path, ns=(previous + 1000000, previous + 1000000))
                    ingress.poll_once()
                self.assertEqual(queue.pending_count, 2)
            finally:
                queue.close()



class AdditionalInputBoundaries(unittest.TestCase):
    def test_unusable_finite_scaling_fails_before_opencv_allocation(self):
        thresholds = HsvThresholds.from_json(ROOT / "config/hsv_thresholds.json")
        frame = np.zeros((20, 20, 3), np.uint8)
        for scale in (1e308, 1e-10, 1e6):
            with self.subTest(scale=scale):
                detector = ResistorDetector(thresholds, DetectorParams(resize_factor=scale))
                result = detector.detect(frame)
                self.assertFalse(result.input_ok)
                self.assertEqual(result.command, "NONE")

    def test_pixel_limit_rejects_before_queue_admission(self):
        jpeg = (ROOT / "assets/sample_resistors/resistor_01.jpg").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            queue = CaptureQueue(Path(directory), max_pixels=100)
            try:
                with self.assertRaises(ImageInputError):
                    queue.publish(jpeg)
                self.assertEqual(queue.pending_count, 0)
            finally:
                queue.close()

    def test_corrupt_png_crc_is_flagged_input_failure(self):
        ok, encoded = cv2.imencode(".png", np.zeros((20, 20, 3), np.uint8))
        self.assertTrue(ok)
        data = bytearray(encoded.tobytes())
        data[29] ^= 1
        detector = ResistorDetector(HsvThresholds.from_json(ROOT / "config/hsv_thresholds.json"))
        result = detector.detect_bytes(bytes(data))
        self.assertEqual(result.command, "NONE")
        self.assertFalse(result.input_ok)

    def test_uncertain_capture_blocks_live_before_serial(self):
        jpeg = (ROOT / "assets/sample_resistors/resistor_01.jpg").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            queue = CaptureQueue(Path(directory))
            queue.publish(jpeg)
            queue.take(0)
            queue.close()
            settings = {"capture": {"queue_dir": directory, "resume_pending": True}}
            with patch.object(vision_main, "ArduinoSerial") as serial:
                with self.assertRaisesRegex(RuntimeError, "Uncertain in-flight"):
                    vision_main.run_live(settings, False, None)
                serial.assert_not_called()
            self.assertEqual(len(list(Path(directory).glob("*.uncertain"))), 1)


if __name__ == "__main__":
    unittest.main()
