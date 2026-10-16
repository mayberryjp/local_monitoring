"""Image download page and the process-local Docker pull tracker API."""

from __future__ import annotations

from typing import Any

from bottle import Bottle, request, response

from local_monitoring.domain import image_downloads
from local_monitoring.domain.errors import CheckError

_DOWNLOADS_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Local Monitoring - Downloads</title>
<style>
  :root { --bg: #09090b; --panel: #101013; --border: #26262d; --fg: #ececf1;
          --muted: #8b8b95; --accent: #6ea8fe; --bad: #f87171; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg);
         font: 14px/1.55 ui-sans-serif, -apple-system, "Segoe UI", sans-serif; }
  .wrap { max-width: 1000px; margin: auto; padding: 2.2rem 1.25rem 4rem; }
  h1 { font-size: 1.25rem; }
  header { border-bottom: 1px solid var(--border); margin-bottom: 1.4rem; }
  nav, form { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.2rem; }
  nav a { color: var(--accent); text-decoration: none; }
  nav a[aria-current] { color: var(--fg); border-bottom: 2px solid var(--accent); }
  input, button { font: inherit; color: var(--fg); background: #17171c;
                 border: 1px solid var(--border); border-radius: 6px; padding: .5rem .7rem; }
  input { flex: 1; min-width: 0; }
  button { cursor: pointer; }
  button:hover { border-color: var(--accent); }
  button:disabled { opacity: .5; cursor: default; }
  .muted { color: var(--muted); }
  .error { color: var(--bad); white-space: pre-wrap; }
  article { background: var(--panel); border: 1px solid var(--border); border-radius: 8px;
            margin: 1rem 0; padding: 1rem; overflow-wrap: anywhere; }
  h2 { margin: 0; font-size: 1rem; }
  progress { width: 100%; height: 1rem; accent-color: var(--accent); }
  .layer { padding: .5rem 0; border-top: 1px solid var(--border); font-size: .85rem; }
  details { margin-top: .7rem; }
  summary { cursor: pointer; }
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
  <p class="muted">Track pulls started here, directly through Docker. No containers are restarted.
    Pulls started by other apps cannot be observed here. Private images use Docker's configured
    registry credentials, if available.</p>
  <form id="pull-form">
    <label for="image">Image</label>
    <input id="image" name="image" placeholder="nginx:latest" required maxlength="512"
           autocomplete="off" spellcheck="false">
    <button id="pull" type="submit">download image</button>
  </form>
  <p id="action-message" role="status"></p>
  <p id="poll-error" class="error" role="alert" hidden></p>
  <p id="status" class="muted" role="status">Loading downloads...</p>
  <p class="muted">Refreshes every 2 seconds. Byte totals cover layers Docker has reported so far,
    not a guaranteed whole-image size. Cached layers need no download; extraction is separate.
    History is kept in memory (last 50 pulls) and resets when this service restarts.</p>
  <section id="downloads" aria-label="Image downloads"></section>
</main>
<script>
  var list = document.getElementById("downloads");
  var statusText = document.getElementById("status");
  var pollError = document.getElementById("poll-error");
  var message = document.getElementById("action-message");
  var pullButton = document.getElementById("pull");
  var form = document.getElementById("pull-form");
  var polling = false;

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

  function progress(parent, current, total, label, complete) {
    var bar = document.createElement("progress");
    bar.setAttribute("aria-label", label);
    if (complete) { bar.max = 1; bar.value = 1; }
    else if (total > 0) { bar.max = total; bar.value = current; }
    parent.appendChild(bar);
  }

  function render(downloads) {
    var open = new Set(Array.from(list.querySelectorAll("details[open]"))
      .map(function (details) { return details.dataset.id; }));
    list.replaceChildren();
    downloads.forEach(function (job) {
      var card = document.createElement("article");
      text(card, "h2", job.image);
      text(card, "p", job.state + " - " + job.message);
      if (job.error) text(card, "p", job.error, "error");
      text(card, "p", bytes(job.downloaded_bytes) + " / " + bytes(job.total_bytes) +
        " downloaded (reported layers)" +
        (job.unmeasured_layers ? " - " + job.unmeasured_layers + " layers without byte totals" : ""));
      progress(card, job.downloaded_bytes, job.total_bytes, "Reported download bytes for " + job.image,
               job.state === "complete");
      var details = document.createElement("details");
      details.dataset.id = job.id;
      details.open = open.has(job.id);
      text(details, "summary", job.layers.length + " reported layers");
      job.layers.forEach(function (layer) {
        var row = document.createElement("div");
        row.className = "layer";
        text(row, "div", layer.id + " - " + layer.state);
        if (layer.state === "Already exists") {
          text(row, "div", "Cached locally - no download needed", "muted");
        } else {
          text(row, "div", bytes(layer.downloaded_bytes) + " / " + bytes(layer.total_bytes) + " downloaded");
          progress(row, layer.downloaded_bytes, layer.total_bytes, "Download " + layer.id, false);
          if (layer.extracted_bytes !== null) {
            text(row, "div", bytes(layer.extracted_bytes) + " / " +
              bytes(layer.extract_total_bytes) + " extracted", "muted");
          }
        }
        details.appendChild(row);
      });
      card.appendChild(details);
      list.appendChild(card);
    });
    statusText.textContent = downloads.length
      ? downloads.length + " tracked pulls - updated " + new Date().toLocaleTimeString()
      : "No tracked downloads. Start an image pull above.";
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
      render(data.downloads);
      pollError.hidden = true;
    }).catch(function (error) {
      pollError.textContent = "Progress unavailable; displayed data may be stale: " + error.message;
      pollError.hidden = false;
    }).then(function () { polling = false; });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (pullButton.disabled) return;
    var image = document.getElementById("image").value.trim();
    if (!image) return;
    if (!window.confirm("Download " + image + " on the Docker host? This uses bandwidth and disk space. " +
                        "Running containers will not be restarted.")) return;
    pullButton.disabled = true;
    message.className = "";
    message.textContent = "Starting pull...";
    requestJson("/actions/pull-image", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: image })
    }).then(function (data) {
      message.textContent = (data.already_running ? "Already downloading " : "Started downloading ") +
        data.download.image;
      refresh();
    }).catch(function (error) {
      message.className = "error";
      message.textContent = "Could not start download: " + error.message;
    }).then(function () { pullButton.disabled = false; });
  });
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
        return {"status": "ok", **image_downloads.tracker.collect()}

    @app.post("/actions/pull-image")
    def pull_image() -> dict[str, Any]:
        try:
            body = request.json
        except (ValueError, TypeError):
            body = None
        image = body.get("image") if isinstance(body, dict) else None
        if not isinstance(image, str) or not image.strip():
            response.status = 400
            return {
                "status": "error",
                "code": "invalid_request",
                "error": "image must be a non-empty string",
            }
        try:
            result = image_downloads.tracker.start(image)
        except CheckError as exc:
            response.status = 400 if exc.code == "invalid_request" else 503
            return {"status": "error", "code": exc.code, "error": exc.message}
        response.status = 200 if result["already_running"] else 202
        return {"status": "ok", **result}
