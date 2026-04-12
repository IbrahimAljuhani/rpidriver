"""
Tests for hw_proxy endpoints (Odoo 17/18/19 compatibility).
"""

import json


# ── /hw_proxy/hello ───────────────────────────────────────────────────────────


def test_hello(client):
    """GET /hw_proxy/hello must return the plain string 'ping'."""
    resp = client.get("/hw_proxy/hello")
    assert resp.status_code == 200
    assert resp.data == b"ping"


# ── /hw_proxy/handshake ───────────────────────────────────────────────────────


def test_handshake_returns_true(client):
    """POST /hw_proxy/handshake must return JSON-RPC result: true."""
    payload = {"jsonrpc": "2.0", "method": "call", "id": 1, "params": {}}
    resp = client.post(
        "/hw_proxy/handshake",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["jsonrpc"] == "2.0"
    assert body["result"] is True
    assert body["id"] == 1


def test_handshake_no_body(client):
    """handshake must not crash on an empty body."""
    resp = client.post("/hw_proxy/handshake")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["result"] is True


# ── /hw_proxy/status_json ─────────────────────────────────────────────────────


def test_status_json_structure(client):
    """POST /hw_proxy/status_json must return a JSON-RPC dict result."""
    payload = {"jsonrpc": "2.0", "method": "call", "id": 2, "params": {}}
    resp = client.post(
        "/hw_proxy/status_json",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["jsonrpc"] == "2.0"
    assert isinstance(body["result"], dict)


# ── /hw_proxy/scale_read ──────────────────────────────────────────────────────


def test_scale_read_no_driver(client):
    """
    POST /hw_proxy/scale_read with no scale driver loaded must return
    a zero-weight result rather than an error.
    """
    payload = {"jsonrpc": "2.0", "method": "call", "id": 3, "params": {}}
    resp = client.post(
        "/hw_proxy/scale_read",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "weight" in body["result"]
    assert isinstance(body["result"]["weight"], (int, float))


# ── /hw_proxy/print_receipt ───────────────────────────────────────────────────


def test_print_receipt_no_driver(client):
    """print_receipt with no driver must return False without crashing."""
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "id": 4,
        "params": {"receipt": "Test receipt"},
    }
    resp = client.post(
        "/hw_proxy/print_receipt",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["result"] is False
