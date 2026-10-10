"""Human-friendly dark "actions dashboard" that renders the /summary issue lists."""

from __future__ import annotations

import json

from bottle import Bottle, response

from local_monitoring.config import settings

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Local Monitoring \u00b7 Actions</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%23101013'/%3E%3Cpath d='M3 17h5l3-8 4 14 3-9 2 3h6' fill='none' stroke='%236ea8fe' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<style>
  :root {
    --bg: #09090b; --panel: #101013; --panel2: #17171c; --border: #26262d;
    --fg: #ececf1; --muted: #8b8b95;
    --ok: #34d399; --warn: #fbbf24; --bad: #f87171; --accent: #6ea8fe;
  }
  * { box-sizing: border-box; }
  html, body { background: var(--bg); }
  body {
    margin: 0; color: var(--fg);
    font: 14px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .wrap { max-width: 920px; margin: 0 auto; padding: 2.2rem 1.25rem 4rem; }
  header { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem;
           flex-wrap: wrap; border-bottom: 1px solid var(--border); padding-bottom: .9rem;
           margin-bottom: 1.4rem; }
  .title { font-size: 1.25rem; font-weight: 700; letter-spacing: .2px; }
  .title::before { content: "\u258d"; color: var(--accent); margin-right: .4rem; }
  .header-actions { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
  .tag { color: var(--muted); font-size: .72rem; margin-top: .25rem; text-transform: uppercase;
         letter-spacing: .16em; }
  button { font: inherit; font-size: .8rem; color: var(--fg); background: var(--panel2);
           border: 1px solid var(--border); border-radius: 6px; padding: .4rem .9rem;
           cursor: pointer; transition: border-color .15s, color .15s; }
  button:hover { border-color: var(--accent); color: #fff; }
  button:disabled { opacity: .5; cursor: default; }
  button.danger { border-color: #713b3b; color: #ffb4b4; }
  button.danger:hover { border-color: var(--bad); color: var(--bad); }
  select { max-width: 12rem; min-width: 8rem; font: inherit; font-size: .72rem; color: var(--fg);
           background: var(--panel2); border: 1px solid var(--border); border-radius: 6px;
           padding: .28rem .45rem; }
  .status { display: flex; align-items: center; gap: .65rem; margin-bottom: 1.4rem; font-weight: 600;
            background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
            padding: .75rem .95rem; }
  .status .dot { flex: 0 0 auto; width: .7rem; height: .7rem; border-radius: 50%; background: var(--muted); }
  .status.ok { color: var(--ok); }
  .status.ok .dot { background: var(--ok); box-shadow: 0 0 0 3px rgba(52,211,153,.14); }
  .status.alert { color: var(--warn); }
  .status.alert .dot { background: var(--warn); box-shadow: 0 0 0 3px rgba(251,191,36,.14); }
  table { width: 100%; border-collapse: collapse; background: var(--panel);
          border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  thead th { text-align: left; font-size: .68rem; text-transform: uppercase; letter-spacing: .13em;
             color: var(--muted); font-weight: 600; padding: .7rem .95rem;
             border-bottom: 1px solid var(--border); background: var(--panel2); }
  tbody td { padding: .62rem .95rem; border-top: 1px solid var(--border); vertical-align: middle; }
  tbody tr:first-child td { border-top: none; }
  tbody tr:hover { background: var(--panel2); }
  .type { white-space: nowrap; font-weight: 600; color: var(--accent); }
  .issue { word-break: break-all; }
  .issue .sub { color: var(--muted); }
  .act { white-space: nowrap; text-align: right; }
  .act .btn { font-size: .72rem; padding: .25rem .65rem; margin-left: .55rem; }
  .act .btn.danger:hover { border-color: var(--bad); color: var(--bad); }
  .act a.open { color: var(--muted); text-decoration: none; font-size: .74rem;
                border-bottom: 1px solid transparent; }
  .act a.open:hover { color: var(--accent); border-bottom-color: var(--accent); }
  tr.err .type, tr.err .issue { color: var(--bad); }
  .allclear { background: var(--panel); border: 1px solid var(--border); border-left: 3px solid var(--ok);
              border-radius: 10px; padding: 1.1rem; color: var(--ok); font-weight: 600; }
  footer { margin-top: 1.6rem; border-top: 1px solid var(--border); padding-top: .8rem;
           color: var(--muted); font-size: .78rem; }

  /* Phones: the 3-column table can't fit, so stack each row into a card. */
  @media (max-width: 640px) {
    .wrap { padding: 1.4rem 1rem 3rem; }
    header { margin-bottom: 1.1rem; }
    thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
    table { border: none; background: transparent; border-radius: 0; overflow: visible; }
    tbody tr, tbody tr:hover { display: block; background: var(--panel); border: 1px solid var(--border);
             border-radius: 10px; padding: .75rem .9rem; margin-bottom: .7rem; }
    tbody td, tbody tr:first-child td { display: block; padding: 0; border: none; }
    .type { margin-bottom: .25rem; }
    .issue { white-space: normal; margin-bottom: .6rem; }
    .act { text-align: left; white-space: normal; display: flex; flex-wrap: wrap;
           align-items: center; gap: .5rem; }
    .act .btn { margin-left: 0; }
    .act a.open { margin-left: auto; }
  }
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <div class="title">local-monitoring</div>
        <div class="tag">actions dashboard</div>
      </div>
      <div class="header-actions">
        <button id="delete-all-monitors" class="danger" type="button">delete all Kuma monitors</button>
        <button id="refresh" type="button">refresh</button>
      </div>
    </header>

    <div id="status" class="status"><span class="dot"></span><span id="status-text">loading\u2026</span></div>

    <table id="board" hidden>
      <thead><tr><th>Monitor type</th><th>Issue</th><th>Action</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
    <div id="allclear" class="allclear" hidden>\u2713 No issues \u2014 everything is healthy.</div>

    <footer id="footer">\u2014</footer>
  </div>

  <script>
    var REFRESH_MS = 300000;
    var LINKS = __LINKS_JSON__;
    var CARDS = [
      { type: "Monitor", key: "uptime_kuma", list: "down_monitors", link: "kuma", note: "down" },
      { type: "Ping", key: "ping_monitors", list: "unmonitored_devices", link: "kuma",
        note: "no ping monitor",
        action: { url: "/actions/add-ping-monitor", label: "add monitor", field: "device" } },
      { type: "Container monitor", key: "docker_monitors", list: "unmonitored_containers",
        link: "kuma", note: "no docker monitor", dockerHost: true },
      { type: "Compose source", key: "compose_stacks", list: "containers", link: "portainer",
        map: function (i) {
          var detail = i.source === "github" ? "GitHub: " + i.source_file :
            (i.source === "local compose" ? "not linked to configured GitHub source" : "not managed by Compose");
          return {
            issue: i.name + " · " + detail,
            target: i.name,
            actions: i.can_redeploy ? [
              { url: "/actions/redeploy-compose", label: "pull & redeploy", field: "container" }
            ] : []
          };
        } },
      { type: "Additional", key: "additional_monitors", list: "additional_monitors",
        link: "kuma", note: "unexpected monitor",
        action: { url: "/actions/delete-monitor", label: "delete monitor", field: "name", danger: true } },
      { type: "Allowlist", key: "allowlist", list: "unmatched_allowed", link: "kuma",
        note: "matches no monitor" },
      { type: "Container", key: "docker_containers", list: "stopped_containers",
        link: "portainer", note: "stopped",
        actions: [
          { url: "/actions/start-container", label: "start", field: "name" },
          { url: "/actions/delete-container", label: "delete", field: "name", danger: true }
        ] },
      { type: "Update", key: "docker_updater", list: "pending_containers", link: "updater",
        note: "update available",
        action: { url: "/actions/update", label: "update", field: "name" },
        map: function (i) { return { issue: i.image || i.name, target: i.name }; } },
      { type: "Image", key: "docker_images", list: "unused_images", link: "portainer",
        note: "unused",
        action: { url: "/actions/delete-image", label: "delete image", field: "image", danger: true } }
    ];

    var refreshBtn = document.getElementById("refresh");
    var deleteAllBtn = document.getElementById("delete-all-monitors");
    var statusEl = document.getElementById("status");
    var statusText = document.getElementById("status-text");
    var board = document.getElementById("board");
    var rowsEl = document.getElementById("rows");
    var allclear = document.getElementById("allclear");
    var footer = document.getElementById("footer");
    var DOCKER_HOSTS = [];
    var DOCKER_HOSTS_ERROR = "";
    var MONITOR_TOTAL = null;

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
    }

    function openLink(card) {
      var url = LINKS[card.link];
      if (!url) return "";
      return ' <a class="open" href="' + escapeHtml(url) +
        '" target="_blank" rel="noopener noreferrer">open \u2197</a>';
    }

    function rowHtml(card, item) {
      var mapped = card.map ? card.map(item) : { issue: item, target: item };
      var issue = escapeHtml(mapped.issue);
      if (card.note) issue += ' <span class="sub">\u00b7 ' + escapeHtml(card.note) + "</span>";
      var act = "";
      var actions = mapped.actions || card.actions || (card.action ? [card.action] : []);
      if (card.dockerHost) {
        var options = '<option value="">select Docker host</option>';
        DOCKER_HOSTS.forEach(function (host) {
          options += '<option value="' + escapeHtml(host.id) + '">' +
            escapeHtml(host.name || ("Docker host #" + host.id)) + " (#" + escapeHtml(host.id) + ")</option>";
        });
        if (DOCKER_HOSTS_ERROR || DOCKER_HOSTS.length === 0) {
          options = '<option value="">' + escapeHtml(DOCKER_HOSTS_ERROR || "no Docker hosts configured") + "</option>";
        }
        act += '<select class="host-select" aria-label="Docker host for ' + issue + '"' +
          (DOCKER_HOSTS_ERROR || DOCKER_HOSTS.length === 0 ? " disabled" : "") + ">" + options + "</select>";
        act += '<button class="btn" data-url="/actions/add-docker-monitor" data-field="container"' +
          ' data-target="' + encodeURIComponent(mapped.target) + '" data-label="add monitor"' +
          ' data-host-required="true" disabled' +
          '>add monitor</button>';
      } else {
        actions.forEach(function (a) {
          var cls = "btn" + (a.danger ? " danger" : "");
          act += '<button class="' + cls + '" data-url="' + a.url +
            '" data-field="' + a.field +
            '" data-target="' + encodeURIComponent(mapped.target) +
            '" data-label="' + escapeHtml(a.label) + '">' +
            escapeHtml(a.label) + "</button>";
        });
      }
      act += openLink(card);
      if (!act) act = '<span class="sub">\u2014</span>';
      return '<tr><td class="type">' + escapeHtml(card.type) + '</td><td class="issue">' +
        issue + '</td><td class="act">' + act + "</td></tr>";
    }

    function errRowHtml(card, msg) {
      var act = openLink(card) || '<span class="sub">\u2014</span>';
      return '<tr class="err"><td class="type">' + escapeHtml(card.type) +
        '</td><td class="issue">' + escapeHtml(msg) + '</td><td class="act">' + act + "</td></tr>";
    }

    function render(checks) {
      var html = "";
      var issues = 0, errors = 0;
      CARDS.forEach(function (card) {
        var check = checks[card.key];
        if (!check) return;
        if (check.status === "error") {
          errors++;
          html += errRowHtml(card, check.error || "unavailable");
          return;
        }
        var items = Array.isArray(check[card.list]) ? check[card.list] : [];
        items.forEach(function (item) { issues++; html += rowHtml(card, item); });
      });
      rowsEl.innerHTML = html;
      var hasRows = (issues + errors) > 0;
      board.hidden = !hasRows;
      allclear.hidden = hasRows;
      bindActions();
      return { issues: issues, errors: errors };
    }

    function setStatus(res) {
      if (res.issues === 0 && res.errors === 0) {
        statusEl.className = "status ok";
        statusText.textContent = "OK \u2014 all clear";
        return;
      }
      statusEl.className = "status alert";
      var parts = [];
      if (res.issues) parts.push(res.issues + " issue" + (res.issues === 1 ? "" : "s"));
      if (res.errors) parts.push(res.errors + " check" + (res.errors === 1 ? "" : "s") + " unavailable");
      statusText.textContent = "ATTENTION \u2014 " + parts.join(" \u00b7 ");
    }

    function describeAction(url, target, d) {
      if (url.indexOf("redeploy-compose") >= 0) return "Git Compose redeploy requested for " + (d.container || target);
      if (url.indexOf("add-ping-monitor") >= 0) return "created monitor " + (d.created || target);
      if (url.indexOf("delete-monitor") >= 0) return "deleted monitor " + (d.deleted || target);
      if (url.indexOf("delete-image") >= 0) return "removed image " + (d.removed || target);
      if (url.indexOf("start-container") >= 0) return "started " + (d.started || target);
      if (url.indexOf("delete-container") >= 0) return "deleted container " + (d.deleted || target);
      if (url.indexOf("update") >= 0) return "update triggered for " + (d.triggered || target);
      return "done";
    }

    function runAction(b) {
      b.disabled = true;
      var label = b.getAttribute("data-label");
      b.textContent = "working\u2026";
      var url = b.getAttribute("data-url");
      var field = b.getAttribute("data-field");
      var target = decodeURIComponent(b.getAttribute("data-target"));
      var payload = {};
      if (field) payload[field] = target;
      var hostSelect = b.parentElement.querySelector(".host-select");
      if (hostSelect) payload.host_id = Number(hostSelect.value);
      fetch(url, {
        method: "POST", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }).then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, data: d }; });
      }).then(function (res) {
        if (!res.ok || !res.data || res.data.status === "error") {
          throw new Error(res.data && res.data.error ? res.data.error : "action failed");
        }
        footer.textContent = describeAction(url, target, res.data);
        refresh();
      }).catch(function (e) {
        footer.textContent = "action failed: " + e.message;
        b.disabled = false;
        b.textContent = label;
      });
    }

    function bindActions() {
      var buttons = rowsEl.querySelectorAll(".act .btn");
      buttons.forEach(function (b) {
        b.addEventListener("click", function () { runAction(b); });
      });
      rowsEl.querySelectorAll(".host-select").forEach(function (select) {
        select.addEventListener("change", function () {
          var button = select.parentElement.querySelector("button[data-host-required]");
          if (button) button.disabled = !select.value;
        });
      });
    }

    function deleteAllMonitors() {
      var countText = MONITOR_TOTAL === null ? "all" : MONITOR_TOTAL;
      if (!window.confirm("Permanently delete " + countText + " Uptime Kuma monitors? This cannot be undone.")) return;
      deleteAllBtn.disabled = true;
      deleteAllBtn.textContent = "deleting...";
      fetch("/actions/delete-all-monitors", { method: "POST", cache: "no-store" }).then(function (r) {
        return r.json().then(function (d) { return { ok: r.ok, data: d }; });
      }).then(function (res) {
        if (!res.ok || !res.data || res.data.status === "error") {
          throw new Error(res.data && res.data.error ? res.data.error : "delete-all failed");
        }
        var failed = Array.isArray(res.data.failed) ? res.data.failed.length : 0;
        footer.textContent = failed
          ? "deleted " + res.data.deleted + " of " + res.data.total + " monitors; " + failed + " failed"
          : "deleted " + res.data.deleted + " of " + res.data.total + " monitors";
        refresh();
      }).catch(function (e) {
        footer.textContent = "delete-all failed: " + e.message;
      }).then(function () {
        deleteAllBtn.disabled = false;
        deleteAllBtn.textContent = "delete all Kuma monitors";
      });
    }

    function refresh(forceCompose) {
      if (refreshBtn.disabled) return;
      refreshBtn.disabled = true;
      refreshBtn.textContent = "refreshing\u2026";
      var composeUrl = "/compose-stacks" + (forceCompose ? "?refresh=true" : "");
      Promise.all([
        fetch("/summary", { cache: "no-store" }).then(function (r) { return r.json(); }),
        fetch("/docker-hosts", { cache: "no-store" }).then(function (r) {
          return r.json().then(function (data) { return { ok: r.ok, data: data }; });
        }).catch(function (e) { return { ok: false, data: { error: String(e) } }; }),
        fetch(composeUrl, { cache: "no-store" }).then(function (r) {
          return r.json().then(function (data) { return { ok: r.ok, data: data }; });
        }).catch(function (e) { return { ok: false, data: { error: String(e) } }; })
      ]).then(function (results) {
        var data = results[0];
        var hostsResult = results[1];
        var composeResult = results[2];
        DOCKER_HOSTS = hostsResult.ok && Array.isArray(hostsResult.data.hosts) ? hostsResult.data.hosts : [];
        DOCKER_HOSTS_ERROR = hostsResult.ok ? "" : (hostsResult.data.error || "Docker hosts unavailable");
        MONITOR_TOTAL = data.checks && data.checks.uptime_kuma ? data.checks.uptime_kuma.total : null;
        data.checks = data.checks || {};
        data.checks.compose_stacks = composeResult.ok
          ? { status: "ok", containers: composeResult.data.containers || [] }
          : { status: "error", error: composeResult.data.error || "Compose source status unavailable" };
        setStatus(render(data.checks || {}));
        footer.textContent = "updated " + new Date().toLocaleTimeString() + " \u00b7 auto every 5m";
      }).catch(function (e) {
        statusEl.className = "status alert";
        statusText.textContent = "failed to load status";
        footer.textContent = String(e);
      }).then(function () {
        refreshBtn.disabled = false;
        refreshBtn.textContent = "refresh";
      });
    }

    refreshBtn.addEventListener("click", function () { refresh(true); });
    deleteAllBtn.addEventListener("click", deleteAllMonitors);
    refresh();
    setInterval(refresh, REFRESH_MS);
  </script>
</body>
</html>
"""


def _section_links() -> dict[str, str]:
    """Browser-reachable URL for each dashboard action link (blank -> no link)."""
    return {
        "kuma": settings.uptime_kuma_public_url or settings.uptime_kuma_base_url,
        "portainer": settings.portainer_url,
        "updater": settings.docker_updater_public_url or settings.docker_updater_base_url,
    }


def _render_dashboard() -> str:
    # json.dumps yields a valid JS object literal; neutralise any "</" so a URL
    # cannot break out of the <script> element.
    links = json.dumps(_section_links()).replace("</", "<\\/")
    return _DASHBOARD_HTML.replace("__LINKS_JSON__", links)


def register_dashboard_routes(app: Bottle) -> None:
    @app.get("/")
    def dashboard() -> str:
        response.content_type = "text/html; charset=utf-8"
        return _render_dashboard()
