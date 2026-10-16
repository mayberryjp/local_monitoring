"""Separate container management page; monitoring stays on the dashboard."""

from __future__ import annotations

from bottle import Bottle, response

_CONTAINERS_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Local Monitoring - Containers</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%23101013'/%3E%3Cpath d='M3 17h5l3-8 4 14 3-9 2 3h6' fill='none' stroke='%236ea8fe' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<style>
  :root { --bg: #09090b; --panel: #101013; --border: #26262d; --fg: #ececf1;
          --muted: #8b8b95; --accent: #6ea8fe; --bad: #f87171; }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--fg);
         font: 14px/1.55 ui-sans-serif, -apple-system, "Segoe UI", sans-serif; }
  .wrap { max-width: 1100px; margin: auto; padding: 2.2rem 1.25rem 4rem; }
  header { display: flex; align-items: center; justify-content: space-between; gap: 1rem;
           border-bottom: 1px solid var(--border); margin-bottom: 1.4rem; }
  h1 { font-size: 1.25rem; }
  nav { display: flex; gap: 1rem; margin-bottom: 1.2rem; }
  nav a { color: var(--accent); text-decoration: none; }
  nav a[aria-current] { color: var(--fg); border-bottom: 2px solid var(--accent); }
  button { font: inherit; font-size: .8rem; color: var(--fg); background: #17171c;
           border: 1px solid var(--border); border-radius: 6px; padding: .4rem .7rem;
           cursor: pointer; }
  button:hover { border-color: var(--accent); }
  button:disabled { opacity: .5; cursor: default; }
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; background: var(--panel); }
  th, td { text-align: left; padding: .7rem; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-size: .75rem; text-transform: uppercase; }
  td { overflow-wrap: anywhere; }
  .actions { min-width: 200px; }
  .actions button { margin: .15rem; }
  .muted { color: var(--muted); }
  .error { color: var(--bad); }
  #message, #warning { white-space: pre-wrap; }
  @media (max-width: 640px) { .wrap { padding: 1.4rem 1rem 3rem; } }
</style>
</head>
<body>
<main class="wrap">
  <header><h1>Container management</h1><button id="refresh" type="button">refresh</button></header>
  <nav aria-label="Main navigation">
    <a href="/">Monitoring</a><a href="/containers" aria-current="page">Containers</a>
    <a href="/downloads">Downloads</a>
  </nav>
  <p class="muted">Restart keeps the existing container configuration.
    Redeploy pulls the configured Git Compose source and redeploys the entire Portainer stack,
    not just this container. It does not force image pulling.</p>
  <p id="status" role="status">Loading containers...</p>
  <p id="warning" class="error" role="alert" hidden></p>
  <p id="message" role="status"></p>
  <div class="table-wrap">
    <table id="board" hidden>
      <thead><tr><th>Container</th><th>State</th><th>Image</th><th>Actions</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>
</main>
<script>
  var refreshButton = document.getElementById("refresh");
  var statusText = document.getElementById("status");
  var warning = document.getElementById("warning");
  var message = document.getElementById("message");
  var board = document.getElementById("board");
  var rows = document.getElementById("rows");
  var busy = false;

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

  function cell(row, text) {
    var td = document.createElement("td");
    td.textContent = text;
    row.appendChild(td);
    return td;
  }

  function actionButton(cell, label, container, redeploy) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.setAttribute("aria-label", label + " " + container.name);
    button.addEventListener("click", function () { runAction(button, container, redeploy); });
    cell.appendChild(button);
    return button;
  }

  function render(containers, compose) {
    var redeployable = new Set((compose ? compose.containers : [])
      .filter(function (item) { return item.can_redeploy; })
      .map(function (item) { return item.name; }));
    rows.replaceChildren();
    containers.forEach(function (container) {
      var row = document.createElement("tr");
      cell(row, container.name);
      cell(row, container.state);
      cell(row, container.image);
      var actions = cell(row, "");
      actions.className = "actions";
      actionButton(actions, "restart", container, false);
      var redeploy = actionButton(actions, "redeploy", container, true);
      redeploy.disabled = !redeployable.has(container.name);
      redeploy.dataset.unavailable = String(redeploy.disabled);
      redeploy.title = redeploy.disabled
        ? (compose ? "No supported Portainer Git stack for this container"
                   : "Portainer stack information unavailable")
        : "Pull Git Compose source and redeploy the entire stack";
      rows.appendChild(row);
    });
    board.hidden = containers.length === 0;
    statusText.textContent = containers.length ? containers.length + " containers"
                                             : "No containers found.";
  }

  function load(forceCompose) {
    statusText.textContent = "Loading containers...";
    warning.hidden = true;
    // Docker inventory remains usable even when Portainer is unconfigured or unreachable.
    return Promise.all([
      requestJson("/container-inventory", { cache: "no-store" }),
      requestJson("/compose-stacks" + (forceCompose ? "?refresh=true" : ""),
                  { cache: "no-store" }).then(function (data) { return data; })
        .catch(function (error) {
          warning.textContent = "Redeploy unavailable: " + error.message;
          warning.hidden = false;
          return null;
        })
    ]).then(function (results) {
      render(results[0].containers, results[1]);
    }).catch(function (error) {
      rows.replaceChildren();
      board.hidden = true;
      statusText.textContent = "Failed to load containers: " + error.message;
    });
  }

  function setBusy(value) {
    busy = value;
    refreshButton.disabled = value;
    rows.querySelectorAll("button").forEach(function (button) {
      button.disabled = value || button.dataset.unavailable === "true";
    });
  }

  function refresh() {
    if (busy) return;
    setBusy(true);
    load(true).then(function () { setBusy(false); });
  }

  function runAction(button, container, redeploy) {
    if (busy) return;
    var prompt = redeploy
      ? "Pull Git Compose source and redeploy the ENTIRE stack for " + container.name + "?"
      : "Restart " + container.name + "? This may interrupt the service.";
    if (!window.confirm(prompt)) return;
    setBusy(true);
    button.textContent = "working...";
    message.className = "";
    message.textContent = "";
    requestJson(redeploy ? "/actions/redeploy-compose" : "/actions/restart-container", {
      method: "POST", cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(redeploy ? { container: container.name } : { name: container.name })
    }).then(function (data) {
      message.textContent = redeploy
        ? "Stack redeploy requested for " + container.name + (data.stack ? " (" + data.stack + ")" : "")
        : "Restarted " + container.name;
      return load(true);
    }).catch(function (error) {
      message.className = "error";
      message.textContent = "Action failed: " + error.message;
    }).then(function () {
      button.textContent = redeploy ? "redeploy" : "restart";
      setBusy(false);
    });
  }

  refreshButton.addEventListener("click", refresh);
  refresh();
</script>
</body>
</html>
"""


def register_container_routes(app: Bottle) -> None:
    @app.get("/containers")
    def containers() -> str:
        response.content_type = "text/html; charset=utf-8"
        return _CONTAINERS_HTML
