"""Tests for the shared local DNS reload action and Mirenai integration."""

from __future__ import annotations

import json
from threading import Barrier
from typing import Any

import pytest
import requests
from webtest import TestApp

from local_monitoring.config import settings
from local_monitoring.domain import local_dns


@pytest.fixture(autouse=True)
def configure_mirenai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mirenai_base_url", "http://mirenai:8000/")


def test_reload_refreshes_all_zones_concurrently_and_reloads_list(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = Barrier(3, timeout=5)
    calls: list[tuple[str, str]] = []

    def upstream(method: str, url: str, *, timeout: float) -> requests.Response:
        assert timeout == settings.http_timeout_seconds
        calls.append((method, url))
        if method == "POST":
            barrier.wait()
            payload = {"status": "ok", "local_zone": {}}
        else:
            payload = {
                "status": "ok",
                "local_zones": [
                    {"id": 1, "enabled": True},
                    {"id": 2, "enabled": False},
                    {"id": 3, "enabled": True},
                ],
                "total": 3,
            }
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(payload).encode()
        return response

    monkeypatch.setattr(local_dns.requests, "request", upstream)
    result = client.post("/actions/reload-local-dns").json
    assert result == {
        "status": "ok",
        "message": "local DNS: 3 of 3 zones refreshed; 0 failed",
        "refreshed": 3,
        "failed": 0,
    }
    assert calls[0] == calls[-1] == ("GET", "http://mirenai:8000/local-zones")
    assert sorted(calls[1:-1]) == [
        ("POST", f"http://mirenai:8000/local-zones/{zone_id}/refresh")
        for zone_id in (1, 2, 3)
    ]


def test_reload_waits_for_all_refreshes_despite_failures(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    barrier = Barrier(3, timeout=5)
    completed: list[str] = []
    listings: list[str] = []

    def upstream(method: str, path: str) -> dict[str, Any]:
        if method == "GET":
            listings.append(path)
            return {"local_zones": [{"id": 1}, {"id": 2}, {"id": 3}]}
        barrier.wait()
        completed.append(path)
        if path.endswith("/2/refresh"):
            raise local_dns.CheckError("upstream_error", "download failed")
        return {}

    monkeypatch.setattr(local_dns, "_request", upstream)
    result = client.post("/actions/reload-local-dns", status=503).json
    assert result["status"] == "error"
    assert result["error"] == "local DNS: 2 of 3 zones refreshed; 1 failed"
    assert result["detail"] == "zone 2: download failed"
    assert len(completed) == 3
    assert listings == ["/local-zones", "/local-zones"]


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (502, b"bad gateway"),
        (200, b"not JSON"),
        (200, b"[]"),
        (200, b'{"status":"error","error":"failed"}'),
        (200, b'{"status":"ok"}'),
        (200, b'{"status":"ok","local_zones":[{"id":true}]}'),
        (200, b'{"status":"ok","local_zones":[{"id":"1"}]}'),
        (200, b'{"status":"ok","local_zones":[{"id":0}]}'),
    ],
)
def test_reload_rejects_invalid_upstream_responses(
    client: TestApp, monkeypatch: pytest.MonkeyPatch, status: int, body: bytes
) -> None:
    response = requests.Response()
    response.status_code = status
    response._content = body
    monkeypatch.setattr(local_dns.requests, "request", lambda *a, **kw: response)
    result = client.post("/actions/reload-local-dns", status=503).json
    assert result["status"] == "error"
    assert result["code"] == "upstream_error"


def test_reload_unreachable(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(*args: Any, **kwargs: Any) -> requests.Response:
        raise requests.Timeout("timed out")

    monkeypatch.setattr(local_dns.requests, "request", unreachable)
    result = client.post("/actions/reload-local-dns", status=503).json
    assert result["code"] == "upstream_unreachable"
    assert result["detail"] == "timed out"


def test_reload_unconfigured(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mirenai_base_url", "")
    result = client.post("/actions/reload-local-dns", status=503).json
    assert result["code"] == "not_configured"
    assert "MIRENAI_BASE_URL" in result["error"]


def test_reload_empty_zone_list(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_dns, "_request", lambda *args: {"local_zones": []})
    result = client.post("/actions/reload-local-dns").json
    assert result["refreshed"] == result["failed"] == 0
    assert result["message"] == "local DNS: 0 of 0 zones refreshed; 0 failed"


def test_reload_list_failure_after_refresh(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def upstream(method: str, path: str) -> dict[str, Any]:
        calls.append(method)
        if len(calls) == 3:
            raise local_dns.CheckError("upstream_unreachable", "connection lost")
        return {"local_zones": [{"id": 1}]}

    monkeypatch.setattr(local_dns, "_request", upstream)
    result = client.post("/actions/reload-local-dns", status=503).json
    assert calls == ["GET", "POST", "GET"]
    assert "1 of 1 zones refreshed; 0 failed" in result["error"]
    assert "could not reload the zone list" in result["error"]
    assert "connection lost" in result["detail"]
