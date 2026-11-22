# Technical limitations and future improvements

This page summarizes the current design boundaries and possible engineering extensions. Implementation details and regression evidence are documented separately in [Software](software.md), [Capture delivery](capture_delivery.md), and [Validation](validation.md).

## Recognition and evaluation

The color-code detector uses fixed HSV thresholds and contour-based segmentation. Its output depends on illumination, shadows, reflections, focus, resistor orientation, and color-band separation. Gray and white are the least robust thresholds: calibration images show gray bands merging with the metal end caps and white bands with the body color ([examples](images/neutral_color_confusion.jpg)). Image-format validation rejects malformed inputs, but a valid JPEG can still be blurred or overexposed.

The decoder uses the **first three selected color bands** to calculate resistance; it does not decode tolerance bands or general five-/six-band resistors. There is no calibrated confidence score or machine-learning inference. Recognized values may also fall outside the **26 configured sorting routes**.

In capstone testing, about **80% of roughly 100 resistor types** were recognized correctly with a single fixed HSV configuration (team estimate; per-trial records were not retained). Warm, high-contrast bands were the most reliable; cool colors and bands with little contrast against the body were more sensitive to small lighting changes. The **eight sample images** and **117 capstone captures** used in this repository are regression baselines that lock in the detector's behavior; a labeled accuracy benchmark across lighting conditions is listed under future improvements. See [Validation](validation.md) for details.

## Capture and communication

- **Capture initiation:** The ESP32-CAM takes images when its physical button is pressed. There is no host-controlled shutter or automatic capture linked to a particular physical resistor.
- **Upload and retry:** Accepted uploads enter a bounded FIFO queue; new requests receive HTTP 503 when capacity is reached. The camera protocol has no idempotency key or automatic retry after 503. If an HTTP response is lost, a retransmission may create another capture event.
- **Dispatch feedback:** The Arduino serial protocol has no startup/readiness or motor-completion acknowledgement. Interrupted or uncertain in-flight dispatches require operator reconciliation before resuming physical sorting.
- **Legacy mode:** The optional single-file polling workflow can miss intermediate captures when the same file is overwritten. Integrated queued delivery addresses accepted-event preservation; see [Capture delivery](capture_delivery.md).
- **Deployment:** The Python HTTP receiver is intended for a trusted local network; it has no authentication or TLS termination. Internet-facing deployment would require additional security controls.

## Motion and hardware

The sorter uses an **Arduino Mega 2560**, **four 5V 28BYJ-48 stepper motors**, and **four ULN2003 driver boards**, with an **ESP32-CAM** for image capture. The three storage layers and sorting platform are driven open loop. Their reference positions are manually aligned; no home sensor, encoder, or missed-step detection verifies actual movement.

The `MOTOR_ADJUST` sequence (`-20° / +30° / -10°`) leaves a **net +1 commanded step** because the firmware converts angles to integer step counts by truncation. Repeated adjustments may therefore accumulate a command-position offset. In addition, if the installed motors use the common $\approx 63.684:1$ 28BYJ-48 gear train ($\approx 2037.9$ full steps/rev vs. `2048` configured), a 324° move overshoots by about **$+1.57^\circ$** in-cycle; the offset cancels on the return move.

Because the Arduino `Stepper` library retains two energized phases on each moved motor without de-energizing after `step()`, continuous static holding across all four motors is calculated at **$0.640\text{–}0.672\text{ A}$ ($3.20\text{–}3.36\text{ W}$)** on a 5 V motor rail after ULN2003 Darlington $V_{CE(\text{sat})}$ drops. Firmware-derived motion durations range from **5.644 s** (36° sort) to **13.647 s** (324° / unknown sort), with **3.655 s** for `MOTOR_ADJUST` (against the host's 4.0 s wait, a 0.345 s margin).

The ESP32-CAM firmware disables hardware brownout detection (`RTC_CNTL_BROWN_OUT_REG = 0`), so supply-rail droop during Wi-Fi/camera bursts does not trigger a reset. The repository has no wiring schematic or power-supply specification; the pin map and firmware settings define the connections. The printable parts are in [`hardware/cad/`](../hardware/cad/README.md); shaft couplers and motor mounts are not included. See [Hardware and BOM](hardware_and_bom.md) for the complete BOM, power/timing derivations and bench measurement plan.

## Future improvements

| Area | Proposed improvement | Expected benefit |
| --- | --- | --- |
| Image acquisition | Stabilize lighting and camera positioning; collect labeled images across lighting and orientation conditions | More consistent segmentation and measurable recognition performance |
| Resistance decoding | Extend band selection and decoding to tolerance bands and five-/six-band resistors | Broader resistor coverage |
| Non-color-coded parts | Revisit OCR for printed cement resistors. A June 2024 experiment isolated the marking but misread `5W470ΩJ` as `SH40Q` ([example](images/ocr_cement_exploration.jpg)) | Sorting of power resistors that carry printed values instead of bands |
| Capture delivery | Add capture IDs understood by both client and server, idempotent retries, and backoff for HTTP 503 | Fewer duplicate or lost-in-uncertainty capture submissions |
| Device protocol | Add Arduino readiness and movement-completion acknowledgements, tied to capture/command IDs | Better correlation of commands with physical operations |
| Reference alignment | Add home switches or photo interrupters and a defined homing routine; consider encoders for position feedback | Repeatable zero reference and better detection of motion faults |
| Motion conversion | Review integer angle-to-step rounding, compensate `MOTOR_ADJUST`, and calibrate `STEPS_PER_REV` against physical motor gearing | Reduce accumulated drift and improve angular accuracy |
| Power integrity & thermal design | Measure supply droop, coil/driver temperatures, and reset causes with brownout detection enabled; de-energize idle stepper coils where mechanically safe | Verify 5 V / 3.3 V rail stability, prevent flash corruption, and cut continuous idle holding heat |
| Evaluation and deployment | Establish a ground-truth test set, end-to-end hardware trials, and authenticated transport for deployments beyond a trusted LAN | Quantified accuracy, verified system behavior, and safer network exposure |


## Reproduction and publication

Software verification was performed on **Windows with CPython 3.11.4**; toolchain versions, commands, and compiler warnings are available in the [Reproduction guide](reproduction.md). See [Contributions](../CONTRIBUTIONS.md) and [Project history and sources](provenance.md) for development history.
