"""Deterministic pull-stream tests; these never connect to Docker."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import Mock

import pytest
import requests
from docker.errors import DockerException
from webtest import TestApp

from local_monitoring.domain import image_downloads
from local_monitoring.domain.errors import CheckError


@pytest.fixture()
def tracker(monkeypatch: pytest.MonkeyPatch) -> image_downloads.DownloadTracker:
    monkeypatch.setattr(image_downloads.threading, "Thread", Mock())
    return image_downloads.DownloadTracker()


def _job(tracker: image_downloads.DownloadTracker) -> dict[str, Any]:
    result: dict[str, Any] = tracker.collect()["downloads"][0]
    return result


def test_start_normalizes_and_deduplicates(tracker: image_downloads.DownloadTracker) -> None:
    first = tracker.start(" nginx ")
    second = tracker.start("nginx:latest")
    assert first["download"]["image"] == "nginx:latest"
    assert first["download"]["state"] == "pulling"
    assert first["already_running"] is False
    assert second["already_running"] is True
    assert second["download"]["id"] == first["download"]["id"]
    assert len(tracker.collect()["downloads"]) == 1


@pytest.mark.parametrize(
    "image", ["", " ", "-bad", "https://host/image", "a\nb", "a;whoami", "a:", "a@", "a/"]
)
def test_invalid_reference(tracker: image_downloads.DownloadTracker, image: str) -> None:
    with pytest.raises(CheckError) as exc:
        tracker.start(image)
    assert exc.value.code == "invalid_request"
    assert tracker.collect() == {"downloads": []}


@pytest.mark.parametrize(
    "reference", ["localhost:5000/team/app:v1", "nginx:1.27", "repo/app@sha256:" + "a" * 64]
)
def test_reference_keeps_registry_tag_and_digest(
    tracker: image_downloads.DownloadTracker, reference: str
) -> None:
    assert tracker.start(reference)["download"]["image"] == reference


def test_active_limit_and_no_leaked_slot(
    tracker: image_downloads.DownloadTracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker.start("first")
    tracker.start("second")
    with pytest.raises(CheckError) as exc:
        tracker.start("third")
    assert exc.value.code == "busy"
    assert tracker.start("first")["already_running"] is True
    assert len(tracker.collect()["downloads"]) == 2

    empty_tracker = image_downloads.DownloadTracker()
    monkeypatch.setattr(
        image_downloads.threading,
        "Thread",
        Mock(return_value=Mock(start=Mock(side_effect=RuntimeError("no thread")))),
    )
    with pytest.raises(CheckError, match="could not start"):
        empty_tracker.start("web")
    assert empty_tracker.collect() == {"downloads": []}


def test_layer_counters_keep_download_and_extraction_separate(
    tracker: image_downloads.DownloadTracker,
) -> None:
    job_id = tracker.start("web")["download"]["id"]
    tracker._event(job_id, {"id": "latest", "status": "Pulling from library/web"})
    tracker._event(job_id, {"id": "cached", "status": "Already exists"})
    tracker._event(job_id, {"id": "waiting", "status": "Waiting"})
    tracker._event(
        job_id,
        {"id": "a", "status": "Downloading", "progressDetail": {"current": 40, "total": 100}},
    )
    snapshot = _job(tracker)
    assert snapshot["downloaded_bytes"] == 40
    assert snapshot["total_bytes"] is None
    assert snapshot["unmeasured_layers"] == 1
    assert len(snapshot["layers"]) == 3
    tracker._event(job_id, {"id": "a", "status": "Download complete"})
    tracker._event(
        job_id,
        {"id": "a", "status": "Extracting", "progressDetail": {"current": 200, "total": 1000}},
    )
    tracker._event(
        job_id, {"id": "b", "status": "Downloading", "progressDetail": {"current": 10, "total": 50}}
    )
    snapshot = _job(tracker)
    assert snapshot["downloaded_bytes"] == 110
    assert snapshot["total_bytes"] is None
    layer = next(layer for layer in snapshot["layers"] if layer["id"] == "a")
    assert layer["downloaded_bytes"] == 100
    assert layer["extracted_bytes"] == 200
    assert layer["extract_total_bytes"] == 1000
    assert snapshot["state"] == "pulling"
    snapshot["layers"].clear()
    assert len(_job(tracker)["layers"]) == 4
    tracker._event(job_id, {"id": "waiting", "status": "Already exists"})
    assert _job(tracker)["total_bytes"] == 150
    tracker._event(job_id, {"id": "a", "status": "Pull complete"})
    completed = next(layer for layer in _job(tracker)["layers"] if layer["id"] == "a")
    assert completed["extracted_bytes"] == 1000


def test_unknown_totals_do_not_become_zero_or_fake_completion(
    tracker: image_downloads.DownloadTracker,
) -> None:
    job_id = tracker.start("web")["download"]["id"]
    tracker._event(job_id, {"id": "a", "status": "Downloading", "progressDetail": {"current": 25}})
    tracker._event(job_id, {"id": "b", "status": "Already exists"})
    snapshot = _job(tracker)
    assert snapshot["total_bytes"] is None
    assert snapshot["downloaded_bytes"] == 25
    assert snapshot["unmeasured_layers"] == 1
    assert snapshot["layers"][0]["downloaded_bytes"] == 25
    tracker._event(
        job_id,
        {"id": "a", "status": "Downloading", "progressDetail": {"current": 110, "total": 100}},
    )
    assert _job(tracker)["downloaded_bytes"] == 100


def test_worker_streams_progress_and_confirms_success(
    tracker: image_downloads.DownloadTracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = tracker.start("web")["download"]["id"]
    closed = Mock()

    def events() -> Iterator[dict[str, Any]]:
        try:
            yield {
                "id": "a",
                "status": "Downloading",
                "progressDetail": {"current": 15, "total": 100},
            }
            assert _job(tracker)["downloaded_bytes"] == 15
            yield {"id": "a", "status": "Pull complete"}
            assert _job(tracker)["state"] == "pulling"
            yield {"status": "Status: Downloaded newer image for web:latest"}
        finally:
            closed()

    docker_client = Mock()
    docker_client.api.pull.return_value = events()
    monkeypatch.setattr(image_downloads.docker, "DockerClient", Mock(return_value=docker_client))
    tracker._pull(job_id)
    docker_client.api.pull.assert_called_once_with("web:latest", stream=True, decode=True)
    docker_client.close.assert_called_once()
    docker_client.containers.assert_not_called()
    closed.assert_called_once()
    assert _job(tracker)["state"] == "complete"
    assert _job(tracker)["finished_at"] is not None
    assert _job(tracker)["downloaded_bytes"] == 100
    assert tracker.start("web")["already_running"] is False


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"id": "a", "status": "Pull complete"}],
        [{"error": "denied: access forbidden"}],
        [{"errorDetail": {"message": "registry denied"}}],
        [{"progressDetail": "bad"}],
        ["not an event"],
    ],
)
def test_failed_or_interrupted_stream_is_not_success(
    tracker: image_downloads.DownloadTracker, monkeypatch: pytest.MonkeyPatch, events: list[Any]
) -> None:
    job_id = tracker.start("private/app")["download"]["id"]
    docker_client = Mock()
    docker_client.api.pull.return_value = (event for event in events)
    monkeypatch.setattr(image_downloads.docker, "DockerClient", Mock(return_value=docker_client))
    tracker._pull(job_id)
    assert _job(tracker)["state"] == "failed"
    assert _job(tracker)["error"]
    assert _job(tracker)["finished_at"]
    docker_client.close.assert_called_once()


@pytest.mark.parametrize(
    "error", [DockerException("no daemon"), requests.ConnectionError("lost connection")]
)
def test_connection_errors_release_job(
    tracker: image_downloads.DownloadTracker, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    job_id = tracker.start("web")["download"]["id"]
    monkeypatch.setattr(image_downloads.docker, "DockerClient", Mock(side_effect=error))
    tracker._pull(job_id)
    assert _job(tracker)["state"] == "failed"
    assert _job(tracker)["error"] == str(error)


def test_history_is_bounded(
    tracker: image_downloads.DownloadTracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker_client = Mock()
    docker_client.api.pull.side_effect = lambda *args, **kwargs: iter_events()

    def iter_events() -> Iterator[dict[str, Any]]:
        yield {"status": "Status: Image is up to date for web"}

    monkeypatch.setattr(image_downloads.docker, "DockerClient", Mock(return_value=docker_client))
    for index in range(51):
        job_id = tracker.start(f"web:{index}")["download"]["id"]
        tracker._pull(job_id)
    jobs = tracker.collect()["downloads"]
    assert len(jobs) == 50
    assert jobs[0]["image"] == "web:50"
    assert jobs[-1]["image"] == "web:1"


def test_connection_loss_preserves_partial_bytes_and_closes(
    tracker: image_downloads.DownloadTracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = tracker.start("web")["download"]["id"]

    def events() -> Iterator[dict[str, Any]]:
        yield {
            "id": "a",
            "status": "Downloading",
            "progressDetail": {"current": 25, "total": 100},
        }
        raise requests.ConnectionError("stream disconnected")

    docker_client = Mock()
    docker_client.api.pull.return_value = events()
    monkeypatch.setattr(image_downloads.docker, "DockerClient", Mock(return_value=docker_client))
    tracker._pull(job_id)
    assert _job(tracker)["downloaded_bytes"] == 25
    assert _job(tracker)["state"] == "failed"
    assert _job(tracker)["error"] == "stream disconnected"
    docker_client.close.assert_called_once()


def test_routes_and_navigation(
    client: TestApp, tracker: image_downloads.DownloadTracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_downloads, "tracker", tracker)
    page = client.get("/downloads")
    assert page.content_type == "text/html"
    assert "setInterval(refresh, 2000)" in page.text
    assert "Running containers will not be restarted" in page.text
    for path in ("/", "/containers"):
        assert 'href="/downloads"' in client.get(path).text
    assert client.get("/image-downloads").json == {"status": "ok", "downloads": []}
    started = client.post_json("/actions/pull-image", {"image": "web"}, status=202)
    assert started.json["download"]["image"] == "web:latest"
    duplicate = client.post_json("/actions/pull-image", {"image": "web"}, status=200)
    assert duplicate.json["already_running"] is True
    response = client.get("/image-downloads")
    assert response.headers["Cache-Control"] == "no-store"
    assert len(response.json["downloads"]) == 1


@pytest.mark.parametrize("body", [{}, [], {"image": 1}, {"image": ""}, {"image": "a b"}])
def test_pull_route_rejects_invalid_input(
    client: TestApp,
    tracker: image_downloads.DownloadTracker,
    monkeypatch: pytest.MonkeyPatch,
    body: object,
) -> None:
    monkeypatch.setattr(image_downloads, "tracker", tracker)
    assert (
        client.post_json("/actions/pull-image", body, status=400).json["code"] == "invalid_request"
    )
    assert tracker.collect() == {"downloads": []}


def test_pull_route_reports_capacity(
    client: TestApp, tracker: image_downloads.DownloadTracker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image_downloads, "tracker", tracker)
    tracker.start("one")
    tracker.start("two")
    response = client.post_json("/actions/pull-image", {"image": "three"}, status=503)
    assert response.json["code"] == "busy"
