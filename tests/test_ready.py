"""Tests for the /ready endpoint."""

from __future__ import annotations

from webtest import TestApp


def test_ready_ok(client: TestApp) -> None:
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"
