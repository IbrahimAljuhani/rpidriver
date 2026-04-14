"""
Tests for dashboard views:
  GET  /
  GET  /status
  GET  /system
  GET  /config
  GET  /logs
  GET  /usb_devices
  GET  /login  POST /login
  GET  /logout
"""

import os

import pytest


# ── Public routes (no auth required) ─────────────────────────────────────────

def test_index_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_index_contains_rpidriver(client):
    resp = client.get("/")
    assert b"RPiDriver" in resp.data


# ── Dashboard routes (open when no password is set) ───────────────────────────

def test_status_open_without_password(client):
    resp = client.get("/status")
    assert resp.status_code == 200


def test_system_open_without_password(client):
    resp = client.get("/system")
    assert resp.status_code == 200


def test_config_open_without_password(client):
    resp = client.get("/config")
    assert resp.status_code == 200


def test_logs_open_without_password(client):
    resp = client.get("/logs")
    assert resp.status_code == 200


def test_usb_devices_open_without_password(client):
    resp = client.get("/usb_devices")
    assert resp.status_code == 200


# ── Auth fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture()
def auth_app(tmp_path):
    cfg = tmp_path / "config.ini"
    cfg.write_text(
        "[rpidriver]\nhost = 127.0.0.1\nport = 8069\ndrivers =\ndashboard_password = testpass\n",
        encoding="utf-8",
    )
    os.environ["RPIDRIVER_CONFIG"] = str(cfg)
    from rpidriver import create_app
    app = create_app(config_path=str(cfg))
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def auth_client(auth_app):
    return auth_app.test_client()


# ── Auth — redirect when password set ────────────────────────────────────────

def test_status_redirects_when_auth_required(auth_client):
    resp = auth_client.get("/status")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_config_redirects_when_auth_required(auth_client):
    resp = auth_client.get("/config")
    assert resp.status_code == 302


def test_system_redirects_when_auth_required(auth_client):
    resp = auth_client.get("/system")
    assert resp.status_code == 302


# ── Login page ────────────────────────────────────────────────────────────────

def test_login_page_renders(auth_client):
    resp = auth_client.get("/login")
    assert resp.status_code == 200
    assert b"login" in resp.data.lower() or b"password" in resp.data.lower()


def test_login_wrong_password_shows_error(auth_client):
    resp = auth_client.post(
        "/login",
        data={"password": "wrongpass"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Invalid" in resp.data or "غير صحيح".encode() in resp.data


def test_login_correct_password_redirects(auth_client):
    resp = auth_client.post(
        "/login",
        data={"password": "testpass"},
    )
    assert resp.status_code == 302
    # Must redirect to / (or next param)
    assert resp.headers["Location"].endswith("/") or "login" not in resp.headers["Location"]


def test_after_login_dashboard_accessible(auth_client):
    # Log in
    auth_client.post("/login", data={"password": "testpass"})
    # Now access protected page
    resp = auth_client.get("/status")
    assert resp.status_code == 200


# ── Logout ────────────────────────────────────────────────────────────────────

def test_logout_clears_session(auth_client):
    # Log in first
    auth_client.post("/login", data={"password": "testpass"})
    # Confirm access
    assert auth_client.get("/status").status_code == 200
    # Log out
    auth_client.get("/logout")
    # Must redirect again
    resp = auth_client.get("/status")
    assert resp.status_code == 302


# ── Language toggle ───────────────────────────────────────────────────────────

def test_set_language_ar(client):
    resp = client.get("/lang/ar")
    assert resp.status_code == 302


def test_set_language_en(client):
    resp = client.get("/lang/en")
    assert resp.status_code == 302


def test_set_language_invalid_ignored(client):
    resp = client.get("/lang/fr")
    assert resp.status_code == 302  # still redirects, just doesn't set lang


# ── SSL routes ────────────────────────────────────────────────────────────────

def test_ssl_cert_download_404_when_no_cert(client):
    resp = client.get("/ssl/cert.pem")
    # No cert exists in test env — expect 404
    assert resp.status_code == 404


def test_ssl_generate_requires_post(client):
    resp = client.get("/ssl/generate")
    assert resp.status_code == 405
