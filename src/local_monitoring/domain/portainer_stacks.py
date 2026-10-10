"""Find Portainer Git stacks for live Compose containers and redeploy them."""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

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


def _deployment_metadata(stack: dict[str, Any]) -> tuple[str, str, str, tuple[str, ...]]:
    git_config = stack.get("GitConfig") or {}
    deployment = stack.get("CurrentDeploymentInfo") or {}
    deployed_commit = str(deployment.get("ConfigHash") or git_config.get("ConfigHash") or "")
    reference = str(deployment.get("ReferenceName") or git_config.get("ReferenceName") or "")
    config_path = str(
        deployment.get("ConfigFilePath") or git_config.get("ConfigFilePath") or ""
    )
    additional_files = deployment.get("AdditionalFiles") or stack.get("AdditionalFiles") or []
    return deployed_commit, reference, config_path, tuple(str(path) for path in additional_files)


def _compose_drift(stack: dict[str, Any]) -> dict[str, str]:
    deployed_commit, reference, config_path, additional_files = _deployment_metadata(stack)
    if not settings.github_api_token:
        return {"status": "unknown", "detail": "GITHUB_API_TOKEN is not configured"}
    if not deployed_commit:
        return {"status": "unknown", "detail": "Portainer stack has no deployed commit"}

    expected_repo, _ = _compose_source()
    repository = expected_repo.removeprefix("github.com/")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {settings.github_api_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if not reference:
        try:
            repo_resp = requests.get(
                f"https://api.github.com/repos/{repository}",
                headers=headers,
                timeout=settings.http_timeout_seconds,
            )
        except requests.RequestException as exc:
            return {"status": "unknown", "detail": f"GitHub repository lookup failed: {exc}"}
        if repo_resp.status_code != 200:
            return {
                "status": "unknown",
                "detail": f"GitHub repository lookup returned HTTP {repo_resp.status_code}",
            }
        try:
            reference = str(repo_resp.json().get("default_branch") or "")
        except ValueError:
            reference = ""
        if not reference:
            return {"status": "unknown", "detail": "GitHub repository has no default branch"}

    if reference.startswith("refs/heads/"):
        reference = reference.removeprefix("refs/heads/")
    elif reference.startswith("refs/tags/"):
        reference = "tags/" + reference.removeprefix("refs/tags/")
    url = (
        f"https://api.github.com/repos/{repository}/compare/"
        f"{quote(deployed_commit, safe='')}...{quote(reference, safe='')}"
    )
    try:
        resp = requests.get(
            url,
            headers=headers,
            timeout=settings.http_timeout_seconds,
        )
    except requests.RequestException as exc:
        return {"status": "unknown", "detail": f"GitHub compare request failed: {exc}"}
    if resp.status_code != 200:
        return {"status": "unknown", "detail": f"GitHub compare returned HTTP {resp.status_code}"}
    try:
        comparison = resp.json()
    except ValueError:
        return {"status": "unknown", "detail": "GitHub compare returned invalid JSON"}

    compare_status = comparison.get("status")
    if compare_status == "identical":
        return {"status": "current", "detail": ""}
    if compare_status in {"behind", "diverged"}:
        return {"status": "changed", "detail": "configured Git reference differs from the deployed commit"}

    compose_path = config_path.replace("\\", "/").lstrip("./")
    watched_paths = {
        compose_path,
        *(path.replace("\\", "/").lstrip("./") for path in additional_files),
    }
    changed_paths = {
        str(path)
        for item in comparison.get("files") or []
        for path in (item.get("filename"), item.get("previous_filename"))
        if path
    }
    if watched_paths.intersection(changed_paths):
        return {"status": "changed", "detail": "Compose source changed since deployment"}
    if compare_status == "ahead":
        return {"status": "current", "detail": ""}
    return {"status": "unknown", "detail": "GitHub returned an unsupported comparison status"}


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


def _matching_stacks(container: dict[str, Any], stacks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    config_files = [
        PurePosixPath(path.strip().replace("\\", "/")).parts
        for path in container.get("config_files", "").split(",")
        if path.strip()
    ]
    if not container.get("project") or not config_files:
        return []

    expected_repo, source_path = _compose_source()
    matches: list[dict[str, Any]] = []
    for stack in stacks:
        git_config = stack.get("GitConfig") or {}
        if not git_config or _repo_key(str(git_config.get("URL") or "")) != expected_repo:
            continue
        git_path = str(git_config.get("ConfigFilePath") or "").replace("\\", "/").lstrip("./")
        git_parts = PurePosixPath(git_path).parts
        if not git_path or git_parts[: len(source_path)] != source_path:
            continue
        if not any(
            len(path_parts) >= len(git_parts) and path_parts[-len(git_parts) :] == git_parts
            for path_parts in config_files
        ):
            continue
        matches.append(stack)
    return matches


def _stack_for_container(container: dict[str, Any], stacks: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = _matching_stacks(container, stacks)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        project = str(container.get("project") or "").casefold()
        named_matches = [
            stack for stack in matches if str(stack.get("Name") or "").casefold() == project
        ]
        if len(named_matches) == 1:
            return named_matches[0]
        working_dir = PurePosixPath(str(container.get("working_dir") or "").replace("\\", "/"))
        path_matches = [
            stack
            for stack in matches
            if PurePosixPath(str(stack.get("ProjectPath") or "").replace("\\", "/"))
            == working_dir.parent
        ]
        if len(path_matches) == 1:
            return path_matches[0]
    return None


def _collect_uncached() -> dict[str, Any]:
    base_url, headers = _configured()
    stack_data = _request_json("GET", f"{base_url}/api/stacks", headers)
    if not isinstance(stack_data, list):
        raise CheckError("upstream_error", "Portainer stack response was not a list")

    rows: list[dict[str, Any]] = []
    drift_cache: dict[tuple[str, ...], dict[str, str]] = {}
    for container in _container_rows():
        stack = _stack_for_container(container, stack_data)
        has_compose = bool(container.get("project"))
        git_path = _deployment_metadata(stack)[2] if stack else ""
        drift = {"status": "not_applicable", "detail": ""}
        if stack:
            deployed_commit, reference, _, extra_paths = _deployment_metadata(stack)
            cache_key = (deployed_commit, reference, git_path, *extra_paths)
            if cache_key not in drift_cache:
                drift_cache[cache_key] = _compose_drift(stack)
            drift = drift_cache[cache_key]
        rows.append(
            {
                **container,
                "source": "github" if stack else ("local compose" if has_compose else "unmanaged"),
                "github_managed": stack is not None,
                "drift_status": drift["status"],
                "drift_detail": drift["detail"],
                "source_file": git_path,
                "can_redeploy": bool(stack and stack.get("Id") and stack.get("EndpointId")),
            }
        )
    return {
        "containers": rows,
        "total": len(rows),
        "github_managed": sum(row["source"] == "github" for row in rows),
        "unlinked_compose": sum(row["source"] == "local compose" for row in rows),
        "unmanaged": sum(row["source"] == "unmanaged" for row in rows),
        "drifted": sum(row["drift_status"] == "changed" for row in rows),
        "comparison_unknown": sum(row["drift_status"] == "unknown" for row in rows),
    }


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