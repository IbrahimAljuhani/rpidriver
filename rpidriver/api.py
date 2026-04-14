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
    cfg = ConfigParser()
    cfg.read(_config_path())
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
                if maxlen and len(str_val) > int(maxlen):
                    return jsonify({"success": False,
                                    "error": f"[{section}] {key}: exceeds max length of {maxlen}"}), 400

            # ── Detect restart-required changes ───────────────────────────────
            # Compare against the effective current value (schema default when
            # the key is absent) to avoid false positives on the first save.
            if schema_field.get("restart"):
                default_str = str(schema_field.get("default", ""))
                effective   = cfg.get(section, key, fallback=default_str).strip()
                if effective != str_val:
                    restart_required = True

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
