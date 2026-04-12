"""
CUPS network printing driver.

Sends print jobs to a CUPS server (local or remote) using the IPP protocol
via the `requests` library.  No native CUPS bindings required.

Registered in drivers{} as "cups_driver".
"""

import itertools
import logging
import struct
import threading

import requests

from rpidriver.plugins.base_driver import AbstractDriver

logger = logging.getLogger(__name__)

# IPP operation codes
IPP_OP_PRINT_JOB = 0x0002
IPP_VERSION = (2, 0)

_request_id_counter = itertools.count(1)

_CONNECT_TIMEOUT = 2   # seconds — GET /  health check
_PRINT_TIMEOUT = 10    # seconds — POST IPP print job


def _ipp_attribute(tag: int, name: str, value: bytes) -> bytes:
    """Encode a single IPP attribute."""
    return (
        struct.pack("B", tag)
        + struct.pack(">H", len(name))
        + name.encode("utf-8")
        + struct.pack(">H", len(value))
        + value
    )


def _build_ipp_print_job(printer_uri: str, job_name: str, document: bytes) -> bytes:
    """Build a minimal IPP Print-Job request."""
    request_id = next(_request_id_counter)

    # Attribute group delimiters
    TAG_OPERATION = 0x01
    TAG_END = 0x03
    # Value tags
    TAG_URI = 0x45
    TAG_CHARSET = 0x47
    TAG_LANG = 0x48
    TAG_NAME_WITHOUT_LANGUAGE = 0x42

    attrs = struct.pack(">BB", *IPP_VERSION)
    attrs += struct.pack(">H", IPP_OP_PRINT_JOB)
    attrs += struct.pack(">I", request_id)

    # Operation attributes group
    attrs += struct.pack("B", TAG_OPERATION)
    attrs += _ipp_attribute(TAG_CHARSET, "attributes-charset", b"utf-8")
    attrs += _ipp_attribute(TAG_LANG, "attributes-natural-language", b"en-us")
    attrs += _ipp_attribute(TAG_URI, "printer-uri", printer_uri.encode())
    attrs += _ipp_attribute(TAG_NAME_WITHOUT_LANGUAGE, "job-name", job_name.encode())

    # End-of-attributes marker + document data
    attrs += struct.pack("B", TAG_END)
    attrs += document

    return attrs


class CupsDriver(AbstractDriver):
    name = "cups_driver"

    def __init__(self, config=None):
        super().__init__(config)
        cfg = config or {}
        self._cups_host = cfg.get("cups_host", "localhost")
        self._cups_port = int(cfg.get("cups_port", 631))
        self._printer_name = cfg.get("printer_name", "Receipt_Printer")
        # Serialise print jobs — one at a time to avoid IPP race conditions
        self._lock = threading.Lock()
        self._check_connection()

    def get_device(self):
        return None

    @property
    def _printer_uri(self) -> str:
        return f"ipp://{self._cups_host}:{self._cups_port}/printers/{self._printer_name}"

    @property
    def _ipp_url(self) -> str:
        # CUPS accepts IPP over HTTP on port 631
        return f"http://{self._cups_host}:{self._cups_port}/printers/{self._printer_name}"

    def _check_connection(self):
        try:
            r = requests.get(
                f"http://{self._cups_host}:{self._cups_port}/",
                timeout=_CONNECT_TIMEOUT,
            )
            if r.status_code < 400:
                self.set_status("connected")
                logger.info(
                    "CupsDriver: CUPS reachable at %s:%s.",
                    self._cups_host,
                    self._cups_port,
                )
            else:
                self.set_status("error", f"CUPS returned HTTP {r.status_code}")
        except requests.RequestException as exc:
            # Catches ConnectionError, Timeout, and all other request errors
            self.set_status("disconnected", str(exc))
            logger.warning("CupsDriver: cannot reach CUPS: %s", exc)

    def print_raw(self, data: bytes, job_name: str = "rpidriver-job"):
        """Send raw bytes (ESC/POS) to the CUPS printer queue."""
        ipp_body = _build_ipp_print_job(self._printer_uri, job_name, data)
        with self._lock:
            try:
                resp = requests.post(
                    self._ipp_url,
                    data=ipp_body,
                    headers={"Content-Type": "application/ipp"},
                    timeout=_PRINT_TIMEOUT,
                )
                resp.raise_for_status()
                logger.info("CupsDriver: job '%s' submitted.", job_name)
            except requests.RequestException as exc:
                self.set_status("error", str(exc))
                logger.exception("CupsDriver: print failed: %s", exc)
                raise

    def print_text(self, text: str, job_name: str = "rpidriver-text"):
        """Print plain text via CUPS."""
        self.print_raw(text.encode("utf-8"), job_name=job_name)

    def print_image_receipt(self, receipt_b64: str, job_name: str = "rpidriver-receipt"):
        """
        Print a receipt received from Odoo 17/18/19 POS via CUPS.

        Converts the base64 JPEG to a PNG in memory and sends it as a raw
        print job.  Requires CUPS to be configured with a raster or PDF filter.
        """
        import io
        from base64 import b64decode

        from PIL import Image

        raw = b64decode(receipt_b64)
        im = Image.open(io.BytesIO(raw))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        self.print_raw(buf.getvalue(), job_name=job_name)

    def open_cashbox(self):
        """Cash drawer is not supported via CUPS — log a warning."""
        logger.warning("CupsDriver: cash drawer not supported over CUPS/IPP.")

    def print_receipt(self, receipt_data, job_name: str = "rpidriver-receipt"):
        """
        Print an Odoo POS receipt via CUPS.

        Accepts:
          - dict  : Odoo receipt object — formatted to text lines
          - str   : plain text sent as-is
          - list  : pre-split lines joined with newlines
        """
        from rpidriver.plugins.escpos_driver import _format_receipt

        if isinstance(receipt_data, dict):
            lines = _format_receipt(receipt_data)
            text = "\n".join(lines) + "\n\n\n"
        elif isinstance(receipt_data, list):
            text = "\n".join(receipt_data) + "\n\n\n"
        else:
            text = str(receipt_data)

        self.print_text(text, job_name=job_name)


# ── Plugin registration ───────────────────────────────────────────────────────

DRIVER_CLASS = CupsDriver
