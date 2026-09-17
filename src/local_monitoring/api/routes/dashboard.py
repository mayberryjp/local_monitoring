"""Human-friendly HTML status page that renders the /summary issue lists."""

from __future__ import annotations

from bottle import Bottle, response

_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>local-monitoring \u00b7 status</title>
<style>
  :root {
    --bg: #0f172a; --card: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8;
    --ok: #22c55e; --warn: #f59e0b; --bad: #ef4444; --accent: #38bdf8;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text); line-height: 1.5;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  .wrap { max-width: 900px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
  header { display: flex; align-items: center; justify-content: space-between;
           gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
  h1 { font-size: 1.35rem; margin: 0; letter-spacing: .5px; }
  h1 .sub { display: block; color: var(--muted); font-weight: 400; font-size: .85rem; }
  .banner { display: flex; align-items: center; gap: .9rem; padding: 1rem 1.25rem;
            border: 1px solid var(--border); background: var(--card); border-radius: 14px;
            margin-bottom: 1.5rem; font-size: 1.1rem; font-weight: 600; }
  .banner .dot { flex: 0 0 auto; width: 14px; height: 14px; border-radius: 50%;
                 background: var(--muted); }
  .banner.ok { border-color: rgba(34,197,94,.4); }
  .banner.ok .dot { background: var(--ok); box-shadow: 0 0 12px var(--ok); }
  .banner.issues { border-color: rgba(239,68,68,.4); }
  .banner.issues .dot { background: var(--bad); box-shadow: 0 0 12px var(--bad); }
  .grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 14px;
          padding: 1.1rem 1.2rem; }
  .card h2 { display: flex; align-items: center; gap: .6rem; margin: 0 0 .75rem; font-size: .95rem; }
  .card h2 .ico { color: var(--accent); }
  .badge { margin-left: auto; padding: .15rem .6rem; border-radius: 999px; font-size: .8rem;
           font-weight: 700; color: var(--muted); background: #0b1220; border: 1px solid var(--border); }
  .card.has-issues { border-color: rgba(245,158,11,.45); }
  .card.has-issues .badge { color: #0b1220; background: var(--warn); border-color: transparent; }
  .card.errored { border-color: rgba(239,68,68,.45); }
  .card.errored .badge { color: #0b1220; background: var(--bad); border-color: transparent; }
  .items { list-style: none; margin: 0; padding: 0; }
  .items li { display: flex; align-items: center; gap: .55rem; padding: .45rem .1rem;
              border-top: 1px solid var(--border); font-size: .9rem; word-break: break-all; }
  .items li:first-child { border-top: none; }
  .items li::before { content: "\u25b2"; color: var(--warn); font-size: .7rem; }
  .allclear { display: flex; align-items: center; gap: .5rem; color: var(--ok); font-size: .9rem; }
  .allclear::before { content: "\u2713"; font-weight: 700; }
  .err { color: var(--bad); font-size: .85rem; }
  button { font: inherit; color: var(--text); background: var(--card);
           border: 1px solid var(--border); border-radius: 10px; padding: .45rem .9rem; cursor: pointer; }
  button:hover { border-color: var(--accent); }
  button:disabled { opacity: .6; cursor: default; }
  footer { margin-top: 1.5rem; color: var(--muted); font-size: .8rem; text-align: center; }
  .spin { display: inline-block; animation: sp .8s linear infinite; }
  @keyframes sp { to { transform: rotate(360deg); } }
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>local-monitoring<span class="sub">homelab status</span></h1>
      <button id="refresh" type="button"><span id="ricon">\u21bb</span> Refresh</button>
    </header>

    <div id="banner" class="banner"><span class="dot"></span><span id="banner-text">Loading\u2026</span></div>

    <div class="grid">
      <section class="card" id="card-monitors">
        <h2><span class="ico">\u25c9</span> Down monitors <span class="badge">\u2013</span></h2>
        <div class="body"></div>
      </section>
      <section class="card" id="card-containers">
        <h2><span class="ico">\u25a3</span> Stopped containers <span class="badge">\u2013</span></h2>
        <div class="body"></div>
      </section>
      <section class="card" id="card-updates">
        <h2><span class="ico">\u2b73</span> Pending updates <span class="badge">\u2013</span></h2>
        <div class="body"></div>
      </section>
    </div>

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
    var ricon = document.getElementById("ricon");
    var banner = document.getElementById("banner");
    var bannerText = document.getElementById("banner-text");

    function escapeHtml(s) {
      return String(s).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
    }

    function renderCard(cfg, check) {
      var el = document.getElementById(cfg.id);
      var badge = el.querySelector(".badge");
      var body = el.querySelector(".body");
      el.classList.remove("has-issues", "errored");

      if (!check || check.status === "error") {
        el.classList.add("errored");
        badge.textContent = "!";
        var msg = check && check.error ? check.error : "unavailable";
        body.innerHTML = '<div class="err">Check failed: ' + escapeHtml(msg) + "</div>";
        return "error";
      }

      var items = Array.isArray(check[cfg.list]) ? check[cfg.list] : [];
      badge.textContent = items.length;
      if (items.length === 0) {
        body.innerHTML = '<div class="allclear">' + escapeHtml(cfg.empty) + "</div>";
        return "ok";
      }
      el.classList.add("has-issues");
      body.innerHTML = '<ul class="items">' + items.map(function (i) {
        return "<li>" + escapeHtml(i) + "</li>";
      }).join("") + "</ul>";
      return "issues";
    }

    function refresh() {
      if (btn.disabled) return;
      btn.disabled = true;
      ricon.classList.add("spin");
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
          banner.className = "banner ok";
          bannerText.textContent = "All clear";
        } else {
          banner.className = "banner issues";
          var parts = [];
          if (issues) parts.push(issues + " area" + (issues === 1 ? "" : "s") + " need attention");
          if (errors) parts.push(errors + " check" + (errors === 1 ? "" : "s") + " unavailable");
          bannerText.textContent = parts.join(" \u00b7 ");
        }
        document.getElementById("footer").textContent = "Updated " + new Date().toLocaleTimeString();
      }).catch(function (e) {
        banner.className = "banner issues";
        bannerText.textContent = "Failed to load status";
        document.getElementById("footer").textContent = String(e);
      }).then(function () {
        btn.disabled = false;
        ricon.classList.remove("spin");
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
