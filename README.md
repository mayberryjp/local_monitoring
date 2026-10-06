# local-monitoring

A low-bandwidth REST proxy for a homelab. It calls a handful of chatty, local,
high-bandwidth monitoring APIs and reduces each one to a tiny JSON response, so a
remote/low-bandwidth client can poll a single small endpoint instead of several
large ones.

All eight downstream requests are issued **in parallel** (thread pool, not asyncio)
when the aggregate endpoint is called.

## Checks

| Check | Reduces | Response shape |
| --- | --- | --- |
| `uptime_kuma` | An Uptime Kuma status-page slug | `{"up": N, "down": M, "total": T, "down_monitors": [name, ...]}` |
| `webdav` | A single file's WebDAV last-modified time | `{"result": "OK"\|"STALE", "recent": bool, "timestamp": ..., "age_hours": ..., "threshold_hours": ...}` |
| `docker_updater` | [docker-updater](https://github.com/liquidguru/docker-updater) `/api/status` | `{"pending_updates": N, "pending_images": [image, ...]}` |
| `docker_containers` | The Docker socket | `{"running": N, "stopped": M, "total": T, "stopped_containers": [name, ...]}` |
| `docker_monitors` | A per-site container list vs. [uptime-kuma-v2-api](https://github.com/paul-hph/uptime-kuma-v2-api) `docker` monitors | `{"monitored": N, "unmonitored": M, "total": T, "unmonitored_containers": [name, ...]}` |
| `ping_monitors` | A per-site device list vs. [uptime-kuma-v2-api](https://github.com/paul-hph/uptime-kuma-v2-api) `ping` monitors | `{"monitored": N, "unmonitored": M, "total": T, "unmonitored_devices": [name, ...]}` |
| `additional_monitors` | Uptime Kuma v2 monitors not matched by the container or ping checks (minus a whitelist) | `{"additional": N, "allowed": W, "total": T, "additional_monitors": [name, ...]}` |
| `docker_images` | The Docker socket (images unused by any container, plus dangling) | `{"unused": N, "total": T, "unused_images": [tag_or_id, ...]}` |

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | HTML status page rendering the down monitors, stopped containers, pending updates, unmonitored containers, and unused images. |
| `GET` | `/health` | Process liveness. |
| `GET` | `/ready` | Readiness (always ok — downstreams are checked per request). |
| `GET` | `/summary` | All eight checks in one object, run in parallel. |
| `GET` | `/uptime-kuma` | Uptime Kuma up/down counter. |
| `GET` | `/webdav` | WebDAV file freshness. |
| `GET` | `/docker-updater` | docker-updater pending-update count. |
| `GET` | `/docker` | Running/stopped container count. |
| `GET` | `/docker-monitors` | Containers missing an Uptime Kuma v2 docker monitor. |
| `GET` | `/ping-monitors` | Devices missing an Uptime Kuma v2 ping monitor. |
| `GET` | `/additional-monitors` | Monitors not covered by the container or ping checks. |
| `GET` | `/docker-images` | Unused/dangling image count. |
| `POST` | `/actions/update-all` | Trigger a docker-updater update for every container with a pending update. |
| `POST` | `/actions/update` | Trigger a docker-updater update for one container (JSON body `{"name": ...}`). |
| `POST` | `/actions/prune-images` | Delete every image not used by a container (Docker `prune -a`). |
| `POST` | `/actions/delete-image` | Delete one unused image (JSON body `{"image": ...}`). |
| `POST` | `/actions/add-ping-monitor` | Create an Uptime Kuma v2 ping monitor for one device (JSON body `{"device": ...}`). |

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
    "docker_updater": {"status": "ok", "pending_updates": 3, "pending_images": ["nginx:latest", "ghcr.io/owner/app:main", "redis:7"], "pending_containers": [{"name": "web", "image": "nginx:latest"}]},
    "docker_containers": {"status": "ok", "running": 21, "stopped": 2, "total": 23, "stopped_containers": ["backup-runner", "old-db"]},
    "docker_monitors": {"status": "ok", "monitored": 6, "unmonitored": 1, "total": 7, "unmonitored_containers": ["homeassistant"]},
    "ping_monitors": {"status": "ok", "monitored": 4, "unmonitored": 1, "total": 5, "unmonitored_devices": ["printer"]},
    "additional_monitors": {"status": "ok", "additional": 1, "allowed": 2, "total": 14, "additional_monitors": ["GARAGE HTTP DOORUI"]},
    "docker_images": {"status": "ok", "unused": 2, "total": 25, "unused_images": ["redis:7", "sha256:0a1b2c3d4e5f"]}
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
| `CONTAINER_BLOB` | — | URL(s) of the per-site container list (comma-separate multiple URLs to merge them); the container name is the first DNS label of each line's 2nd comma-separated field (`<target>,<container>.<domain>,<ttl>`). |
| `UPTIME_KUMA_V2_API_BASE_URL` | — | Base URL of [uptime-kuma-v2-api](https://github.com/paul-hph/uptime-kuma-v2-api), e.g. `http://uptimekuma-v2-api:12000`. |
| `UPTIME_KUMA_V2_API_KEY` | — | API key sent as the `X-API-Key` header to uptime-kuma-v2-api. |
| `SANDO_DEVICES_URL` | — | URL of the per-site device list (`ip_address,domain_name,interval` lines); a device is the first DNS label of the 2nd field, matched against ping monitors named like `OFFICE PING NETGEARSWITCH`. |
| `ALLOWED_ADDITIONAL_MONITORS` | — | Comma-separated monitor names (or last-word tokens) to exclude from the `additional_monitors` check. |
| `UPTIME_KUMA_PUBLIC_URL` | — | Browser-reachable Uptime Kuma URL for the dashboard's monitor section links (falls back to `UPTIME_KUMA_BASE_URL`). |
| `PORTAINER_URL` | — | Browser-reachable Portainer URL for the container and image section links. |
| `DOCKER_UPDATER_PUBLIC_URL` | — | Browser-reachable docker-updater URL for the pending-updates section link (falls back to `DOCKER_UPDATER_BASE_URL`). |

The dashboard is a dark "actions dashboard": a single table with **Monitor type**,
**Issue**, and **Action** columns, one row per issue, where sections with no issues are
hidden. Every row's action cell links to the relevant web UI (reusing the section URLs
above), and actionable rows carry a singular button: **add monitor** (create a ping
monitor for an uncovered device), **update** (a docker-updater update for one container),
and **delete image** (remove one unused image). These are unauthenticated `POST` actions,
so only expose this service on a trusted network.

The Docker check reads the mounted socket, and the **delete image** action writes to it
(image remove), so the socket is mounted read-write. The image runs as a non-root user,
so grant access with a `group_add` entry matching the host's docker group GID (see the
commented example in `docker-compose.yml`).

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
