"""Shared header, navigation, and global actions for the HTML pages."""

from __future__ import annotations

from html import escape

from local_monitoring import __version__

_STYLES = """
  html { scrollbar-gutter: stable; }
  .wrap { max-width: 1100px; margin: 0 auto; padding: 2.2rem 1.25rem 4rem; }
  .app-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem;
                flex-wrap: wrap; border-bottom: 1px solid var(--border); padding-bottom: .9rem;
                margin-bottom: 1.4rem; }
  .app-header .title { font-size: 1.25rem; font-weight: 700; letter-spacing: .2px; }
  .app-header .title::before { content: "\\258d"; color: var(--accent); margin-right: .4rem; }
  .app-version { margin-left: .5rem; color: var(--muted); font-size: .7rem;
                 font-weight: 400; letter-spacing: 0; white-space: nowrap; }
  .app-header .tag { color: var(--muted); font-size: .72rem; margin-top: .25rem;
                     text-transform: uppercase; letter-spacing: .16em; }
  .header-actions { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; }
  .header-actions button { font: inherit; font-size: .8rem; color: var(--fg); background: #17171c;
                           border: 1px solid var(--border); border-radius: 6px;
                           padding: .4rem .9rem; min-height: 36px; cursor: pointer; }
  .header-actions button:hover { border-color: var(--accent); color: #fff; }
  .header-actions button:disabled { opacity: .5; cursor: default; }
  .header-actions button.danger { border-color: #713b3b; color: #ffb4b4; }
  .header-actions button.danger:hover { border-color: var(--bad); color: var(--bad); }
  .header-actions button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  #header-message, #header-error { white-space: pre-wrap; overflow-wrap: anywhere; }
  #header-error { color: var(--bad); }
  .page-nav { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .35rem;
              padding: .35rem; margin-bottom: 1.4rem; background: var(--panel);
              border: 1px solid var(--border); border-radius: 10px; }
  .page-nav a { display: flex; align-items: center; justify-content: center; min-height: 44px;
                padding: .55rem .35rem; border: 1px solid var(--border); border-radius: 7px;
                background: #17171c; color: var(--muted); font-weight: 600; text-decoration: none; }
  .page-nav a:hover { color: var(--fg); border-color: var(--accent); }
  .page-nav a[aria-current="page"] { color: #fff; background: #1d3557; border-color: var(--accent);
                                   box-shadow: inset 0 -3px 0 var(--accent); }
  .page-nav a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  @media (max-width: 640px) {
    .wrap { padding: 1.4rem 1rem 3rem; }
    .app-header { margin-bottom: 1.1rem; }
  }
"""

_HEADER = """
  <header class="app-header">
    <div>
      <div class="title">local-monitoring <small class="app-version" aria-label="Application version">v__APP_VERSION__</small></div>
      <div class="tag">actions dashboard</div>
    </div>
    <div class="header-actions">
      <button id="clear-all-heartbeats" class="danger" type="button">clear all monitor heartbeats</button>
      <button id="check-updates" type="button">check for container updates</button>
      <button id="refresh" type="button">refresh</button>
    </div>
  </header>
"""

_FEEDBACK = """
  <p id="header-message" role="status" hidden></p>
  <p id="header-error" role="alert" hidden></p>
"""

_SCRIPT = """
<script>
  (function () {
    var message = document.getElementById("header-message");
    var error = document.getElementById("header-error");
    var clearButton = document.getElementById("clear-all-heartbeats");
    var checkButton = document.getElementById("check-updates");

    function run(button, url, working, fallback, suffix, refreshAfter) {
      if (button.disabled) return;
      var label = button.textContent;
      button.disabled = true;
      button.textContent = working;
      message.hidden = true;
      error.hidden = true;
      fetch(url, { method: "POST", cache: "no-store" }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok || !data || data.status === "error") {
            throw new Error(data && data.error ? data.error : "Request failed: HTTP " + response.status);
          }
          return data;
        });
      }).then(function (data) {
        message.textContent = (data.message || fallback) + suffix;
        message.hidden = false;
        if (refreshAfter) document.getElementById("refresh").click();
      }).catch(function (exc) {
        error.textContent = label + " failed: " + exc.message;
        error.hidden = false;
      }).then(function () {
        button.disabled = false;
        button.textContent = label;
      });
    }

    clearButton.addEventListener("click", function () {
      if (clearButton.disabled) return;
      if (!window.confirm("Clear heartbeat history and uptime statistics for all monitors? Monitor definitions will remain; active monitors may restart.")) return;
      run(clearButton, "/actions/clear-heartbeats", "clearing...",
          "all monitor heartbeats and uptime statistics cleared", "", true);
    });
    checkButton.addEventListener("click", function () {
      run(checkButton, "/actions/check-updates", "starting check...",
          "docker-updater container check started", " - click refresh in a minute for results", false);
    });
  })();
</script>
"""


def render_page(template: str, current_path: str) -> str:
    links = []
    for path, label in (("/", "Monitoring"), ("/containers", "Containers"), ("/downloads", "Downloads")):
        current = ' aria-current="page"' if path == current_path else ""
        links.append(f'<a href="{path}"{current}>{label}</a>')
    navigation = '<nav class="page-nav" aria-label="Main navigation">' + "\n".join(links) + "</nav>"
    return (
        template.replace("__PAGE_STYLES__", _STYLES)
        .replace("__PAGE_HEADER__", _HEADER.replace("__APP_VERSION__", escape(__version__)) + navigation + _FEEDBACK)
        .replace("__HEADER_SCRIPT__", _SCRIPT)
    )
