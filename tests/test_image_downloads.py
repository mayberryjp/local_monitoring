"""docker-updater pull progress tests; these never connect to Docker."""

from typing import Any
from unittest.mock import Mock

import pytest
import requests
from webtest import TestApp

from local_monitoring.domain import docker_updater, image_downloads


@pytest.fixture()
def upstream(monkeypatch: pytest.MonkeyPatch) -> Mock:
    monkeypatch.setattr(image_downloads.settings, "docker_updater_base_url", "http://updater/")
    get = Mock(return_value=Mock(status_code=200, json=Mock(return_value={"pulls": []})))
    monkeypatch.setattr(image_downloads.requests, "get", get)
    return get


def _pull(**changes: Any) -> dict[str, Any]:
    return {
        "id": "web",
        "image": "nginx:latest",
        "container": "web",
        "host_id": "local",
        "started_at": "2026-10-16T17:00:00Z",
        "progress_bytes": 5242880,
        "total_bytes": 10485760,
        "percent_complete": 50.0,
        "total_estimated": False,
        "phase": "downloading",
        **changes,
    }


def test_routes_and_navigation(client: TestApp, upstream: Mock) -> None:
    page = client.get("/downloads")
    assert page.content_type == "text/html"
    assert "setInterval(refresh, 2000)" in page.text
    assert "docker-updater" in page.text
    assert "data.pulls" in page.text
    assert 'id="pull-form"' not in page.text
    assert "/actions/pull-image" not in page.text
    for path in ("/", "/containers"):
        assert 'href="/downloads"' in client.get(path).text
    response = client.get("/image-downloads")
    assert response.json == {"status": "ok", "pulls": []}
    assert response.headers["Cache-Control"] == "no-store"
    upstream.assert_called_once_with(
        "http://updater/api/pulls",
        timeout=image_downloads.settings.http_timeout_seconds,
        allow_redirects=False,
    )
    client.post_json("/actions/pull-image", {"image": "nginx:latest"}, status=405)


def test_update_from_monitoring_appears_in_downloads(
    client: TestApp, upstream: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    pull = _pull()
    update = Mock(return_value={"triggered": "web"})
    monkeypatch.setattr(docker_updater, "update_one", update)
    assert client.post_json("/actions/update", {"name": "web"}).json["triggered"] == "web"
    update.assert_called_once_with("web")
    upstream.return_value.json.return_value = {"pulls": [pull]}
    assert client.get("/image-downloads").json == {"status": "ok", "pulls": [pull]}
    upstream.return_value.json.return_value = {"pulls": []}
    assert client.get("/image-downloads").json["pulls"] == []


def test_unknown_totals_cached_layers_and_multiple_hosts(client: TestApp, upstream: Mock) -> None:
    pulls = [
        _pull(total_bytes=None, percent_complete=None),
        _pull(id="remote::web", host_id="remote", progress_bytes=0, total_bytes=0,
              percent_complete=100.0),
    ]
    upstream.return_value.json.return_value = {"pulls": pulls}
    assert client.get("/image-downloads").json["pulls"] == pulls


@pytest.mark.parametrize("phase", ["starting", "downloading", "extracting", "finishing"])
@pytest.mark.parametrize("total_estimated", [False, True])
def test_phase_and_estimate_are_preserved(
    client: TestApp, upstream: Mock, phase: str, total_estimated: bool
) -> None:
    pull = _pull(phase=phase, total_estimated=total_estimated)
    upstream.return_value.json.return_value = {"pulls": [pull]}
    assert client.get("/image-downloads").json["pulls"] == [pull]


@pytest.mark.parametrize("field", ["phase", "total_estimated"])
def test_legacy_progress_is_rejected(client: TestApp, upstream: Mock, field: str) -> None:
    pull = _pull()
    del pull[field]
    upstream.return_value.json.return_value = {"pulls": [pull]}
    response = client.get("/image-downloads", status=503)
    assert response.json["code"] == "upstream_error"
    assert response.json["error"] == "docker-updater returned invalid pull progress"


def test_unconfigured_is_not_an_empty_list(
    client: TestApp, upstream: Mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_downloads.settings, "docker_updater_base_url", "")
    response = client.get("/image-downloads", status=503)
    assert response.json["code"] == "not_configured"
    assert "pulls" not in response.json
    upstream.assert_not_called()


@pytest.mark.parametrize("status", [302, 401, 403, 404, 500])
def test_upstream_http_errors(client: TestApp, upstream: Mock, status: int) -> None:
    upstream.return_value.status_code = status
    response = client.get("/image-downloads", status=503)
    assert response.json["status"] == "error"
    assert response.json["code"] == "upstream_error"
    assert str(status) in response.json["error"]
    if status == 404:
        assert "GET /api/pulls" in response.json["error"]


@pytest.mark.parametrize(
    "error", [requests.ConnectionError("connection lost"), requests.Timeout("timed out")]
)
def test_network_failure(client: TestApp, upstream: Mock, error: Exception) -> None:
    upstream.side_effect = error
    response = client.get("/image-downloads", status=503)
    assert response.json["code"] == "upstream_unreachable"
    assert response.json["detail"] == str(error)


@pytest.mark.parametrize(
    "payload",
    [
        None, [], {}, {"pulls": None}, {"pulls": {}}, {"pulls": [None]},
        {"pulls": [{"image": "nginx"}]},
        {"pulls": [_pull(progress_bytes=-1)]},
        {"pulls": [_pull(progress_bytes=True)]},
        {"pulls": [_pull(progress_bytes="5")]},
        {"pulls": [_pull(total_bytes=-1)]},
        {"pulls": [_pull(percent_complete=101)]},
        {"pulls": [_pull(percent_complete=float("nan"))]},
        {"pulls": [_pull(percent_complete=float("inf"))]},
        {"pulls": [_pull(image="")]},
        {"pulls": [_pull(total_estimated=None)]},
        {"pulls": [_pull(total_estimated="true")]},
        {"pulls": [_pull(total_estimated=1)]},
        {"pulls": [_pull(phase=None)]},
        {"pulls": [_pull(phase="queued")]},
        {"pulls": [_pull(phase="")]},
        {"pulls": [_pull(phase=1)]},
    ],
)
def test_malformed_progress_is_an_explicit_error(
    client: TestApp, upstream: Mock, payload: Any
) -> None:
    upstream.return_value.json.return_value = payload
    response = client.get("/image-downloads", status=503)
    assert response.json["code"] == "upstream_error"
    assert response.json["error"] == "docker-updater returned invalid pull progress"


def test_non_json_response(client: TestApp, upstream: Mock) -> None:
    upstream.return_value.json.side_effect = ValueError("not JSON")
    response = client.get("/image-downloads", status=503)
    assert response.json["code"] == "upstream_error"
    assert response.json["detail"] == "not JSON"
