"""
Serial scale driver.

Supported protocols:
  - Toledo 8217   (default) — used by Mettler Toledo scales
  - Adam Equipment — used by Adam balance scales

The driver runs a background polling thread and caches the latest reading.
Registered in drivers{} as "scale_driver".
"""

import logging
import re

import serial

from rpidriver.plugins.base_driver import ThreadDriver

logger = logging.getLogger(__name__)

# ── Protocol parsers ──────────────────────────────────────────────────────────


def parse_toledo8217(line: bytes) -> dict | None:
    """
    Parse a Toledo 8217 weight frame.

    Frame format (ASCII): ?W+000001.234kg\r\n  or  W+000001kg\r\n
    Returns {"weight": float, "unit": str} or None on parse failure.
    """
    try:
        text = line.decode("ascii", errors="ignore").strip()
        # \.\d* makes the decimal point optional (handles integer weights too)
        match = re.search(r"([+-]?\d+\.?\d*)\s*([a-zA-Z]+)", text)
        if match:
            weight = float(match.group(1))
            unit = match.group(2).lower()
            return {"weight": weight, "unit": unit, "status": "ok"}
    except Exception:
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
    except Exception:
        pass
    return None


PROTOCOL_PARSERS = {
    "toledo8217": parse_toledo8217,
    "adam": parse_adam,
}


# ── Driver class ──────────────────────────────────────────────────────────────


class ScaleDriver(ThreadDriver):
    name = "scale_driver"
    # poll_interval is effectively dominated by the serial read timeout (1.0 s).
    # This value applies only when the port is open and returns data immediately.
    poll_interval = 0.1

    def __init__(self, config=None):
        super().__init__(config)
        cfg = config or {}
        self._port = cfg.get("port", "/dev/ttyUSB0")
        self._baudrate = int(cfg.get("baudrate", 9600))
        self._protocol = cfg.get("protocol", "toledo8217")
        self._timeout = float(cfg.get("timeout", 1.0))
        self._serial: serial.Serial | None = None
        self._latest: dict = {"weight": 0.0, "unit": "kg", "status": "disconnected"}
        # _lock is inherited from ThreadDriver — do not shadow it
        self._parser = PROTOCOL_PARSERS.get(self._protocol, parse_toledo8217)
        self._open_serial()

    def get_device(self):
        return self._serial

    def _open_serial(self):
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=self._timeout,
            )
            self.set_status("connected")
            logger.info("ScaleDriver: opened %s at %d baud.", self._port, self._baudrate)
        except serial.SerialException as exc:
            self.set_status("disconnected", str(exc))
            logger.warning("ScaleDriver: could not open %s: %s", self._port, exc)

    # ── ThreadDriver.run ──────────────────────────────────────────────────

    def run(self):
        if self._serial is None or not self._serial.is_open:
            # Use the stop event so the thread can be interrupted during the wait
            self._stop_event.wait(2)
            self._open_serial()
            return

        try:
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
            self._serial = None

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
