"""
Tests for REST API endpoints:
  GET  /api/config
  POST /api/config
  POST /api/service/restart
  GET  /api/logs
"""

import json
import os
import tempfile

import pytest


# ── Config API ────────────────────────────────────────────────────────────────

def test_config_get_returns_json(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.get_json()
    assert isinstance(body, dict)
    assert "rpidriver" in body


def test_config_get_contains_schema_keys(client):
    resp = client.get("/api/config")
    body = resp.get_json()
    rpi = body["rpidriver"]
    assert "host" in rpi
    assert "port" in rpi
    assert "drivers" in rpi


def test_config_save_returns_success(client):
    payload = {"rpidriver": {"host": "127.0.0.1"}}
    resp = client.post(
        "/api/config",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True


def test_config_save_unknown_section_skipped(client):
    """Posting an unknown section must not crash and must return success."""
    payload = {"unknown_section": {"key": "value"}}
    resp = client.post(
        "/api/config",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True


def test_config_save_unknown_key_skipped(client):
    """Posting an unknown key inside a known section must not crash."""
    payload = {"rpidriver": {"nonexistent_key": "value"}}
    resp = client.post(
        "/api/config",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True


def test_config_save_restart_required_flag(client):
    """Changing a restart-required field must set restart_required=True."""
    payload = {"rpidriver": {"port": "9999"}}
    resp = client.post(
        "/api/config",
        data=json.dumps(payload),
        content_type="application/json",
    )
    body = resp.get_json()
    assert body["success"] is True
    assert body.get("restart_required") is True


def test_config_save_empty_body_succeeds(client):
    resp = client.post(
        "/api/config",
        data="{}",
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True


# ── Service restart ───────────────────────────────────────────────────────────

def test_service_restart_returns_json(client):
    """POST /api/service/restart must return JSON (may fail without systemd)."""
    resp = client.post("/api/service/restart")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "success" in body


# ── Logs ──────────────────────────────────────────────────────────────────────

def test_logs_get_returns_json(client):
    resp = client.get("/api/logs")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "logs" in body
    assert isinstance(body["logs"], str)


def test_logs_get_custom_lines_param(client):
    resp = client.get("/api/logs?lines=10")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "logs" in body


def test_logs_get_invalid_lines_param(client):
    """Non-numeric lines param must fall back gracefully."""
    resp = client.get("/api/logs?lines=abc")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "logs" in body


# ── Authentication ────────────────────────────────────────────────────────────

@pytest.fixture()
def auth_app(tmp_path):
    """App with dashboard_password set in config."""
    cfg_path = tmp_path / "config.ini"
    cfg_path.write_text(
        "[rpidriver]\nhost = 127.0.0.1\nport = 8069\ndrivers =\ndashboard_password = secret123\n",
        encoding="utf-8",
    )
    os.environ["RPIDRIVER_CONFIG"] = str(cfg_path)
    from rpidriver import create_app
    application = create_app(config_path=str(cfg_path))
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def auth_client(auth_app):
    return auth_app.test_client()


def test_api_config_requires_auth(auth_client):
    """GET /api/config must return 401 when password is set and user is unauthenticated."""
    resp = auth_client.get("/api/config")
    assert resp.status_code == 401


def test_api_config_save_requires_auth(auth_client):
    resp = auth_client.post(
        "/api/config",
        data=json.dumps({"rpidriver": {"host": "0.0.0.0"}}),
        content_type="application/json",
    )
    assert resp.status_code == 401


def test_api_restart_requires_auth(auth_client):
    resp = auth_client.post("/api/service/restart")
    assert resp.status_code == 401


def test_api_logs_requires_auth(auth_client):
    resp = auth_client.get("/api/logs")
    assert resp.status_code == 401


def test_login_then_api_works(auth_client):
    """After logging in through the session, API endpoints must be accessible."""
    with auth_client.session_transaction() as sess:
        sess["authenticated"] = True
    resp = auth_client.get("/api/config")
    assert resp.status_code == 200


def test_no_password_config_allows_api(client):
    """When no password is configured, API must be accessible without auth."""
    resp = client.get("/api/config")
    assert resp.status_code == 200
