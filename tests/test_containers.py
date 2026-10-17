"""Container management inventory, actions, and page tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from docker.errors import DockerException
from webtest import TestApp

from local_monitoring.domain import docker_containers
from local_monitoring.domain.errors import CheckError


def test_management_page_is_separate(client: TestApp) -> None:
    dashboard = client.get("/")
    assert 'href="/containers"' in dashboard.text
    assert "/container-inventory" not in dashboard.text
    page = client.get("/containers")
    assert page.content_type == "text/html"
    assert 'href="/"' in page.text
    assert "/container-inventory" in page.text
    assert "/actions/restart-container" in page.text
    assert "/actions/redeploy-compose" in page.text
    assert "/actions/delete-standalone-container" in page.text
    assert "container.compose_managed === false" in page.text
    assert "Permanently DELETE" in page.text
    assert "This cannot be undone." in page.text
    assert "window.confirm" in page.text
    assert "ENTIRE stack" in page.text


def test_inventory_includes_all_states_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    containers = [
        SimpleNamespace(
            name="web", status="running",
            attrs={"Config": {"Image": "nginx:latest", "Labels": {"com.docker.compose.project": "app"}}},
        ),
        SimpleNamespace(
            name="Backup", status="exited",
            attrs={"Config": {"Image": "backup:1", "Labels": None}},
        ),
        SimpleNamespace(name="portainer", status="paused", attrs={}),
    ]
    docker_client = Mock()
    docker_client.containers.list.return_value = containers
    monkeypatch.setattr(docker_containers.docker, "DockerClient", Mock(return_value=docker_client))

    assert docker_containers.inventory() == {
        "containers": [
            {"name": "Backup", "state": "exited", "image": "backup:1", "compose_managed": False},
            {"name": "portainer", "state": "paused", "image": "", "compose_managed": False},
            {"name": "web", "state": "running", "image": "nginx:latest", "compose_managed": True},
        ]
    }
    docker_client.containers.list.assert_called_once_with(all=True)
    docker_client.close.assert_called_once()


@pytest.mark.parametrize("state", ["running", "exited"])
def test_restart_matches_exact_live_name(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    container = Mock()
    container.name = "web"
    container.status = state
    other = Mock()
    other.name = "web-old"
    docker_client = Mock()
    docker_client.containers.list.return_value = [other, container]
    monkeypatch.setattr(docker_containers.docker, "DockerClient", Mock(return_value=docker_client))

    assert docker_containers.restart_container(" web ") == {"restarted": "web"}
    docker_client.containers.list.assert_called_once_with(all=True)
    container.restart.assert_called_once_with()
    other.restart.assert_not_called()
    docker_client.close.assert_called_once()


def test_restart_rejects_unknown_name_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    container = Mock()
    container.name = "web-old"
    docker_client = Mock()
    docker_client.containers.list.return_value = [container]
    monkeypatch.setattr(docker_containers.docker, "DockerClient", Mock(return_value=docker_client))

    with pytest.raises(CheckError, match="was not found") as exc:
        docker_containers.restart_container("web")
    assert exc.value.code == "not_found"
    container.restart.assert_not_called()
    docker_client.close.assert_called_once()


@pytest.mark.parametrize("operation", ["inventory", "restart-list", "restart"])
def test_docker_failures_are_explicit_and_close(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    docker_client = Mock()
    container = Mock()
    container.name = "web"
    if operation == "restart":
        docker_client.containers.list.return_value = [container]
        container.restart.side_effect = DockerException("denied")
    else:
        docker_client.containers.list.side_effect = DockerException("unavailable")
    monkeypatch.setattr(docker_containers.docker, "DockerClient", Mock(return_value=docker_client))

    with pytest.raises(CheckError) as exc:
        if operation == "inventory":
            docker_containers.inventory()
        else:
            docker_containers.restart_container("web")
    assert exc.value.code == "docker_unreachable"
    docker_client.close.assert_called_once()


def test_inventory_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    result = {"containers": [{"name": "web", "state": "running", "image": "nginx:latest"}]}
    monkeypatch.setattr(docker_containers, "inventory", lambda: result)
    assert client.get("/container-inventory").json == {"status": "ok", **result}


def test_restart_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    restart = Mock(return_value={"restarted": "web"})
    monkeypatch.setattr(docker_containers, "restart_container", restart)
    assert client.post_json("/actions/restart-container", {"name": "web"}).json == {
        "status": "ok",
        "restarted": "web",
    }
    restart.assert_called_once_with("web")


@pytest.mark.parametrize("state", ["running", "exited", "paused"])
def test_delete_standalone_matches_exact_live_name(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    container = Mock(attrs={"Config": {"Labels": {"custom.label": "value"}}})
    container.name = "web"
    container.status = state
    other = Mock()
    other.name = "web-old"
    docker_client = Mock()
    docker_client.containers.list.return_value = [other, container]
    monkeypatch.setattr(docker_containers.docker, "DockerClient", Mock(return_value=docker_client))

    assert docker_containers.remove_standalone_container(" web ") == {"deleted": "web"}
    docker_client.containers.list.assert_called_once_with(all=True)
    container.remove.assert_called_once_with(force=True)
    other.remove.assert_not_called()
    docker_client.close.assert_called_once()


@pytest.mark.parametrize("label", ["com.docker.compose.project", "com.docker.compose.service"])
def test_delete_standalone_rejects_compose_on_server(
    client: TestApp, monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    container = Mock(attrs={"Config": {"Labels": {label: "app"}}})
    container.name = "web"
    docker_client = Mock()
    docker_client.containers.list.return_value = [container]
    monkeypatch.setattr(docker_containers.docker, "DockerClient", Mock(return_value=docker_client))

    response = client.post_json(
        "/actions/delete-standalone-container", {"name": "web"}, status=503
    )
    assert response.json["code"] == "compose_managed"
    container.remove.assert_not_called()
    docker_client.close.assert_called_once()


def test_delete_standalone_rejects_unknown_name(monkeypatch: pytest.MonkeyPatch) -> None:
    container = Mock()
    container.name = "web-old"
    docker_client = Mock()
    docker_client.containers.list.return_value = [container]
    monkeypatch.setattr(docker_containers.docker, "DockerClient", Mock(return_value=docker_client))

    with pytest.raises(CheckError, match="was not found") as exc:
        docker_containers.remove_standalone_container("web")
    assert exc.value.code == "not_found"
    container.remove.assert_not_called()
    docker_client.close.assert_called_once()


@pytest.mark.parametrize("operation", ["connect", "list", "remove"])
def test_delete_standalone_docker_failures(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    docker_client = Mock()
    container = Mock(attrs={})
    container.name = "web"
    docker_client.containers.list.return_value = [container]
    if operation == "list":
        docker_client.containers.list.side_effect = DockerException("unavailable")
    elif operation == "remove":
        container.remove.side_effect = DockerException("denied")
    factory = Mock(return_value=docker_client)
    if operation == "connect":
        factory.side_effect = DockerException("unavailable")
    monkeypatch.setattr(docker_containers.docker, "DockerClient", factory)

    with pytest.raises(CheckError) as exc:
        docker_containers.remove_standalone_container("web")
    assert exc.value.code == "docker_unreachable"
    if operation != "connect":
        docker_client.close.assert_called_once()


def test_delete_standalone_endpoint(client: TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    remove = Mock(return_value={"deleted": "web"})
    monkeypatch.setattr(docker_containers, "remove_standalone_container", remove)
    assert client.post_json("/actions/delete-standalone-container", {"name": "web"}).json == {
        "status": "ok",
        "deleted": "web",
    }
    remove.assert_called_once_with("web")


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "  "}, []])
def test_delete_standalone_requires_name(
    client: TestApp, monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    remove = Mock()
    monkeypatch.setattr(docker_containers, "remove_standalone_container", remove)
    response = client.post_json("/actions/delete-standalone-container", payload, status=400)
    assert response.json["code"] == "invalid_request"
    remove.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "  "}, []])
def test_restart_requires_name(
    client: TestApp, monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    restart = Mock()
    monkeypatch.setattr(docker_containers, "restart_container", restart)
    response = client.post_json("/actions/restart-container", payload, status=400)
    assert response.json["code"] == "invalid_request"
    restart.assert_not_called()


@pytest.mark.parametrize(
    ("path", "method", "function"),
    [
        ("/container-inventory", "GET", "inventory"),
        ("/actions/restart-container", "POST", "restart_container"),
        ("/actions/delete-standalone-container", "POST", "remove_standalone_container"),
    ],
)
def test_endpoint_reports_docker_errors(
    client: TestApp, monkeypatch: pytest.MonkeyPatch, path: str, method: str, function: str
) -> None:
    monkeypatch.setattr(
        docker_containers,
        function,
        Mock(side_effect=CheckError("docker_unreachable", "Docker unavailable", "socket closed")),
    )
    response = (
        client.get(path, status=503)
        if method == "GET"
        else client.post_json(path, {"name": "web"}, status=503)
    )
    assert response.json == {
        "status": "error",
        "code": "docker_unreachable",
        "error": "Docker unavailable",
        "detail": "socket closed",
    }
