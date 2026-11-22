# Contributions and development history

This repository documents a **four-person undergraduate electrical engineering capstone** and the **post-graduation software refactoring and reliability testing** that followed. The sections below separate the team's capstone prototype from the software work that followed.

## Undergraduate Capstone (Four-Student Team)

The project was developed by a four-student team at **Feng Chia University** and received **3rd Place, Senior Capstone Project Competition**, Department of Electrical Engineering, Feng Chia University. In Mar 2025, the group report was selected for the **Feng Chia University Outstanding Academic Papers by Students** database on the advisor's recommendation.

### Direct engineering contributions

The responsibilities below describe my work within the four-student undergraduate team. Supporting firmware and system details are linked for inspection.

- **Mechanical concept, assembly and integration:** Proposed the three-tier rotating pass-through storage concept, participated in its assembly and calibration, and collaborated with CAD teammates on drop-path alignment, shaft fit, and mechanical integration. During the May 2024 midterm stage, printed the first storage-box test piece in the university maker club. It took more print time and filament than planned, so I proposed removing unused space from the sector-shaped compartments. The sorting geometry uses manually established pass-through references and open-loop return.
- **Arduino electromechanical control:** Developed the Arduino stepper-control logic for four motor channels, including 26 configured resistance routes plus an unknown destination, storage-layer indexing, platform-paddle actuation, and reverse-step return. The implemented pin and routing constants are in [sorter firmware](src/firmware/resistor_sorter/resistor_sorter.ino) and [stepper configuration](src/firmware/resistor_sorter/stepper_control.h).
- **Vision calibration and end-to-end testing:** Co-developed and tuned HSV color-band detection with the team, collaborated on Python-to-Arduino 9600-baud command integration and retry behavior, and participated in system-level motion and sorting tests.

Image recognition, networking, CAD design, and the final prototype were collaborative team efforts. The competition award belongs to the full team.

For implementation details see [Vision and decoding](docs/vision_and_algorithm.md), [Mechatronics](docs/mechatronics_and_control.md), and [Troubleshooting](docs/troubleshooting_and_calibration.md).

## Post-Graduation Software Refactoring and Testing

After graduation, the host software was modularized and hardened in two distinct phases:

- **Post-graduation refactoring:** Separated vision detection, serial dispatch, and configuration validation (`src/vision/`); added mock transport, synthetic demonstration images, and an interactive HSV calibration helper (`tools/hsv_calibrator.py`); implemented the camera upload endpoint as a **Python HTTP receiver** (`src/vision/upload_server.py`), replacing the capstone's XAMPP/PHP endpoint; and established sample baselines with **16 initial regression tests**.
- **Post-graduation reliability work:** Added independent capture IDs, bounded FIFO queuing (`src/vision/capture_queue.py`), strict input/configuration validation, camera-side `2xx` HTTP response checks, and **31 additional reliability tests** (bringing the suite to **47 tests** total), along with compilation verification for all three Arduino/ESP32 firmware sketches.

All post-graduation software work (refactoring, the Python receiver, tooling, and the 47-test suite) was developed with AI coding tools from task instructions I wrote (ChatGPT for planning, Codex for implementation) and reviewed by me. The capstone firmware and original recognition code are the team's 2024 work.

Implementation details and verification results are documented in [Validation](docs/validation.md), [Capture delivery](docs/capture_delivery.md), and [Reproduction](docs/reproduction.md).

## Rights

**All rights reserved. No open-source license is provided.** For project history and media sources, see [Project history and sources](docs/provenance.md).
