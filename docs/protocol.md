# Interfaces and command protocol

## Camera to host

| Property | Implementation |
| --- | --- |
| Transport | Wi-Fi, plain HTTP POST |
| Body | multipart/form-data |
| Endpoint example | /upload/upload.php |
| Form field | image |
| Filename | photo.jpg |
| Camera setting | JPEG, SVGA configuration |
| Trigger | GPIO12 active-low physical button |
| Camera diagnostic serial | 115200 baud |

The endpoint keeps the PHP-style path used by the capstone XAMPP server; the repository's Python receiver serves the same path.

Capture is initiated by the camera's physical button rather than a host request. The camera accepts any HTTP `2xx` confirmation response.

## Host admission and file handoff

Accepted uploads have unique IDs, immutable capture files, and FIFO admission.
HTTP 200 and X-Capture-ID acknowledge admission, not recognition or motion.
Invalid inputs are 400, oversized requests 413, full queues 503, and storage
failure before acceptance 500. There is no automatic camera retry for 503.

Duplicate-content requests are distinct events. The latest photo.jpg file is
a compatibility preview only. Legacy polling cannot recover unseen overwrites.
See [delivery and recovery](capture_delivery.md) for ownership, ordering,
cleanup, restart review, and acknowledgement ambiguity.

## Host to Arduino

The host opens a serial port at 9600 baud. pyserial defaults supply 8 data bits, no parity, and one stop bit; no explicit flow-control configuration is added. Commands are ASCII with one LF byte at the end. The firmware reads to LF and trims surrounding whitespace.

| Payload before LF | Meaning |
| --- | --- |
| Decimal value, for example 4700 | Look up exact text in the firmware table |
| MOTOR_ADJUST | Execute the platform adjustment sequence |
| NONE | Route to unknown |
| Any other nonempty text | Also routes to unknown |

Numeric predictions outside the 26-entry table are transmitted unchanged by the host and routed to unknown by firmware. They do not cause the recognition-failure retry policy: that policy is triggered only by NONE.

The unknown destination is layer 1 at 324 degrees. The other layers receive zero commanded movement.

## Return traffic and timing

The firmware emits diagnostic messages, including motion-completion messages. The host uses a configured delay between retry operations rather than a serial acknowledgement handshake. Opening the serial port may reset some Arduino boards.

Only valid-image `NONE` enters the retry state machine; input failures send no command and leave the state unchanged. The first valid `NONE` triggers `MOTOR_ADJUST` and a configured pause. The workflow then assumes the operator captures the same resistor again within the host session. A second valid `NONE` in that retry state dispatches the final unknown command.

## Manual motor utility

The standalone `motor_control` sketch supports manual testing and adjustment. It accepts `motor-index,angle` text, with motors 1–3 controlling storage layers and motor 4 controlling the platform. Its `reset` command reverses each motor by one configured revolution using open-loop control, without position sensors. The platform motor uses a different configured speed from the main sorting firmware.
