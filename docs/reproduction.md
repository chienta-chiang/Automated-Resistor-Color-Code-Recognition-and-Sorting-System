# Reproduction and build guide

**Verified environment (2026-11-13):** Windows, CPython 3.11.4. The recorded verification covers the offline Python workflow, automated tests, and compilation of three firmware sketches for Arduino Mega and ESP32-CAM targets.

## Python environment

Run these commands in PowerShell from the repository root. Python 3.11.4 must be installed and available via the Windows Python launcher (`py -3.11`).

| Package | Tested version |
| --- | --- |
| CPython | 3.11.4 |
| opencv-python | 4.9.0.80 |
| NumPy | 1.26.4 |
| pyserial | 3.5 |
| PyYAML | 6.0.1 |
| Pillow | 12.2.0 |

`requirements-lock.txt` records the tested direct-dependency versions.

```powershell
py -3.11 -m venv .venv
$Py = Join-Path (Resolve-Path .venv).Path 'Scripts\python.exe'
& $Py -X utf8 -m pip install -r requirements-lock.txt
& $Py -X utf8 -B -m pip check
& $Py -X utf8 -B -m unittest discover -s tests -v
& $Py -X utf8 -B src/vision/main.py --mock
& $Py -X utf8 -B tools/routing.py output/mock_results/summary.csv
& $Py -X utf8 -B tools/hsv_calibrator.py --self-test
```

The offline demo processes the eight sample captures and a synthetic retry example, creating annotated images and `output/mock_results/summary.csv`. The automated suite runs with mocked serial communication and local HTTP listeners. In the recorded environment, **all 47 tests and the listed offline checks passed**. See [Validation](validation.md) for the test inventory and recorded predictions.

### Optional historical capture regression

The 117 capstone captures used for this comparison are not distributed with the repository. With a local copy of the capture set and its baseline, run:

```powershell
& $Py -X utf8 -B tools/verify_private_regression.py --source-root "C:\path\to\capstone-captures" --baseline "C:\path\to\capture-baseline.json"
```

The comparison covers **117 capstone captures**.

## Arduino toolchain

| Component | Recorded version / target |
| --- | --- |
| Arduino CLI | 1.6.0 (commit `50a0e80da`) |
| AVR core | `arduino:avr` 1.8.6 |
| AVR compiler | GCC 7.3.0 (`7.3.0-atmel3.6.1-arduino7`) |
| Stepper library | 1.1.3 |
| Sorter and manual control target | `arduino:avr:mega:cpu=atmega2560` |
| ESP32 core | `esp32:esp32` 3.0.2 |
| ESP32 compiler | crosstool-NG `esp-12.2.0_20230208`, GCC 12.2.0; esp-x32 2302 |
| ESP32 SDK bundle | `idf-release_v5.1-bd2b9390ef` |
| Camera target | `esp32:esp32:esp32cam` (core defaults) |
| Core-bundled libraries | WiFi 2.0.0; Networking 1.0.0; HTTPClient 2.0.0; NetworkClientSecure 2.0.0 |

### Firmware setup and compilation

The commands below provide a reproducible setup example on Windows. Download the portable **Arduino CLI 1.6.0** executable from the [official release](https://github.com/arduino/arduino-cli/releases/tag/v1.6.0) and place `arduino-cli.exe` in `C:\dev\arduino-cli\`. Run from the repository root.

```powershell
# Set up portable paths; create an independent build workspace.
$Cli = 'C:\dev\arduino-cli\arduino-cli.exe'
$Workspace = 'C:\dev\resistor-build'
$CliConfig = Join-Path $Workspace 'arduino-cli.yaml'
$Scratch = Join-Path $Workspace 'sketches'
$BuildRoot = Join-Path $Workspace 'build'
New-Item -ItemType Directory -Force $Workspace, $Scratch, $BuildRoot | Out-Null

# Initialize a dedicated Arduino CLI configuration.
& $Cli config init --dest-file $CliConfig
& $Cli --config-file $CliConfig config set directories.data (Join-Path $Workspace 'data')
& $Cli --config-file $CliConfig config set directories.downloads (Join-Path $Workspace 'downloads')
& $Cli --config-file $CliConfig config set directories.user (Join-Path $Workspace 'user')
& $Cli --config-file $CliConfig config set board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json

# Install the recorded platform and library versions.
& $Cli --config-file $CliConfig core update-index
& $Cli --config-file $CliConfig core install arduino:avr@1.8.6
& $Cli --config-file $CliConfig core install esp32:esp32@3.0.2
& $Cli --config-file $CliConfig lib install Stepper@1.1.3

# Copy sketches into short ASCII-only build paths.
Copy-Item src/firmware/resistor_sorter (Join-Path $Scratch 'resistor_sorter') -Recurse
Copy-Item src/firmware/motor_control (Join-Path $Scratch 'motor_control') -Recurse
Copy-Item src/firmware/esp32_cam (Join-Path $Scratch 'esp32_cam') -Recurse
Copy-Item (Join-Path $Scratch 'esp32_cam\arduino_secrets.h.example') (Join-Path $Scratch 'esp32_cam\arduino_secrets.h')

# Compile all three sketches.
& $Cli --config-file $CliConfig compile --fqbn arduino:avr:mega:cpu=atmega2560 --build-path (Join-Path $BuildRoot 'resistor_sorter') --warnings all (Join-Path $Scratch 'resistor_sorter')
& $Cli --config-file $CliConfig compile --fqbn arduino:avr:mega:cpu=atmega2560 --build-path (Join-Path $BuildRoot 'motor_control') --warnings all (Join-Path $Scratch 'motor_control')
& $Cli --config-file $CliConfig compile --fqbn esp32:esp32:esp32cam --build-path (Join-Path $BuildRoot 'esp32_cam') --warnings all (Join-Path $Scratch 'esp32_cam')
```

The example `arduino_secrets.h` contains placeholder Wi-Fi and server settings, sufficient for compilation; configure actual connection details separately when deploying hardware.

## Windows build notes

**Path compatibility:** Use short ASCII-only paths without braces (`{}`) for the ESP32 SDK, compiler, sketch, and build-output directories. The recorded Windows build encountered an ELF linker failure with a non-ASCII path and Arduino CLI placeholder-expansion issues with a brace-containing path. Moving the build to ordinary ASCII paths resolved those issues.

**Recorded compilation results:** All three sketches compiled successfully. The warning inventory is:

| Source | Recorded warning |
| --- | --- |
| AVR core 1.8.6 | Four unused `nothrow` parameter warnings per AVR build |
| ESP32-CAM sketch | Three omitted `camera_config_t` member initializers: `fb_location`, `grab_mode`, `sccb_i2c_port` |

**Recorded memory usage (Arduino Mega 2560 builds):**

| Sketch | Program storage (flash) | Global variables (SRAM) |
| --- | --- | --- |
| `resistor_sorter` | 7,142 of 253,952 bytes (2%) | 596 of 8,192 bytes (7%) |
| `motor_control` | 6,976 of 253,952 bytes (2%) | 578 of 8,192 bytes (7%) |

## References

- [Official Arduino CLI installation](https://github.com/arduino/arduino-cli/blob/master/docs/installation.md)
- [Arduino CLI 1.6.0 release](https://github.com/arduino/arduino-cli/releases/tag/v1.6.0)
- [Arduino sketch build process](https://github.com/arduino/arduino-cli/blob/master/docs/sketch-build-process.md)
