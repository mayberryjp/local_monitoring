"""Image download page backed by docker-updater's active pulls API."""

from __future__ import annotations

from typing import Any

from bottle import Bottle, response

from local_monitoring.domain import image_downloads
from local_monitoring.domain.errors import CheckError

_DOWNLOADS_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Local Monitoring - Downloads</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%23101013'/%3E%3Cpath d='M3 17h5l3-8 4 14 3-9 2 3h6' fill='none' stroke='%236ea8fe' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<style>
  :root { --bg: #09090b; --panel: #101013; --border: #26262d; --fg: #ececf1;
          --muted: #8b8b95; --accent: #6ea8fe; --bad: #f87171; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg);
         font: 14px/1.55 ui-sans-serif, -apple-system, "Segoe UI", sans-serif; }
  .wrap { max-width: 1000px; margin: auto; padding: 2.2rem 1.25rem 4rem; }
  h1 { font-size: 1.25rem; }
  header { border-bottom: 1px solid var(--border); margin-bottom: 1.4rem; }
  nav { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.2rem; }
  nav a { color: var(--accent); text-decoration: none; }
  nav a[aria-current] { color: var(--fg); border-bottom: 2px solid var(--accent); }
  .muted { color: var(--muted); }
  .error { color: var(--bad); white-space: pre-wrap; }
  article { background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
            margin: 1rem 0; padding: 1rem; overflow-wrap: anywhere; }
  h2 { margin: 0; font-size: 1rem; }
  progress { width: 100%; height: 1rem; accent-color: var(--accent); }
  @media (max-width: 640px) { .wrap { padding: 1.4rem 1rem 3rem; } }
</style>
</head>
<body>
<main class="wrap">
  <header><h1>Image downloads</h1></header>
  <nav aria-label="Main navigation">
    <a href="/">Monitoring</a><a href="/containers">Containers</a>
    <a href="/downloads" aria-current="page">Downloads</a>
  </nav>
  <p class="muted">Live image pulls from docker-updater, including updates started from
    Monitoring. Start container updates on the <a href="/">Monitoring page</a> or in
    docker-updater. This page only observes progress; it does not start another pull.</p>
  <p id="poll-error" class="error" role="alert" hidden></p>
  <p id="status" class="muted" role="status">Loading downloads...</p>
  <p class="muted">Refreshes every 2 seconds. Totals may change as Docker reports layers and
    may be unknown. Cached layers need no download; 100% downloaded does not mean extraction
    or the container update has finished. Pulls disappear when they finish, fail, or are cancelled.
    No history or final update result is provided here; check docker-updater for the outcome.</p>
  <section id="downloads" aria-label="Image downloads"></section>
</main>
<script>
  var list = document.getElementById("downloads");
  var statusText = document.getElementById("status");
  var pollError = document.getElementById("poll-error");
  var polling = false;
  var loaded = false;

  function bytes(value) {
    if (value === null || value === undefined) return "unknown";
    var units = ["B", "KiB", "MiB", "GiB", "TiB"], unit = 0;
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
    return (unit ? value.toFixed(1) : String(value)) + " " + units[unit];
  }

  function text(parent, tag, value, className) {
    var element = document.createElement(tag);
    element.textContent = value;
    if (className) element.className = className;
    parent.appendChild(element);
    return element;
  }

  function progress(parent, percent, label) {
    var bar = document.createElement("progress");
    bar.setAttribute("aria-label", label);
    bar.max = 100;
    if (percent !== null) bar.value = percent;
    parent.appendChild(bar);
  }

  function render(pulls) {
    list.replaceChildren();
    pulls.forEach(function (job) {
      var card = document.createElement("article");
      text(card, "h2", job.image);
      text(card, "p", "Container: " + job.container + " | Host: " + job.host_id);
      text(card, "p", "Started: " + job.started_at, "muted");
      text(card, "p", bytes(job.progress_bytes) + " / " + bytes(job.total_bytes) +
        " downloaded - " +
        (job.percent_complete === null ? "percentage unknown" : job.percent_complete + "%"));
      progress(card, job.percent_complete, "Download progress for " + job.container + " on " + job.host_id);
      list.appendChild(card);
    });
    statusText.textContent = pulls.length
      ? pulls.length + " active pulls - updated " + new Date().toLocaleTimeString()
      : "No active image pulls. Start a container update from Monitoring or docker-updater.";
  }

  function requestJson(url, options) {
    return fetch(url, options).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || data.status === "error") {
          throw new Error(data.error || ("Request failed: HTTP " + response.status));
        }
        return data;
      });
    });
  }

  function refresh() {
    if (polling) return;
    polling = true;
    requestJson("/image-downloads", { cache: "no-store" }).then(function (data) {
      render(data.pulls);
      loaded = true;
      pollError.hidden = true;
    }).catch(function (error) {
      if (!loaded) statusText.textContent = "Download status unavailable.";
      pollError.textContent = "Progress unavailable; displayed data may be stale: " + error.message;
      pollError.hidden = false;
    }).then(function () { polling = false; });
  }

  refresh();
  setInterval(refresh, 2000);
</script>
</body>
</html>
"""


def register_download_routes(app: Bottle) -> None:
    @app.get("/downloads")
    def downloads_page() -> str:
        response.content_type = "text/html; charset=utf-8"
        return _DOWNLOADS_HTML

    @app.get("/image-downloads")
    def downloads() -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            return {"status": "ok", **image_downloads.collect()}
        except CheckError as exc:
            response.status = 503
            result: dict[str, Any] = {"status": "error", "code": exc.code, "error": exc.message}
            if exc.detail is not None:
                result["detail"] = exc.detail
            return result
