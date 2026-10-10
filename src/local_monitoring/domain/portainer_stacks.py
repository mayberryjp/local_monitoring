"""Find Portainer Git stacks for live Compose containers and redeploy them."""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

import docker
import requests
from docker.errors import DockerException

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError

PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
CONFIG_FILES_LABEL = "com.docker.compose.project.config_files"
WORKING_DIR_LABEL = "com.docker.compose.project.working_dir"
_CACHE_LOCK = threading.Lock()
_CACHE_ENTRY: tuple[tuple[str, str, str], float, dict[str, Any]] | None = None


def _configured() -> tuple[str, dict[str, str]]:
    base_url = settings.portainer_url.rstrip("/")
    if not base_url or not settings.portainer_api_key:
        raise CheckError("not_configured", "Portainer API URL and API key are required")
    return base_url, {"X-API-Key": settings.portainer_api_key}


def _request_json(method: str, url: str, headers: dict[str, str], **kwargs: Any) -> Any:
    try:
        resp = requests.request(
            method,
            url,
            headers=headers,
            timeout=settings.http_timeout_seconds,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise CheckError("upstream_unreachable", "Portainer API request failed", str(exc)) from exc
    if resp.status_code not in (200, 201):
        raise CheckError("upstream_error", f"Portainer API returned HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise CheckError("upstream_error", "Portainer API returned invalid JSON") from exc


def _repo_key(url: str) -> str:
    value = url.strip().removesuffix(".git").rstrip("/").lower()
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", 1)
        return f"{host}/{path}".removesuffix(".git").rstrip("/")
    parsed = urlparse(value)
    if parsed.hostname:
        return f"{parsed.hostname}{parsed.path}".removesuffix(".git").rstrip("/")
    return value.removeprefix("https://").removeprefix("http://").rstrip("/")


def _compose_source() -> tuple[str, tuple[str, ...]]:
    value = settings.docker_compose.strip()
    if not value:
        raise CheckError("not_configured", "DOCKER_COMPOSE must point to the GitHub Compose source")
    parsed = urlparse(value if "://" in value else f"https://{value}")
    parts = PurePosixPath(parsed.path.strip("/")).parts
    if parsed.hostname != "github.com" or len(parts) < 3:
        raise CheckError(
            "invalid_config",
            "DOCKER_COMPOSE must include github.com/<owner>/<repo>/<site-directory>",
        )
    repo = f"github.com/{parts[0]}/{parts[1].removesuffix('.git')}".lower()
    return repo, parts[2:]


def _container_rows() -> list[dict[str, Any]]:
    try:
        client = docker.DockerClient(base_url=settings.docker_host)
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker socket unavailable", str(exc)) from exc
    try:
        containers = client.containers.list(all=True)
        return [
            {
                "name": container.name,
                "status": container.status,
                "project": (container.labels or {}).get(PROJECT_LABEL),
                "service": (container.labels or {}).get(SERVICE_LABEL),
                "config_files": (container.labels or {}).get(CONFIG_FILES_LABEL, ""),
                "working_dir": (container.labels or {}).get(WORKING_DIR_LABEL, ""),
            }
            for container in containers
        ]
    except DockerException as exc:
        raise CheckError("docker_unreachable", "docker container listing failed", str(exc)) from exc
    finally:
        client.close()


def _stack_for_container(container: dict[str, Any], stacks: list[dict[str, Any]]) -> dict[str, Any] | None:
    project = container.get("project")
    config_files = [path.strip() for path in container.get("config_files", "").split(",")]
    if not project or not any(config_files):
        return None

    expected_repo, source_path = _compose_source()
    matches: list[dict[str, Any]] = []
    for stack in stacks:
        git_config = stack.get("GitConfig") or {}
        if not git_config or _repo_key(str(git_config.get("URL") or "")) != expected_repo:
            continue
        if str(stack.get("Name") or "").casefold() != str(project).casefold():
            continue
        git_path = str(git_config.get("ConfigFilePath") or "").replace("\\", "/").lstrip("./")
        git_file = PurePosixPath(git_path)
        if not git_path or git_file.parts[: len(source_path)] != source_path:
            continue
        if not any(PurePosixPath(path.replace("\\", "/")).name == git_file.name for path in config_files):
            continue
        matches.append(stack)

    return matches[0] if len(matches) == 1 else None


def _collect_uncached() -> dict[str, Any]:
    base_url, headers = _configured()
    stack_data = _request_json("GET", f"{base_url}/api/stacks", headers)
    if not isinstance(stack_data, list):
        raise CheckError("upstream_error", "Portainer stack response was not a list")

    rows: list[dict[str, Any]] = []
    for container in _container_rows():
        stack = _stack_for_container(container, stack_data)
        has_compose = bool(container.get("project"))
        git_path = str((stack.get("GitConfig") or {}).get("ConfigFilePath") or "") if stack else ""
        rows.append(
            {
                **container,
                "source": "github" if stack else ("local compose" if has_compose else "unmanaged"),
                "source_file": git_path,
                "can_redeploy": bool(stack and stack.get("Id") and stack.get("EndpointId")),
            }
        )
    return {"containers": rows}


def clear_cache() -> None:
    """Invalidate the inventory after an action changes a stack."""
    global _CACHE_ENTRY
    with _CACHE_LOCK:
        _CACHE_ENTRY = None


def collect(force_refresh: bool = False) -> dict[str, Any]:
    """Classify containers, reusing the Docker/Portainer snapshot until its TTL expires."""
    global _CACHE_ENTRY
    cache_key = (
        settings.docker_host,
        settings.portainer_url,
        settings.docker_compose,
    )
    ttl = max(settings.compose_cache_ttl_seconds, 0)
    with _CACHE_LOCK:
        if not force_refresh and ttl and _CACHE_ENTRY is not None:
            cached_key, cached_at, cached_value = _CACHE_ENTRY
            if cached_key == cache_key and time.monotonic() - cached_at < ttl:
                return deepcopy(cached_value)

        value = _collect_uncached()
        _CACHE_ENTRY = (cache_key, time.monotonic(), deepcopy(value))
        return value


def redeploy_for_container(container_name: str) -> dict[str, Any]:
    """Pull the mapped Git Compose source and redeploy its Portainer stack, without repulling images."""
    base_url, headers = _configured()
    target = container_name.strip()
    containers = _container_rows()
    container = next((item for item in containers if item["name"] == target), None)
    if container is None:
        raise CheckError("not_found", f"container {target!r} was not found")

    stack_data = _request_json("GET", f"{base_url}/api/stacks", headers)
    if not isinstance(stack_data, list):
        raise CheckError("upstream_error", "Portainer stack response was not a list")
    stack = _stack_for_container(container, stack_data)
    if stack is None:
        raise CheckError(
            "not_found", f"container {target!r} has no unambiguous Portainer Git stack in the configured source"
        )

    stack_id = stack.get("Id")
    endpoint_id = stack.get("EndpointId")
    if not stack_id or not endpoint_id:
        raise CheckError("upstream_error", "matched Portainer stack is missing its ID or endpoint")

    payload = {
        "Env": stack.get("Env") or [],
        "Prune": bool((stack.get("Option") or {}).get("Prune", False)),
        "RepullImageAndRedeploy": False,
    }
    result = _request_json(
        "PUT",
        f"{base_url}/api/stacks/{stack_id}/git/redeploy",
        headers,
        params={"endpointId": endpoint_id},
        json=payload,
    )
    clear_cache()
    return {
        "container": target,
        "stack": stack.get("Name"),
        "stack_id": stack_id,
        "source_file": (stack.get("GitConfig") or {}).get("ConfigFilePath"),
        "image_pull": False,
        "status": result.get("Status") if isinstance(result, dict) else None,
    }