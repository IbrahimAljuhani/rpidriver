"""
Customer display driver.

Supported displays:
  - Bixolon BCD-1000 / BCD-1100  (USB-CDC → /dev/ttyACM0)
  - Epson OCD300                  (RS-232)

Both use a simple 2×20 character LCD protocol (VFD/LCD display commands).

Note: Arabic text is NOT supported on customer displays — the hardware
only accepts ASCII/cp437. Arabic strings will be encoded with '?' replacements.

Registered in drivers{} as "display_driver".
"""

import logging
import threading

import serial

from rpidriver.plugins.base_driver import AbstractDriver

logger = logging.getLogger(__name__)

# ── Display command constants ─────────────────────────────────────────────────

ESC = b"\x1b"
INIT = ESC + b"@"
LINE2 = b"\n"
CLEAR = b"\x0c"

COLS = 20


class DisplayDriver(AbstractDriver):
    name = "display_driver"

    def __init__(self, config=None):
        super().__init__(config)
        cfg = config or {}
        self._port = cfg.get("port", "/dev/ttyACM0")
        if not self._port.startswith("/dev/"):
            logger.warning(
                "DisplayDriver: invalid port %r — must start with /dev/. Defaulting to /dev/ttyACM0.",
                self._port,
            )
            self._port = "/dev/ttyACM0"
        self._baudrate = int(cfg.get("baudrate", 9600))
        self._serial: serial.Serial | None = None
        self._lock = threading.Lock()
        self._connect()

    def get_device(self):
        return self._serial

    # ── Connection ────────────────────────────────────────────────────────

    def _connect(self):
        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=1,
                write_timeout=1,  # Prevent indefinite block if display freezes
            )
            self._write_raw(INIT)
            self.set_status("connected")
            logger.info("DisplayDriver: connected to %s.", self._port)
        except serial.SerialException as exc:
            self._serial = None
            self.set_status("disconnected", str(exc))
            logger.warning("DisplayDriver: could not open %s: %s", self._port, exc)

    def _write_raw(self, data: bytes):
        """Write bytes directly without reconnect guard (used in _connect)."""
        if self._serial and self._serial.is_open:
            with self._lock:
                self._serial.write(data)

    def _write(self, data: bytes):
        """Write bytes, attempting reconnect if the port is closed."""
        if self._serial is None or not self._serial.is_open:
            logger.info("DisplayDriver: reconnecting to %s.", self._port)
            self._connect()
        if self._serial is None or not self._serial.is_open:
            logger.warning("DisplayDriver: write skipped — port unavailable.")
            self.set_status("disconnected", "Port unavailable")
            return
        with self._lock:
            try:
                self._serial.write(data)
            except serial.SerialException as exc:
                logger.warning("DisplayDriver: write error: %s", exc)
                self.set_status("error", str(exc))
                self._serial = None

    # ── Public API ────────────────────────────────────────────────────────

    def display_text(self, line1: str = "", line2: str = ""):
        """
        Show two lines of text on the customer display.

        Lines are padded/truncated to COLS (20) characters.
        Arabic text will appear as '?' — the hardware does not support it.
        """
        ln1 = line1[:COLS].ljust(COLS)
        ln2 = line2[:COLS].ljust(COLS)
        payload = (
            CLEAR
            + ln1.encode("cp437", errors="replace")
            + LINE2
            + ln2.encode("cp437", errors="replace")
        )
        self._write(payload)

    def display_price(self, item_name: str, price: float, currency: str = "SAR"):
        """Convenience method: show item name on line 1 and price on line 2."""
        line2 = f"{price:.2f} {currency}".rjust(COLS)
        self.display_text(line1=item_name, line2=line2)

    def clear(self):
        """Clear the display."""
        self._write(CLEAR)

    def welcome(self, msg: str = "Welcome!"):
        """Show a welcome message centered on line 1."""
        self.display_text(line1=msg.center(COLS), line2="")

    def stop(self):
        """Stop the driver and close the serial port (called by plugin loader on shutdown)."""
        self.close()

    def close(self):
        """Close the serial port and mark status as disconnected."""
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None
        self.set_status("disconnected")


# ── Plugin registration ───────────────────────────────────────────────────────

DRIVER_CLASS = DisplayDriver
