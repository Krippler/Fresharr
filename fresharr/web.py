"""Fresharr's web interface.

Serves a single-page UI plus a small JSON API. This is where the run
schedule lives and where each discovery site is enabled or disabled -
those settings are deliberately not environment variables.
"""

import logging
import time

from flask import Flask, jsonify, request

from . import __version__
from .config import Config
from .scheduler import Scheduler
from .settings import SettingsError, SettingsStore
from .sources import describe_sources
from .state import State
from .status import load_status

log = logging.getLogger(__name__)


def create_app(config: Config, settings: SettingsStore, scheduler: Scheduler) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return INDEX_HTML

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/overview")
    def overview():
        status = load_status(config.status_file)
        recent = _recent_additions(config)
        return jsonify({
            "version": __version__,
            "settings": settings.snapshot(),
            "sources": describe_sources(config, settings),
            "last_run": status or None,
            "next_run_at": int(scheduler.next_run_at()),
            "running": scheduler.running,
            "dry_run": config.dry_run,
            "arr": {
                "radarr": config.radarr_enabled,
                "sonarr": config.sonarr_enabled,
            },
            "recent_additions": recent,
            "server_time": int(time.time()),
        })

    @app.post("/api/settings")
    def update_settings():
        payload = request.get_json(silent=True)
        try:
            snapshot = settings.update(payload)
        except SettingsError as exc:
            return jsonify({"error": str(exc)}), 400
        log.info("Settings updated via web UI: interval %.1f day(s), sources: %s",
                 snapshot["run_interval_days"],
                 ", ".join(n for n, e in snapshot["sources"].items() if e["enabled"])
                 or "none")
        return jsonify(snapshot)

    @app.post("/api/run")
    def run_now():
        if scheduler.running:
            return jsonify({"error": "A run is already in progress"}), 409
        scheduler.request_run()
        return jsonify({"requested": True})

    return app


def _recent_additions(config: Config, limit: int = 15) -> list[dict]:
    from . import state as state_mod
    store = State(config.state_file)
    added = [
        {"title": entry.get("title", key), "at": entry.get("at")}
        for key, entry in store.entries().items()
        if entry.get("status") == state_mod.ADDED
    ]
    added.sort(key=lambda e: e.get("at") or 0, reverse=True)
    return added[:limit]


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fresharr</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; }
  body { font: 15px/1.5 system-ui, -apple-system, sans-serif;
         background: #101418; color: #dde3ea; padding: 1.5rem; }
  .wrap { max-width: 780px; margin: 0 auto; display: grid; gap: 1rem; }
  header { display: flex; align-items: baseline; gap: .75rem; }
  h1 { font-size: 1.5rem; color: #7bd88f; letter-spacing: .02em; }
  .ver { color: #6b7684; font-size: .8rem; }
  .card { background: #1a2027; border: 1px solid #2a323c; border-radius: 10px;
          padding: 1rem 1.25rem; }
  h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .08em;
       color: #8b96a5; margin-bottom: .75rem; }
  .source { display: flex; align-items: center; gap: .9rem;
            padding: .6rem 0; border-top: 1px solid #232b34; }
  .source:first-of-type { border-top: none; }
  .source .info { flex: 1; }
  .source .name { font-weight: 600; }
  .source .desc { color: #8b96a5; font-size: .82rem; }
  .source .detail { color: #6b7684; font-size: .78rem; }
  .badge { font-size: .7rem; padding: .1rem .45rem; border-radius: 99px;
           border: 1px solid #5a4a1a; color: #d8b44a; white-space: nowrap; }
  .switch { position: relative; width: 42px; height: 24px; flex-shrink: 0; }
  .switch input { opacity: 0; width: 0; height: 0; }
  .slider { position: absolute; inset: 0; background: #333d49; border-radius: 99px;
            cursor: pointer; transition: background .15s; }
  .slider:before { content: ""; position: absolute; width: 18px; height: 18px;
                   left: 3px; top: 3px; background: #aab4c0; border-radius: 50%;
                   transition: transform .15s, background .15s; }
  input:checked + .slider { background: #2f6b3d; }
  input:checked + .slider:before { transform: translateX(18px); background: #7bd88f; }
  input:disabled + .slider { opacity: .45; cursor: not-allowed; }
  .row { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap; }
  select, button { font: inherit; background: #232b34; color: #dde3ea;
                   border: 1px solid #333d49; border-radius: 7px; padding: .4rem .7rem; }
  button { cursor: pointer; }
  button.primary { background: #2f6b3d; border-color: #3a8049; color: #eafff0; }
  button:disabled { opacity: .5; cursor: wait; }
  .stat { display: flex; gap: 1.5rem; flex-wrap: wrap; }
  .stat div span { display: block; }
  .stat .k { color: #8b96a5; font-size: .75rem; text-transform: uppercase;
             letter-spacing: .06em; }
  .stat .v { font-size: 1.05rem; font-weight: 600; }
  .muted { color: #6b7684; font-size: .85rem; }
  .err { color: #e07a7a; }
  .dry { color: #d8b44a; font-size: .8rem; }
  ul.recent { list-style: none; }
  ul.recent li { padding: .3rem 0; border-top: 1px solid #232b34; font-size: .9rem; }
  ul.recent li:first-child { border-top: none; }
  ul.recent .when { color: #6b7684; font-size: .78rem; float: right; }
  #toast { position: fixed; bottom: 1rem; right: 1rem; background: #2f6b3d;
           color: #eafff0; padding: .5rem .9rem; border-radius: 8px;
           opacity: 0; transition: opacity .2s; pointer-events: none; }
  #toast.show { opacity: 1; }
  #toast.error { background: #6b2f2f; color: #ffeaea; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Fresharr</h1>
    <span class="ver" id="version"></span>
    <span class="dry" id="dryrun" hidden>DRY RUN &mdash; nothing is sent to Radarr/Sonarr</span>
  </header>

  <div class="card">
    <h2>Status</h2>
    <div class="stat" id="status">Loading&hellip;</div>
    <p class="muted err" id="lasterror" hidden></p>
  </div>

  <div class="card">
    <h2>Schedule</h2>
    <div class="row">
      <label for="interval">Check for new titles</label>
      <select id="interval">
        <option value="1">Once a day</option>
        <option value="2">Every 2 days</option>
        <option value="3">Every 3 days</option>
        <option value="7">Once a week</option>
        <option value="15">Twice a month</option>
        <option value="30">Once a month</option>
      </select>
      <button class="primary" id="runnow">Run now</button>
    </div>
    <p class="muted" style="margin-top:.5rem">
      Daily is the most frequent schedule &mdash; discovery lists change slowly
      and the sites don't need more traffic.
    </p>
  </div>

  <div class="card">
    <h2>Discovery sites</h2>
    <div id="sources"></div>
  </div>

  <div class="card">
    <h2>Recently added</h2>
    <ul class="recent" id="recent"><li class="muted">Nothing yet.</li></ul>
  </div>
</div>
<div id="toast"></div>

<script>
const $ = id => document.getElementById(id);

function toast(msg, isError) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "show" + (isError ? " error" : "");
  setTimeout(() => el.className = "", 2500);
}

function fmtTime(ts) {
  if (!ts) return "never";
  return new Date(ts * 1000).toLocaleString();
}

function fmtRelative(ts, now) {
  const diff = ts - now;
  if (diff <= 0) return "due now";
  const hours = diff / 3600;
  if (hours < 1.5) return "in about an hour";
  if (hours < 36) return "in " + Math.round(hours) + " hours";
  return "in " + Math.round(hours / 24) + " day(s)";
}

async function api(path, opts) {
  const resp = await fetch(path, opts);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || resp.statusText);
  return data;
}

function render(o) {
  $("version").textContent = "v" + o.version;
  $("dryrun").hidden = !o.dry_run;

  const lr = o.last_run;
  const counts = (lr && lr.counts) || {};
  $("status").innerHTML = `
    <div><span class="k">Last run</span><span class="v">${fmtTime(lr && lr.last_run_at)}</span></div>
    <div><span class="k">Next run</span><span class="v">${o.running ? "running now" : fmtRelative(o.next_run_at, o.server_time)}</span></div>
    <div><span class="k">Added last run</span><span class="v">${counts.added ?? (counts.would_add !== undefined ? counts.would_add + " (dry)" : "–")}</span></div>
    <div><span class="k">Radarr</span><span class="v">${o.arr.radarr ? "configured" : "off"}</span></div>
    <div><span class="k">Sonarr</span><span class="v">${o.arr.sonarr ? "configured" : "off"}</span></div>`;
  const errEl = $("lasterror");
  errEl.hidden = !(lr && lr.error);
  if (lr && lr.error) errEl.textContent = "Last run error: " + lr.error;

  const sel = $("interval");
  const days = o.settings.run_interval_days;
  if (![...sel.options].some(opt => Number(opt.value) === days)) {
    const opt = document.createElement("option");
    opt.value = days; opt.textContent = "Every " + days + " days";
    sel.appendChild(opt);
  }
  sel.value = days;

  $("sources").innerHTML = o.sources.map(s => `
    <div class="source">
      <div class="info">
        <span class="name">${s.label}</span>
        ${!s.configured ? `<span class="badge">needs ${s.requires}</span>` : ""}
        <div class="desc">${s.description}</div>
        <div class="detail">${s.detail}</div>
      </div>
      <label class="switch">
        <input type="checkbox" data-source="${s.name}"
               ${s.enabled ? "checked" : ""} ${!s.configured && !s.enabled ? "disabled" : ""}>
        <span class="slider"></span>
      </label>
    </div>`).join("");

  document.querySelectorAll("[data-source]").forEach(box => {
    box.addEventListener("change", async () => {
      try {
        await api("/api/settings", {method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({sources: {[box.dataset.source]: {enabled: box.checked}}})});
        toast((box.checked ? "Enabled " : "Disabled ") + box.dataset.source);
      } catch (e) { toast(e.message, true); box.checked = !box.checked; }
    });
  });

  const recent = $("recent");
  recent.innerHTML = (o.recent_additions && o.recent_additions.length)
    ? o.recent_additions.map(r =>
        `<li>${r.title}<span class="when">${fmtTime(r.at)}</span></li>`).join("")
    : '<li class="muted">Nothing yet.</li>';
}

async function refresh() {
  try { render(await api("/api/overview")); }
  catch (e) { toast("Failed to load: " + e.message, true); }
}

$("interval").addEventListener("change", async ev => {
  try {
    await api("/api/settings", {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({run_interval_days: Number(ev.target.value)})});
    toast("Schedule updated");
    refresh();
  } catch (e) { toast(e.message, true); }
});

$("runnow").addEventListener("click", async () => {
  const btn = $("runnow");
  btn.disabled = true;
  try { await api("/api/run", {method: "POST"}); toast("Run started"); }
  catch (e) { toast(e.message, true); }
  setTimeout(() => { btn.disabled = false; refresh(); }, 1500);
});

refresh();
setInterval(refresh, 15000);
</script>
</body>
</html>
"""
