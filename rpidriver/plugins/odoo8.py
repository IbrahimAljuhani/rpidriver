"""
hw_proxy endpoints — compatible with Odoo 17, 18, and 19.

All three versions send identical JSON-RPC 2.0 requests to these routes.
"""

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
        return _jsonrpc_result({"weight": 0.0, "unit": "kg", "status": "error"}, _get_jsonrpc_id())


@bp.route("/print_receipt", methods=["POST"])
def print_receipt():
    """
    POST /hw_proxy/print_receipt  (JSON-RPC)
    Accepts an ESC/POS receipt XML/JSON payload from Odoo POS and prints it.
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
