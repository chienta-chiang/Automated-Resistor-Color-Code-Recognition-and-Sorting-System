# Capture delivery and recovery

## Integrated mode

The reliability path is the integrated host process using --live --serve-upload.
The ESP32 continues POSTing multipart field image with filename photo.jpg to the
configured /upload/upload.php endpoint. No pin, timing, button, or multipart
change is required in the camera; only its successful HTTP response predicate
changes to 2xx.

The host validates the complete request and image before admission. Each
admitted request receives a sequence plus random UUID, an immutable encoded
capture file, and an X-Capture-ID response header. Content hashes verify bytes;
they do not deduplicate events. Two identical JPEG requests create two events.

The configured queue capacity includes pending and in-flight events. At capacity,
new uploads receive 503 and no accepted event is evicted. Invalid requests are
400, oversized bodies 413, and storage failure before acceptance 500.

Accepted events are ordered by publication under the queue lock, after
validation completes. Concurrent request-start order is not guaranteed. The
legacy latest-image preview is updated separately and is not the queue.

## Processing and cleanup

A single consumer claims the oldest pending file by atomically renaming its
extension from .jpg to .processing. It verifies the admitted hash and decodes
the file. Invalid input is logged and removed without entering SortingSession.
Valid-image NONE retains the original two-stage recognition retry policy.

After a successful software dispatch return, the processing file is removed.
A dispatch exception or interruption leaves the processing file for review
instead of automatically repeating a potentially transmitted command.

Temporary files are independently named and cleaned after write/replace failure.
The latest-image preview can be unavailable or reflect concurrent update
completion order without affecting the queued events.

## Shutdown and restart

The HTTP service stops accepting connections and waits for active handlers.
Pending captures remain on disk. The queue directory has one owner marker;
another process cannot open the same spool.

After an abnormal shutdown, a stale `.owner` marker may block restart.
Confirm that no process owns the spool, review pending work, and manually
remove the stale marker before restarting.

On a subsequent open, .processing files become .uncertain. Existing .uncertain
files also block live startup. Review them against physical state and move them
to private investigation storage before starting motion. Do not replay them
automatically.

Recovered pending .jpg files require review and an explicit
capture.resume_pending: true setting before live startup. Use it only when the
physical resistor sequence still corresponds to that work. The default is false.
The serial port is not opened when startup review is required.

The queue is single-owner. Do not launch the standalone receiver and live worker
as independent owners of the same spool. Use the integrated process. A standalone
receiver can queue captures for later reviewed consumption, but has no motor
worker and eventually returns 503 if not drained.

## Delivery semantics and recovery boundaries

Within a healthy integrated process, each admitted upload is represented by one
distinct event and offered to the single consumer in FIFO admission order.
Processing or `MOTOR_ADJUST` delays do not consume later arrivals; queue saturation
returns HTTP 503 instead of silently overwriting admitted events.

Pending captures are written, flushed, and fsynced before atomic publication.
After an unexpected shutdown, persisted queue files are reviewed before processing
resumes. A process can fail after publication but before the client receives
HTTP 200; retransmission can then create a second event because the camera
contract has no client idempotency key. The camera does not automatically retry
HTTP 503; the operator checks upload status and recaptures when appropriate.

Interrupted dispatches are quarantined for operator review instead of
being automatically replayed: the host cannot determine whether a motor command
was already executed. The sorter uses open-loop motion without transaction-ID
acknowledgements or completion feedback, so physical sorting is reconciled
manually after an uncertain dispatch. For routine operation, process one physical
resistor through its recognition and sorting cycle before introducing the next.

## Legacy file mode

Without --serve-upload, an independent polling thread observes replacements of
the configured latest-image file and publishes observed snapshots into the same
queue. It checks timestamp, size, and hash, so observed same-content replacements
with changed metadata are separate events. Invalid snapshots do not dispatch.

Legacy polling captures observed file updates on a best-effort basis. Versions
overwritten between polling intervals cannot be recovered, and identical content
with unchanged metadata may not register as a new event. At capacity it retries
the latest observed snapshot; intervening writes may be lost before admission.

## Resource and decoder limits

The example configuration limits each complete multipart request to 5 MiB,
input and resized frames to 16 million pixels, and admitted work to 32 pending/in-flight captures.
Pillow verifies structure and loads pixels; OpenCV decodes BGR for recognition.
JPEG framing checks reject missing end markers.

The HTTP server is intended for a trusted LAN and does not implement TLS,
authentication, or public-Internet connection/rate hardening.
