# System architecture

## Implemented nodes

| Node | Implementation | Responsibility |
| --- | --- | --- |
| Camera | ../src/firmware/esp32_cam/esp32_cam.ino | GPIO12 button trigger, JPEG capture, HTTP multipart POST |
| Host | ../src/vision/main.py and detector.py | Consume queued capture events or legacy snapshots, recognize, dispatch |
| Motion | ../src/firmware/resistor_sorter/resistor_sorter.ino | Interpret newline text and drive four steppers |

See the [software guide](software.md) and [protocol](protocol.md) for implementation details.

## Capstone deployment and current host

In the capstone demonstration, the camera uploaded to an XAMPP/PHP endpoint and the host application monitored the uploaded image file. The [Python receiver](../src/vision/upload_server.py) in this repository serves the same multipart endpoint and feeds a bounded capture queue; file monitoring remains available as legacy mode.

After graduation the host code was split into modules for vision detection, upload queuing, and serial dispatch.

## Capture and handoff

The ESP32-CAM firmware uses JPEG/SVGA, one frame buffer, and GPIO12 button capture. It sends an HTTP multipart POST using the `image` field and `photo.jpg` filename, accepting any HTTP `2xx` confirmation response.

The integrated host validates each request and publishes immutable capture files
with independent IDs into a bounded FIFO. Identical content is not deduplicated.
A separate photo.jpg preview preserves compatibility but is not consumed by the
integrated worker. The former latest-file signature overwrite defect is removed
from this path.

A single consumer claims events in admission order. Invalid inputs do not enter
the recognition retry state. Full queues return HTTP 503 rather than evicting
work. Restart and in-flight uncertainty require operator review. Legacy polling
remains best effort. See [delivery guarantees](capture_delivery.md).

## Recognition

Resizing, HSV threshold masks, morphology, largest-contour selection, minimum-area rectangle orientation, affine rotation, and band filters produce candidate colors. Candidates are ordered horizontally, with direction chosen from terminal-band/body-edge distances. The first three selected colors yield two significant digits and a nonnegative decimal exponent.

**Decoder scope:** The three selected bands encode two significant digits and a multiplier, following the resistance-value portion of a four-band color code. Reading direction uses band-to-body-edge geometry. Tolerance decoding and general five-/six-band decoding are outside the implemented scope; when more than three band candidates are present, the decoder still uses the first three selected colors.

## Dispatch state

| State and observation | Output | Next state |
| --- | --- | --- |
| Input-invalid, either state | No command | State unchanged |
| Initial, numeric result | Numeric text | Initial |
| Initial, NONE | MOTOR_ADJUST, then configured sleep | Waiting for another capture |
| Waiting, numeric result | Numeric text | Initial |
| Waiting, NONE | NONE | Initial |

Retry state is maintained per host session. Capture-event IDs track queued images; without end-to-end hardware handshakes, HTTP acknowledgement confirms queue admission rather than physical-component tracking or completed motor motion.

The operator triggers recapture in live operation. In offline mock mode, the same test image is loaded again to exercise the `MOTOR_ADJUST` → `NONE` state transition.

## Mechanical routing

The table selects one of three storage layers at multiples of 36 degrees. Other layers receive zero commanded movement and are assumed to have been aligned to their pass-through reference. The platform paddle then executes +46/-10 nominal degrees, followed by opposite commanded storage movement.

Motor zero is established through manual alignment, without a position sensor or startup reference search.

