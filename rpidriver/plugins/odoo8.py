"""
hw_proxy endpoints — compatible with Odoo 13 through 19.

JSON-RPC 2.0 over HTTP.  All endpoints accept POST; /hello also accepts GET.
"""

import json
import logging

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("odoo8", __name__, url_prefix="/hw_proxy")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _jsonrpc_result(result, req_id=None):
    """Wrap a value in a JSON-RPC 2.0 result envelope."""
    return jsonify({"jsonrpc": "2.0", "id": req_id, "result": result})


def _jsonrpc_error(message: str, code: int = -32000, req_id=None):
    """Wrap an error in a JSON-RPC 2.0 error envelope."""
    return jsonify({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    })


def _get_jsonrpc_id():
    data = request.get_json(force=True, silent=True)
    return data.get("id") if data else None


def _get_drivers():
    from rpidriver import get_drivers
    return get_drivers()


# ── Endpoints ─────────────────────────────────────────────────────────────────


@bp.route("/hello")
def hello():
    """
    GET /hw_proxy/hello
    Odoo uses this as a connectivity probe. Must return the plain string "ping".
    """
    return "ping"


@bp.route("/handshake", methods=["POST"])
def handshake():
    """
    POST /hw_proxy/handshake  (JSON-RPC)
    Called by Odoo on POS startup to verify the proxy is alive.
    Returns: true
    """
    return _jsonrpc_result(True, _get_jsonrpc_id())


@bp.route("/status_json", methods=["POST"])
def status_json():
    """
    POST /hw_proxy/status_json  (JSON-RPC)
    Returns status of all registered drivers.

    Expected shape:
        {"escpos": {"status": "connected", "messages": []},
         "scale":  {"status": "disconnected", "messages": ["no device"]}}
    """
    drivers = _get_drivers()
    result = {}
    for name, drv in drivers.items():
        try:
            result[name] = drv.get_status()
        except Exception as exc:
            logger.warning("status_json: driver %s raised %s", name, exc)
            result[name] = {"status": "error", "messages": [str(exc)]}
    return _jsonrpc_result(result, _get_jsonrpc_id())


@bp.route("/scale_read", methods=["POST"])
def scale_read():
    """
    POST /hw_proxy/scale_read  (JSON-RPC)
    Returns the current weight from the scale driver.

    Expected shape: {"weight": 1.23}
    """
    drivers = _get_drivers()
    scale = drivers.get("scale_driver")
    if scale is None:
        return _jsonrpc_error("No scale driver loaded", req_id=_get_jsonrpc_id())
    try:
        reading = scale.read_weight()
        return _jsonrpc_result(reading, _get_jsonrpc_id())
    except Exception as exc:
        logger.exception("scale_read failed: %s", exc)
        return _jsonrpc_error(str(exc), req_id=_get_jsonrpc_id())


@bp.route("/default_printer_action", methods=["POST"])
def default_printer_action():
    """
    POST /hw_proxy/default_printer_action  (JSON-RPC)
    Primary print endpoint for Odoo 17 / 18 / 19.

    params.data.action values:
      "print_receipt" — params.data.receipt is a base64 JPEG rendered from HTML canvas
      "cashbox"       — open the cash drawer
    """
    data = request.get_json(force=True, silent=True) or {}
    req_id = data.get("id")
    action_data = (data.get("params") or {}).get("data") or {}
    action = action_data.get("action", "")

    drivers = _get_drivers()
    printer = drivers.get("escpos_driver") or drivers.get("cups_driver")
    if printer is None:
        return _jsonrpc_error("No printer driver loaded", req_id=req_id)

    if action == "cashbox":
        try:
            printer.open_cashbox()
            return _jsonrpc_result(True, req_id)
        except Exception as exc:
            logger.exception("default_printer_action cashbox failed: %s", exc)
            return _jsonrpc_error(str(exc), req_id=req_id)

    if action == "print_receipt":
        receipt_b64 = action_data.get("receipt", "")
        try:
            printer.print_image_receipt(receipt_b64)
            return _jsonrpc_result(True, req_id)
        except Exception as exc:
            logger.exception("default_printer_action print failed: %s", exc)
            return _jsonrpc_error(str(exc), req_id=req_id)

    return _jsonrpc_error(f"Unknown action: {action!r}", req_id=req_id)


@bp.route("/print_receipt", methods=["POST"])
def print_receipt():
    """
    POST /hw_proxy/print_receipt  (JSON-RPC)
    Legacy endpoint for Odoo 13–16.  Odoo 17+ uses /hw_proxy/default_printer_action.
    """
    data = request.get_json(force=True, silent=True) or {}
    params = data.get("params", {})
    receipt = params.get("receipt", "")

    req_id = data.get("id")
    drivers = _get_drivers()
    printer = drivers.get("escpos_driver") or drivers.get("cups_driver")
    if printer is None:
        return _jsonrpc_error("No printer driver loaded", req_id=req_id)
    try:
        printer.print_receipt(receipt)
        return _jsonrpc_result(True, req_id)
    except Exception as exc:
        logger.exception("print_receipt failed: %s", exc)
        return _jsonrpc_error(str(exc), req_id=req_id)


@bp.route("/open_cashbox", methods=["POST", "GET"])
def open_cashbox():
    """
    POST /hw_proxy/open_cashbox  (JSON-RPC)
    Dedicated cash-drawer endpoint — called by some Odoo 13–16 versions directly.
    Odoo 17+ uses default_printer_action with action="cashbox".
    """
    req_id = _get_jsonrpc_id()
    drivers = _get_drivers()
    printer = drivers.get("escpos_driver") or drivers.get("cups_driver")
    if printer is None:
        return _jsonrpc_error("No printer driver loaded", req_id=req_id)
    try:
        printer.open_cashbox()
        return _jsonrpc_result(True, req_id)
    except Exception as exc:
        logger.exception("open_cashbox failed: %s", exc)
        return _jsonrpc_error(str(exc), req_id=req_id)


@bp.route("/send_text_customer_display", methods=["POST"])
def send_text_customer_display():
    """
    POST /hw_proxy/send_text_customer_display  (JSON-RPC)
    Called by Odoo POS to show product/price text on the customer display.

    params.text_to_display is a JSON-encoded list of strings:
        '["Product Name", "  12.50 SAR"]'
    """
    data = request.get_json(force=True, silent=True) or {}
    req_id = data.get("id")
    raw = (data.get("params") or {}).get("text_to_display", "[]")

    try:
        lines = json.loads(raw) if isinstance(raw, str) else list(raw)
    except (json.JSONDecodeError, TypeError):
        lines = [str(raw)]

    drivers = _get_drivers()
    display = drivers.get("display_driver")
    if display is not None:
        try:
            line1 = str(lines[0]) if len(lines) > 0 else ""
            line2 = str(lines[1]) if len(lines) > 1 else ""
            display.display_text(line1=line1, line2=line2)
        except Exception as exc:
            logger.warning("send_text_customer_display failed: %s", exc)

    # Always return True — display is optional; don't break POS if absent
    return _jsonrpc_result(True, req_id)


@bp.route("/log", methods=["POST", "GET"])
def log_proxy():
    """
    POST /hw_proxy/log  (JSON-RPC)
    Odoo POS sends client-side log messages here. We log them server-side
    and always return True so the POS doesn't report a network error.
    """
    data = request.get_json(force=True, silent=True) or {}
    arguments = (data.get("params") or {}).get("arguments", [])
    if arguments:
        logger.info("[odoo-pos] %s", " ".join(str(a) for a in arguments))
    return _jsonrpc_result(True, data.get("id"))


@bp.route("/print_xml_receipt", methods=["POST"])
def print_xml_receipt():
    """
    POST /hw_proxy/print_xml_receipt  (JSON-RPC)
    Legacy endpoint used by Odoo 8 / 9 / 10 / 11 with xmlescpos library.

    Odoo 13+ uses /hw_proxy/print_receipt.
    Odoo 17+ uses /hw_proxy/default_printer_action.

    We return a clear error message so the POS operator knows to upgrade,
    rather than a cryptic 404.
    """
    data = request.get_json(force=True, silent=True) or {}
    req_id = data.get("id")
    logger.info("print_xml_receipt called — this endpoint requires Odoo ≤ 11 / xmlescpos.")
    return _jsonrpc_result(
        {
            "status": "error",
            "message": (
                "print_xml_receipt is for Odoo 8–11 only. "
                "Use print_receipt (Odoo 13–16) or default_printer_action (Odoo 17+)."
            ),
        },
        req_id,
    )


@bp.route("/serial_read", methods=["POST"])
def serial_read():
    """
    POST /hw_proxy/serial_read  (JSON-RPC)
    Read data from a generic serial device managed by serial_driver.

    Expected params:
        device   — serial port path (e.g. "/dev/ttyUSB1")
        size     — number of bytes to read (default: 64)
        timeout  — read timeout in seconds (default: 1)

    Returns {"data": "<hex-encoded bytes>", "status": "ok"}
    """
    data = request.get_json(force=True, silent=True) or {}
    req_id = data.get("id")
    params = data.get("params") or {}

    drivers = _get_drivers()
    serial_drv = drivers.get("serial_driver")

    # Fallback: open the port directly if serial_driver is not loaded
    device = params.get("device", "")
    size = int(params.get("size", 64))
    timeout = float(params.get("timeout", 1.0))

    if serial_drv is not None:
        try:
            raw = serial_drv.read(size=size, timeout=timeout)
            return _jsonrpc_result({"data": raw.hex(), "status": "ok"}, req_id)
        except Exception as exc:
            logger.exception("serial_read via serial_driver failed: %s", exc)
            return _jsonrpc_error(str(exc), req_id=req_id)

    # Direct serial read (no serial_driver loaded)
    if not device:
        return _jsonrpc_error(
            "No serial_driver loaded and no 'device' param provided.", req_id=req_id
        )
    try:
        import serial as _serial
        with _serial.Serial(device, timeout=timeout) as ser:
            raw = ser.read(size)
        return _jsonrpc_result({"data": raw.hex(), "status": "ok"}, req_id)
    except Exception as exc:
        logger.exception("serial_read direct failed on %s: %s", device, exc)
        return _jsonrpc_error(str(exc), req_id=req_id)


@bp.route("/serial_write", methods=["POST"])
def serial_write():
    """
    POST /hw_proxy/serial_write  (JSON-RPC)
    Write data to a generic serial device managed by serial_driver.

    Expected params:
        device   — serial port path (e.g. "/dev/ttyUSB1")
        data     — hex-encoded bytes to send (e.g. "57" for Toledo 'W' command)
        timeout  — write timeout in seconds (default: 1)

    Returns {"bytes_written": N, "status": "ok"}
    """
    data = request.get_json(force=True, silent=True) or {}
    req_id = data.get("id")
    params = data.get("params") or {}

    drivers = _get_drivers()
    serial_drv = drivers.get("serial_driver")

    device = params.get("device", "")
    hex_data = params.get("data", "")
    timeout = float(params.get("timeout", 1.0))

    try:
        raw_bytes = bytes.fromhex(hex_data) if hex_data else b""
    except ValueError:
        return _jsonrpc_error(
            f"Invalid hex string: {hex_data!r}. "
            "Expected hex-encoded bytes, e.g. '57' for ASCII 'W'.",
            req_id=req_id,
        )

    if serial_drv is not None:
        try:
            n = serial_drv.write(raw_bytes)
            return _jsonrpc_result({"bytes_written": n, "status": "ok"}, req_id)
        except Exception as exc:
            logger.exception("serial_write via serial_driver failed: %s", exc)
            return _jsonrpc_error(str(exc), req_id=req_id)

    if not device:
        return _jsonrpc_error(
            "No serial_driver loaded and no 'device' param provided.", req_id=req_id
        )
    try:
        import serial as _serial
        with _serial.Serial(device, timeout=timeout) as ser:
            n = ser.write(raw_bytes)
        return _jsonrpc_result({"bytes_written": n, "status": "ok"}, req_id)
    except Exception as exc:
        logger.exception("serial_write direct failed on %s: %s", device, exc)
        return _jsonrpc_error(str(exc), req_id=req_id)


# ── Payment terminal endpoints ────────────────────────────────────────────────


def _get_payment_driver():
    """
    Return the first loaded PaymentTerminalDriver instance, or None.

    The plugin loader registers drivers by their plugin name (e.g. "neoleap_driver"),
    not by the generic key "payment_driver".  We therefore scan the drivers dict for
    any instance that inherits from PaymentTerminalDriver rather than looking up a
    fixed key — this makes the payment endpoints work automatically for any current
    or future payment terminal driver without configuration changes.
    """
    from rpidriver.plugins.payment_base_driver import PaymentTerminalDriver
    for drv in _get_drivers().values():
        if isinstance(drv, PaymentTerminalDriver):
            return drv
    return None


@bp.route("/payment_terminal_transaction_start", methods=["POST"])
def payment_terminal_transaction_start():
    """
    POST /hw_proxy/payment_terminal_transaction_start  (JSON-RPC)
    Initiate a payment transaction on the connected terminal.

    Expected params (Odoo POS standard):
        amount      — amount in smallest currency unit (halalas / fils)
        currency_id — ISO 4217 numeric currency code  (e.g. 682 = SAR)
        payment_mode — "debit" | "credit"

    Returns:
        {"status": "waiting" | "accepted" | "error", "message": str}
    """
    data = request.get_json(force=True, silent=True) or {}
    req_id = data.get("id")
    params = (data.get("params") or {})

    terminal = _get_payment_driver()
    if terminal is None:
        logger.warning("payment_terminal_transaction_start: no payment_driver loaded.")
        return _jsonrpc_result(
            {"status": "error", "message": "No payment terminal driver loaded."},
            req_id,
        )
    try:
        result = terminal.transaction_start(params)
        return _jsonrpc_result(result, req_id)
    except Exception as exc:
        logger.exception("payment_terminal_transaction_start failed: %s", exc)
        return _jsonrpc_result({"status": "error", "message": str(exc)}, req_id)


@bp.route("/payment_terminal_transaction_status", methods=["POST"])
def payment_terminal_transaction_status():
    """
    POST /hw_proxy/payment_terminal_transaction_status  (JSON-RPC)
    Poll the current state of the active payment transaction.

    Odoo POS calls this repeatedly after transaction_start until it gets
    a terminal status of "accepted", "cancelled", or "error".

    Returns:
        {
            "status":  "waiting" | "accepted" | "cancelled" | "error",
            "message": str,
            "ticket":  str | None,   # receipt text from the terminal
        }
    """
    data = request.get_json(force=True, silent=True) or {}
    req_id = data.get("id")

    terminal = _get_payment_driver()
    if terminal is None:
        return _jsonrpc_result(
            {"status": "error", "message": "No payment terminal driver loaded."},
            req_id,
        )
    try:
        result = terminal.transaction_status()
        return _jsonrpc_result(result, req_id)
    except Exception as exc:
        logger.exception("payment_terminal_transaction_status failed: %s", exc)
        return _jsonrpc_result({"status": "error", "message": str(exc)}, req_id)


@bp.route("/payment_terminal_transaction_cancel", methods=["POST"])
def payment_terminal_transaction_cancel():
    """
    POST /hw_proxy/payment_terminal_transaction_cancel  (JSON-RPC)
    Cancel / abort the active payment transaction.

    Called by Odoo POS when the cashier presses the cancel button,
    or when a timeout occurs on the POS side.

    Returns:
        {"status": "cancelled" | "error", "message": str}
    """
    data = request.get_json(force=True, silent=True) or {}
    req_id = data.get("id")

    terminal = _get_payment_driver()
    if terminal is None:
        return _jsonrpc_result(
            {"status": "cancelled", "message": "No payment terminal driver loaded."},
            req_id,
        )
    try:
        result = terminal.cancel()
        return _jsonrpc_result(result, req_id)
    except Exception as exc:
        logger.exception("payment_terminal_transaction_cancel failed: %s", exc)
        return _jsonrpc_result({"status": "error", "message": str(exc)}, req_id)
