# local-monitoring

A low-bandwidth REST proxy for a homelab. It calls a handful of chatty, local,
high-bandwidth monitoring APIs and reduces each one to a tiny JSON response, so a
remote/low-bandwidth client can poll a single small endpoint instead of several
large ones.

All four downstream requests are issued **in parallel** (thread pool, not asyncio)
when the aggregate endpoint is called.

## Checks

| Check | Reduces | Response shape |
| --- | --- | --- |
| `uptime_kuma` | An Uptime Kuma status-page slug | `{"up": N, "down": M, "total": T, "down_monitors": [name, ...]}` |
| `webdav` | A single file's WebDAV last-modified time | `{"result": "OK"\|"STALE", "recent": bool, "timestamp": ..., "age_hours": ..., "threshold_hours": ...}` |
| `docker_updater` | [docker-updater](https://github.com/liquidguru/docker-updater) `/api/status` | `{"pending_updates": N, "pending_images": [image, ...]}` |
| `docker_containers` | The Docker socket | `{"running": N, "stopped": M, "total": T, "stopped_containers": [name, ...]}` |

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | HTML status page rendering the down monitors, stopped containers, and pending updates. |
| `GET` | `/health` | Process liveness. |
| `GET` | `/ready` | Readiness (always ok — downstreams are checked per request). |
| `GET` | `/summary` | All four checks in one object, run in parallel. |
| `GET` | `/uptime-kuma` | Uptime Kuma up/down counter. |
| `GET` | `/webdav` | WebDAV file freshness. |
| `GET` | `/docker-updater` | docker-updater pending-update count. |
| `GET` | `/docker` | Running/stopped container count. |

`/summary` always returns `200`; a failing check appears as an error object under its
key. Individual check endpoints return `503` with a JSON error envelope when their
downstream is unreachable or unconfigured.

Example `/summary`:

```json
{
  "status": "ok",
  "checks": {
    "uptime_kuma": {"status": "ok", "up": 12, "down": 1, "total": 13, "down_monitors": ["Database"]},
    "webdav": {"status": "ok", "result": "OK", "recent": true, "timestamp": "2026-09-14T08:12:00-04:00", "age_hours": 1.2, "threshold_hours": 24.0},
    "docker_updater": {"status": "ok", "pending_updates": 3, "pending_images": ["nginx:latest", "ghcr.io/owner/app:main", "redis:7"]},
    "docker_containers": {"status": "ok", "running": 21, "stopped": 2, "total": 23, "stopped_containers": ["backup-runner", "old-db"]}
  }
}
```

## Configuration

All configuration is via environment variables, set in `docker-compose.yml`.

| Variable | Default | Description |
| --- | --- | --- |
| `API_LISTEN_ADDRESS` | `0.0.0.0` | Bind address. |
| `API_PORT` | `8000` | Listen port. |
| `LOG_LEVEL` | `INFO` | Log level. |
| `HTTP_TIMEOUT_SECONDS` | `10` | Timeout for each downstream call. |
| `TZ` | `America/New_York` | Container time zone (authoritative for timestamps). |
| `UPTIME_KUMA_BASE_URL` | — | Base URL of Uptime Kuma, e.g. `http://uptime-kuma:3001`. |
| `UPTIME_KUMA_SLUG` | — | Status-page slug. |
| `WEBDAV_URL` | — | Full URL of the file to check. |
| `WEBDAV_USERNAME` | — | Optional basic-auth user. |
| `WEBDAV_PASSWORD` | — | Optional basic-auth password. |
| `WEBDAV_RECENT_HOURS` | `24` | File is "recent" if modified within this many hours. |
| `DOCKER_UPDATER_BASE_URL` | — | Base URL of docker-updater, e.g. `http://docker-updater:9090`. |
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Docker socket for the container count. |

The Docker check needs read access to the mounted socket. The image runs as a
non-root user, so grant access with a `group_add` entry matching the host's docker
group GID (see the commented example in `docker-compose.yml`).

This service is stateless: it stores nothing and has no database, so there are no
migrations.

## Local runbook

```bash
# install (dev deps)
make install

# lint / typecheck / test / security
make lint
make typecheck
make test
make security

# build the image
make docker-build

# run via compose (uses the published image)
docker compose up
```

Verify:

```bash
curl localhost:8000/health
curl localhost:8000/summary
```

## Publishing

Pushing to `main` builds and publishes `mayberry4477/local_monitoring:latest` (and a
`:${sha}` tag) to Docker Hub via `.github/workflows/docker-publish.yml`. Set the
`DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets.
