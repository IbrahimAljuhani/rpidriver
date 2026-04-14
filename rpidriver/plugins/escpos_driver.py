"""
ESC/POS USB printer driver.

Supports:
  - Epson TM-T20 / T82 / T88  (vendor 0x04b8)
  - Star Micronics TSP series  (vendor 0x0519)
  - Any ESC/POS compatible USB printer

Registered in drivers{} as "escpos_driver".
"""

import logging
import queue
import threading

try:
    import usb.core
    import usb.util
    _USB_AVAILABLE = True
except ImportError:
    _USB_AVAILABLE = False

from rpidriver.plugins.base_driver import AbstractDriver

logger = logging.getLogger(__name__)

# ── Known printer vendor/product IDs ─────────────────────────────────────────

KNOWN_PRINTERS = [
    # Epson
    {"vendor": 0x04B8, "product": 0x0202},  # TM-T88
    {"vendor": 0x04B8, "product": 0x0E15},  # TM-T20
    {"vendor": 0x04B8, "product": 0x0E28},  # TM-T82
    # Star Micronics
    {"vendor": 0x0519, "product": 0x0003},
    # Generic fallback — match any Epson
    {"vendor": 0x04B8, "product": None},
]

# ESC/POS command constants
ESC = b"\x1b"
GS = b"\x1d"
INIT = ESC + b"@"
CUT_PARTIAL = GS + b"V\x01"
LF = b"\n"
# Cash drawer pulse: ESC p pin t1 t2  (pin 0, 25ms on, 25ms off)
CASHBOX_PULSE = ESC + b"\x70\x00\x19\x19"


# ── Receipt renderer ──────────────────────────────────────────────────────────

def _format_receipt(
    receipt: dict,
    cols: int = 42,
    thank_you: str = "Thank you! — شكراً لزيارتكم",
) -> list[str]:
    """
    Convert an Odoo POS receipt dict to a list of printable text lines.

    Handles the receipt structure sent by Odoo 17/18/19 hw_proxy.
    """
    SEP = "-" * cols
    SEP2 = "=" * cols
    lines = []

    # ── Company header ────────────────────────────────────────────────────
    company = receipt.get("company", {})
    if company.get("name"):
        lines.append(company["name"].center(cols))
    if company.get("phone"):
        lines.append(company["phone"].center(cols))
    if company.get("email"):
        lines.append(company["email"].center(cols))
    if company.get("vat"):
        lines.append(f"VAT: {company['vat']}".center(cols))
    if company.get("street"):
        lines.append(company["street"].center(cols))
    lines.append(SEP)

    # ── Order info ────────────────────────────────────────────────────────
    half = cols // 2
    if receipt.get("name"):
        lines.append(f"{'Order':<{half}}{receipt['name'][:half]:>{half}}")
    if receipt.get("date"):
        date_val = receipt["date"]
        if isinstance(date_val, dict):
            date_val = date_val.get("repr", str(date_val))
        lines.append(f"{'Date':<{half}}{str(date_val)[:half]:>{half}}")
    if receipt.get("cashier"):
        lines.append(f"{'Cashier':<{half}}{receipt['cashier'][:half]:>{half}}")
    lines.append(SEP)

    # ── Order lines ───────────────────────────────────────────────────────
    for ol in receipt.get("orderlines", []):
        name = str(ol.get("product_name", ""))
        qty = ol.get("qty", 1)
        price_display = str(ol.get("price_display", f"{ol.get('price_with_tax', 0):.2f}"))

        # Product name on its own line (truncated to fit)
        lines.append(name[:cols])
        # Qty × price right-aligned
        detail = f"  {qty} x {price_display}"
        lines.append(detail.rjust(cols))

    lines.append(SEP2)

    # ── Totals ────────────────────────────────────────────────────────────
    subtotal = receipt.get("total_without_tax", receipt.get("amount_untaxed", 0))
    tax_amt = receipt.get("total_tax", receipt.get("amount_tax", 0))
    total = receipt.get("total_with_tax", receipt.get("amount_total", 0))
    paid = receipt.get("amount_paid", total)
    change = receipt.get("amount_return", max(0.0, float(paid) - float(total)))

    label_w = cols - 12
    if subtotal:
        lines.append(f"{'Subtotal':<{label_w}}{float(subtotal):>10.2f}")
    if tax_amt:
        lines.append(f"{'VAT':<{label_w}}{float(tax_amt):>10.2f}")
    lines.append(f"{'TOTAL':<{label_w}}{float(total):>10.2f}")

    # ── Payment lines ─────────────────────────────────────────────────────
    for pl in receipt.get("paymentlines", []):
        method = str(pl.get("name", "Payment"))
        amount = float(pl.get("amount", 0))
        lines.append(f"{method:<{label_w}}{amount:>10.2f}")

    if change:
        lines.append(f"{'Change':<{label_w}}{float(change):>10.2f}")

    lines.append(SEP2)
    lines.append("")
    lines.append(thank_you.center(cols))
    lines.append("")

    return lines


class EscposDriver(AbstractDriver):
    name = "escpos_driver"

    def __init__(self, config=None):
        super().__init__(config)
        self._device = None
        self._endpoint_out = None
        self._lock = threading.Lock()
        _pw = int((config or {}).get("paper_width", 576))
        if _pw not in (384, 576):
            logger.warning(
                "EscposDriver: unexpected paper_width=%d — expected 384 (58mm) or 576 (80mm). Defaulting to 576.",
                _pw,
            )
            _pw = 576
        self._paper_width = _pw
        self._font_path = (config or {}).get("arabic_font_path") or None
        self._thank_you = (config or {}).get(
            "thank_you_message", "Thank you! — شكراً لزيارتكم"
        )
        # 42 chars for 80mm paper, 32 for 58mm
        self._cols = 42 if self._paper_width >= 576 else 32

        # ── Optional USB vendor/product override ──────────────────────────
        # When set, only a printer with this exact vendor:product is used.
        # Leave empty to auto-detect from KNOWN_PRINTERS (default).
        _raw_vendor  = str((config or {}).get("usb_vendor",  "")).strip().lower()
        _raw_product = str((config or {}).get("usb_product", "")).strip().lower()
        try:
            self._usb_vendor  = int(_raw_vendor,  16) if _raw_vendor  else None
        except ValueError:
            logger.warning("EscposDriver: invalid usb_vendor %r — ignored.", _raw_vendor)
            self._usb_vendor = None
        try:
            self._usb_product = int(_raw_product, 16) if _raw_product else None
        except ValueError:
            logger.warning("EscposDriver: invalid usb_product %r — ignored.", _raw_product)
            self._usb_product = None

        # ── Print queue: serialises concurrent print requests ─────────────
        # Odoo POS may fire multiple print requests simultaneously (e.g. receipt
        # + cashbox pulse).  The queue ensures USB writes never overlap, which
        # would corrupt the output or raise a USBError.
        self._print_queue: queue.Queue = queue.Queue()
        self._queue_thread = threading.Thread(
            target=self._process_queue,
            name="rpidriver-print-queue",
            daemon=True,
        )

        # Connect to hardware first — queue thread starts after so it never
        # races with an uninitialised device handle.
        self._connect()

        self._queue_thread.start()
        logger.info("EscposDriver: print queue started.")

    # ── AbstractDriver ────────────────────────────────────────────────────

    def get_device(self):
        return self._device

    # ── Connection ────────────────────────────────────────────────────────

    def _connect(self):
        """Attempt to find and open a USB printer."""
        if not _USB_AVAILABLE:
            self.set_status("error", "pyusb not installed — run: pip install pyusb")
            logger.error("EscposDriver: pyusb not available.")
            return

        # Release resources held by any previous device handle before resetting state
        if self._device is not None:
            try:
                usb.util.dispose_resources(self._device)
            except Exception:
                pass
        self._device = None
        self._endpoint_out = None

        # If the operator pinned a specific vendor:product, try that first.
        if self._usb_vendor is not None:
            kwargs = {"idVendor": self._usb_vendor}
            if self._usb_product is not None:
                kwargs["idProduct"] = self._usb_product
            dev = usb.core.find(**kwargs)
            if dev is not None:
                self._device = dev
                logger.info(
                    "EscposDriver: using pinned USB device %04x:%s",
                    self._usb_vendor,
                    f"{self._usb_product:04x}" if self._usb_product else "*",
                )
            else:
                logger.warning(
                    "EscposDriver: pinned USB device %04x:%s not found — "
                    "falling back to auto-detect.",
                    self._usb_vendor,
                    f"{self._usb_product:04x}" if self._usb_product else "*",
                )

        # Auto-detect from KNOWN_PRINTERS if no device found yet
        if self._device is None:
            for spec in KNOWN_PRINTERS:
                kwargs = {"idVendor": spec["vendor"]}
                if spec["product"] is not None:
                    kwargs["idProduct"] = spec["product"]
                dev = usb.core.find(**kwargs)
                if dev is not None:
                    self._device = dev
                    break

        if self._device is None:
            self.set_status("disconnected", "No ESC/POS printer found on USB")
            logger.warning("EscposDriver: no printer found.")
            return

        try:
            try:
                if self._device.is_kernel_driver_active(0):
                    self._device.detach_kernel_driver(0)
            except (NotImplementedError, usb.core.USBError):
                pass  # not supported on this platform / backend
            self._device.set_configuration()
            cfg = self._device.get_active_configuration()
            intf = cfg[(0, 0)]
            self._endpoint_out = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                == usb.util.ENDPOINT_OUT,
            )
            if self._endpoint_out is None:
                logger.warning(
                    "EscposDriver: no OUT endpoint on %04x:%04x",
                    self._device.idVendor,
                    self._device.idProduct,
                )
                self._device = None
                self.set_status("error", "No OUT endpoint found on printer interface")
                return
            self.set_status("connected")
            logger.info(
                "EscposDriver: connected to %04x:%04x",
                self._device.idVendor,
                self._device.idProduct,
            )
        except Exception as exc:
            self._device = None
            self._endpoint_out = None
            self.set_status("error", str(exc))
            logger.exception("EscposDriver: failed to open device: %s", exc)

    # ── Low-level write ───────────────────────────────────────────────────

    def _write(self, data: bytes):
        """Write raw bytes to the USB endpoint (called from the queue thread)."""
        with self._lock:
            if self._endpoint_out is None:
                self._connect()
            if self._endpoint_out is None:
                raise IOError("Printer not connected")
            self._endpoint_out.write(data)

    # ── Print queue ───────────────────────────────────────────────────────

    def _process_queue(self):
        """
        Background thread: drain the print queue one job at a time.

        Serialising all USB writes via a queue prevents concurrent access that
        would corrupt the print output or raise a usb.core.USBError.
        A sentinel value of ``None`` shuts the thread down cleanly on close().
        """
        while True:
            job = self._print_queue.get()
            if job is None:          # sentinel — shut down
                self._print_queue.task_done()
                break
            func, args = job
            try:
                func(*args)
            except Exception as exc:
                logger.exception("EscposDriver: print job failed: %s", exc)
                self.set_status("error", str(exc))
            finally:
                self._print_queue.task_done()

    def _enqueue(self, func, *args):
        """Add a print job to the queue (non-blocking, returns immediately)."""
        self._print_queue.put((func, args))

    # ── High-level API (public — non-blocking, enqueued) ──────────────────

    def print_receipt(self, receipt_data: str | dict | list):
        """
        Queue an Odoo POS receipt for printing.

        Accepts:
          - dict  : Odoo receipt object (orderlines, totals, company, etc.)
          - str   : plain text (Arabic lines rendered as bitmaps)
          - list  : pre-split lines

        Returns immediately; the job is printed in the background queue thread.
        """
        self._enqueue(self._do_print_receipt, receipt_data)

    def print_image_receipt(self, receipt_b64: str):
        """
        Queue a base64 JPEG receipt from Odoo 17/18/19 POS.

        Returns immediately; the job is processed in the background queue thread.
        """
        self._enqueue(self._do_print_image_receipt, receipt_b64)

    def open_cashbox(self):
        """Queue a cash drawer open pulse (ESC p)."""
        self._enqueue(self._write, CASHBOX_PULSE)

    def print_text(self, text: str):
        """Queue raw text bytes for printing (Latin only — no Arabic reshaping)."""
        self._enqueue(self._write, INIT + text.encode("cp437", errors="replace") + LF)

    def cut(self):
        """Queue a partial cut command."""
        self._enqueue(self._write, LF * 3 + CUT_PARTIAL)

    # ── Synchronous internals (called only from queue thread) ─────────────

    def _do_print_receipt(self, receipt_data: str | dict | list):
        from rpidriver.plugins.arabic_escpos import render_receipt_lines

        if isinstance(receipt_data, dict):
            lines = _format_receipt(receipt_data, cols=self._cols, thank_you=self._thank_you)
        elif isinstance(receipt_data, list):
            lines = receipt_data
        else:
            lines = str(receipt_data).splitlines()

        payload = (
            INIT
            + render_receipt_lines(
                lines, width_px=self._paper_width, font_path=self._font_path
            )
            + LF * 3
            + CUT_PARTIAL
        )
        self._write(payload)

    def _do_print_image_receipt(self, receipt_b64: str):
        """
        Print a receipt received from Odoo 17/18/19 POS.

        Odoo renders the HTML receipt to a canvas, encodes it as base64 JPEG,
        and sends it to /hw_proxy/default_printer_action.  This method:
          1. Decodes the base64 JPEG
          2. Converts to greyscale → inverts → 1-bit bitmap
          3. Encodes as ESC/POS GS v 0 raster command
          4. Sends to the printer with a partial cut
        """
        import io
        from base64 import b64decode

        from PIL import Image, ImageOps

        from rpidriver.plugins.arabic_escpos import image_to_escpos_raster

        raw = b64decode(receipt_b64)
        im = Image.open(io.BytesIO(raw))

        # Match the IoT box colour pipeline: greyscale → invert → 1-bit
        im = im.convert("L")
        im = ImageOps.invert(im)
        im = im.convert("1")

        # Scale width to match paper (preserving aspect ratio)
        if im.width != self._paper_width:
            ratio = self._paper_width / im.width
            new_h = max(1, int(im.height * ratio))
            im = im.resize((self._paper_width, new_h), Image.LANCZOS)

        payload = INIT + image_to_escpos_raster(im) + LF * 3 + CUT_PARTIAL
        self._write(payload)

    def close(self):
        """
        Drain the print queue, then release USB resources.

        Sends a sentinel None to the queue thread so it exits cleanly before
        the USB device handle is disposed.
        """
        # Signal queue thread to stop and wait for it
        self._print_queue.put(None)
        self._queue_thread.join(timeout=10)
        if self._queue_thread.is_alive():
            logger.warning(
                "EscposDriver: print queue thread did not exit within 10 s — "
                "remaining jobs may be lost. The thread is daemon=True and will "
                "be killed when the process exits."
            )

        if self._device is not None and _USB_AVAILABLE:
            try:
                usb.util.dispose_resources(self._device)
            except Exception:
                pass
        self._device = None
        self._endpoint_out = None
        self.set_status("disconnected")


# ── Plugin registration ───────────────────────────────────────────────────────

DRIVER_CLASS = EscposDriver
