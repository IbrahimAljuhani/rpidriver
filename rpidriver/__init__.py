"""
RPiDriver — Smart hardware proxy for Odoo POS.
Flask application factory, config loader, Babel setup, and plugin loader.
"""

import atexit
import importlib
import logging
import os
import secrets
from configparser import ConfigParser

from flask import Flask, request, session
from flask_babel import Babel, gettext
from flask_cors import CORS

logger = logging.getLogger(__name__)

# Drivers registry: plugin_name → driver instance
drivers = {}
_atexit_registered = False


def get_drivers() -> dict:
    """Return the global drivers registry. Use this instead of importing `drivers` directly."""
    return drivers


def get_config(app=None):
    """Load config.ini from the path in RPIDRIVER_CONFIG env var or /etc/rpidriver/config.ini."""
    config = ConfigParser()
    config_path = os.environ.get("RPIDRIVER_CONFIG", "/etc/rpidriver/config.ini")
    read = config.read(config_path)
    if not read:
        logger.warning("Config file not found at %s — using defaults.", config_path)
    return config


def get_locale():
    """Return the active locale (stored in session, falls back to browser negotiation)."""
    if "lang" in session:
        return session["lang"]
    return request.accept_languages.best_match(["ar", "en"], default="en")


def create_app(config_path=None):
    """Application factory."""
    app = Flask(__name__, instance_relative_config=False)
    _secret = os.environ.get("RPIDRIVER_SECRET")
    if not _secret:
        _secret = secrets.token_hex(32)
        logger.warning(
            "RPIDRIVER_SECRET not set — using a random key. "
            "Sessions will not survive a restart. "
            "Set RPIDRIVER_SECRET in the environment for production."
        )
    app.secret_key = _secret

    # ── Config ──────────────────────────────────────────────────────────────
    if config_path:
        os.environ["RPIDRIVER_CONFIG"] = config_path
    config = get_config(app)
    app.config["RPIDRIVER_CONFIG"] = config

    # ── CORS — allow Odoo browser JS to reach all /hw_proxy/* endpoints ──────
    # Odoo POS runs in the browser and makes XHR requests directly to this
    # server. Without CORS headers the browser blocks every request.
    # cors_origins defaults to "*"; restrict via [rpidriver] cors_origins in
    # config.ini (e.g. "https://odoo.example.com") for a locked-down setup.
    _cors_origins = config.get("rpidriver", "cors_origins", fallback="*").strip() or "*"
    CORS(app, resources={r"/hw_proxy/*": {"origins": _cors_origins}})

    # ── Request size limit — 1 MB for print jobs (base64 JPEG receipts) ──────
    app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

    # Stop any running drivers from a previous create_app() call (e.g. in tests),
    # then clear the registry so it doesn't accumulate stale instances.
    for _drv in list(drivers.values()):
        if hasattr(_drv, "stop"):
            try:
                _drv.stop()
            except Exception:
                pass
    drivers.clear()

    # ── Flask-Babel ──────────────────────────────────────────────────────────
    app.config["BABEL_TRANSLATION_DIRECTORIES"] = os.path.join(
        os.path.dirname(__file__), "translations"
    )
    app.config["BABEL_DEFAULT_LOCALE"] = "en"
    babel = Babel(app, locale_selector=get_locale)  # noqa: F841

    # ── Views blueprint ──────────────────────────────────────────────────────
    from rpidriver import views  # noqa: E402

    app.register_blueprint(views.bp)

    # ── REST API blueprint (config, service control, logs) ───────────────────
    from rpidriver import api  # noqa: E402

    app.register_blueprint(api.bp)

    # ── Plugin loader ────────────────────────────────────────────────────────
    driver_list = []
    if config.has_option("rpidriver", "drivers"):
        raw = config.get("rpidriver", "drivers")
        driver_list = [d.strip() for d in raw.split(",") if d.strip()]

    for plugin_name in driver_list:
        module_path = f"rpidriver.plugins.{plugin_name}"
        try:
            module = importlib.import_module(module_path)
            # Each plugin must expose DRIVER_CLASS pointing to its driver class.
            if hasattr(module, "DRIVER_CLASS"):
                cfg_dict = (
                    dict(config.items(plugin_name))
                    if config.has_section(plugin_name)
                    else {}
                )
                instance = module.DRIVER_CLASS(cfg_dict)
                # ThreadDrivers need an explicit start()
                if hasattr(instance, "start"):
                    instance.start()
                drivers[plugin_name] = instance
                logger.info("Loaded plugin: %s", plugin_name)
            else:
                logger.warning("Plugin %s has no DRIVER_CLASS — skipped.", plugin_name)
            if hasattr(module, "bp"):
                app.register_blueprint(module.bp)
                logger.info("Registered blueprint for plugin: %s", plugin_name)
        except ImportError as exc:
            logger.error("Failed to load plugin %s: %s", plugin_name, exc)
        except Exception as exc:
            logger.error("Failed to initialise plugin %s: %s", plugin_name, exc, exc_info=True)

    # Register a single atexit handler that reads drivers at shutdown time,
    # avoiding stale references when create_app() is called more than once
    # (e.g. repeated calls in tests).
    global _atexit_registered

    def _stop_all_drivers():
        for name, drv in drivers.items():
            if hasattr(drv, "stop"):
                try:
                    drv.stop()
                except Exception:
                    logger.exception("Error stopping driver %s", name)

    if not _atexit_registered:
        atexit.register(_stop_all_drivers)
        _atexit_registered = True

    # odoo8 (hw_proxy endpoints) is always loaded
    from rpidriver.plugins import odoo8  # noqa: E402

    app.register_blueprint(odoo8.bp)

    # ── Jinja2 context processor ─────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        return {"get_locale": get_locale, "_": gettext}

    return app


def _build_ssl_context(config):
    """
    Build an SSL context tuple (cert_path, key_path) or None.

    Priority:
      1. Explicit paths in config [rpidriver] ssl_cert / ssl_key
      2. Auto-detect default install location: /etc/rpidriver/ssl/cert.pem
      3. None → plain HTTP with a warning
    """
    cert = config.get("rpidriver", "ssl_cert", fallback="").strip()
    key  = config.get("rpidriver", "ssl_key",  fallback="").strip()

    # Fall back to the standard install location generated by install_pi.sh
    if not cert:
        cert = "/etc/rpidriver/ssl/cert.pem"
        key  = "/etc/rpidriver/ssl/key.pem"

    if os.path.exists(cert) and os.path.exists(key):
        logger.info("SSL enabled — certificate: %s", cert)
        return (cert, key)

    logger.warning(
        "SSL certificate not found at '%s'. Running on HTTP. "
        "Odoo 17+ on HTTPS requires the IoT proxy to also use HTTPS — "
        "the browser will block mixed-content requests. "
        "Run scripts/install_pi.sh to generate a self-signed certificate.",
        cert,
    )
    return None


def main():
    """Entry point for the rpidriver CLI."""
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    config = app.config["RPIDRIVER_CONFIG"]
    host  = config.get("rpidriver", "host", fallback="0.0.0.0")
    port  = config.getint("rpidriver", "port", fallback=8069)
    debug = config.getboolean("rpidriver", "debug", fallback=False)

    ssl_context = _build_ssl_context(config)
    protocol = "https" if ssl_context else "http"
    logger.info("Starting RPiDriver on %s://0.0.0.0:%d", protocol, port)

    app.run(host=host, port=port, debug=debug, ssl_context=ssl_context)


if __name__ == "__main__":
    main()
