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

import logging
import os
import subprocess
from configparser import ConfigParser

from flask import Blueprint, Response, jsonify, request, stream_with_context

from rpidriver.config_schema import AVAILABLE_DRIVERS, CONFIG_SCHEMA

logger = logging.getLogger(__name__)

bp = Blueprint("api", __name__, url_prefix="/api")

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
def config_get():
    """Return the current configuration as JSON (merged with schema defaults)."""
    cfg = _read_cfg()
    raw = _cfg_to_dict(cfg)
    return jsonify(_merge_defaults(raw))


@bp.route("/config", methods=["POST"])
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

        # Validate section and keys against schema
        schema_section = CONFIG_SCHEMA.get(section, {})

        if not cfg.has_section(section):
            cfg.add_section(section)

        for key, value in fields.items():
            if key.startswith("_"):
                continue
            str_val = str(value).strip()

            # Detect restart-required changes
            schema_field = schema_section.get(key, {})
            if schema_field.get("restart"):
                current = cfg.get(section, key, fallback=None)
                if current != str_val:
                    restart_required = True

            cfg.set(section, key, str_val)

    try:
        with open(_config_path(), "w") as fh:
            cfg.write(fh)
        logger.info("api.config_save: config.ini written (restart_required=%s)", restart_required)
    except OSError as exc:
        logger.error("api.config_save: write failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500

    return jsonify({"success": True, "restart_required": restart_required})


# ── Service control ───────────────────────────────────────────────────────────

@bp.route("/service/restart", methods=["POST"])
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


# ── Log endpoints ─────────────────────────────────────────────────────────────

@bp.route("/logs")
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
                    yield f"data: {line}\n\n"
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
