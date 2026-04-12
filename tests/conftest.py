"""
Pytest fixtures shared across all test modules.
"""

import os
import tempfile

import pytest

# ── Config fixture ────────────────────────────────────────────────────────────

MINIMAL_CONFIG = """
[rpidriver]
host = 127.0.0.1
port = 8069
debug = false
drivers =
"""


@pytest.fixture(scope="session")
def config_file():
    """Write a minimal config.ini to a temp file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ini", delete=False, encoding="utf-8"
    ) as f:
        f.write(MINIMAL_CONFIG)
        path = f.name
    yield path
    os.unlink(path)


# ── Flask test client fixture ─────────────────────────────────────────────────


@pytest.fixture()
def app(config_file):
    """Create the Flask application with a minimal test config.

    Function-scoped so each test gets a fresh app instance and drivers
    registry, preventing state leakage between tests.
    """
    os.environ["RPIDRIVER_CONFIG"] = config_file
    from rpidriver import create_app

    application = create_app(config_path=config_file)
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    """Return a Flask test client."""
    return app.test_client()
