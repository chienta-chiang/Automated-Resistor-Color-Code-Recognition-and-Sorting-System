# Validation and regression results

## Verification summary

**Verified environment:** Windows, CPython 3.11.4. Verification covers offline recognition, automated unit and integration tests, routing baseline consistency, and compilation of the three Arduino/ESP32 firmware sketches.

| Check | Result |
| --- | --- |
| Python environment | Fresh isolated installation, `pip check`, module imports, and CLI checks passed |
| Automated tests | **47 passed:** 16 recognition/dispatch regression tests and 31 reliability tests covering recognition, serial dispatch, routing, HTTP upload validation, and capture-queue recovery |
| Sample image baseline | All eight image hashes, predicted commands, colors, band counts, reading directions, and route eligibility match `tests/baselines/approved_samples.json` |
| Historical capture regression | 117 capstone captures compared (60 numeric predictions, 57 `NONE`); 5 command differences from the original single-file detector (`read_resistance_value()`) |
| Routing table | All 26 firmware routes (resistance value, layer, angle) match `tests/baselines/routing_table.json`; pin mappings, speeds, step conversion, and motion sequences are not part of this automated comparison |
| Offline demonstration | Eight sample predictions and one synthetic retry scenario; nine annotated PNG files and `summary.csv` generated |
| Routing and HSV utilities | Routing report generated; HSV self-test rendered eleven targets in memory |
| Firmware compilation | Three sketches compiled for Arduino Mega 2560 and ESP32-CAM targets (compiler warnings are recorded in the [reproduction guide](reproduction.md)) |

The tested Python dependencies and firmware toolchain are listed in the [reproduction guide](reproduction.md).

## Sample baseline and routing coverage

The **eight sample images** (`assets/sample_resistors/`) and **117 capstone captures** are regression baselines: they lock in the detector's outputs so that refactoring cannot change recognition behavior unnoticed. Across the 117 captures, the modular detector produced **60 numeric predictions** (33 matching one of the 26 configured sorting routes and 27 outside the routing table) and **57 `NONE` results**, with **5 command differences** relative to the original single-file `read_resistance_value()` function.

During the capstone, the team tested recognition on **roughly 100 resistor types** collected from other laboratory courses and recognized about **80%** correctly with a single fixed HSV configuration (team estimate; per-trial records were not retained). Some resistors failed because of reflective surfaces or hard-to-separate band colors; in the team's tuning, thresholds adjusted for them made many other resistors fail, so one configuration was kept for the broader test set. Because the storage tower holds only 26 configured values, the sorting demonstration used selected resistors from the reliably recognized set, sorted into their assigned compartments, plus recognized values outside the storage configuration to show routing to the unknown bin. No per-compartment demonstration record was kept, so this does not claim that all 26 destinations were exercised.

The eight sample predicted commands are `12`, `300`, `510`, `560`, `750`, `4700`, `5600`, and `75000`. Sample 5 produces five band candidates; the decoder selects the first three colors in reading order and outputs `750`. A numeric prediction and eligibility for one of the 26 configured routes are tracked separately.

Regression references: [sample baseline](../tests/baselines/approved_samples.json) and [firmware routing baseline](../tests/baselines/routing_table.json).

## Reliability regression coverage

The [47-test suite](../tests/test_regression.py) covers core recognition/dispatch behavior and capture-delivery reliability:

| Scenario | Verified behavior |
| --- | --- |
| Empty or corrupt image | Returns `NONE` with `input_error`; invalid input never dispatches or advances retry state |
| Malformed multipart or damaged JPEG | Framing, structure/load, and OpenCV validation reject invalid uploads with HTTP 400 |
| Concurrent identical uploads | Independent capture IDs preserve distinct accepted events in bounded FIFO admission order |
| Arrival during recognition or `MOTOR_ADJUST` | Immutable queued events are processed sequentially without dropping overlapping uploads |
| Concurrent upload temporary files | Independent temporary writes and atomic publication prevent collisions |
| Invalid HSV bounds or processing settings | Channel, dimension, type, order, finite-scale, and positive-kernel checks reject invalid config |
| Camera HTTP confirmation | ESP32-CAM firmware accepts `200..299` responses as upload success |

Additional checks exercise truncated JPEGs, PNG CRC damage, `cv2.error` containment, oversized uploads, pixel/resize limits, even morphology kernels, queue saturation (HTTP 503), spool ownership, shutdown recovery, and uncertain in-flight work. Tests use mocked serial transport and ephemeral HTTP listeners bound to `127.0.0.1`.

For the valid-image retry and input-failure state machine, see [Software](software.md) and [Architecture](architecture.md). For event delivery and recovery, see [Capture delivery](capture_delivery.md).

## Optional historical capture comparison

The repository also includes [verify_private_regression.py](../tools/verify_private_regression.py) for comparing the modular detector and routing table against the original capstone code and the 117-capture set (`--source-root` and `--baseline`; the capture set is not distributed with this repository), extracting only `read_resistance_value()` via AST without executing module-level serial or file-watching code.

## Reproduce the checks

From the repository root, using the [offline Python setup](../README.md#quick-start):

```powershell
python -X utf8 -B -m unittest discover -s tests -v
python -X utf8 -B -m pip check
python -X utf8 -B src/vision/main.py --mock
python -X utf8 -B tools/routing.py output/mock_results/summary.csv
python -X utf8 -B tools/hsv_calibrator.py --self-test
```

All three firmware sketches compiled using **Arduino CLI 1.6.0**, with the recorded AVR and ESP32 targets. See [Arduino toolchain](reproduction.md#arduino-toolchain) for platform versions, build instructions, and compiler warnings. Further design boundaries are documented in [Limitations](limitations.md).
