"""Tests for the aggregate and individual check endpoints and reducers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests
from webtest import TestApp

from local_monitoring.domain import (
    additional_monitors,
    allowlist,
    docker_containers,
    docker_images,
    docker_monitors,
    docker_updater,
    ping_monitors,
    portainer_stacks,
    uptime_kuma,
    uptime_kuma_v2,
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
    monkeypatch.setattr(docker_monitors, "collect", lambda: {"monitored": 6, "unmonitored": 1})
    monkeypatch.setattr(ping_monitors, "collect", lambda: {"monitored": 3, "unmonitored": 0})
    monkeypatch.setattr(additional_monitors, "collect", lambda: {"additional": 2})
    monkeypatch.setattr(allowlist, "collect", lambda: {"unmatched": 1})
    monkeypatch.setattr(docker_images, "collect", lambda: {"unused": 2, "total": 25})
    monkeypatch.setattr(
        portainer_stacks,
        "collect",
        lambda force_refresh=False: {"containers": []},
    )

    resp = client.get("/summary")

    assert resp.status_code == 200
    checks = resp.json["checks"]
    assert set(checks) == {
        "uptime_kuma",
        "webdav",
        "docker_updater",
        "docker_containers",
        "docker_monitors",
        "ping_monitors",
        "additional_monitors",
        "allowlist",
        "docker_images",
        "compose_stacks",
    }
    assert checks["uptime_kuma"] == {"status": "ok", "up": 2, "down": 1, "total": 3}
    assert checks["docker_updater"]["pending_updates"] == 4
    assert checks["compose_stacks"] == {"status": "ok", "containers": []}


def test_summary_force_refresh_passes_to_compose_check(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    refresh_values: list[bool] = []
    monkeypatch.setattr(
        portainer_stacks,
        "collect",
        lambda force_refresh=False: refresh_values.append(force_refresh) or {"containers": []},
    )
    resp = client.get("/summary?refresh=true")
    assert resp.status_code == 200
    assert resp.json["checks"]["compose_stacks"]["status"] == "ok"
    assert refresh_values == [True]


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
    monkeypatch.setattr(docker_monitors, "collect", lambda: {"monitored": 1, "unmonitored": 0})
    monkeypatch.setattr(ping_monitors, "collect", lambda: {"monitored": 1, "unmonitored": 0})
    monkeypatch.setattr(additional_monitors, "collect", lambda: {"additional": 0})
    monkeypatch.setattr(allowlist, "collect", lambda: {"unmatched": 0})
    monkeypatch.setattr(docker_images, "collect", lambda: {"unused": 0, "total": 10})

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


def test_uptime_kuma_accepts_full_status_page_url_as_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def fake_get(url: str, *a: Any, **k: Any) -> _FakeResponse:
        requested.append(url)
        return _FakeResponse(200, {"heartbeatList": {"3": [{"status": 1}]}})

    monkeypatch.setattr(uptime_kuma.settings, "uptime_kuma_base_url", "http://uptimekuma.azure.farm:3001/")
    monkeypatch.setattr(
        uptime_kuma.settings,
        "uptime_kuma_slug",
        "http://uptimekuma.azure.farm:3001/status/allstatus",
    )
    monkeypatch.setattr(requests, "get", fake_get)

    assert uptime_kuma.collect() == {
        "up": 1,
        "down": 0,
        "total": 1,
        "down_monitors": [],
    }
    assert requested == [
        "http://uptimekuma.azure.farm:3001/api/status-page/heartbeat/allstatus"
    ]


def test_summary_handles_non_json_uptime_kuma_response(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _InvalidJsonResponse:
        status_code = 200

        def json(self) -> Any:
            raise ValueError("Expecting value")

    monkeypatch.setattr(uptime_kuma.settings, "uptime_kuma_base_url", "http://kuma")
    monkeypatch.setattr(uptime_kuma.settings, "uptime_kuma_slug", "mine")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _InvalidJsonResponse())
    monkeypatch.setattr(webdav, "collect", dict)
    monkeypatch.setattr(docker_updater, "collect", dict)
    monkeypatch.setattr(docker_containers, "collect", dict)
    monkeypatch.setattr(docker_monitors, "collect", dict)
    monkeypatch.setattr(ping_monitors, "collect", dict)
    monkeypatch.setattr(additional_monitors, "collect", dict)
    monkeypatch.setattr(allowlist, "collect", dict)
    monkeypatch.setattr(docker_images, "collect", dict)

    resp = client.get("/summary")

    assert resp.status_code == 200
    assert resp.json["checks"]["uptime_kuma"] == {
        "status": "error",
        "code": "upstream_error",
        "error": "uptime-kuma returned invalid JSON",
        "detail": "Expecting value",
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
        "pending_containers": [
            {"name": None, "image": "nginx:latest"},
            {"name": None, "image": "ghcr.io/owner/app:main"},
        ],
    }


def test_docker_monitors_flags_uncovered_containers(monkeypatch: pytest.MonkeyPatch) -> None:
    blob = (
        "# comment line\n"
        "docker.azure.mayberry.farm,homeassistant.azure.mayberry.farm,86400\n"
        "docker.azure.mayberry.farm,caddy.azure.mayberry.farm,86400\n"
        "docker.azure.mayberry.farm,web.azure.mayberry.farm,86400\n"
        "\n"
        "docker.azure.mayberry.farm,bitwarden.azure.mayberry.farm,86400\n"
    )
    monitors = {
        "monitors": [
            {"id": 1, "name": "AZURE CONTAINER CADDY", "type": "docker"},
            {"id": 2, "name": "AZURE CONTAINER BITWARDEN", "type": "docker"},
            {"id": 3, "name": "AZURE CONTAINER HOMEASSISTANT", "type": "http"},
            {"id": 4, "name": "AZURE CONTAINER WEBHOOK", "type": "docker"},
        ],
        "count": 4,
    }

    def fake_get(url: str, *a: Any, **k: Any) -> _FakeResponse:
        return _FakeResponse(200, monitors if "/v1/monitors" in url else None, text=blob)

    monkeypatch.setattr(docker_monitors.settings, "container_blob_url", "http://blob/list")
    monkeypatch.setattr(
        docker_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(docker_monitors.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(requests, "get", fake_get)

    # caddy + bitwarden match the last token; homeassistant's monitor is http (not
    # docker); "web" must NOT match "WEBHOOK" (last-token whole-word, not substring).
    assert docker_monitors.collect() == {
        "monitored": 2,
        "unmonitored": 2,
        "total": 4,
        "unmonitored_containers": ["homeassistant", "web"],
    }


def test_docker_monitors_merges_multiple_blobs(monkeypatch: pytest.MonkeyPatch) -> None:
    blobs = {
        "http://blob/a": "docker.site,caddy.site.farm,86400\n",
        "http://blob/b": (
            "docker.site,bitwarden.site.farm,86400\ndocker.site,caddy.site.farm,86400\n"
        ),
    }
    monitors = {
        "monitors": [{"id": 1, "name": "AZURE CONTAINER CADDY", "type": "docker"}],
        "count": 1,
    }

    def fake_get(url: str, *a: Any, **k: Any) -> _FakeResponse:
        if "/v1/monitors" in url:
            return _FakeResponse(200, monitors)
        return _FakeResponse(200, None, text=blobs[url])

    monkeypatch.setattr(
        docker_monitors.settings, "container_blob_url", "http://blob/a,http://blob/b"
    )
    monkeypatch.setattr(
        docker_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(docker_monitors.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(requests, "get", fake_get)

    # caddy appears in both blobs (deduped); bitwarden only in the second.
    assert docker_monitors.collect() == {
        "monitored": 1,
        "unmonitored": 1,
        "total": 2,
        "unmonitored_containers": ["bitwarden"],
    }


def test_docker_monitors_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_monitors.settings, "container_blob_url", "")
    monkeypatch.setattr(docker_monitors.settings, "uptime_kuma_v2_api_base_url", "")
    with pytest.raises(CheckError) as excinfo:
        docker_monitors.collect()
    assert excinfo.value.code == "not_configured"


def test_docker_images_flags_unused_and_dangling(monkeypatch: pytest.MonkeyPatch) -> None:
    images = [
        SimpleNamespace(id="sha256:aaa", tags=["nginx:latest"], short_id="sha256:aaaaaa"),
        SimpleNamespace(id="sha256:bbb", tags=["redis:7"], short_id="sha256:bbbbbb"),
        SimpleNamespace(id="sha256:ccc", tags=[], short_id="sha256:cccccc"),
    ]
    # containers.list() yields inspect-shaped attrs: the image id is under "Image".
    containers = [SimpleNamespace(attrs={"Image": "sha256:aaa"})]
    client = SimpleNamespace(
        images=SimpleNamespace(list=lambda *a, **k: images),
        containers=SimpleNamespace(list=lambda *a, **k: containers),
        close=lambda: None,
    )
    monkeypatch.setattr(docker_images.docker, "DockerClient", lambda *a, **k: client)

    # nginx is used by a container; redis is used by none; the untagged image is dangling.
    assert docker_images.collect() == {
        "unused": 2,
        "total": 3,
        "unused_images": ["redis:7", "sha256:cccccc"],
    }


def test_docker_updater_update_all_triggers_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    status = {
        "containers": [
            {"name": "web", "status": "update", "image": "nginx:latest"},
            {"name": "db", "status": "ok", "image": "postgres:16"},
            {"name": "cache", "status": "update", "image": "redis:7"},
        ]
    }
    posted: list[str] = []

    def fake_post(url: str, *a: Any, **k: Any) -> _FakeResponse:
        posted.append(url)
        # 409 (already updating) must still count as triggered.
        return _FakeResponse(409 if url.endswith("/cache") else 200, {"ok": True})

    monkeypatch.setattr(docker_updater.settings, "docker_updater_base_url", "http://du")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, status))
    monkeypatch.setattr(requests, "post", fake_post)

    assert docker_updater.update_all() == {"triggered": ["web", "cache"], "count": 2}
    assert posted == ["http://du/api/update/web", "http://du/api/update/cache"]


def test_docker_updater_update_all_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_updater.settings, "docker_updater_base_url", "")
    with pytest.raises(CheckError) as excinfo:
        docker_updater.update_all()
    assert excinfo.value.code == "not_configured"


def test_docker_images_prune_unused_reports_reclaimed(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_prune(filters: Any = None) -> dict[str, Any]:
        captured["filters"] = filters
        return {
            "ImagesDeleted": [
                {"Untagged": "redis:7"},
                {"Deleted": "sha256:aaa"},
                {"Deleted": "sha256:bbb"},
            ],
            "SpaceReclaimed": 2 * 1024 * 1024,
        }

    client = SimpleNamespace(images=SimpleNamespace(prune=fake_prune), close=lambda: None)
    monkeypatch.setattr(docker_images.docker, "DockerClient", lambda *a, **k: client)

    # dangling=False prunes all unused images; only the two "Deleted" entries are removals.
    assert docker_images.prune_unused() == {
        "deleted": 2,
        "space_reclaimed": 2 * 1024 * 1024,
        "space_reclaimed_human": "2.0MB",
    }
    assert captured["filters"] == {"dangling": False}


def test_action_update_all_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_updater, "update_all", lambda: {"triggered": ["web"], "count": 1})
    resp = client.post("/actions/update-all")
    assert resp.status_code == 200
    assert resp.json == {"status": "ok", "triggered": ["web"], "count": 1}


def test_action_prune_images_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        docker_images,
        "prune_unused",
        lambda: {"deleted": 3, "space_reclaimed": 100, "space_reclaimed_human": "100B"},
    )
    resp = client.post("/actions/prune-images")
    assert resp.status_code == 200
    assert resp.json == {
        "status": "ok",
        "deleted": 3,
        "space_reclaimed": 100,
        "space_reclaimed_human": "100B",
    }


def test_action_error_returns_503(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> dict[str, Any]:
        raise CheckError("not_configured", "docker-updater is not configured")

    monkeypatch.setattr(docker_updater, "update_all", _boom)
    resp = client.post("/actions/update-all", expect_errors=True)
    assert resp.status_code == 503
    assert resp.json["status"] == "error"
    assert resp.json["code"] == "not_configured"


def test_ping_monitors_flags_uncovered_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    blob = (
        "# comment line\n"
        "10.0.1.5,netgearswitch.office.mayberry.farm,86400\n"
        "10.0.1.6,printer.office.mayberry.farm,86400\n"
        "10.0.1.7,router.home.mayberry.farm,86400\n"
    )
    monitors = {
        "monitors": [
            {"id": 1, "name": "OFFICE PING NETGEARSWITCH", "type": "ping"},
            {"id": 2, "name": "HOME PING ROUTER", "type": "http"},
            {"id": 3, "name": "OFFICE PING PRINTERLABEL", "type": "ping"},
        ],
        "count": 3,
    }

    def fake_get(url: str, *a: Any, **k: Any) -> _FakeResponse:
        return _FakeResponse(200, monitors if "/v1/monitors" in url else None, text=blob)

    monkeypatch.setattr(ping_monitors.settings, "sando_devices_url", "http://blob/devices")
    monkeypatch.setattr(
        ping_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(ping_monitors.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(requests, "get", fake_get)

    # netgearswitch has a ping monitor (last token matches); router's monitor is http
    # (not ping); "printer" must NOT match "PRINTERLABEL" (last-token whole-word).
    assert ping_monitors.collect() == {
        "monitored": 1,
        "unmonitored": 2,
        "total": 3,
        "unmonitored_devices": ["printer", "router"],
    }


def test_ping_monitors_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ping_monitors.settings, "sando_devices_url", "")
    monkeypatch.setattr(ping_monitors.settings, "uptime_kuma_v2_api_base_url", "")
    with pytest.raises(CheckError) as excinfo:
        ping_monitors.collect()
    assert excinfo.value.code == "not_configured"


def test_add_ping_monitor_creates_from_sando(monkeypatch: pytest.MonkeyPatch) -> None:
    # The device line's third field is a DNS TTL (86400s) and must be ignored; the
    # created monitor uses the fixed PING_INTERVAL_SECONDS cadence instead.
    blob = "10.0.1.5,netgearswitch.office.mayberry.farm,86400\n"
    posted: list[dict[str, Any]] = []

    def fake_post(url: str, *a: Any, **k: Any) -> _FakeResponse:
        posted.append({"url": url, "json": k.get("json"), "headers": k.get("headers")})
        return _FakeResponse(200, {"ok": True, "monitorID": 7, "msg": "successAdded"})

    monkeypatch.setattr(ping_monitors.settings, "sando_devices_url", "http://blob/devices")
    monkeypatch.setattr(
        ping_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(ping_monitors.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(ping_monitors.settings, "uptime_kuma_slug", "mine")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, text=blob))
    monkeypatch.setattr(requests, "post", fake_post)

    # name is built from the SANDO record (site + PING + device), not the caller input.
    assert ping_monitors.add_ping_monitor("NetgearSwitch") == {
        "created": "OFFICE PING NETGEARSWITCH",
        "monitor_id": 7,
        "hostname": "10.0.1.5",
        "status_page": "mine",
    }
    assert posted[0]["url"] == "http://kuma-v2:12000/v1/monitors"
    assert posted[0]["json"] == {
        "type": "ping",
        "name": "OFFICE PING NETGEARSWITCH",
        "hostname": "10.0.1.5",
        "interval": 60,
    }
    assert posted[0]["headers"] == {"X-API-Key": "secret"}
    assert posted[1]["url"] == "http://kuma-v2:12000/v1/statuspages/mine/monitors"
    assert posted[1]["json"] == {"monitor_ids": [7]}
    assert posted[1]["headers"] == {"X-API-Key": "secret"}


def test_add_ping_monitor_rejects_unknown_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ping_monitors.settings, "sando_devices_url", "http://blob/devices")
    monkeypatch.setattr(
        ping_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _FakeResponse(200, text="10.0.1.5,known.office.farm,86400\n")
    )
    with pytest.raises(CheckError) as excinfo:
        ping_monitors.add_ping_monitor("unknown")
    assert excinfo.value.code == "not_found"


def test_add_docker_monitor_creates_and_adds_to_status_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blob = "docker.azure.farm,web.azure.farm,86400\n"
    posted: list[dict[str, Any]] = []

    def fake_get(url: str, *a: Any, **k: Any) -> _FakeResponse:
        if url.endswith("/v1/monitors"):
            return _FakeResponse(200, {"monitors": []})
        if url.endswith("/v1/docker-hosts"):
            return _FakeResponse(200, {"hosts": [{"id": 2, "name": "local Docker"}]})
        return _FakeResponse(200, text=blob)

    def fake_post(url: str, *a: Any, **k: Any) -> _FakeResponse:
        posted.append({"url": url, "json": k.get("json"), "headers": k.get("headers")})
        payload = {"ok": True, "monitorID": 17} if url.endswith("/v1/monitors") else {"ok": True}
        return _FakeResponse(200, payload)

    monkeypatch.setattr(docker_monitors.settings, "container_blob_url", "http://blob/list")
    monkeypatch.setattr(
        docker_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(docker_monitors.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(docker_monitors.settings, "uptime_kuma_slug", "mine")
    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)

    assert docker_monitors.add_docker_monitor("web", 2) == {
        "created": "AZURE CONTAINER WEB",
        "monitor_id": 17,
        "container": "web",
        "docker_host": 2,
        "status_page": "mine",
    }
    assert posted[0]["url"] == "http://kuma-v2:12000/v1/monitors"
    assert posted[0]["json"] == {
        "type": "docker",
        "name": "AZURE CONTAINER WEB",
        "docker_host": 2,
        "docker_container": "web",
    }
    assert posted[1]["url"] == "http://kuma-v2:12000/v1/statuspages/mine/monitors"
    assert posted[1]["json"] == {"monitor_ids": [17]}
    assert all(call["headers"] == {"X-API-Key": "secret"} for call in posted)


def test_clear_all_heartbeats_uses_bulk_beats_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_delete(url: str, *a: Any, **k: Any) -> _FakeResponse:
        captured.update(url=url, headers=k.get("headers"))
        return _FakeResponse(200, {"ok": True, "msg": "all heartbeats and uptime statistics cleared"})

    monkeypatch.setattr(
        uptime_kuma_v2.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(uptime_kuma_v2.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(requests, "delete", fake_delete)

    assert uptime_kuma_v2.clear_all_heartbeats() == {
        "cleared": True,
        "message": "all heartbeats and uptime statistics cleared",
    }
    assert captured == {
        "url": "http://kuma-v2:12000/v1/beats",
        "headers": {"X-API-Key": "secret"},
    }


def test_additional_monitors_lists_uncovered(monkeypatch: pytest.MonkeyPatch) -> None:
    container_blob = "docker.site,caddy.azure.farm,86400\n"
    device_blob = "10.0.1.5,netgearswitch.office.farm,86400\n"
    monitors = {
        "monitors": [
            {"id": 1, "name": "AZURE CONTAINER CADDY", "type": "docker"},
            {"id": 2, "name": "OFFICE PING NETGEARSWITCH", "type": "ping"},
            {"id": 3, "name": "HOME HTTP ROUTERUI", "type": "http"},
            {"id": 4, "name": "OFFICE PING ORPHAN", "type": "ping"},
            {"id": 5, "name": "WHITELISTED THING", "type": "http"},
        ],
        "count": 5,
    }

    def fake_get(url: str, *a: Any, **k: Any) -> _FakeResponse:
        if "/v1/monitors" in url:
            return _FakeResponse(200, monitors)
        return _FakeResponse(200, text=device_blob if "devices" in url else container_blob)

    monkeypatch.setattr(
        additional_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(additional_monitors.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(additional_monitors.settings, "container_blob_url", "http://blob/containers")
    monkeypatch.setattr(additional_monitors.settings, "sando_devices_url", "http://blob/devices")
    monkeypatch.setattr(
        additional_monitors.settings, "allowed_additional_monitors", "WHITELISTED THING"
    )
    monkeypatch.setattr(requests, "get", fake_get)

    # caddy (docker) and netgearswitch (ping) are covered; the http monitor and the
    # orphan ping monitor are additional; the whitelisted monitor is excluded by name.
    assert additional_monitors.collect() == {
        "additional": 2,
        "allowed": 1,
        "total": 5,
        "additional_monitors": ["HOME HTTP ROUTERUI", "OFFICE PING ORPHAN"],
    }


def test_additional_monitors_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(additional_monitors.settings, "uptime_kuma_v2_api_base_url", "")
    with pytest.raises(CheckError) as excinfo:
        additional_monitors.collect()
    assert excinfo.value.code == "not_configured"


def test_additional_monitors_whitelist_partial_substring(monkeypatch: pytest.MonkeyPatch) -> None:
    monitors = {
        "monitors": [
            {"id": 1, "name": "HOME HTTP ROUTERUI", "type": "http"},
            {"id": 2, "name": "OFFICE HTTP SWITCHUI", "type": "http"},
        ],
        "count": 2,
    }
    monkeypatch.setattr(
        additional_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(additional_monitors.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(additional_monitors.settings, "container_blob_url", "")
    monkeypatch.setattr(additional_monitors.settings, "sando_devices_url", "")
    # a lower-case partial ("router") whitelists any monitor whose name contains it.
    monkeypatch.setattr(additional_monitors.settings, "allowed_additional_monitors", "router")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, monitors))

    assert additional_monitors.collect() == {
        "additional": 1,
        "allowed": 1,
        "total": 2,
        "additional_monitors": ["OFFICE HTTP SWITCHUI"],
    }


def test_docker_updater_update_one_triggers_known(monkeypatch: pytest.MonkeyPatch) -> None:
    status = {
        "containers": [
            {"name": "web", "status": "update", "image": "nginx:latest"},
            {"name": "db", "status": "ok", "image": "postgres:16"},
        ]
    }
    posted: list[str] = []

    def fake_post(url: str, *a: Any, **k: Any) -> _FakeResponse:
        posted.append(url)
        return _FakeResponse(200, {"ok": True})

    monkeypatch.setattr(docker_updater.settings, "docker_updater_base_url", "http://du")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, status))
    monkeypatch.setattr(requests, "post", fake_post)

    assert docker_updater.update_one("web") == {"triggered": "web"}
    assert posted == ["http://du/api/update/web"]


def test_docker_updater_update_one_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    status = {"containers": [{"name": "web", "status": "ok", "image": "nginx:latest"}]}
    monkeypatch.setattr(docker_updater.settings, "docker_updater_base_url", "http://du")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, status))
    with pytest.raises(CheckError) as excinfo:
        docker_updater.update_one("web")
    assert excinfo.value.code == "not_found"


def test_docker_images_remove_image_removes_unused(monkeypatch: pytest.MonkeyPatch) -> None:
    images = [
        SimpleNamespace(id="sha256:aaa", tags=["nginx:latest"], short_id="sha256:aaaaaa"),
        SimpleNamespace(id="sha256:bbb", tags=["redis:7"], short_id="sha256:bbbbbb"),
    ]
    containers = [SimpleNamespace(attrs={"Image": "sha256:aaa"})]
    removed: dict[str, Any] = {}

    def fake_remove(image: str, force: bool) -> None:
        removed["image"] = image
        removed["force"] = force

    client = SimpleNamespace(
        images=SimpleNamespace(list=lambda *a, **k: images, remove=fake_remove),
        containers=SimpleNamespace(list=lambda *a, **k: containers),
        close=lambda: None,
    )
    monkeypatch.setattr(docker_images.docker, "DockerClient", lambda *a, **k: client)

    # redis is used by no container (unused), so it is removable with force=False.
    assert docker_images.remove_image("redis:7") == {"removed": "redis:7"}
    assert removed == {"image": "redis:7", "force": False}


def test_docker_images_remove_image_rejects_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    images = [SimpleNamespace(id="sha256:aaa", tags=["nginx:latest"], short_id="sha256:aaaaaa")]
    containers = [SimpleNamespace(attrs={"Image": "sha256:aaa"})]
    client = SimpleNamespace(
        images=SimpleNamespace(list=lambda *a, **k: images, remove=lambda **k: None),
        containers=SimpleNamespace(list=lambda *a, **k: containers),
        close=lambda: None,
    )
    monkeypatch.setattr(docker_images.docker, "DockerClient", lambda *a, **k: client)

    with pytest.raises(CheckError) as excinfo:
        docker_images.remove_image("nginx:latest")
    assert excinfo.value.code == "not_found"


def test_ping_monitors_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ping_monitors,
        "collect",
        lambda: {"monitored": 1, "unmonitored": 1, "total": 2, "unmonitored_devices": ["printer"]},
    )
    resp = client.get("/ping-monitors")
    assert resp.status_code == 200
    assert resp.json == {
        "status": "ok",
        "monitored": 1,
        "unmonitored": 1,
        "total": 2,
        "unmonitored_devices": ["printer"],
    }


def test_additional_monitors_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        additional_monitors,
        "collect",
        lambda: {"additional": 1, "allowed": 0, "total": 4, "additional_monitors": ["X"]},
    )
    resp = client.get("/additional-monitors")
    assert resp.status_code == 200
    assert resp.json["additional_monitors"] == ["X"]


def test_action_add_ping_monitor_endpoint(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def fake(device: str) -> dict[str, Any]:
        captured["device"] = device
        return {"created": "OFFICE PING NETGEARSWITCH", "monitor_id": 7, "hostname": "10.0.1.5"}

    monkeypatch.setattr(ping_monitors, "add_ping_monitor", fake)
    resp = client.post_json("/actions/add-ping-monitor", {"device": "netgearswitch"})
    assert resp.status_code == 200
    assert resp.json["created"] == "OFFICE PING NETGEARSWITCH"
    assert captured["device"] == "netgearswitch"


def test_docker_hosts_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        uptime_kuma_v2,
        "fetch_docker_hosts",
        lambda: [{"id": 2, "name": "local Docker"}],
    )
    resp = client.get("/docker-hosts")
    assert resp.status_code == 200
    assert resp.json == {
        "status": "ok",
        "hosts": [{"id": 2, "name": "local Docker"}],
        "count": 1,
    }


def test_action_add_docker_monitor_endpoint(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def fake(container: str, host_id: int) -> dict[str, Any]:
        captured.update(container=container, host_id=host_id)
        return {"created": "AZURE CONTAINER WEB", "monitor_id": 17}

    monkeypatch.setattr(docker_monitors, "add_docker_monitor", fake)
    resp = client.post_json(
        "/actions/add-docker-monitor", {"container": "web", "host_id": 2}
    )
    assert resp.status_code == 200
    assert resp.json["created"] == "AZURE CONTAINER WEB"
    assert captured == {"container": "web", "host_id": 2}


def test_action_clear_heartbeats_endpoint(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        uptime_kuma_v2,
        "clear_all_heartbeats",
        lambda: {"cleared": True, "message": "all monitor heartbeats cleared"},
    )
    resp = client.post_json("/actions/clear-heartbeats", {})
    assert resp.status_code == 200
    assert resp.json == {
        "status": "ok",
        "cleared": True,
        "message": "all monitor heartbeats cleared",
    }


def test_action_redeploy_compose_endpoint(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        portainer_stacks,
        "redeploy_for_container",
        lambda name: {"container": name, "stack": "localmonitoring", "image_pull": False},
    )
    resp = client.post_json("/actions/redeploy-compose", {"container": "localmonitoring"})
    assert resp.status_code == 200
    assert resp.json == {
        "status": "ok",
        "container": "localmonitoring",
        "stack": "localmonitoring",
        "image_pull": False,
    }


def test_compose_stacks_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        portainer_stacks,
        "collect",
        lambda force_refresh=False: {"containers": [{"name": "web"}]},
    )
    resp = client.get("/compose-stacks")
    assert resp.status_code == 200
    assert resp.json == {"status": "ok", "containers": [{"name": "web"}]}


def test_compose_stacks_force_refresh_query(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(
        portainer_stacks,
        "collect",
        lambda force_refresh=False: calls.append(force_refresh) or {"containers": []},
    )
    resp = client.get("/compose-stacks?refresh=true")
    assert resp.status_code == 200
    assert calls == [True]


def test_compose_stacks_cache_and_force_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_collect() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"containers": [{"name": str(calls)}]}

    monkeypatch.setattr(portainer_stacks, "_collect_uncached", fake_collect)
    monkeypatch.setattr(portainer_stacks.settings, "compose_cache_ttl_seconds", 300)
    monkeypatch.setattr(portainer_stacks.settings, "docker_host", "tcp://docker-test")
    monkeypatch.setattr(portainer_stacks.settings, "portainer_url", "http://portainer-test")
    monkeypatch.setattr(portainer_stacks.settings, "docker_compose", "github.com/org/repo/site")
    portainer_stacks.clear_cache()
    try:
        assert portainer_stacks.collect() == {"containers": [{"name": "1"}]}
        assert portainer_stacks.collect() == {"containers": [{"name": "1"}]}
        assert calls == 1
        assert portainer_stacks.collect(force_refresh=True) == {"containers": [{"name": "2"}]}
        assert calls == 2
    finally:
        portainer_stacks.clear_cache()


def test_portainer_redeploy_matches_git_stack_and_disables_image_pull(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = {
        "Id": 42,
        "EndpointId": 4,
        "Name": "portainer-stack-name-differs",
        "ProjectPath": "/data/compose/31",
        "Env": [{"name": "SITE", "value": "house"}],
        "Option": {"Prune": True},
        "GitConfig": {
            "URL": "https://github.com/mayberryjp/dockercompose.git",
            "ConfigFilePath": "house/localmonitoring.yml",
            "ReferenceName": "refs/heads/main",
        },
    }
    monkeypatch.setattr(
        portainer_stacks.settings, "portainer_url", "http://portainer:9000"
    )
    monkeypatch.setattr(portainer_stacks.settings, "portainer_api_key", "secret")
    monkeypatch.setattr(
        portainer_stacks.settings,
        "docker_compose",
        "github.com/mayberryjp/dockercompose/house",
    )
    monkeypatch.setattr(
        portainer_stacks,
        "_container_rows",
        lambda: [
            {
                "name": "localmonitoring",
                "status": "running",
                "project": "localmonitoring",
                "service": "api",
                "config_files": "/data/compose/31/house/localmonitoring.yml",
                "working_dir": "/data/compose/31/house",
            }
        ],
    )
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, headers: dict[str, str], **kwargs: Any) -> Any:
        calls.append({"method": method, "url": url, "headers": headers, **kwargs})
        return [stack] if method == "GET" else {"Status": 1}

    monkeypatch.setattr(portainer_stacks, "_request_json", fake_request)

    assert portainer_stacks.redeploy_for_container("localmonitoring") == {
        "container": "localmonitoring",
        "stack": "portainer-stack-name-differs",
        "stack_id": 42,
        "source_file": "house/localmonitoring.yml",
        "image_pull": False,
        "status": 1,
    }
    assert calls[0]["url"] == "http://portainer:9000/api/stacks"
    assert calls[1]["method"] == "PUT"
    assert calls[1]["url"] == "http://portainer:9000/api/stacks/42/git/redeploy"
    assert calls[1]["params"] == {"endpointId": 4}
    assert calls[1]["json"] == {
        "Env": [{"name": "SITE", "value": "house"}],
        "Prune": True,
        "RepullImageAndRedeploy": False,
    }
    assert calls[1]["headers"] == {"X-API-Key": "secret"}


def test_portainer_redeploy_rejects_unlinked_compose_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        portainer_stacks.settings, "portainer_url", "http://portainer:9000"
    )
    monkeypatch.setattr(portainer_stacks.settings, "portainer_api_key", "secret")
    monkeypatch.setattr(
        portainer_stacks.settings,
        "docker_compose",
        "github.com/mayberryjp/dockercompose/house",
    )
    monkeypatch.setattr(
        portainer_stacks,
        "_container_rows",
        lambda: [{"name": "web", "project": "web", "config_files": "/opt/web/compose.yml"}],
    )
    monkeypatch.setattr(portainer_stacks, "_request_json", lambda *a, **k: [])

    with pytest.raises(CheckError) as excinfo:
        portainer_stacks.redeploy_for_container("web")
    assert excinfo.value.code == "not_found"


def test_compose_source_directory_selects_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        portainer_stacks.settings,
        "docker_compose",
        "https://github.com/mayberryjp/dockercompose/farm",
    )
    container = {
        "project": "app",
        "config_files": "/data/compose/4/farm/app.yml",
    }
    stack = {
        "Name": "app",
        "GitConfig": {
            "URL": "https://github.com/mayberryjp/dockercompose.git",
            "ConfigFilePath": "farm/app.yml",
        },
    }
    wrong_site = {
        "Name": "app",
        "GitConfig": {
            "URL": "https://github.com/mayberryjp/dockercompose.git",
            "ConfigFilePath": "house/app.yml",
        },
    }

    assert portainer_stacks._stack_for_container(container, [stack]) == stack
    assert portainer_stacks._stack_for_container(container, [wrong_site]) is None


def test_compose_inventory_classifies_linked_local_and_unmanaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portainer_stacks.settings, "portainer_url", "http://portainer:9000")
    monkeypatch.setattr(portainer_stacks.settings, "portainer_api_key", "secret")
    monkeypatch.setattr(
        portainer_stacks.settings,
        "docker_compose",
        "https://github.com/mayberryjp/dockercompose/house",
    )
    monkeypatch.setattr(
        portainer_stacks,
        "_container_rows",
        lambda: [
            {
                "name": "git-app",
                "project": "generated-compose-project",
                "service": "api",
                "config_files": "/data/compose/4/house/app.yml",
                "working_dir": "/data/compose/4/house",
            },
            {
                "name": "local-app",
                "project": "local-app",
                "service": "app",
                "config_files": "/opt/local/compose.yml",
                "working_dir": "/opt/local",
            },
            {"name": "manual", "project": None, "service": None, "config_files": ""},
        ],
    )
    monkeypatch.setattr(
        portainer_stacks,
        "_request_json",
        lambda *a, **k: [
            {
                "Id": 10,
                "EndpointId": 1,
                "Name": "portainer-stack-name-differs",
                "GitConfig": {
                    "URL": "https://github.com/mayberryjp/dockercompose.git",
                    "ConfigFilePath": "house/app.yml",
                },
            }
        ],
    )

    result = portainer_stacks._collect_uncached()["containers"]
    assert [(row["source"], row["github_managed"]) for row in result] == [
        ("github", True),
        ("local compose", False),
        ("unmanaged", False),
    ]
    assert result[0]["can_redeploy"] is True


@pytest.mark.parametrize(
    ("changed_path", "expected_status"),
    [("house/app.yml", "changed"), ("house/other.yml", "current")],
)
def test_compose_drift_checks_only_the_stack_compose_file(
    monkeypatch: pytest.MonkeyPatch, changed_path: str, expected_status: str
) -> None:
    request: dict[str, Any] = {}

    def fake_get(url: str, *a: Any, **kwargs: Any) -> _FakeResponse:
        request.update(url=url, headers=kwargs.get("headers"))
        return _FakeResponse(200, {"status": "ahead", "files": [{"filename": changed_path}]})

    monkeypatch.setattr(portainer_stacks.settings, "github_api_token", "gh-token")
    monkeypatch.setattr(
        portainer_stacks.settings,
        "docker_compose",
        "https://github.com/mayberryjp/dockercompose/house",
    )
    monkeypatch.setattr(portainer_stacks.requests, "get", fake_get)
    stack = {
        "GitConfig": {
            "ConfigHash": "deployed123",
            "ReferenceName": "refs/heads/main",
            "ConfigFilePath": "house/app.yml",
        }
    }

    assert portainer_stacks._compose_drift(stack)["status"] == expected_status
    assert "/repos/mayberryjp/dockercompose/compare/deployed123...main" in request["url"]
    assert request["headers"]["Authorization"] == "Bearer gh-token"


def test_compose_drift_is_unknown_without_github_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portainer_stacks.settings, "github_api_token", "")
    assert portainer_stacks._compose_drift({"GitConfig": {}}) == {
        "status": "unknown",
        "detail": "GITHUB_API_TOKEN is not configured",
    }


def test_compose_drift_reads_portainer_current_deployment_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: str, *a: Any, **kwargs: Any) -> _FakeResponse:
        captured["url"] = url
        return _FakeResponse(200, {"status": "ahead", "files": [{"filename": "azure/app.yml"}]})

    monkeypatch.setattr(portainer_stacks.settings, "github_api_token", "gh-token")
    monkeypatch.setattr(
        portainer_stacks.settings,
        "docker_compose",
        "https://github.com/mayberryjp/dockercompose/azure",
    )
    monkeypatch.setattr(portainer_stacks.requests, "get", fake_get)
    stack = {
        "GitConfig": {"URL": "https://github.com/mayberryjp/dockercompose.git"},
        "CurrentDeploymentInfo": {
            "ConfigHash": "deployed-from-current-info",
            "ReferenceName": "refs/heads/main",
            "ConfigFilePath": "azure/app.yml",
        },
    }

    assert portainer_stacks._compose_drift(stack)["status"] == "changed"
    assert "/compare/deployed-from-current-info...main" in captured["url"]


def test_compose_drift_uses_github_default_branch_when_portainer_ref_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    def fake_get(url: str, *a: Any, **kwargs: Any) -> _FakeResponse:
        urls.append(url)
        if url.endswith("/repos/mayberryjp/dockercompose"):
            return _FakeResponse(200, {"default_branch": "main"})
        return _FakeResponse(
            200,
            {"status": "ahead", "files": [{"filename": "azure/homepage.yml"}]},
        )

    monkeypatch.setattr(portainer_stacks.settings, "github_api_token", "gh-token")
    monkeypatch.setattr(
        portainer_stacks.settings,
        "docker_compose",
        "https://github.com/mayberryjp/dockercompose/azure",
    )
    monkeypatch.setattr(portainer_stacks.requests, "get", fake_get)
    stack = {
        "CurrentDeploymentInfo": {
            "ConfigHash": "deployed123",
            "ReferenceName": "",
            "ConfigFilePath": "azure/homepage.yml",
        }
    }

    assert portainer_stacks._compose_drift(stack)["status"] == "changed"
    assert urls == [
        "https://api.github.com/repos/mayberryjp/dockercompose",
        "https://api.github.com/repos/mayberryjp/dockercompose/compare/deployed123...main",
    ]


def test_dashboard_shows_monitor_actions(client: TestApp) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'id="clear-all-heartbeats"' in resp.text
    assert "clear all monitor heartbeats" in resp.text
    assert "Monitor definitions will remain" in resp.text
    assert 'data-url="/actions/add-docker-monitor"' in resp.text
    assert 'url: "/actions/redeploy-compose"' in resp.text
    assert 'var REFRESH_MS = 300000;' in resp.text
    assert 'var summaryUrl = "/summary"' in resp.text
    assert 'fetch(summaryUrl, { cache: "no-store" })' in resp.text
    assert 'fetch(composeUrl' not in resp.text
    assert 'refreshBtn.addEventListener("click", function () { refresh(true); });' in resp.text


def test_action_update_one_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_updater, "update_one", lambda name: {"triggered": name})
    resp = client.post_json("/actions/update", {"name": "web"})
    assert resp.status_code == 200
    assert resp.json == {"status": "ok", "triggered": "web"}


def test_action_delete_image_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_images, "remove_image", lambda image: {"removed": image})
    resp = client.post_json("/actions/delete-image", {"image": "redis:7"})
    assert resp.status_code == 200
    assert resp.json == {"status": "ok", "removed": "redis:7"}


def test_action_missing_field_returns_400(client: TestApp) -> None:
    resp = client.post_json("/actions/update", {}, expect_errors=True)
    assert resp.status_code == 400
    assert resp.json["code"] == "invalid_request"


def test_additional_monitors_delete_removes_additional(monkeypatch: pytest.MonkeyPatch) -> None:
    monitors = {
        "monitors": [
            {"id": 1, "name": "AZURE CONTAINER CADDY", "type": "docker"},
            {"id": 9, "name": "HOME HTTP ROUTERUI", "type": "http"},
        ],
        "count": 2,
    }
    deleted: dict[str, Any] = {}

    def fake_delete(url: str, *a: Any, **k: Any) -> _FakeResponse:
        deleted["url"] = url
        deleted["headers"] = k.get("headers")
        return _FakeResponse(200, {"ok": True, "msg": "Deleted Successfully."})

    monkeypatch.setattr(
        additional_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(additional_monitors.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(additional_monitors.settings, "container_blob_url", "")
    monkeypatch.setattr(additional_monitors.settings, "sando_devices_url", "")
    monkeypatch.setattr(additional_monitors.settings, "allowed_additional_monitors", "caddy")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, monitors))
    monkeypatch.setattr(requests, "delete", fake_delete)

    # caddy is whitelisted, so only the uncovered http monitor is additional/deletable.
    assert additional_monitors.delete_monitor("HOME HTTP ROUTERUI") == {
        "deleted": "HOME HTTP ROUTERUI",
        "monitor_id": 9,
    }
    assert deleted["url"] == "http://kuma-v2:12000/v1/monitors/9"
    assert deleted["headers"] == {"X-API-Key": "secret"}


def test_additional_monitors_delete_rejects_non_additional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitors = {
        "monitors": [{"id": 1, "name": "AZURE CONTAINER CADDY", "type": "docker"}],
        "count": 1,
    }
    monkeypatch.setattr(
        additional_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(additional_monitors.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(additional_monitors.settings, "container_blob_url", "")
    monkeypatch.setattr(additional_monitors.settings, "sando_devices_url", "")
    monkeypatch.setattr(additional_monitors.settings, "allowed_additional_monitors", "caddy")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, monitors))

    # caddy is whitelisted (not additional), so it cannot be deleted via this action.
    with pytest.raises(CheckError) as excinfo:
        additional_monitors.delete_monitor("AZURE CONTAINER CADDY")
    assert excinfo.value.code == "not_found"


def test_allowlist_flags_unmatched_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monitors = {
        "monitors": [
            {"id": 1, "name": "AZURE CONTAINER CADDY", "type": "docker"},
            {"id": 2, "name": "OFFICE PING NETGEARSWITCH", "type": "ping"},
        ],
        "count": 2,
    }
    monkeypatch.setattr(allowlist.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000")
    monkeypatch.setattr(allowlist.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(
        allowlist.settings, "allowed_additional_monitors", "caddy, ghost, netgear"
    )
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, monitors))

    # "caddy" and "netgear" appear in a monitor name; "ghost" matches nothing -> warn.
    assert allowlist.collect() == {
        "allowed": 3,
        "unmatched": 1,
        "unmatched_allowed": ["ghost"],
    }


def test_allowlist_empty_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> _FakeResponse:
        raise AssertionError("allowlist must not fetch monitors when the whitelist is empty")

    monkeypatch.setattr(allowlist.settings, "allowed_additional_monitors", "")
    monkeypatch.setattr(allowlist.settings, "uptime_kuma_v2_api_base_url", "")
    monkeypatch.setattr(requests, "get", boom)
    assert allowlist.collect() == {"allowed": 0, "unmatched": 0, "unmatched_allowed": []}


def test_allowlist_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        allowlist,
        "collect",
        lambda: {"allowed": 2, "unmatched": 1, "unmatched_allowed": ["ghost"]},
    )
    resp = client.get("/allowlist")
    assert resp.status_code == 200
    assert resp.json["unmatched_allowed"] == ["ghost"]


def test_action_delete_monitor_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        additional_monitors, "delete_monitor", lambda name: {"deleted": name, "monitor_id": 9}
    )
    resp = client.post_json("/actions/delete-monitor", {"name": "HOME HTTP ROUTERUI"})
    assert resp.status_code == 200
    assert resp.json == {"status": "ok", "deleted": "HOME HTTP ROUTERUI", "monitor_id": 9}


def test_docker_containers_start_container_starts_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: dict[str, Any] = {}

    def fake_start() -> None:
        started["ok"] = True

    stopped = SimpleNamespace(name="old-db", status="exited", start=fake_start)
    running = SimpleNamespace(name="web", status="running")
    client = SimpleNamespace(
        containers=SimpleNamespace(list=lambda *a, **k: [running, stopped]),
        close=lambda: None,
    )
    monkeypatch.setattr(docker_containers.docker, "DockerClient", lambda *a, **k: client)

    assert docker_containers.start_container("old-db") == {"started": "old-db"}
    assert started == {"ok": True}


def test_docker_containers_start_container_rejects_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = SimpleNamespace(name="web", status="running", start=lambda: None)
    client = SimpleNamespace(
        containers=SimpleNamespace(list=lambda *a, **k: [running]), close=lambda: None
    )
    monkeypatch.setattr(docker_containers.docker, "DockerClient", lambda *a, **k: client)

    with pytest.raises(CheckError) as excinfo:
        docker_containers.start_container("web")
    assert excinfo.value.code == "not_found"


def test_docker_containers_delete_container_removes_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    removed: dict[str, Any] = {}

    def fake_remove(**k: Any) -> None:
        removed.update(k)

    stopped = SimpleNamespace(name="old-db", status="exited", remove=fake_remove)
    client = SimpleNamespace(
        containers=SimpleNamespace(list=lambda *a, **k: [stopped]), close=lambda: None
    )
    monkeypatch.setattr(docker_containers.docker, "DockerClient", lambda *a, **k: client)

    assert docker_containers.remove_container("old-db") == {"deleted": "old-db"}
    assert removed == {"force": False}


def test_docker_containers_delete_container_rejects_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = SimpleNamespace(name="web", status="running", remove=lambda **k: None)
    client = SimpleNamespace(
        containers=SimpleNamespace(list=lambda *a, **k: [running]), close=lambda: None
    )
    monkeypatch.setattr(docker_containers.docker, "DockerClient", lambda *a, **k: client)

    with pytest.raises(CheckError) as excinfo:
        docker_containers.remove_container("web")
    assert excinfo.value.code == "not_found"


def test_action_start_container_endpoint(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(docker_containers, "start_container", lambda name: {"started": name})
    resp = client.post_json("/actions/start-container", {"name": "old-db"})
    assert resp.status_code == 200
    assert resp.json == {"status": "ok", "started": "old-db"}


def test_action_delete_container_endpoint(
    client: TestApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(docker_containers, "remove_container", lambda name: {"deleted": name})
    resp = client.post_json("/actions/delete-container", {"name": "old-db"})
    assert resp.status_code == 200
    assert resp.json == {"status": "ok", "deleted": "old-db"}
