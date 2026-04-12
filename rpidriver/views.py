"""
Web interface views for RPiDriver dashboard.
"""

import platform
import subprocess

from flask import Blueprint, render_template, redirect, session, url_for
from flask_babel import gettext as _

bp = Blueprint("views", __name__)


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
            statuses[name] = {"status": "error", "messages": [_("Driver unavailable")]}
    return render_template("status.html", statuses=statuses)


@bp.route("/system")
def system():
    info = {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "arch": platform.machine(),
    }
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=2
        )
        info["temperature"] = result.stdout.strip()
    except OSError:
        info["temperature"] = _("N/A (not a Raspberry Pi)")
    return render_template("system.html", info=info)


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
