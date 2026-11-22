"""Serial link to the Arduino sorter and the ``MOTOR_ADJUST`` two-stage retry state machine.

Protocol (Python -> Arduino, 9600 baud, newline-terminated ASCII):

* ``<ohms>``         e.g. ``4700`` - sort the resistor into the bin assigned to that value
* ``MOTOR_ADJUST``   nudge the platform fan (M4) so the resistor settles differently
* ``NONE``           recognition failed twice - route the resistor to the ``unknown`` bin

Two-stage retry policy:

1. First frame recognised            -> send the value.
2. First frame ``NONE``              -> send ``MOTOR_ADJUST``, wait, then judge the **next frame**.
3. Second consecutive frame ``NONE`` -> send ``NONE`` (Arduino fills the ``unknown`` bin).
4. A value on the second frame       -> send the value. The counter resets after every send.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional, Protocol

BAUDRATE = 9600  # fixed: must match Serial.begin(9600) in resistor_sorter.ino
CMD_ADJUST = "MOTOR_ADJUST"
CMD_NONE = "NONE"


class SerialLink(Protocol):
    """Minimal transport interface used by :class:`SortingSession`."""

    def send(self, command: str) -> None:
        """Transmit one command line."""

    def close(self) -> None:
        """Release the transport."""


class ArduinoSerial:
    """Real serial port (pyserial) running at 9600 baud."""

    def __init__(self, port: str, baudrate: int = BAUDRATE, timeout_s: float = 1.0) -> None:
        import serial  # imported lazily so --mock works without a serial port

        if baudrate != BAUDRATE:
            raise ValueError(f"Baudrate must be {BAUDRATE} to match the Arduino firmware, got {baudrate}")
        self._ser = serial.Serial(port, baudrate, timeout=timeout_s)

    def send(self, command: str) -> None:
        self._ser.write(f"{command}\n".encode("ascii"))
        print(f"[SERIAL TX] {command}")

    def close(self) -> None:
        self._ser.close()


class MockSerial:
    """Offline stand-in that prints what would be transmitted."""

    def __init__(self) -> None:
        self.sent: List[str] = []

    def send(self, command: str) -> None:
        self.sent.append(command)
        print(f"[MOCK SERIAL TX] {command}")

    def close(self) -> None:
        pass


class SortingSession:
    """Two-stage fault-tolerant dispatcher between the detector and the Arduino."""

    def __init__(
        self,
        link: SerialLink,
        adjust_wait_s: float = 4.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._link = link
        self._adjust_wait_s = adjust_wait_s
        self._sleep = sleep
        self.none_count = 0

    @property
    def awaiting_retry(self) -> bool:
        """True after ``MOTOR_ADJUST`` was sent and the next frame must be judged."""
        return self.none_count == 1

    def on_recognition(self, command: str) -> Optional[str]:
        """Handle one recognition result (``"<ohms>"`` or ``"NONE"``).

        Returns the final command sent to the Arduino (a value or ``"NONE"``), or ``None``
        when only ``MOTOR_ADJUST`` was sent and another frame is needed.
        """
        if command == CMD_NONE:
            self.none_count += 1
            if self.none_count == 1:
                self._link.send(CMD_ADJUST)
                self._sleep(self._adjust_wait_s)  # let the fan motor finish before the next frame
                return None
        self._link.send(command)
        self.none_count = 0
        return command
