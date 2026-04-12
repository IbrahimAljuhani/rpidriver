"""
ESC/POS USB printer driver.

Supports:
  - Epson TM-T20 / T82 / T88  (vendor 0x04b8)
  - Star Micronics TSP series  (vendor 0x0519)
  - Any ESC/POS compatible USB printer

Registered in drivers{} as "escpos_driver".
"""

import logging
import threading

import usb.core
import usb.util

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


# ── Receipt renderer ──────────────────────────────────────────────────────────

def _format_receipt(receipt: dict, cols: int = 42) -> list[str]:
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
    lines.append("Thank you! — شكراً لزيارتكم".center(cols))
    lines.append("")

    return lines


class EscposDriver(AbstractDriver):
    name = "escpos_driver"

    def __init__(self, config=None):
        super().__init__(config)
        self._device = None
        self._endpoint_out = None
        self._lock = threading.Lock()
        self._paper_width = int((config or {}).get("paper_width", 576))
        self._font_path = (config or {}).get("arabic_font_path") or None
        # 42 chars for 80mm paper, 32 for 58mm
        self._cols = 42 if self._paper_width >= 576 else 32
        self._connect()

    # ── AbstractDriver ────────────────────────────────────────────────────

    def get_device(self):
        return self._device

    # ── Connection ────────────────────────────────────────────────────────

    def _connect(self):
        """Attempt to find and open a USB printer."""
        # Always reset state before attempting a new connection
        self._device = None
        self._endpoint_out = None

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
        if self._endpoint_out is None:
            self._connect()
        if self._endpoint_out is None:
            raise IOError("Printer not connected")
        with self._lock:
            self._endpoint_out.write(data)

    # ── High-level API ────────────────────────────────────────────────────

    def print_receipt(self, receipt_data: str | dict | list):
        """
        Print an Odoo POS receipt.

        Accepts:
          - dict  : Odoo receipt object (orderlines, totals, company, etc.)
          - str   : plain text (Arabic lines rendered as bitmaps)
          - list  : pre-split lines
        """
        from rpidriver.plugins.arabic_escpos import render_receipt_lines

        if isinstance(receipt_data, dict):
            lines = _format_receipt(receipt_data, cols=self._cols)
            cut = True
        elif isinstance(receipt_data, list):
            lines = receipt_data
            cut = True
        else:
            lines = str(receipt_data).split("\n")
            cut = True

        payload = (
            INIT
            + render_receipt_lines(
                lines, width_px=self._paper_width, font_path=self._font_path
            )
        )
        if cut:
            payload += LF * 3 + CUT_PARTIAL

        self._write(payload)

    def print_text(self, text: str):
        """Print raw text bytes (Latin only — no Arabic reshaping)."""
        self._write(INIT + text.encode("cp437", errors="replace") + LF)

    def cut(self):
        """Send a partial cut command."""
        self._write(LF * 3 + CUT_PARTIAL)


# ── Plugin registration ───────────────────────────────────────────────────────

DRIVER_CLASS = EscposDriver
