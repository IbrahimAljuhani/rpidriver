"""
RPiDriver — Smart hardware proxy for Odoo POS.
Flask application factory, config loader, Babel setup, and plugin loader.
"""

import importlib
import logging
import os
from configparser import ConfigParser

from flask import Flask, request, session
from flask_babel import Babel, gettext

logger = logging.getLogger(__name__)

# Drivers registry: plugin_name → driver instance
drivers = {}


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
    app.secret_key = os.environ.get("RPIDRIVER_SECRET", "rpidriver-dev-secret")

    # ── Config ──────────────────────────────────────────────────────────────
    if config_path:
        os.environ["RPIDRIVER_CONFIG"] = config_path
    config = get_config(app)
    app.config["RPIDRIVER_CONFIG"] = config

    # Clear the drivers registry so repeated create_app() calls don't accumulate
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

    # odoo8 (hw_proxy endpoints) is always loaded
    from rpidriver.plugins import odoo8  # noqa: E402

    app.register_blueprint(odoo8.bp)

    # ── Jinja2 context processor ─────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        return {"get_locale": get_locale, "_": gettext}

    return app


def main():
    """Entry point for the rpidriver CLI."""
    logging.basicConfig(level=logging.INFO)
    # create_app() loads config internally; read host/port/debug from the same instance
    app = create_app()
    config = app.config["RPIDRIVER_CONFIG"]
    host = config.get("rpidriver", "host", fallback="0.0.0.0")
    port = config.getint("rpidriver", "port", fallback=8069)
    debug = config.getboolean("rpidriver", "debug", fallback=False)
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
