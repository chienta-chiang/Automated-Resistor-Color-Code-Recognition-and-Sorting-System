# Mechanical and Vision Illustrations

This directory contains the mechanical CAD views, mechanism overview diagram, and computer-vision pipeline output used across the documentation.

| File | Description |
| --- | --- |
| `system_overview.jpg` | Full CAD assembly showing the top inspection stage and three stacked storage layers |
| `recognition_platform.jpg` | CAD view of the resistor inspection platform and camera mount |
| `storage_mechanism.jpg` | CAD view of a single 10-slot rotating storage disc |
| `three_tier_storage_3d.png` | AI-assisted explanatory diagram of the three-tier pass-through mechanism and drop sequence (not a team CAD export; "home position" in the figure means the manually aligned 0° reference, as there are no home sensors) |
| `vision_pipeline_demo.png` | Annotated OpenCV detection and affine-rectification output for sample `resistor_06.jpg` |
| `platform_storage_cad.jpg` | CAD view of a storage disc with the inspection stage and support column |
| `synthetic_retry_demo.png` | Offline demo output for the synthetic retry frame: one band found, `NONE` sent to the unknown bin |

## Development figures (2024)

These figures document the design iterations described in [Design evolution](../design_evolution.md).

| File | Description | Date |
| --- | --- | --- |
| `design_evolution.jpg` | Early concept, integrated summer model and final three-tier CAD | Apr–Nov 2024 |
| `lens_before_after.jpg` | ESP32-CAM close-up without and with the +40 D lens | 2024 |
| `platform_revision.jpg` | Original vs. revised inspection platform (refocused, lamp opening added) | Aug 2024 |
| `lighting_comparison.jpg` | Same resistor under ring light, yellow LED bar and white LED bar | Aug 2024 |
| `deskew_sequence.jpg` | First orientation-correction prototype: placement, leveling, direction flip, band detection | Aug 2024 |
| `neutral_color_confusion.jpg` | Gray and white bands confused with end cap and body color, with HSV masks | Aug 2024 |
| `ocr_cement_exploration.jpg` | OCR experiment on a printed cement resistor (not adopted) | Jun 2024 |
| `original_run_evidence.png` | Host console, ESP32-CAM serial monitor and receiving-server log from the capstone system | Jul–Nov 2024 |

## Prototype photo and video excerpts

| File | Description |
| --- | --- |
| `physical_prototype.png` | Still frame of the assembled prototype |
| `inspection_platform.gif` | Inspection platform as a resistor is placed for capture |
| `manual_bin_inspection.gif` | A labeled storage compartment of the three-tier tower |
| `machine_overview.gif` | Walk-around view of the assembled three-tier storage tower |

All four come from the [project video](https://youtu.be/1teDK1EO_dk).

See the [README demonstration gallery](../../README.md#project-demonstration--visuals), [mechatronics architecture](../mechatronics_and_control.md), and [vision pipeline](../vision_and_algorithm.md) for context.
