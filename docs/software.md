# Software and configuration

## Entry points

| File | Interface | Role |
| --- | --- | --- |
| [Vision CLI](../src/vision/main.py) | --mock or --live | Offline recognition or queued live consumption and serial dispatch |
| [Upload receiver](../src/vision/upload_server.py) | Standalone CLI; optional live integration | HTTP upload receiver for the ESP32-CAM |
| [HSV utility](../tools/hsv_calibrator.py) | Interactive GUI or --self-test | Threshold inspection and optional saving |
| [Routing report](../tools/routing.py) | Existing summary CSV | Read-only routing eligibility report |
| [Historical capture verifier](../tools/verify_private_regression.py) | Optional; requires the capstone capture set | Compare current predictions with the original capstone function and recorded results |

## Python dependencies

`requirements.txt` preserves dependency lower bounds; `requirements-lock.txt` records tested direct versions: opencv-python 4.9.0.80, NumPy 1.26.4, pyserial 3.5, PyYAML 6.0.1, and Pillow 12.2.0. A fresh Windows Python 3.11.4 virtual environment passed `pip check`, module imports, offline commands, and all 47 automated tests.

## Configuration

The CLI loads --config when supplied. Otherwise config/settings.yaml takes precedence over config/settings.example.yaml. YAML is parsed with safe_load.

| Section | Meaning |
| --- | --- |
| serial | Port, fixed 9600 baud, read timeout |
| capture | Queue directory/capacity, reviewed resume, legacy preview and polling interval |
| upload_server | Bind host, port, endpoint, request byte and pixel limits |
| vision | Resize factor, threshold JSON, morphology sizes, contour filters |
| retry | Sleep after first failed recognition |
| mock | Input/output directories and shorter simulated adjustment wait |

Paths read from settings resolve against the repository root. Explicit --config, --input-dir, and --output-dir arguments use the process working directory. Start commands from the repository root to avoid ambiguity.

Gray and white HSV thresholds may require recalibration under different lighting conditions using `tools/hsv_calibrator.py`.

## Offline execution

Follow [README setup](../README.md#quick-start). The default sample photographs are processed directly inside the configured input directory; traversal is not recursive. A missing/empty usable-image list triggers generation of four synthetic input drawings under output/mock_inputs.

Results are annotated PNG files and a CSV with `image`, `bands_read`, `bands_found`, `command_sent`, and `frames_used` fields. The routing report checks whether decoded resistance commands map to one of the 26 configured sorting destinations.

Invalid inputs are marked with `input_error` and skipped without dispatch. Missing local paths raise `ValueError`. Individual recognition outcomes are recorded in the output CSV.

## Synthetic examples and calibration

The synthetic generator draws resistor images using selected HSV colors. Mock mode reuses the same image to exercise retry-state transitions.

The HSV self-test renders eleven target previews in memory. The interactive calibration tool can save adjusted thresholds to `config/hsv_thresholds.json`.

## Input and settings checks

HSV bounds require three integer channels, H in 0..179 and S/V in 0..255,
with lower <= upper. Scale must be positive and finite. Morphology dimensions
must be positive integers; even kernels remain supported. Contour thresholds
must be finite nonnegative numbers. Invalid setting types are rejected rather
than silently converted.

Capture settings add queue_dir, queue_capacity and resume_pending. The last
defaults to false so old pending work is reviewed before serial opens.
upload_server.max_pixels bounds image dimensions. The example queue capacity
is 32, multipart limit 5 MiB, and image limit 16 million pixels.

A valid-image NONE is recognition failure. Invalid encoded data yields NONE
with input_error and must never be passed to SortingSession. The CLI
and live consumer enforce that separation.

## Live mode and hardware integration

Importing the vision modules does not open serial connections or start HTTP listeners. The `--live` execution path initializes serial communication; the HTTP receiver can run as a standalone service or through integrated `--live --serve-upload` mode. Integrated upload mode processes distinct capture events through a bounded queue, while legacy file polling remains available as a best-effort option.

Automated tests use mocked serial communication and HTTP listeners bound to `127.0.0.1`. Firmware uses Arduino Stepper and AVR/ESP32 cores. All three sketches compiled with portable Arduino CLI 1.6.0, AVR core 1.8.6, ESP32 core 3.0.2, and Stepper 1.1.3. The camera's HTTP success predicate was updated to accept 2xx responses; camera pin assignments, timing, button behavior, and multipart format were preserved.

See [build targets and commands](reproduction.md), [capture delivery and recovery](capture_delivery.md), and [validation](validation.md).
