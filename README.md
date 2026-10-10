# local-monitoring

A low-bandwidth REST proxy for a homelab. It calls a handful of chatty, local,
high-bandwidth monitoring APIs and reduces each one to a tiny JSON response, so a
remote/low-bandwidth client can poll a single small endpoint instead of several
large ones.

All nine downstream requests are issued **in parallel** (thread pool, not asyncio)
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
| `allowlist` | `ALLOWED_ADDITIONAL_MONITORS` entries that match no monitor name (stale whitelist) | `{"allowed": W, "unmatched": N, "unmatched_allowed": [entry, ...]}` |
| `docker_images` | The Docker socket (images unused by any container, plus dangling) | `{"unused": N, "total": T, "unused_images": [tag_or_id, ...]}` |

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | HTML status page rendering the down monitors, stopped containers, pending updates, unmonitored containers, and unused images. |
| `GET` | `/health` | Process liveness. |
| `GET` | `/ready` | Readiness (always ok — downstreams are checked per request). |
| `GET` | `/summary` | All eleven checks in one object, run in parallel. Add `?refresh=true` to bypass the Compose inventory cache. |
| `GET` | `/uptime-kuma` | Uptime Kuma up/down counter. |
| `GET` | `/status-page-monitors` | Uptime Kuma monitors not included in the configured public status page. |
| `GET` | `/webdav` | WebDAV file freshness. |
| `GET` | `/docker-updater` | docker-updater pending-update count. |
| `GET` | `/docker` | Running/stopped container count. |
| `GET` | `/docker-monitors` | Containers missing an Uptime Kuma v2 docker monitor. |
| `GET` | `/docker-hosts` | Configured Uptime Kuma v2 Docker hosts, for selecting the host used by a new monitor. |
| `GET` | `/compose-stacks` | Containers classified by whether their Portainer Compose stack is linked to the configured GitHub source. |
| `GET` | `/ping-monitors` | Devices missing an Uptime Kuma v2 ping monitor. |
| `GET` | `/additional-monitors` | Monitors not covered by the container or ping checks. |
| `GET` | `/allowlist` | `ALLOWED_ADDITIONAL_MONITORS` entries matching no monitor. |
| `GET` | `/docker-images` | Unused/dangling image count. |
| `POST` | `/actions/update-all` | Trigger a docker-updater update for every container with a pending update. |
| `POST` | `/actions/update` | Trigger a docker-updater update for one container (JSON body `{"name": ...}`). |
| `POST` | `/actions/prune-images` | Delete every image not used by a container (Docker `prune -a`). |
| `POST` | `/actions/delete-image` | Delete one unused image (JSON body `{"image": ...}`). |
| `POST` | `/actions/add-ping-monitor` | Create an Uptime Kuma v2 ping monitor for one device (JSON body `{"device": ...}`). |
| `POST` | `/actions/add-docker-monitor` | Create a Docker monitor for one uncovered container (JSON body `{"container": ..., "host_id": ...}`). |
| `POST` | `/actions/add-status-page-monitor` | Add one existing Uptime Kuma monitor to the configured status page (JSON body `{"monitor_id": ...}`). |
| `POST` | `/actions/clear-heartbeats` | Clear heartbeat history and aggregate uptime statistics for every Uptime Kuma v2 monitor; monitor definitions are retained. |
| `POST` | `/actions/redeploy-compose` | Pull and redeploy the Portainer Git stack mapped to a container (JSON body `{"container": ...}`); does not force image pulling. |
| `POST` | `/actions/delete-monitor` | Delete one additional Uptime Kuma v2 monitor (JSON body `{"name": ...}`). |
| `POST` | `/actions/start-container` | Start one stopped container (JSON body `{"name": ...}`). |
| `POST` | `/actions/delete-container` | Delete one stopped container (JSON body `{"name": ...}`). |

`/summary` always returns `200`; a failing check appears as an error object under its
key. Individual check endpoints return `503` with a JSON error envelope when their
downstream is unreachable or unconfigured.

Example `/summary`:

```json
{
  "status": "ok",
  "checks": {
    "uptime_kuma": {"status": "ok", "up": 12, "down": 1, "total": 13, "down_monitors": ["Database"]},
    "status_page_monitors": {"status": "ok", "status_page": "my-status-page", "listed": false, "missing": 1, "unlisted_monitors": [{"id": 7, "name": "New service", "type": "http"}]},
    "webdav": {"status": "ok", "result": "OK", "recent": true, "timestamp": "2026-09-14T08:12:00-04:00", "age_hours": 1.2, "threshold_hours": 24.0},
    "docker_updater": {"status": "ok", "pending_updates": 3, "pending_images": ["nginx:latest", "ghcr.io/owner/app:main", "redis:7"], "pending_containers": [{"name": "web", "image": "nginx:latest"}]},
    "docker_containers": {"status": "ok", "running": 21, "stopped": 2, "total": 23, "stopped_containers": ["backup-runner", "old-db"]},
    "docker_monitors": {"status": "ok", "monitored": 6, "unmonitored": 1, "total": 7, "unmonitored_containers": ["homeassistant"]},
    "ping_monitors": {"status": "ok", "monitored": 4, "unmonitored": 1, "total": 5, "unmonitored_devices": ["printer"]},
    "additional_monitors": {"status": "ok", "additional": 1, "allowed": 2, "total": 14, "additional_monitors": ["GARAGE HTTP DOORUI"]},
    "allowlist": {"status": "ok", "allowed": 2, "unmatched": 1, "unmatched_allowed": ["old-nas"]},
    "docker_images": {"status": "ok", "unused": 2, "total": 25, "unused_images": ["redis:7", "sha256:0a1b2c3d4e5f"]},
    "compose_stacks": {"status": "ok", "total": 23, "github_managed": 21, "unlinked_compose": 1, "unmanaged": 1, "drifted": 2, "comparison_unknown": 0, "containers": [{"name": "localmonitoring", "source": "github", "github_managed": true, "drift_status": "changed", "source_file": "house/localmonitoring.yml", "can_redeploy": true}]}
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
| `UPTIME_KUMA_SLUG` | — | Status-page slug or full status-page URL (the final `/status/<slug>` segment is used). |
| `WEBDAV_URL` | — | Full URL of the file to check. |
| `WEBDAV_USERNAME` | — | Optional basic-auth user. |
| `WEBDAV_PASSWORD` | — | Optional basic-auth password. |
| `WEBDAV_RECENT_HOURS` | `24` | File is "recent" if modified within this many hours. |
| `DOCKER_UPDATER_BASE_URL` | — | Base URL of docker-updater, e.g. `http://docker-updater:9090`. |
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Docker socket for the container count. |
| `PORTAINER_API_KEY` | — | Portainer API access token sent using `X-API-Key`; required for Compose stack lookup and redeploy. |
| `DOCKER_COMPOSE` | — | GitHub Compose source URL including its site directory, e.g. `https://github.com/mayberryjp/dockercompose/house` or `/farm`. |
| `GITHUB_API_TOKEN` | — | GitHub token with read access to the private Compose repository, used to compare the deployed commit's Compose file with the configured branch. |
| `COMPOSE_CACHE_TTL_SECONDS` | `300` | How long the Docker/Portainer Compose inventory is cached. Use the dashboard's **refresh** button to force an immediate refresh. |
| `CONTAINER_BLOB` | — | URL(s) of the per-site container list (comma-separate multiple URLs to merge them); the container name is the first DNS label of each line's 2nd comma-separated field (`<target>,<container>.<domain>,<ttl>`). |
| `UPTIME_KUMA_V2_API_BASE_URL` | — | Base URL of [uptime-kuma-v2-api](https://github.com/paul-hph/uptime-kuma-v2-api), e.g. `http://uptimekuma-v2-api:12000`. |
| `UPTIME_KUMA_V2_API_KEY` | — | API key sent as the `X-API-Key` header to uptime-kuma-v2-api. |
| `SANDO_DEVICES_URL` | — | URL of the per-site device list (`ip_address,domain_name,interval` lines); a device is the first DNS label of the 2nd field, matched against ping monitors named like `OFFICE PING NETGEARSWITCH`. |
| `ALLOWED_ADDITIONAL_MONITORS` | — | Comma-separated, case-insensitive substrings; a monitor is excluded from the `additional_monitors` check when any entry appears anywhere in its name. |
| `UPTIME_KUMA_PUBLIC_URL` | — | Browser-reachable Uptime Kuma URL for the dashboard's monitor section links (falls back to `UPTIME_KUMA_BASE_URL`). |
| `PORTAINER_URL` | — | Portainer base URL for the dashboard link and API requests; must be reachable from the app container, e.g. `http://portainer:9000` or `https://portainer.example.com`. |
| `DOCKER_UPDATER_PUBLIC_URL` | — | Browser-reachable docker-updater URL for the pending-updates section link (falls back to `DOCKER_UPDATER_BASE_URL`). |

The dashboard is a dark "actions dashboard": a single table with **Monitor type**,
**Issue**, and **Action** columns, one row per issue, where sections with no issues are
hidden. Every row's action cell links to the relevant web UI (reusing the section URLs
above). Uncovered containers have a Docker-host selector and **add monitor** action;
uncovered devices can also get a ping monitor. Newly created monitors are added to the
configured Uptime Kuma status page, and existing monitors missing from that page have
an **add to page** action. Other row actions start/delete stopped containers,
trigger one docker-updater update, delete one unused image, or delete an unexpected
Uptime Kuma monitor. A confirmed header action clears all monitor heartbeat history and
aggregate uptime statistics without deleting monitor definitions. These are
unauthenticated `POST` actions, so only expose this service on a trusted network.

Compose rows are matched to Portainer Git stacks using live Compose file labels, the
configured repository, and source directory. `/summary` reports GitHub-managed,
changed, unlinked Compose, unmanaged, and unverified containers. Git-linked rows with
changes or an unavailable comparison offer **pull & redeploy** through Portainer with
`RepullImageAndRedeploy` disabled. Configure a Portainer API token with permission to
view/update stacks and a GitHub token with read access to the private Compose repo.

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
