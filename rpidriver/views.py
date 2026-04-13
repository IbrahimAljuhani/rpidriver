"""
Web interface views for RPiDriver dashboard.
"""

import logging
import os
import platform
import socket
import subprocess

from flask import Blueprint, jsonify, render_template, redirect, \
    session, url_for, Response
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
    # UDP-socket trick: connecting to an external address (no packet sent)
    # forces the OS to choose the correct outbound interface IP — avoids
    # returning 127.0.x.x that gethostbyname(gethostname()) often gives.
    # settimeout(2) prevents hanging if the routing table has no default route.
    try:
        _s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _s.settimeout(2)
        _s.connect(("8.8.8.8", 80))
        local_ip = _s.getsockname()[0]
        _s.close()
    except Exception:
        local_ip = "127.0.0.1"

    info = {
        "hostname": platform.node(),
        "ip": local_ip,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "arch": platform.machine(),
    }

    # 1) Try vcgencmd (Raspberry Pi firmware tool)
    # 2) Fall back to /sys/class/thermal/thermal_zone0/temp (works on all Linux SBCs)
    try:
        result = subprocess.run(
            ["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            info["temperature"] = result.stdout.strip()
        else:
            raise OSError("vcgencmd returned no data")
    except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as _f:
                _milli = int(_f.read().strip())
                info["temperature"] = f"{_milli / 1000:.1f} °C"
        except OSError:
            info["temperature"] = _("N/A")

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


@bp.route("/ssl/generate", methods=["POST"])
def ssl_generate():
    """
    POST /ssl/generate
    Generate a self-signed SSL certificate for HTTPS.

    Writes cert.pem + key.pem to /etc/rpidriver/ssl/ (the directory must be
    writable by the rpidriver service user — handled by install_pi.sh).
    Returns JSON so the UI can show progress without a full page reload.
    After success the user must restart the service to switch to HTTPS.
    """
    from rpidriver import get_config
    config  = get_config()
    ssl_dir = os.path.dirname(
        config.get("rpidriver", "ssl_cert", fallback="").strip()
        or "/etc/rpidriver/ssl/cert.pem"
    )
    cert_path = os.path.join(ssl_dir, "cert.pem")
    key_path  = os.path.join(ssl_dir, "key.pem")

    # Detect the Pi's outbound IP (more reliable than gethostbyname)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        pi_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pi_ip = "127.0.0.1"

    try:
        os.makedirs(ssl_dir, mode=0o755, exist_ok=True)
    except OSError as exc:
        return jsonify({"success": False, "error": f"Cannot create SSL dir: {exc}"}), 500

    san = f"subjectAltName=IP:{pi_ip},IP:127.0.0.1,DNS:rpidriver.local"

    try:
        result = subprocess.run(
            [
                "openssl", "req", "-x509",
                "-newkey", "rsa:2048",
                "-keyout", key_path,
                "-out",    cert_path,
                "-days",   "3650",
                "-nodes",
                "-subj",   "/C=SA/O=RPiDriver/CN=rpidriver",
                "-addext", san,
            ],
            capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")
            logger.error("ssl_generate openssl error: %s", err)
            return jsonify({"success": False, "error": err}), 500
    except FileNotFoundError:
        return jsonify({"success": False, "error": "openssl not found — install it first."}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "openssl timed out."}), 500
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500

    try:
        os.chmod(key_path,  0o600)
        os.chmod(cert_path, 0o644)
    except OSError as exc:
        logger.warning("ssl_generate: chmod failed: %s", exc)

    logger.info("ssl_generate: certificate generated at %s (IP: %s)", cert_path, pi_ip)
    return jsonify({
        "success": True,
        "ip":      pi_ip,
        "cert":    cert_path,
        "message": "Certificate generated — restart RPiDriver to enable HTTPS.",
    })


@bp.route("/ssl/cert.pem")
def ssl_download_cert():
    """
    GET /ssl/cert.pem
    Download the SSL certificate so the user can import it into:
      - The browser (to trust RPiDriver's HTTPS)
      - Odoo → Settings → Technical → IoT → trusted certificates
    """
    from rpidriver import get_config
    config    = get_config()
    cert_path = config.get("rpidriver", "ssl_cert", fallback="").strip() \
                or "/etc/rpidriver/ssl/cert.pem"

    if not os.path.exists(cert_path):
        return _("Certificate not found. Generate one first from the System page."), 404

    try:
        with open(cert_path, "r") as fh:
            cert_pem = fh.read()
    except OSError as exc:
        return str(exc), 500

    return Response(
        cert_pem,
        mimetype="application/x-pem-file",
        headers={"Content-Disposition": 'attachment; filename="rpidriver-cert.pem"'},
    )


@bp.route("/config")
def config():
    from rpidriver.config_schema import AVAILABLE_DRIVERS, DRIVER_LABELS, CONFIG_SCHEMA
    from rpidriver.api import _read_cfg, _cfg_to_dict, _merge_defaults
    cfg  = _read_cfg()
    raw  = _cfg_to_dict(cfg)
    active_raw = raw.get("rpidriver", {}).get("drivers", "")
    active_drivers = [d.strip() for d in active_raw.split(",") if d.strip()]
    return render_template(
        "config.html",
        schema          = CONFIG_SCHEMA,
        current         = _merge_defaults(raw),
        available_drivers = AVAILABLE_DRIVERS,
        active_drivers  = active_drivers,
        driver_labels   = DRIVER_LABELS,
    )


@bp.route("/logs")
def logs():
    return render_template("logs.html")


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
