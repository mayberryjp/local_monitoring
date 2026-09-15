"""Tests for the aggregate and individual check endpoints and reducers."""

from __future__ import annotations

from typing import Any

import pytest
import requests
from webtest import TestApp

from local_monitoring.domain import (
    docker_containers,
    docker_updater,
    uptime_kuma,
    webdav,
)
from local_monitoring.domain.errors import CheckError


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> Any:
        return self._payload


def test_summary_runs_all_checks(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uptime_kuma, "collect", lambda: {"up": 2, "down": 1, "total": 3})
    monkeypatch.setattr(webdav, "collect", lambda: {"result": "OK", "recent": True})
    monkeypatch.setattr(docker_updater, "collect", lambda: {"pending_updates": 4})
    monkeypatch.setattr(
        docker_containers, "collect", lambda: {"running": 5, "stopped": 2, "total": 7}
    )

    resp = client.get("/summary")

    assert resp.status_code == 200
    checks = resp.json["checks"]
    assert set(checks) == {"uptime_kuma", "webdav", "docker_updater", "docker_containers"}
    assert checks["uptime_kuma"] == {"status": "ok", "up": 2, "down": 1, "total": 3}
    assert checks["docker_updater"]["pending_updates"] == 4


def test_summary_reports_partial_failure(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom() -> dict[str, Any]:
        raise CheckError("upstream_unreachable", "nope", "boom")

    monkeypatch.setattr(uptime_kuma, "collect", lambda: {"up": 1, "down": 0, "total": 1})
    monkeypatch.setattr(webdav, "collect", _boom)
    monkeypatch.setattr(docker_updater, "collect", lambda: {"pending_updates": 0})
    monkeypatch.setattr(
        docker_containers, "collect", lambda: {"running": 1, "stopped": 0, "total": 1}
    )

    resp = client.get("/summary")

    assert resp.status_code == 200
    assert resp.json["checks"]["uptime_kuma"]["status"] == "ok"
    assert resp.json["checks"]["webdav"] == {
        "status": "error",
        "code": "upstream_unreachable",
        "error": "nope",
        "detail": "boom",
    }


def test_individual_check_ok(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_updater, "collect", lambda: {"pending_updates": 3})
    resp = client.get("/docker-updater")
    assert resp.status_code == 200
    assert resp.json == {"status": "ok", "pending_updates": 3}


def test_individual_check_error_returns_503(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom() -> dict[str, Any]:
        raise CheckError("not_configured", "webdav is not configured")

    monkeypatch.setattr(webdav, "collect", _boom)
    resp = client.get("/webdav", expect_errors=True)
    assert resp.status_code == 503
    assert resp.json["status"] == "error"
    assert resp.json["code"] == "not_configured"


def test_uptime_kuma_counts_up_and_down(monkeypatch: pytest.MonkeyPatch) -> None:
    heartbeats = {"heartbeatList": {"1": [{"status": 1}], "2": [{"status": 0}], "3": [{"status": 1}]}}
    config = {"publicGroupList": [{"monitorList": [{"id": 2, "name": "Database"}]}]}

    def fake_get(url: str, *a: Any, **k: Any) -> _FakeResponse:
        return _FakeResponse(200, heartbeats if "/heartbeat/" in url else config)

    monkeypatch.setattr(uptime_kuma.settings, "uptime_kuma_base_url", "http://kuma")
    monkeypatch.setattr(uptime_kuma.settings, "uptime_kuma_slug", "mine")
    monkeypatch.setattr(requests, "get", fake_get)

    assert uptime_kuma.collect() == {
        "up": 2,
        "down": 1,
        "total": 3,
        "down_monitors": ["Database"],
    }


def test_docker_updater_counts_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "containers": [
            {"status": "update", "image": "nginx:latest"},
            {"status": "ok", "image": "redis:7"},
            {"status": "update", "image": "ghcr.io/owner/app:main"},
        ]
    }
    monkeypatch.setattr(docker_updater.settings, "docker_updater_base_url", "http://du")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, payload))

    assert docker_updater.collect() == {
        "pending_updates": 2,
        "pending_images": ["nginx:latest", "ghcr.io/owner/app:main"],
    }
