"""
Serial scale driver.

Supported protocols:
  - Toledo 8217   (default) — Mettler Toledo scales
  - Adam Equipment           — Adam balance scales

Toledo 8217 serial parameters (from Mettler-Toledo 8217 protocol manual):
  baudrate=9600, bytesize=7, parity=EVEN, stopbits=1  (7E1)
  Active polling: driver sends b'W', scale replies with STX + frame + CR.

  Frame format after stripping STX (\\x02) and CR (\\r):
    Weight response : b"  1.234"   →  weight in current unit
    Status response : b"?\\xNN"    →  ? + single status byte

  Status byte bits:
    bit 0  motion                — scale is still moving
    bit 1  over_capacity         — weight exceeds maximum
    bit 2  negative              — weight is negative (return 0)
    bit 3  outside_zero_range    — cannot determine zero
    bit 4  center_of_zero        — scale is at exact zero
    bit 5  net_weight            — weight shown is net (tare applied)

Adam Equipment serial parameters:
  baudrate=4800, bytesize=8, parity=NONE, stopbits=1  (8N1)
  Active polling: driver sends b'P', scale replies with weight line + CR LF.

The driver runs a background polling thread and caches the latest reading.
Registered in drivers{} as "scale_driver".
"""

import logging
import re

import serial

from rpidriver.plugins.base_driver import ThreadDriver

logger = logging.getLogger(__name__)

# ── Serial parameter presets per protocol ─────────────────────────────────────

# Toledo 8217: 7E1 — matches Odoo's SerialScaleDriver and Mettler-Toledo manual
_TOLEDO_SERIAL = dict(
    baudrate=9600,
    bytesize=serial.SEVENBITS,
    parity=serial.PARITY_EVEN,
    stopbits=serial.STOPBITS_ONE,
)

# Adam Equipment: 8N1 at 4800 baud
_ADAM_SERIAL = dict(
    baudrate=4800,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
)

PROTOCOL_SERIAL_PARAMS = {
    "toledo8217": _TOLEDO_SERIAL,
    "adam": _ADAM_SERIAL,
}

# ── Toledo status byte bit names ──────────────────────────────────────────────

_TOLEDO_STATUS_BITS = [
    "motion",
    "over_capacity",
    "negative",
    "outside_zero_range",
    "center_of_zero",
    "net_weight",
]


# ── Protocol parsers ──────────────────────────────────────────────────────────


def parse_toledo8217(frame: bytes, last_weight: float = 0.0) -> dict | None:
    """
    Parse a Toledo 8217 weight frame (after STX and CR have been stripped).

    Two possible frame formats:
      Weight  : b"  1.234"   — digits, optional spaces/sign
      Status  : b"?\\xNN"    — literal '?' followed by a status byte

    Returns a dict {"weight": float, "unit": "kg", "status": str | list}
    or None if the frame cannot be parsed at all.

    The ``last_weight`` parameter is used when the scale returns a zero-status
    frame (some Toledo models send the weight once, then repeat status=0 until
    the weight changes — we must return the cached weight in that case).
    """
    # Strip framing bytes so this function works with both raw frames
    # (containing STX/CR from the wire) and pre-stripped frames from _read_frame().
    frame = frame.strip(b"\x02\r\n \t")

    if not frame:
        return None

    try:
        # ── Status frame: starts with '?' ─────────────────────────────────
        if frame[:1] == b"?":
            if len(frame) < 2:
                return {"weight": last_weight, "unit": "kg", "status": "ok"}

            status_byte = frame[1]
            flags = [
                name
                for bit, name in enumerate(_TOLEDO_STATUS_BITS)
                if status_byte & (1 << bit)
            ]

            if flags:
                logger.debug("Toledo status flags: %s", flags)
                # Negative weight → report 0
                weight = 0.0 if "negative" in flags else last_weight
                return {"weight": weight, "unit": "kg", "status": flags}

            # status_byte == 0: no change since last reading — return cached weight
            return {"weight": last_weight, "unit": "kg", "status": "ok"}

        # ── Weight frame: numeric digits ──────────────────────────────────
        text = frame.decode("ascii", errors="ignore").strip()
        match = re.search(r"([+-]?\s*\d+\.?\d*)", text)
        if match:
            weight = float(match.group(1).replace(" ", ""))
            return {"weight": weight, "unit": "kg", "status": "ok"}

    except (ValueError, AttributeError) as exc:
        logger.debug("Toledo parse error: %s on frame %r", exc, frame)

    return None


def parse_adam(line: bytes) -> dict | None:
    """
    Parse an Adam Equipment weight frame.

    Frame format: [sign][digits].[digits][unit][CR][LF]
    Example: b"+   0.000 kg\\r\\n"
    """
    try:
        text = line.decode("ascii", errors="ignore").strip()
        match = re.search(r"([+-]?\s*\d+\.?\d*)\s*([a-zA-Z]+)", text)
        if match:
            weight = float(match.group(1).replace(" ", ""))
            unit = match.group(2).lower()
            return {"weight": weight, "unit": unit, "status": "ok"}
    except (ValueError, AttributeError):
        pass
    return None


PROTOCOL_PARSERS = {
    "toledo8217": parse_toledo8217,
    "adam": parse_adam,
}


# ── Driver class ──────────────────────────────────────────────────────────────


class ScaleDriver(ThreadDriver):
    name = "scale_driver"

    # poll_interval is the sleep between cycles (real pacing = serial timeout)
    poll_interval = 0.1

    def __init__(self, config=None):
        super().__init__(config)
        cfg = config or {}
        self._port = cfg.get("port", "/dev/ttyUSB0")
        # Reject paths that don't point at a real device node — prevents
        # accidental reads from arbitrary files (e.g. /etc/passwd).
        if not self._port.startswith("/dev/"):
            logger.warning(
                "ScaleDriver: invalid port %r — must start with /dev/. "
                "Defaulting to /dev/ttyUSB0.",
                self._port,
            )
            self._port = "/dev/ttyUSB0"
        self._protocol = cfg.get("protocol", "toledo8217")
        self._timeout = float(cfg.get("timeout", 1.0))
        self._serial: serial.Serial | None = None

        # Display unit (conversion applied in read_weight before returning to Odoo)
        self._unit = cfg.get("unit", "kg").lower()
        if self._unit not in ("kg", "g", "lb", "oz"):
            logger.warning(
                "ScaleDriver: unknown unit %r — valid values: kg, g, lb, oz. Defaulting to 'kg'.",
                self._unit,
            )
            self._unit = "kg"

        # Latest cached reading returned to Odoo
        self._latest: dict = {"weight": 0.0, "unit": "kg", "status": "disconnected"}

        # Last *valid* weight value — returned when the scale sends status-only
        # frames (Toledo behaviour: weight sent once, then repeated status=0)
        self._last_weight: float = 0.0

        # Serial parameters: use protocol preset, allow per-key config overrides
        serial_params = dict(PROTOCOL_SERIAL_PARAMS.get(self._protocol, _TOLEDO_SERIAL))
        if "baudrate" in cfg:
            serial_params["baudrate"] = int(cfg["baudrate"])
            _STANDARD_BAUD = {1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200}
            if serial_params["baudrate"] not in _STANDARD_BAUD:
                logger.warning(
                    "ScaleDriver: unusual baudrate %d — common values: %s.",
                    serial_params["baudrate"],
                    sorted(_STANDARD_BAUD),
                )
        self._serial_params = serial_params

        # Active polling command
        self._measure_cmd: bytes = b"W" if self._protocol == "toledo8217" else b"P"

        self._open_serial()

    def get_device(self):
        return self._serial

    def _open_serial(self):
        try:
            self._serial = serial.Serial(
                port=self._port,
                timeout=self._timeout,
                write_timeout=self._timeout,
                **self._serial_params,
            )
            self.set_status("connected")
            logger.info(
                "ScaleDriver: opened %s — protocol=%s %d %d%s%d",
                self._port,
                self._protocol,
                self._serial_params["baudrate"],
                self._serial_params["bytesize"],
                self._serial_params["parity"],
                self._serial_params["stopbits"],
            )
        except serial.SerialException as exc:
            self.set_status("disconnected", str(exc))
            logger.warning("ScaleDriver: could not open %s: %s", self._port, exc)

    def _read_frame(self) -> bytes:
        """
        Read one raw frame from the serial port.

        Toledo 8217 terminates frames with CR (\\r), NOT LF.
        We use read_until(b'\\r') so we don't wait for the full serial timeout
        on every poll.  Adam uses CR+LF so readline() works fine there.
        """
        if self._protocol == "toledo8217":
            raw = self._serial.read_until(b"\r")
            # Strip STX (\\x02), CR (\\r), LF (\\n) framing bytes
            return raw.strip(b"\x02\r\n")
        else:
            raw = self._serial.readline()
            return raw.strip()

    # ── ThreadDriver.run ──────────────────────────────────────────────────────

    def run(self):
        if self._serial is None or not self._serial.is_open:
            self._stop_event.wait(2)
            self._open_serial()
            return

        try:
            # Send the polling command, then read the response frame
            self._serial.write(self._measure_cmd)
            frame = self._read_frame()

            if frame:
                if self._protocol == "toledo8217":
                    parsed = parse_toledo8217(frame, last_weight=self._last_weight)
                else:
                    parsed = parse_adam(frame)

                if parsed:
                    # Update cached last valid weight for Toledo status-only frames
                    if parsed.get("status") == "ok":
                        self._last_weight = parsed["weight"]

                    with self._lock:
                        self._latest = parsed

                    if parsed.get("status") == "ok":
                        self.set_status("connected")
                    else:
                        flags = parsed.get("status", [])
                        self.set_status(
                            "connected",
                            "scale flags: " + ", ".join(flags) if flags else "",
                        )

        except serial.SerialException as exc:
            logger.warning("ScaleDriver: serial error: %s", exc)
            self.set_status("error", str(exc))
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
            self._last_weight = 0.0
            with self._lock:
                self._latest = {"weight": 0.0, "unit": "kg", "status": "disconnected"}

    # ── Unit conversion ───────────────────────────────────────────────────────

    _KG_TO = {
        "kg": 1.0,
        "g":  1000.0,
        "lb": 2.20462,
        "oz": 35.27396,
    }

    def _convert_weight(self, weight_kg: float) -> float:
        """Convert a weight value from kg to the driver's configured unit."""
        return round(weight_kg * self._KG_TO.get(self._unit, 1.0), 4)

    # ── Public API ────────────────────────────────────────────────────────────

    def read_weight(self) -> dict:
        """
        Return the most recent weight reading (thread-safe).

        The weight is converted from the internal kg representation to the
        unit specified in the config (kg / g / lb / oz).  The 'unit' field
        in the returned dict reflects the converted unit.
        """
        with self._lock:
            reading = dict(self._latest)
        # Apply unit conversion only when scale reports kg (Toledo always does;
        # Adam reports its own unit — we convert that too if it happens to be kg).
        if self._unit != "kg" and reading.get("unit") == "kg":
            reading["weight"] = self._convert_weight(reading["weight"])
            reading["unit"] = self._unit
        return reading

    def close(self):
        """Close the serial port."""
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None


# ── Plugin registration ───────────────────────────────────────────────────────

DRIVER_CLASS = ScaleDriver
