"""Human-friendly HTML status page that renders the /summary issue lists."""

from __future__ import annotations

from bottle import Bottle, response

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>Local Monitoring \u00b7 Status</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%231d2021'/%3E%3Cpath d='M3 17h5l3-8 4 14 3-9 2 3h6' fill='none' stroke='%23a9b665' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<style>
  :root {
    --bg: #1d2021; --panel: #282828; --border: #3c3836;
    --fg: #d4be98; --muted: #928374;
    --ok: #a9b665; --warn: #d8a657; --bad: #ea6962; --accent: #89b482;
  }
  * { box-sizing: border-box; }
  html { background: var(--bg); }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 15px/1.6 ui-monospace, "Cascadia Code", "SF Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace;
  }
  .wrap { max-width: 760px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
  header { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem;
           flex-wrap: wrap; border-bottom: 1px solid var(--border); padding-bottom: .8rem;
           margin-bottom: 1.6rem; }
  .title { font-size: 1.2rem; font-weight: 700; }
  .title::before { content: "> "; color: var(--accent); }
  .tag { color: var(--muted); font-size: .82rem; margin-top: .2rem; }
  button { font: inherit; font-size: .82rem; color: var(--fg); background: transparent;
           border: 1px solid var(--border); padding: .35rem .85rem; cursor: pointer; }
  button:hover { border-color: var(--accent); color: var(--accent); }
  button:disabled { opacity: .5; cursor: default; }
  button:disabled:hover { border-color: var(--border); color: var(--fg); }
  .status { display: flex; align-items: center; gap: .7rem; margin-bottom: 2rem; font-weight: 700;
            background: var(--panel); border: 1px solid var(--border); border-left: 3px solid var(--muted);
            padding: .7rem .9rem; }
  .status .sw { flex: 0 0 auto; width: .8rem; height: .8rem; background: var(--muted); }
  .status.ok { color: var(--ok); border-left-color: var(--ok); }
  .status.ok .sw { background: var(--ok); }
  .status.alert { color: var(--bad); border-left-color: var(--bad); }
  .status.alert .sw { background: var(--bad); }
  .block { margin: 0 0 1.7rem; }
  .row { display: flex; align-items: baseline; gap: .6rem; }
  .row .label { white-space: nowrap; font-weight: 700; }
  .row .lead { flex: 1 1 auto; border-bottom: 1px dotted var(--border); transform: translateY(-.3em); }
  .row .count { white-space: nowrap; color: var(--muted); font-variant-numeric: tabular-nums; }
  .block.issues .label, .block.issues .count { color: var(--warn); }
  .block.errored .label, .block.errored .count { color: var(--bad); }
  .body { margin-top: .45rem; }
  .line { display: flex; gap: .7rem; padding: .12rem 0; word-break: break-all; }
  .line .mk { flex: 0 0 1ch; text-align: center; font-weight: 700; }
  .line.ok { color: var(--muted); }
  .line.ok .mk { color: var(--ok); }
  .line.bad .mk { color: var(--warn); }
  .line.err { color: var(--bad); }
  .line.err .mk { color: var(--bad); }
  footer { margin-top: 2rem; border-top: 1px solid var(--border); padding-top: .8rem;
           color: var(--muted); font-size: .8rem; }
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <div class="title">local-monitoring</div>
        <div class="tag">homelab status board</div>
      </div>
      <button id="refresh" type="button">refresh</button>
    </header>

    <div id="status" class="status"><span class="sw"></span><span id="status-text">loading\u2026</span></div>

    <section class="block" id="card-monitors">
      <div class="row"><span class="label">down monitors</span><span class="lead"></span><span class="count">\u2013</span></div>
      <div class="body"></div>
    </section>
    <section class="block" id="card-containers">
      <div class="row"><span class="label">stopped containers</span><span class="lead"></span><span class="count">\u2013</span></div>
      <div class="body"></div>
    </section>
    <section class="block" id="card-updates">
      <div class="row"><span class="label">pending updates</span><span class="lead"></span><span class="count">\u2013</span></div>
      <div class="body"></div>
    </section>

    <footer id="footer">\u2014</footer>
  </div>

  <script>
    var REFRESH_MS = 30000;
    var cards = [
      { id: "card-monitors", key: "uptime_kuma", list: "down_monitors", empty: "All monitors up" },
      { id: "card-containers", key: "docker_containers", list: "stopped_containers", empty: "All containers running" },
      { id: "card-updates", key: "docker_updater", list: "pending_images", empty: "Everything up to date" }
    ];
    var btn = document.getElementById("refresh");
    var statusEl = document.getElementById("status");
    var statusText = document.getElementById("status-text");

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
    }

    function line(cls, mk, text) {
      return '<div class="line ' + cls + '"><span class="mk">' + mk + "</span>" + escapeHtml(text) + "</div>";
    }

    function renderCard(cfg, check) {
      var el = document.getElementById(cfg.id);
      var count = el.querySelector(".count");
      var body = el.querySelector(".body");
      el.classList.remove("issues", "errored");

      if (!check || check.status === "error") {
        el.classList.add("errored");
        count.textContent = "!";
        body.innerHTML = line("err", "\u00d7", check && check.error ? check.error : "unavailable");
        return "error";
      }

      var items = Array.isArray(check[cfg.list]) ? check[cfg.list] : [];
      count.textContent = items.length;
      if (items.length === 0) {
        body.innerHTML = line("ok", "\u2022", cfg.empty);
        return "ok";
      }
      el.classList.add("issues");
      body.innerHTML = items.map(function (i) {
        return line("bad", "!", i);
      }).join("");
      return "issues";
    }

    function refresh() {
      if (btn.disabled) return;
      btn.disabled = true;
      btn.textContent = "refreshing\u2026";
      fetch("/summary", { cache: "no-store" }).then(function (r) {
        return r.json();
      }).then(function (data) {
        var checks = data.checks || {};
        var issues = 0, errors = 0;
        cards.forEach(function (cfg) {
          var state = renderCard(cfg, checks[cfg.key]);
          if (state === "issues") issues++;
          if (state === "error") errors++;
        });
        if (issues === 0 && errors === 0) {
          statusEl.className = "status ok";
          statusText.textContent = "OK \u2014 all clear";
        } else {
          statusEl.className = "status alert";
          var parts = [];
          if (issues) parts.push(issues + " area" + (issues === 1 ? "" : "s") + " need attention");
          if (errors) parts.push(errors + " check" + (errors === 1 ? "" : "s") + " unavailable");
          statusText.textContent = "ATTENTION \u2014 " + parts.join(" \u00b7 ");
        }
        document.getElementById("footer").textContent =
          "updated " + new Date().toLocaleTimeString() + " \u00b7 auto every 30s";
      }).catch(function (e) {
        statusEl.className = "status alert";
        statusText.textContent = "failed to load status";
        document.getElementById("footer").textContent = String(e);
      }).then(function () {
        btn.disabled = false;
        btn.textContent = "refresh";
      });
    }

    btn.addEventListener("click", refresh);
    refresh();
    setInterval(refresh, REFRESH_MS);
  </script>
</body>
</html>
"""


def register_dashboard_routes(app: Bottle) -> None:
    @app.get("/")
    def dashboard() -> str:
        response.content_type = "text/html; charset=utf-8"
        return _DASHBOARD_HTML
