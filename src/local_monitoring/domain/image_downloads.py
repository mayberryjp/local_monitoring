"""Track byte progress from Docker pull streams initiated by this process."""

from __future__ import annotations

import logging
import re
import threading
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import docker
import requests
from docker.errors import DockerException
from docker.utils import parse_repository_tag

from local_monitoring.config import settings
from local_monitoring.domain.errors import CheckError

_LOG = logging.getLogger(__name__)
_LAYER_STATES = {
    "Pulling fs layer",
    "Waiting",
    "Downloading",
    "Verifying Checksum",
    "Download complete",
    "Extracting",
    "Pull complete",
    "Already exists",
}
_SUCCESS = (
    "Status: Downloaded newer image",
    "Status: Image is up to date",
    "Downloaded newer image",
    "Image is up to date",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _reference(image: str) -> str:
    value = image.strip()
    if (
        not value
        or len(value) > 512
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*", value) is None
        or "://" in value
    ):
        raise CheckError("invalid_request", "provide a Docker image reference, e.g. nginx:latest")
    repository, tag = parse_repository_tag(value)
    if not repository or repository.endswith("/") or value.endswith(("@", ":")):
        raise CheckError("invalid_request", "invalid Docker image reference")
    return value if tag else f"{value}:latest"


def _bytes(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class DownloadTracker:
    """In-memory history for a single API process; workers never replace containers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def start(self, image: str) -> dict[str, Any]:
        reference = _reference(image)
        with self._lock:
            active = [job for job in self._jobs.values() if job["state"] == "pulling"]
            existing = next((job for job in active if job["image"] == reference), None)
            if existing is not None:
                return {"download": self._snapshot(existing), "already_running": True}
            if len(active) >= 2:
                raise CheckError(
                    "busy", "two image downloads are already active; wait for one to finish"
                )
            if len(self._jobs) >= 50:
                oldest = next(key for key, job in self._jobs.items() if job["state"] != "pulling")
                del self._jobs[oldest]
            job: dict[str, Any] = {
                "id": uuid4().hex,
                "image": reference,
                "state": "pulling",
                "message": "Connecting to Docker...",
                "error": None,
                "started_at": _now(),
                "finished_at": None,
                "layers": {},
            }
            self._jobs[job["id"]] = job
            worker = threading.Thread(target=self._pull, args=(job["id"],), daemon=True)
            try:
                worker.start()
            except RuntimeError as exc:
                del self._jobs[job["id"]]
                raise CheckError(
                    "unavailable", "could not start the download worker", str(exc)
                ) from exc
            return {"download": self._snapshot(job), "already_running": False}

    def collect(self) -> dict[str, Any]:
        with self._lock:
            return {"downloads": [self._snapshot(job) for job in reversed(self._jobs.values())]}

    @staticmethod
    def _snapshot(job: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(job)
        layers = list(result["layers"].values())
        result["layers"] = layers
        measured = [layer for layer in layers if layer["total_bytes"] is not None]
        result["unmeasured_layers"] = sum(
            layer["total_bytes"] is None and layer["state"] != "Already exists" for layer in layers
        )
        result["downloaded_bytes"] = sum(layer["downloaded_bytes"] for layer in layers)
        result["total_bytes"] = (
            sum(layer["total_bytes"] for layer in measured)
            if measured and not result["unmeasured_layers"]
            else None
        )
        return result

    def _event(self, job_id: str, event: dict[str, Any]) -> bool:
        error_detail = event.get("errorDetail") or {}
        detail = event.get("progressDetail") or {}
        if not isinstance(error_detail, dict) or not isinstance(detail, dict):
            raise CheckError("pull_failed", "Docker returned invalid pull progress details")
        error = event.get("error") or error_detail.get("message")
        if error:
            raise CheckError("pull_failed", str(error))
        status = str(event.get("status") or "")
        with self._lock:
            job = self._jobs[job_id]
            if status:
                job["message"] = status
            layer_id = event.get("id")
            if layer_id and (status in _LAYER_STATES or status.startswith("Retrying")):
                layer = job["layers"].setdefault(
                    str(layer_id),
                    {
                        "id": str(layer_id),
                        "state": status,
                        "downloaded_bytes": 0,
                        "total_bytes": None,
                        "extracted_bytes": None,
                        "extract_total_bytes": None,
                    },
                )
                layer["state"] = status
                current, total = _bytes(detail.get("current")), _bytes(detail.get("total"))
                if status == "Downloading":
                    if total is not None:
                        layer["total_bytes"] = max(total, layer["total_bytes"] or 0)
                    if current is not None:
                        layer["downloaded_bytes"] = current
                    if layer["total_bytes"] is not None:
                        layer["downloaded_bytes"] = min(
                            layer["downloaded_bytes"], layer["total_bytes"]
                        )
                elif status == "Extracting":
                    layer["extracted_bytes"], layer["extract_total_bytes"] = current, total
                if (
                    status in {"Download complete", "Pull complete"}
                    and layer["total_bytes"] is not None
                ):
                    layer["downloaded_bytes"] = layer["total_bytes"]
                if status == "Pull complete" and layer["extract_total_bytes"] is not None:
                    layer["extracted_bytes"] = layer["extract_total_bytes"]
        return status.startswith(_SUCCESS)

    def _pull(self, job_id: str) -> None:
        client = None
        stream = None
        error = None
        complete = False
        try:
            with self._lock:
                image = self._jobs[job_id]["image"]
            client = docker.DockerClient(base_url=settings.docker_host)
            stream = client.api.pull(image, stream=True, decode=True)
            for event in stream:
                if not isinstance(event, dict):
                    raise CheckError(
                        "pull_failed", "Docker returned an invalid pull progress event"
                    )
                complete = self._event(job_id, event) or complete
            if not complete:
                raise CheckError(
                    "pull_incomplete", "Docker pull stream ended without confirming success"
                )
        except (CheckError, DockerException, requests.RequestException, OSError, ValueError) as exc:
            _LOG.warning("Image pull %s failed: %s", job_id, exc)
            error = str(exc)
        finally:
            try:
                try:
                    if stream is not None:
                        stream.close()
                finally:
                    if client is not None:
                        client.close()
            except (DockerException, requests.RequestException, OSError, ValueError) as exc:
                _LOG.warning("Image pull %s cleanup failed: %s", job_id, exc)
                error = error or f"Failed to close Docker pull connection: {exc}"
            finally:
                with self._lock:
                    if not complete:
                        error = error or "Docker pull interrupted before confirming success"
                    job = self._jobs[job_id]
                    job["state"] = "failed" if error else "complete"
                    job["error"] = error
                    if error:
                        job["message"] = "Image pull failed"
                    job["finished_at"] = _now()


tracker = DownloadTracker()
