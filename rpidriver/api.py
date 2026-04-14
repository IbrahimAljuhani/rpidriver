"""
REST API — configuration management, service control, and log streaming.

Endpoints
─────────
GET  /api/config              Return current config.ini as JSON
POST /api/config              Write updated values to config.ini
POST /api/service/restart     Restart the rpidriver systemd service
GET  /api/logs                Return last N log lines as JSON
GET  /api/logs/stream         Server-Sent Events: live log tail
"""

import functools
import logging
import os
import re
import subprocess
import tempfile
from configparser import ConfigParser

from flask import Blueprint, Response, jsonify, request, session, stream_with_context

from rpidriver.config_schema import AVAILABLE_DRIVERS, CONFIG_SCHEMA

logger = logging.getLogger(__name__)

bp = Blueprint("api", __name__, url_prefix="/api")


def _require_auth(f):
    """Protect API endpoints with the same session-based auth as the dashboard."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        from rpidriver import get_config
        pwd = get_config().get("rpidriver", "dashboard_password", fallback="").strip()
        if pwd and not session.get("authenticated"):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

_SERVICE_NAME = "rpidriver"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _config_path() -> str:
    return os.environ.get("RPIDRIVER_CONFIG", "/etc/rpidriver/config.ini")


def _read_cfg() -> ConfigParser:
    from configparser import Error as _CfgError
    cfg = ConfigParser()
    try:
        cfg.read(_config_path())
    except _CfgError as exc:
        logger.error("Config file is malformed: %s", exc)
        # Return an empty config — the caller will fall back to schema defaults
    return cfg


def _cfg_to_dict(cfg: ConfigParser) -> dict:
    return {
        section: dict(cfg.items(section))
        for section in cfg.sections()
    }


def _merge_defaults(raw: dict) -> dict:
    """
    Merge raw config values with schema defaults so the API always returns
    a complete set of keys even for options not yet written to config.ini.
    """
    result = {}
    for section, fields in CONFIG_SCHEMA.items():
        result[section] = {}
        for key, meta in fields.items():
            if key.startswith("_"):
                continue
            result[section][key] = raw.get(section, {}).get(key, meta.get("default", ""))
    return result


# ── Config endpoints ──────────────────────────────────────────────────────────

@bp.route("/config", methods=["GET"])
@_require_auth
def config_get():
    """Return the current configuration as JSON (merged with schema defaults)."""
    cfg = _read_cfg()
    raw = _cfg_to_dict(cfg)
    return jsonify(_merge_defaults(raw))


@bp.route("/config", methods=["POST"])
@_require_auth
def config_save():
    """
    Write posted JSON values to config.ini.

    Expected body:  { "section": { "key": "value", … }, … }
    Response:       { "success": bool, "restart_required": bool, "error"?: str }
    """
    data = request.get_json(force=True, silent=True) or {}
    cfg  = _read_cfg()
    restart_required = False

    for section, fields in data.items():
        if not isinstance(fields, dict):
            continue

        # Reject sections not defined in the schema
        schema_section = CONFIG_SCHEMA.get(section)
        if schema_section is None:
            logger.warning("api.config_save: unknown section %r — skipped", section)
            continue

        if not cfg.has_section(section):
            cfg.add_section(section)

        for key, value in fields.items():
            if key.startswith("_"):
                continue

            # Reject keys not defined in the schema
            if key not in schema_section:
                logger.warning("api.config_save: unknown key %r in [%s] — skipped", key, section)
                continue

            str_val = str(value).strip()
            schema_field = schema_section.get(key, {})
            field_type   = schema_field.get("type", "text")

            # ── Server-side type / range validation ──────────────────────────
            if field_type == "number":
                if str_val == "":
                    str_val = str(schema_field.get("default", ""))
                try:
                    num = float(str_val)
                except (ValueError, TypeError):
                    return jsonify({"success": False,
                                    "error": f"[{section}] {key}: must be a number"}), 400
                min_val = schema_field.get("min")
                max_val = schema_field.get("max")
                if min_val is not None and num < min_val:
                    return jsonify({"success": False,
                                    "error": f"[{section}] {key}: minimum value is {min_val}"}), 400
                if max_val is not None and num > max_val:
                    return jsonify({"success": False,
                                    "error": f"[{section}] {key}: maximum value is {max_val}"}), 400
            elif field_type == "select":
                valid = {v for v, _ in schema_field.get("options", [])}
                if str_val and str_val not in valid:
                    return jsonify({"success": False,
                                    "error": f"[{section}] {key}: invalid option '{str_val}'"}), 400
            elif field_type in ("text", "password"):
                maxlen = schema_field.get("maxlength")
                if maxlen and len(str_val.encode("utf-8")) > int(maxlen):
                    return jsonify({"success": False,
                                    "error": f"[{section}] {key}: exceeds max length of {maxlen}"}), 400

            # ── Detect restart-required changes ───────────────────────────────
            # Compare against the effective current value (schema default when
            # the key is absent) to avoid false positives on the first save.
            default_str = str(schema_field.get("default", ""))
            effective   = cfg.get(section, key, fallback=default_str).strip()
            if schema_field.get("restart") and effective != str_val:
                restart_required = True

            if effective != str_val and schema_field.get("type") not in ("password",):
                logger.info(
                    "CONFIG AUDIT [%s] %s: %r → %r (by %s)",
                    section, key, effective, str_val,
                    request.remote_addr,
                )
            cfg.set(section, key, str_val)

    # ── Atomic write: temp file → os.replace() ───────────────────────────────
    # Prevents a corrupt config.ini if the process dies mid-write.
    config_path = _config_path()
    config_dir  = os.path.dirname(config_path) or "."
    try:
        fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                cfg.write(fh)
            os.replace(tmp_path, config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        logger.info("api.config_save: config.ini written (restart_required=%s)", restart_required)
    except OSError as exc:
        logger.error("api.config_save: write failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500

    return jsonify({"success": True, "restart_required": restart_required})


# ── Service control ───────────────────────────────────────────────────────────

@bp.route("/service/restart", methods=["POST"])
@_require_auth
def service_restart():
    """
    Restart the rpidriver systemd service via sudo.

    Requires the sudoers entry created by install_pi.sh:
        rpidriver ALL=(ALL) NOPASSWD: /bin/systemctl restart rpidriver

    Returns:
        { "success": bool, "error"?: str, "hint"?: str }
    """
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", _SERVICE_NAME],
            capture_output=True, timeout=15,
        )
        if result.returncode == 0:
            logger.info("api.service_restart: service restarted successfully.")
            return jsonify({"success": True})

        err = result.stderr.decode(errors="replace").strip()
        logger.warning("api.service_restart: systemctl returned %d: %s", result.returncode, err)
        return jsonify({
            "success": False,
            "error"  : err or f"systemctl exited with code {result.returncode}",
            "hint"   : f"sudo systemctl restart {_SERVICE_NAME}",
        })
    except FileNotFoundError:
        return jsonify({
            "success": False,
            "error"  : "sudo or systemctl not found.",
            "hint"   : f"sudo systemctl restart {_SERVICE_NAME}",
        })
    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "error"  : "Restart timed out.",
            "hint"   : f"sudo systemctl restart {_SERVICE_NAME}",
        })
    except Exception as exc:
        logger.exception("api.service_restart: unexpected error: %s", exc)
        return jsonify({
            "success": False,
            "error"  : str(exc),
            "hint"   : f"sudo systemctl restart {_SERVICE_NAME}",
        })


# ── NeoLeap ping (unauthenticated — reachability only, no secrets) ────────────

@bp.route("/neoleap/ping", methods=["GET"])
def neoleap_ping():
    """
    GET /api/neoleap/ping

    Test TCP connectivity from the Pi to the configured NeoLeap terminal.
    Deliberately unauthenticated — returns only reachability info (no sensitive config).
    Called by the Odoo payment method 'Test Connection' button so the test runs
    from the Pi (the actual communication path) rather than from the Odoo server.
    """
    import socket as _sock
    from rpidriver import get_drivers

    drv = get_drivers().get("neoleap_driver")
    if drv is None:
        return jsonify({
            "reachable": False,
            "error"    : "neoleap_driver is not loaded — enable it in RPiDriver config",
        })

    ip   = getattr(drv, "_neoleap_ip", "")
    port = getattr(drv, "_port", 9998)

    if not ip:
        return jsonify({
            "reachable": False, "ip": ip, "port": port,
            "error"    : "neoleap_ip is not configured in RPiDriver",
        })

    try:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        s.settimeout(5)
        s.connect((ip, port))
        s.close()
        return jsonify({"reachable": True, "ip": ip, "port": port})
    except OSError as exc:
        return jsonify({"reachable": False, "ip": ip, "port": port, "error": str(exc)})


# ── Health check (unauthenticated) ────────────────────────────────────────────

@bp.route("/health", methods=["GET"])
def health():
    """
    GET /api/health
    Returns overall status and per-driver status.
    Unauthenticated — safe to call from monitoring tools and Odoo.
    """
    from rpidriver import get_drivers
    drivers = get_drivers()
    statuses = {}
    for name, drv in drivers.items():
        try:
            statuses[name] = drv.get_status()
        except Exception as exc:
            statuses[name] = {"status": "error", "messages": [str(exc)]}

    # Overall status: ok if all loaded drivers are connected, degraded otherwise
    if not statuses:
        overall = "ok"   # No drivers configured yet
    elif all(s.get("status") == "connected" for s in statuses.values()):
        overall = "ok"
    else:
        overall = "degraded"

    return jsonify({"status": overall, "drivers": statuses})


# ── Log endpoints ─────────────────────────────────────────────────────────────

@bp.route("/logs")
@_require_auth
def logs_get():
    """
    GET /api/logs?lines=200
    Return recent log lines as JSON.
    """
    try:
        lines = max(1, min(int(request.args.get("lines", 200)), 1000))
    except (TypeError, ValueError):
        lines = 200
    try:
        result = subprocess.run(
            [
                "journalctl", "-u", _SERVICE_NAME,
                f"-n{lines}", "--no-pager",
                "--output=short-iso",
            ],
            capture_output=True, text=True, timeout=5,
        )
        log_text = result.stdout or "(no log entries)"
    except FileNotFoundError:
        log_text = "(journalctl not available — not running under systemd)"
    except Exception as exc:
        log_text = f"Error reading logs: {exc}"

    return jsonify({"logs": log_text})


@bp.route("/logs/stream")
@_require_auth
def logs_stream():
    """
    GET /api/logs/stream
    Server-Sent Events: live tail of the rpidriver journal.

    The client connects once and receives new log lines as they appear.
    Each SSE message contains one log line as plain text.
    """
    @stream_with_context
    def generate():
        try:
            proc = subprocess.Popen(
                [
                    "journalctl", "-u", _SERVICE_NAME,
                    "-f", "--no-pager",
                    "-n50",                       # send last 50 lines on connect
                    "--output=short-monotonic",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except FileNotFoundError:
            yield "data: (journalctl not available)\n\n"
            return

        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    # SSE format: "data: <payload>\n\n"
                    # Replace any embedded newlines so they don't break SSE framing
                    yield f"data: {line.replace(chr(10), ' ')}\n\n"
                # Detect if journalctl died unexpectedly
                if proc.poll() is not None:
                    yield "data: (log stream ended — service may have stopped)\n\n"
                    break
        except GeneratorExit:
            pass
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control"    : "no-cache",
            "X-Accel-Buffering": "no",      # disable nginx buffering
            "Connection"       : "keep-alive",
        },
    )


# ── CUPS printer management ───────────────────────────────────────────────────
#
# All lpadmin write commands are invoked via sudo.
# The sudoers entry (installed by install_pi.sh) grants:
#   rpidriver ALL=(ALL) NOPASSWD: /usr/sbin/lpadmin
# lpstat / lpinfo / lp are read/print commands that the lp group can run
# without sudo — no privilege escalation needed for those.

_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9_.\-]+$')


def _cups_run(cmd, **kwargs):
    """Run a shell command; return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10, **kwargs
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"{cmd[0]}: command not found — is CUPS installed?"
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"


def _cups_list_printers():
    """Return a list of dicts describing all CUPS printers."""
    printers = {}

    # ── Status ── lpstat -p ──────────────────────────────────────────────────
    _, out, _ = _cups_run(["lpstat", "-p"])
    for line in out.splitlines():
        if not line.startswith("printer "):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[1]
        online = "idle" in line or "processing" in line
        printers[name] = {
            "name"       : name,
            "status"     : "connected" if online else "disconnected",
            "uri"        : "",
            "description": "",
            "location"   : "",
        }

    # ── URIs ── lpstat -v ────────────────────────────────────────────────────
    _, out2, _ = _cups_run(["lpstat", "-v"])
    for line in out2.splitlines():
        # "device for NAME: socket://192.168.1.101:9100"
        if not line.startswith("device for "):
            continue
        rest = line[len("device for "):]
        name, sep, uri = rest.partition(": ")
        if sep and name.strip() in printers:
            printers[name.strip()]["uri"] = uri.strip()

    # ── Descriptions ── lpoptions -p NAME ───────────────────────────────────
    # lpoptions -p <name> returns space-separated key=value tokens
    for name in list(printers):
        _, out3, _ = _cups_run(["lpoptions", "-p", name])
        for token in out3.split():
            if "=" not in token:
                continue
            k, _, v = token.partition("=")
            v = v.strip("'\"")
            if k == "printer-info":
                printers[name]["description"] = v
            elif k == "printer-location":
                printers[name]["location"] = v

    return list(printers.values())


@bp.route("/cups/printers", methods=["GET"])
@_require_auth
def cups_printers_list():
    """GET /api/cups/printers — list all CUPS printers."""
    return jsonify({"printers": _cups_list_printers()})


@bp.route("/cups/printers", methods=["POST"])
@_require_auth
def cups_printers_add():
    """
    POST /api/cups/printers
    Body: { name, uri, description?, location? }
    """
    data        = request.get_json(force=True, silent=True) or {}
    name        = data.get("name", "").strip()
    uri         = data.get("uri",  "").strip()
    description = data.get("description", "").strip()
    location    = data.get("location",    "").strip()

    if not name:
        return jsonify({"success": False, "error": "Printer name is required"}), 400
    if not _SAFE_NAME_RE.match(name):
        return jsonify({"success": False,
                        "error": "Name may only contain letters, digits, -, _ and ."}), 400
    if not uri:
        return jsonify({"success": False, "error": "Device URI is required"}), 400

    # Whitelist URI schemes accepted by lpadmin
    _ALLOWED_URI_SCHEMES = {"socket", "usb", "ipp", "ipps", "lpd", "dnssd"}
    _uri_scheme = uri.split("://")[0].lower() if "://" in uri else ""
    if _uri_scheme not in _ALLOWED_URI_SCHEMES:
        return jsonify({
            "success": False,
            "error"  : f"Unsupported URI scheme '{_uri_scheme}'. "
                       f"Allowed: {', '.join(sorted(_ALLOWED_URI_SCHEMES))}",
        }), 400

    cmd = ["sudo", "lpadmin", "-p", name, "-v", uri, "-m", "raw", "-E"]
    if description:
        cmd += ["-D", description]
    if location:
        cmd += ["-L", location]

    rc, _, err = _cups_run(cmd)
    if rc != 0:
        logger.error("cups_printers_add lpadmin failed: %s", err)
        return jsonify({"success": False, "error": err or "lpadmin failed"}), 500
    return jsonify({"success": True})


@bp.route("/cups/printers/<name>", methods=["DELETE"])
@_require_auth
def cups_printers_delete(name):
    """DELETE /api/cups/printers/<name> — remove a printer from CUPS."""
    if not _SAFE_NAME_RE.match(name):
        return jsonify({"success": False, "error": "Invalid printer name"}), 400
    rc, _, err = _cups_run(["sudo", "lpadmin", "-x", name])
    if rc != 0:
        return jsonify({"success": False, "error": err or "lpadmin -x failed"}), 500
    return jsonify({"success": True})


@bp.route("/cups/printers/<name>/test", methods=["POST"])
@_require_auth
def cups_printers_test(name):
    """POST /api/cups/printers/<name>/test — send a test print job."""
    if not _SAFE_NAME_RE.match(name):
        return jsonify({"success": False, "error": "Invalid printer name"}), 400

    test_text = (
        "\n"
        "================================\n"
        "   RPiDriver — Test Print\n"
        "================================\n"
        f"   Printer  : {name}\n"
        "================================\n"
        "\n\n\n"
    )
    rc, out, err = _cups_run(["lp", "-d", name], input=test_text)
    if rc != 0:
        return jsonify({"success": False, "error": err or "lp command failed"}), 500
    return jsonify({"success": True, "message": out or "Test job submitted"})


@bp.route("/cups/devices", methods=["GET"])
@_require_auth
def cups_devices():
    """GET /api/cups/devices — list available printer devices (USB + network)."""
    _, out, _ = _cups_run(["lpinfo", "-v"])
    devices = []
    for line in out.splitlines():
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        dtype, uri = parts
        # Only include actionable device types
        if any(uri.startswith(p) for p in
               ("socket://", "usb://", "ipp://", "ipps://", "lpd://")):
            devices.append({"type": dtype.strip(), "uri": uri.strip()})
    return jsonify({"devices": devices})


# ── Driver test ───────────────────────────────────────────────────────────────

@bp.route("/drivers/<name>/test", methods=["POST"])
@_require_auth
def driver_test(name):
    """
    POST /api/drivers/<name>/test
    Run a quick self-test on the named driver.
    Returns { success, message } or { success, error }.
    """
    if not _SAFE_NAME_RE.match(name):
        return jsonify({"success": False, "error": "Invalid driver name"}), 400

    from rpidriver import get_drivers
    drivers = get_drivers()
    drv = drivers.get(name)
    if drv is None:
        return jsonify({"success": False,
                        "error": f"Driver '{name}' is not loaded"}), 404

    try:
        # ── ESC/POS USB printer ──────────────────────────────────────────────
        if name == "escpos_driver":
            drv.print_text("RPiDriver Test Print\n\n\n")
            return jsonify({"success": True,
                            "message": "Test print sent to USB printer"})

        # ── CUPS network printer ─────────────────────────────────────────────
        elif name == "cups_driver":
            drv.print_text("RPiDriver Test Print\n\n\n")
            return jsonify({"success": True,
                            "message": "Test print sent via CUPS"})

        # ── NeoLeap payment terminal ─────────────────────────────────────────
        elif name == "neoleap_driver":
            import socket as _sock
            ip   = getattr(drv, "_neoleap_ip", "")
            port = getattr(drv, "_port", 9998)
            if not ip:
                return jsonify({"success": False,
                                "error": "NeoLeap IP is not configured"})
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(5)
            s.connect((ip, port))
            s.close()
            return jsonify({"success": True,
                            "message": f"TCP connection OK → {ip}:{port}"})

        # ── Serial scale ─────────────────────────────────────────────────────
        elif name == "scale_driver":
            weight = drv.read_weight()
            return jsonify({"success": True,
                            "message": f"Weight reading: {weight}"})

        # ── Customer display ─────────────────────────────────────────────────
        elif name == "display_driver":
            drv.display_text(line1="RPiDriver", line2="Test OK")
            return jsonify({"success": True,
                            "message": "Test message sent to display"})

        else:
            return jsonify({"success": False,
                            "error": f"No test defined for driver '{name}'"}), 400

    except Exception as exc:
        logger.exception("driver_test '%s' failed: %s", name, exc)
        return jsonify({"success": False, "error": str(exc)})
