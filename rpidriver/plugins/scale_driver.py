"""
Serial scale driver.

Supported protocols:
  - Toledo 8217   (default) — used by Mettler Toledo scales
  - Adam Equipment — used by Adam balance scales

Toledo 8217 serial parameters (from Mettler-Toledo 8217 protocol manual):
  baudrate=9600, bytesize=7, parity=EVEN, stopbits=1
  Active polling: driver sends b'W' and reads back STX + weight + CR.

Adam Equipment serial parameters:
  baudrate=4800, bytesize=8, parity=NONE, stopbits=1
  Active polling: driver sends b'P' and reads back weight line.

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

# ── Protocol parsers ──────────────────────────────────────────────────────────


def parse_toledo8217(line: bytes) -> dict | None:
    """
    Parse a Toledo 8217 weight response.

    Frame: STX  weight_digits  [N]  CR
    e.g.  b'\\x02  1.234\\r'  or  b'\\x02  1234N\\r'
    The STX (0x02) is stripped by readline(); we match the numeric part.
    """
    try:
        # Strip STX, CR, LF, whitespace
        text = line.decode("ascii", errors="ignore").strip().lstrip("\x02")
        # Extract weight; 'N' suffix means weight is negative on some units
        match = re.search(r"([+-]?\s*\d+\.?\d*)\s*N?", text)
        if match:
            weight = float(match.group(1).replace(" ", ""))
            return {"weight": weight, "unit": "kg", "status": "ok"}
    except (ValueError, AttributeError):
        pass
    return None


def parse_adam(line: bytes) -> dict | None:
    """
    Parse an Adam Equipment weight frame.

    Frame format: [sign][digits].[digits][unit][CR][LF]
    Example: +   0.000 kg
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
    # poll_interval applies between active polling cycles (after the serial
    # read timeout returns).  Keep it short; real pacing comes from timeout.
    poll_interval = 0.1

    def __init__(self, config=None):
        super().__init__(config)
        cfg = config or {}
        self._port = cfg.get("port", "/dev/ttyUSB0")
        self._protocol = cfg.get("protocol", "toledo8217")
        self._timeout = float(cfg.get("timeout", 1.0))
        self._serial: serial.Serial | None = None
        self._latest: dict = {"weight": 0.0, "unit": "kg", "status": "disconnected"}
        # _lock is inherited from ThreadDriver — do not shadow it

        # Serial parameters: use protocol preset, allow per-key config overrides
        serial_params = dict(PROTOCOL_SERIAL_PARAMS.get(self._protocol, _TOLEDO_SERIAL))
        if "baudrate" in cfg:
            serial_params["baudrate"] = int(cfg["baudrate"])
            _STANDARD_BAUD = {1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200}
            if serial_params["baudrate"] not in _STANDARD_BAUD:
                logger.warning(
                    "ScaleDriver: unusual baudrate %d — common values are %s.",
                    serial_params["baudrate"],
                    sorted(_STANDARD_BAUD),
                )
        self._serial_params = serial_params

        # Active polling: command sent to the scale to request a weight reading
        self._measure_cmd: bytes = b"W" if self._protocol == "toledo8217" else b"P"

        self._parser = PROTOCOL_PARSERS.get(self._protocol, parse_toledo8217)
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
                "ScaleDriver: opened %s — protocol=%s baudrate=%d %d%s%d",
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

    # ── ThreadDriver.run ──────────────────────────────────────────────────

    def run(self):
        if self._serial is None or not self._serial.is_open:
            self._stop_event.wait(2)
            self._open_serial()
            return

        try:
            # Active polling: send the measure command then read the response
            self._serial.write(self._measure_cmd)
            line = self._serial.readline()
            if line:
                parsed = self._parser(line)
                if parsed:
                    with self._lock:
                        self._latest = parsed
                    self.set_status("connected")
        except serial.SerialException as exc:
            logger.warning("ScaleDriver: read error: %s", exc)
            self.set_status("error", str(exc))
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
            with self._lock:
                self._latest = {"weight": 0.0, "unit": "kg", "status": "disconnected"}

    # ── Public API ────────────────────────────────────────────────────────

    def read_weight(self) -> dict:
        """Return the most recent weight reading."""
        with self._lock:
            return dict(self._latest)

    def close(self):
        """Close the serial port."""
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None


# ── Plugin registration ───────────────────────────────────────────────────────

DRIVER_CLASS = ScaleDriver
