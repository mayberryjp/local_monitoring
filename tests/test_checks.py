"""Tests for the aggregate and individual check endpoints and reducers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests
from webtest import TestApp

from local_monitoring.domain import (
    additional_monitors,
    docker_containers,
    docker_images,
    docker_monitors,
    docker_updater,
    ping_monitors,
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
    monkeypatch.setattr(docker_monitors, "collect", lambda: {"monitored": 6, "unmonitored": 1})
    monkeypatch.setattr(ping_monitors, "collect", lambda: {"monitored": 3, "unmonitored": 0})
    monkeypatch.setattr(additional_monitors, "collect", lambda: {"additional": 2})
    monkeypatch.setattr(docker_images, "collect", lambda: {"unused": 2, "total": 25})

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
        "docker_images",
    }
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
    monkeypatch.setattr(docker_monitors, "collect", lambda: {"monitored": 1, "unmonitored": 0})
    monkeypatch.setattr(ping_monitors, "collect", lambda: {"monitored": 1, "unmonitored": 0})
    monkeypatch.setattr(additional_monitors, "collect", lambda: {"additional": 0})
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
    blob = "10.0.1.5,netgearswitch.office.mayberry.farm,600\n"
    posted: dict[str, Any] = {}

    def fake_post(url: str, *a: Any, **k: Any) -> _FakeResponse:
        posted["url"] = url
        posted["json"] = k.get("json")
        posted["headers"] = k.get("headers")
        return _FakeResponse(200, {"ok": True, "monitorID": 7, "msg": "successAdded"})

    monkeypatch.setattr(ping_monitors.settings, "sando_devices_url", "http://blob/devices")
    monkeypatch.setattr(
        ping_monitors.settings, "uptime_kuma_v2_api_base_url", "http://kuma-v2:12000"
    )
    monkeypatch.setattr(ping_monitors.settings, "uptime_kuma_v2_api_key", "secret")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(200, text=blob))
    monkeypatch.setattr(requests, "post", fake_post)

    # name is built from the SANDO record (site + PING + device), not the caller input.
    assert ping_monitors.add_ping_monitor("NetgearSwitch") == {
        "created": "OFFICE PING NETGEARSWITCH",
        "monitor_id": 7,
        "hostname": "10.0.1.5",
    }
    assert posted["url"] == "http://kuma-v2:12000/v1/monitors"
    assert posted["json"] == {
        "type": "ping",
        "name": "OFFICE PING NETGEARSWITCH",
        "hostname": "10.0.1.5",
        "interval": 600,
    }
    assert posted["headers"] == {"X-API-Key": "secret"}


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
