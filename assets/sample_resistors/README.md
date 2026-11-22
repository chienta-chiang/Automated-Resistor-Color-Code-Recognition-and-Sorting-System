# Sample Resistor Images

This directory contains eight **800 × 600 JPEG images** of resistors captured by the ESP32-CAM during the capstone project.

The images are used for offline demonstrations and software regression testing. They provide reproducible examples of the color-band recognition pipeline.

## Regression Baseline

The [sample baseline](../../tests/baselines/approved_samples.json) records each image's SHA-256 hash, predicted resistance command, detected colors, band count, reading direction, and routing eligibility.

The baseline locks in the detector's output for each image, so any change in recognition behavior fails the regression tests.

For recognition results and additional test coverage, see [Validation](../../docs/validation.md).
