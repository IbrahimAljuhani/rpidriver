"""
Web interface views for RPiDriver dashboard.
"""

import logging
import os
import platform
import subprocess

from flask import Blueprint, render_template, redirect, session, url_for
from flask_babel import gettext as _

bp = Blueprint("views", __name__)
logger = logging.getLogger(__name__)


def _get_drivers():
    from rpidriver import get_drivers
    return get_drivers()


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/status")
def status():
    drivers = _get_drivers()
    statuses = {}
    for name, drv in drivers.items():
        try:
            statuses[name] = drv.get_status()
        except Exception:
            logger.warning("status: driver %s unavailable", name, exc_info=True)
            statuses[name] = {"status": "error", "messages": [_("Driver unavailable")]}
    return render_template("status.html", statuses=statuses)


@bp.route("/system")
def system():
    import socket
    try:
        local_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        local_ip = "127.0.0.1"

    info = {
        "hostname": platform.node(),
        "ip": local_ip,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "arch": platform.machine(),
    }
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            info["temperature"] = result.stdout.strip()
        else:
            info["temperature"] = _("N/A")
    except OSError:
        info["temperature"] = _("N/A (not a Raspberry Pi)")

    ssl_info = _get_ssl_info()
    return render_template("system.html", info=info, ssl=ssl_info)


def _get_ssl_info() -> dict:
    """
    Read SSL certificate information for display in the system dashboard.
    Checks the config-defined path first, then the default install location.
    """
    from rpidriver import get_config
    config = get_config()

    cert_path = config.get("rpidriver", "ssl_cert", fallback="").strip()
    if not cert_path:
        cert_path = "/etc/rpidriver/ssl/cert.pem"

    if not os.path.exists(cert_path):
        return {"enabled": False, "cert_path": cert_path, "expires": None}

    # Read certificate expiry via openssl (always available on Linux)
    expires = _("N/A")
    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout", "-enddate"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            expires = result.stdout.strip().replace("notAfter=", "")
    except OSError:
        pass  # openssl not available (Windows dev env)

    return {"enabled": True, "cert_path": cert_path, "expires": expires}


@bp.route("/usb_devices")
def usb_devices():
    devices = []
    try:
        import usb.core  # lazy import — pyusb optional at module load time

        for dev in usb.core.find(find_all=True):
            devices.append(
                {
                    "vendor_id": f"0x{dev.idVendor:04x}",
                    "product_id": f"0x{dev.idProduct:04x}",
                    "manufacturer": _safe_str(dev, "manufacturer"),
                    "product": _safe_str(dev, "product"),
                }
            )
    except Exception:
        logger.debug("usb_devices: enumeration failed", exc_info=True)
        devices = []
    return render_template("usb_devices.html", devices=devices)


@bp.route("/lang/<locale>")
def set_language(locale):
    if locale in ("ar", "en"):
        session["lang"] = locale
    return redirect(url_for("views.index"))


def _safe_str(dev, attr):
    try:
        return getattr(dev, attr) or ""
    except Exception:
        return ""
