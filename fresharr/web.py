"""Fresharr's web interface.

Serves a single-page UI plus a small JSON API. This is where the run
schedule lives and where each discovery site is enabled or disabled -
those settings are deliberately not environment variables.
"""

import logging
import time

import requests
from flask import Flask, jsonify, request

from . import __version__
from .arr.radarr import Radarr
from .arr.sonarr import Sonarr
from .config import Config
from .options import GENERAL, OPTION_DEFS, RADARR, SONARR
from .scheduler import Scheduler
from .settings import SettingsError, SettingsStore
from .sources import describe_sources
from .state import State
from .status import load_status

log = logging.getLogger(__name__)

# Choices offered by the original-language menu. Sources that don't report
# a language (the scraped review sites) are unaffected by this filter.
LANGUAGE_OPTIONS = [
    {"code": "en", "label": "English"},
    {"code": "ja", "label": "Japanese"},
    {"code": "ko", "label": "Korean"},
    {"code": "zh", "label": "Chinese"},
    {"code": "es", "label": "Spanish"},
    {"code": "fr", "label": "French"},
    {"code": "de", "label": "German"},
    {"code": "it", "label": "Italian"},
    {"code": "pt", "label": "Portuguese"},
    {"code": "hi", "label": "Hindi"},
    {"code": "ru", "label": "Russian"},
    {"code": "sv", "label": "Swedish"},
    {"code": "da", "label": "Danish"},
    {"code": "no", "label": "Norwegian"},
]


def create_app(config: Config, settings: SettingsStore, scheduler: Scheduler) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return INDEX_HTML

    @app.get("/favicon.svg")
    def favicon():
        return app.response_class(FAVICON_SVG, mimetype="image/svg+xml")

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/overview")
    def overview():
        effective = settings.apply_to(config)
        status = load_status(config.status_file)
        recent = _recent_additions(config)
        sources = describe_sources(effective, settings)
        for source in sources:
            source["options"] = _option_payloads(effective, source["name"])
        return jsonify({
            "version": __version__,
            "settings": settings.snapshot(),
            "language_options": LANGUAGE_OPTIONS,
            "sources": sources,
            "connections": {
                "radarr": _option_payloads(effective, RADARR),
                "sonarr": _option_payloads(effective, SONARR),
            },
            "general_options": _option_payloads(effective, GENERAL),
            "last_run": status or None,
            "next_run_at": int(scheduler.next_run_at()),
            "running": scheduler.running,
            "dry_run": config.dry_run,
            "arr": {
                "radarr": effective.radarr_enabled,
                "sonarr": effective.sonarr_enabled,
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
        log.info("Settings updated via web UI: interval %.1f day(s); sources: %s; "
                 "languages movie/tv/anime: %s / %s / %s",
                 snapshot["run_interval_days"],
                 ", ".join(n for n, e in snapshot["sources"].items() if e["enabled"])
                 or "none",
                 ", ".join(snapshot["movie_languages"]) or "all",
                 ", ".join(snapshot["tv_languages"]) or "all",
                 ", ".join(snapshot["anime_languages"]) or "all")
        return jsonify(snapshot)

    @app.get("/api/arr/<app_name>/choices")
    def arr_choices(app_name: str):
        """Quality profiles and root folders fetched live from the connected
        Radarr/Sonarr, so the UI can offer dropdowns instead of free text."""
        effective = settings.apply_to(config)
        if app_name == "radarr":
            configured, factory = effective.radarr_enabled, Radarr
        elif app_name == "sonarr":
            configured, factory = effective.sonarr_enabled, Sonarr
        else:
            return jsonify({"error": f"Unknown app: {app_name}"}), 404
        if not configured:
            return jsonify({"configured": False, "connected": False,
                            "profiles": [], "root_folders": []})
        client = factory(effective)
        try:
            profiles = client._get("qualityprofile", timeout=15)
            folders = client._get("rootfolder", timeout=15)
        except requests.RequestException as exc:
            return jsonify({"configured": True, "connected": False,
                            "error": _short_error(exc),
                            "profiles": [], "root_folders": []})
        return jsonify({
            "configured": True,
            "connected": True,
            "profiles": [{"id": p.get("id"), "name": p.get("name", "?")}
                         for p in profiles],
            "root_folders": [f.get("path", "") for f in folders],
        })

    @app.post("/api/run")
    def run_now():
        if scheduler.running:
            return jsonify({"error": "A run is already in progress"}), 409
        scheduler.request_run()
        return jsonify({"requested": True})

    return app


def _short_error(exc: Exception) -> str:
    """A concise reason for a failed Radarr/Sonarr connection."""
    text = str(exc)
    if "Connection refused" in text or "Failed to establish" in text:
        return "connection refused (check URL/port)"
    if "Name or service not known" in text or "getaddrinfo" in text:
        return "host not found (check URL)"
    if "timed out" in text.lower():
        return "timed out"
    if "401" in text:
        return "unauthorized (check API key)"
    return text.split(":")[-1].strip()[:80] or "unreachable"


def _option_payloads(effective_config: Config, group: str) -> list[dict]:
    payloads = []
    for defn in OPTION_DEFS:
        if defn.group != group:
            continue
        value = getattr(effective_config, defn.key, "")
        if defn.is_list and isinstance(value, list):
            value = ", ".join(value)
        payloads.append({
            "key": defn.key,
            "label": defn.label,
            "type": defn.type,
            "description": defn.description,
            "min": defn.min,
            "max": defn.max,
            "value": value,
            "select": defn.select,
        })
    return payloads


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


# Flat, filter-free variant of unraid/icon.svg so it stays crisp as a favicon.
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
    '<rect x="16" y="16" width="480" height="480" rx="116" fill="#3ba368"/>'
    '<path d="M256 214C256 184 256 168 256 150" fill="none" stroke="#eafff2" '
    'stroke-width="16" stroke-linecap="round"/>'
    '<path d="M256 186C226 182 202 158 200 126 232 128 256 150 256 186Z" fill="#dff8e7"/>'
    '<path d="M256 172C282 166 302 144 306 116 278 120 256 140 256 172Z" fill="#cff2db"/>'
    '<path d="M214 226 214 366 338 296Z" fill="#fff" stroke="#fff" '
    'stroke-width="30" stroke-linejoin="round"/></svg>'
)

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fresharr</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; }
  body { font: 15px/1.5 system-ui, -apple-system, sans-serif;
         background: #101418; color: #dde3ea; padding: 1.5rem; }
  .wrap { max-width: 2600px; margin: 0 auto; }
  header { display: flex; align-items: baseline; gap: .75rem; margin-bottom: 1rem;
           flex-wrap: wrap; }
  h1 { font-size: 1.5rem; color: #7bd88f; letter-spacing: .02em; }
  .ver { color: #6b7684; font-size: .8rem; }
  /* Masonry via independent flex columns (count chosen in JS by width):
     each column stacks its own cards, so expanding one card only grows
     its column - other columns never shift. */
  .cards { display: flex; align-items: flex-start; gap: 1.25rem; }
  .col { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column;
         gap: 1.25rem; }
  .card { background: #1a2027; border: 1px solid #2a323c; border-radius: 10px;
          padding: 1rem 1.25rem; }
  h2 { font-size: .8rem; text-transform: uppercase; letter-spacing: .08em;
       color: #8b96a5; margin-bottom: .75rem; }
  .source { border-top: 1px solid #232b34; }
  .source:first-child { border-top: none; }
  .source-head { display: flex; align-items: center; gap: .7rem;
                 padding: .6rem 0; cursor: pointer; }
  .source-head:hover .name { color: #fff; }
  .chevron { flex-shrink: 0; width: 14px; color: #6b7684; transition: transform .15s;
             font-size: .8rem; line-height: 1; }
  .source.open .chevron { transform: rotate(90deg); color: #8b96a5; }
  .source .info { flex: 1; min-width: 0; }
  .source .name { font-weight: 600; }
  .source .desc { color: #8b96a5; font-size: .82rem; }
  .source .detail { color: #6b7684; font-size: .78rem; margin-top: .1rem; }
  .source .srcopts { display: none; padding: 0 0 .7rem 1.4rem; }
  .source.open .srcopts { display: block; }
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
  input[type=text], input[type=password], input[type=number] {
    font: inherit; background: #232b34; color: #dde3ea;
    border: 1px solid #333d49; border-radius: 7px; padding: .35rem .6rem;
    width: 100%; }
  .opt select { width: 100%; padding: .35rem .6rem; }
  .optgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
             gap: .6rem .8rem; margin-top: .5rem; }
  .opt { display: flex; flex-direction: column; gap: .2rem; }
  .opt > span { font-size: .75rem; color: #8b96a5; }
  .opt small { color: #6b7684; font-size: .72rem; }
  /* Collapsible connection rows: only the name and connection status show
     until the row is expanded, mirroring the discovery-site rows. */
  .conn-row { border-top: 1px solid #232b34; }
  .conn-row:first-of-type { border-top: none; }
  .conn-head { display: flex; align-items: center; gap: .7rem;
               padding: .6rem 0; cursor: pointer; }
  .conn-head:hover .name { color: #fff; }
  .conn-head .name { font-weight: 600; flex: 1; min-width: 0; }
  .conn-row.open .chevron { transform: rotate(90deg); color: #8b96a5; }
  .conn-body { display: none; padding: .1rem 0 .7rem 1.4rem; }
  .conn-row.open .conn-body { display: block; }
  .conn-head .state { flex: 0 1 auto; text-align: right; font-size: .75rem;
                      margin: 0; overflow-wrap: anywhere; }
  .state.ok { color: #7bd88f; }
  .state.off { color: #6b7684; }
  .state.connecting { color: #d8b44a; }
  .state.err { color: #e07a7a; }
  .state .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%;
                margin-right: .3rem; background: currentColor; vertical-align: middle; }
  .state.connecting .dot { animation: pulse 1s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .25; } }
  input:disabled, select:disabled { opacity: .55; cursor: not-allowed; }
  .srcopts { margin-top: .4rem; }
  .srcopts .desc { margin-bottom: .5rem; }
  .srcopts .optgrid { margin-top: .2rem; }
  .langgroup { display: flex; align-items: center; gap: .6rem; margin-top: .55rem; }
  .langgroup .k { color: #8b96a5; font-size: .75rem; text-transform: uppercase;
                  letter-spacing: .06em; flex: 0 0 4.5rem; }
  .dropdown { position: relative; flex: 1 1 auto; min-width: 0; }
  .dd-trigger { width: 100%; display: flex; align-items: center; justify-content: space-between;
                gap: .5rem; border: 1px solid #333d49; border-radius: 8px; background: #161c24;
                color: #d7dee6; padding: .4rem .65rem; font-size: .85rem; cursor: pointer;
                text-align: left; }
  .dd-trigger:hover { border-color: #3a8049; }
  .dd-trigger .cur { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dd-trigger .cur.none { color: #6b7684; }
  .dd-trigger .caret { flex: 0 0 auto; color: #6b7684; font-size: .7rem; }
  .dropdown.open .dd-trigger { border-color: #3a8049; }
  .dd-panel { display: none; position: absolute; z-index: 20; top: calc(100% + 4px); left: 0;
              right: 0; max-height: 15rem; overflow-y: auto; background: #1a212b;
              border: 1px solid #333d49; border-radius: 8px; padding: .3rem;
              box-shadow: 0 8px 24px rgba(0,0,0,.45); }
  .dropdown.open .dd-panel { display: block; }
  .dd-opt { display: flex; align-items: center; gap: .5rem; padding: .35rem .5rem;
            border-radius: 6px; cursor: pointer; font-size: .85rem; color: #c3ccd6; }
  .dd-opt:hover { background: #232b34; }
  .dd-opt input { accent-color: #2f6b3d; }
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

  <div class="cards" id="cards" style="visibility:hidden">
  <div class="card" data-col="0">
    <h2>Status</h2>
    <div class="stat" id="status">Loading&hellip;</div>
    <p class="muted err" id="lasterror" hidden></p>
  </div>

  <div class="card" data-col="0">
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
      Runs at a <strong>random time</strong> around this interval, at least 18h
      apart. Daily is the maximum.
    </p>
  </div>

  <div class="card" data-col="0">
    <h2>Connections</h2>
    <div class="conn-row" data-conn="radarr">
      <div class="conn-head">
        <span class="chevron">&#9656;</span>
        <span class="name">Radarr <span class="muted">(movies)</span></span>
        <span class="state" id="radarr-state"></span>
      </div>
      <div class="conn-body">
        <p class="muted">Saved on blur, applied next run. Empty = use the env
          default.</p>
        <div class="optgrid" id="conn-radarr"></div>
      </div>
    </div>
    <div class="conn-row" data-conn="sonarr">
      <div class="conn-head">
        <span class="chevron">&#9656;</span>
        <span class="name">Sonarr <span class="muted">(TV)</span></span>
        <span class="state" id="sonarr-state"></span>
      </div>
      <div class="conn-body">
        <p class="muted">Saved on blur, applied next run. Empty = use the env
          default.</p>
        <div class="optgrid" id="conn-sonarr"></div>
      </div>
    </div>
  </div>

  <div class="card" data-col="1">
    <h2>Discovery &mdash; Movies &amp; TV</h2>
    <div id="sources-mediatv"></div>
  </div>

  <div class="card" data-col="1">
    <h2>Discovery &mdash; Anime</h2>
    <div id="sources-anime"></div>
  </div>

  <div class="card" data-col="2">
    <h2>Original language</h2>
    <p class="muted">
      Keep only these original languages (none = all). Applies where the
      source reports language; unknown always passes.
    </p>
    <div class="langgroup"><span class="k">Movies</span>
      <div class="dropdown" id="langs-movie"></div>
    </div>
    <div class="langgroup"><span class="k">TV shows</span>
      <div class="dropdown" id="langs-tv"></div>
    </div>
    <div class="langgroup"><span class="k">Anime</span>
      <div class="dropdown" id="langs-anime"></div>
    </div>
  </div>

  <div class="card" data-col="2">
    <h2>Limits</h2>
    <div class="optgrid" id="general"></div>
  </div>

  <div class="card" data-col="2">
    <h2>Recently added</h2>
    <ul class="recent" id="recent"><li class="muted">Nothing yet.</li></ul>
  </div>
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
  lastOverview = o;
  $("version").textContent = "v" + o.version;
  $("dryrun").hidden = !o.dry_run;

  const lr = o.last_run;
  const counts = (lr && lr.counts) || {};
  $("status").innerHTML = `
    <div><span class="k">Last run</span><span class="v">${fmtTime(lr && lr.last_run_at)}</span></div>
    <div><span class="k">Next run</span><span class="v">${o.running ? "running now" : fmtRelative(o.next_run_at, o.server_time)}</span></div>
    <div><span class="k">Added last run</span><span class="v">${counts.added ?? (counts.would_add !== undefined ? counts.would_add + " (dry)" : "–")}</span></div>`;
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

  const sourceRow = s => `
    <div class="source ${expandedSources.has(s.name) ? "open" : ""}" data-src="${s.name}">
      <div class="source-head">
        <span class="chevron">&#9656;</span>
        <div class="info">
          <span class="name">${s.label}</span>
          ${!s.configured ? `<span class="badge">needs ${s.requires.replaceAll("_", " ").toLowerCase()}</span>` : ""}
          <div class="detail">${s.detail}</div>
        </div>
        <label class="switch" title="${s.enabled ? "Enabled" : "Disabled"}">
          <input type="checkbox" data-source="${s.name}"
                 ${s.enabled ? "checked" : ""} ${!s.configured && !s.enabled ? "disabled" : ""}>
          <span class="slider"></span>
        </label>
      </div>
      <div class="srcopts">
        <div class="desc">${s.description}</div>
        <div class="optgrid">${s.options.map(optionInput).join("")}</div>
      </div>
    </div>`;
  const isAnime = s => s.category.toLowerCase().includes("anime");
  $("sources-mediatv").innerHTML = o.sources.filter(s => !isAnime(s)).map(sourceRow).join("");
  $("sources-anime").innerHTML = o.sources.filter(isAnime).map(sourceRow).join("");

  $("conn-radarr").innerHTML = o.connections.radarr.map(optionInput).join("");
  $("conn-sonarr").innerHTML = o.connections.sonarr.map(optionInput).join("");
  $("general").innerHTML = o.general_options.map(optionInput).join("");
  renderConnState("radarr", o.arr.radarr);
  renderConnState("sonarr", o.arr.sonarr);
  wireOptionInputs();

  // Expand/collapse a connection by clicking its header.
  document.querySelectorAll(".conn-row").forEach(row => {
    const name = row.dataset.conn;
    row.classList.toggle("open", expandedConns.has(name));
    row.querySelector(".conn-head").addEventListener("click", () => {
      if (expandedConns.has(name)) expandedConns.delete(name);
      else expandedConns.add(name);
      row.classList.toggle("open");
    });
  });

  // Expand/collapse a site by clicking its header (but not the toggle).
  document.querySelectorAll(".source-head").forEach(head => {
    head.addEventListener("click", ev => {
      if (ev.target.closest(".switch")) return;
      const row = head.closest(".source");
      const name = row.dataset.src;
      if (expandedSources.has(name)) expandedSources.delete(name);
      else expandedSources.add(name);
      row.classList.toggle("open");
    });
  });

  document.querySelectorAll("[data-source]").forEach(box => {
    box.addEventListener("change", async () => {
      try {
        await api("/api/settings", {method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({sources: {[box.dataset.source]: {enabled: box.checked}}})});
        toast((box.checked ? "Enabled " : "Disabled ") + box.dataset.source);
        box.closest(".switch").title = box.checked ? "Enabled" : "Disabled";
      } catch (e) { toast(e.message, true); box.checked = !box.checked; }
    });
  });

  renderLanguages("langs-movie", "movie_languages", o);
  renderLanguages("langs-tv", "tv_languages", o);
  renderLanguages("langs-anime", "anime_languages", o);

  const recent = $("recent");
  recent.innerHTML = (o.recent_additions && o.recent_additions.length)
    ? o.recent_additions.map(r =>
        `<li>${r.title}<span class="when">${fmtTime(r.at)}</span></li>`).join("")
    : '<li class="muted">Nothing yet.</li>';
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

const arrChoices = {radarr: null, sonarr: null};
const expandedSources = new Set();  // sites whose settings are shown (persists across re-renders)
const expandedConns = new Set();  // connections whose settings are shown (persists across re-renders)
const openLangs = new Set();  // language dropdowns currently open (persists across re-renders)
let lastOverview = null;

// Close any open language dropdown when clicking outside it.
document.addEventListener("click", ev => {
  if (!openLangs.size) return;
  if (ev.target.closest(".dropdown")) return;
  openLangs.clear();
  document.querySelectorAll(".dropdown").forEach(d => d.classList.remove("open"));
});

function optionInput(opt) {
  // Quality profile / root folder are dropdowns fed by the connected app's
  // API. Until that app is actually connected they stay disabled - no free
  // typing before the real options load.
  if (opt.select) {
    const app = opt.key.startsWith("sonarr") ? "sonarr" : "radarr";
    const choices = arrChoices[app];
    const current = String(opt.value ?? "");
    if (choices && choices.connected) {
      const values = opt.select === "profiles"
        ? choices.profiles.map(p => p.name) : choices.root_folders;
      const opts = [`<option value="">(auto: first)</option>`]
        .concat(values.map(v =>
          `<option value="${escapeHtml(v)}" ${v === current ? "selected" : ""}>${escapeHtml(v)}</option>`));
      if (current && !values.includes(current))
        opts.push(`<option value="${escapeHtml(current)}" selected>${escapeHtml(current)} (not found)</option>`);
      return `<label class="opt"><span>${escapeHtml(opt.label)}</span>
        <select data-opt="${opt.key}">${opts.join("")}</select>
        ${opt.description ? `<small>${escapeHtml(opt.description)}</small>` : ""}
      </label>`;
    }
    // Not connected yet: show current value read-only with a hint.
    const hint = arrConnecting(app)
      ? "connecting to " + app + "…"
      : "connect " + app + " to choose";
    return `<label class="opt"><span>${escapeHtml(opt.label)}</span>
      <input type="text" value="${escapeHtml(current)}" disabled placeholder="${hint}">
      <small>${hint}</small>
    </label>`;
  }
  const type = opt.type === "secret" ? "password"
             : (opt.type === "str" ? "text" : "number");
  const numberAttrs = type !== "number" ? "" :
    `step="${opt.type === "float" ? "0.1" : "1"}"` +
    (opt.min != null ? ` min="${opt.min}"` : "") +
    (opt.max != null ? ` max="${opt.max}"` : "");
  return `<label class="opt"><span>${escapeHtml(opt.label)}</span>
    <input type="${type}" data-opt="${opt.key}" ${numberAttrs}
           value="${escapeHtml(opt.value ?? "")}" autocomplete="off">
    ${opt.description ? `<small>${escapeHtml(opt.description)}</small>` : ""}
  </label>`;
}

const arrRetryTimers = {radarr: null, sonarr: null};
const arrFirstAttempt = {radarr: 0, sonarr: 0};
// Keep showing "connecting…" (not "failed") for this long while an app that
// is configured hasn't answered yet - covers a slow or still-starting
// Radarr/Sonarr so a transient timeout doesn't flash as a failure.
const ARR_GRACE_MS = 25000;

// true while we should still say "connecting…" rather than "connect failed".
function arrConnecting(app) {
  const ch = arrChoices[app];
  if (ch === null || ch === undefined) return true;      // first attempt in flight
  if (ch.connected || !ch.configured) return false;      // up, or nothing to wait for
  return (Date.now() - (arrFirstAttempt[app] || 0)) < ARR_GRACE_MS;
}

async function loadArrChoices(app, isRetry) {
  if (arrRetryTimers[app]) { clearTimeout(arrRetryTimers[app]); arrRetryTimers[app] = null; }
  if (!isRetry) {
    arrFirstAttempt[app] = Date.now();
    arrChoices[app] = null;                 // show "connecting…" on the first attempt
    if (lastOverview) render(lastOverview);
  }
  let result;
  try { result = await api("/api/arr/" + app + "/choices"); }
  catch (e) {
    result = {configured: true, connected: false, error: "unreachable",
              profiles: [], root_folders: []};
  }
  arrChoices[app] = result;
  const active = document.activeElement;
  if (lastOverview && !(active && active.dataset && active.dataset.opt))
    render(lastOverview);
  // Configured but not up yet (still starting, slow, wrong port): keep polling
  // so it flips to "connected" on its own once it answers - no page reload.
  if (result.configured && !result.connected) {
    arrRetryTimers[app] = setTimeout(() => loadArrChoices(app, true), 4000);
  }
}

function wireOptionInputs() {
  document.querySelectorAll("[data-opt]").forEach(input => {
    input.addEventListener("change", async () => {
      try {
        await api("/api/settings", {method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({options: {[input.dataset.opt]: input.value}})});
        toast("Saved");
        // A changed URL or API key invalidates the profile/folder dropdowns
        const conn = input.dataset.opt.match(/^(radarr|sonarr)_(url|api_key)$/);
        if (conn) loadArrChoices(conn[1]); else refresh();
      } catch (e) { toast(e.message, true); }
    });
  });
}

function renderConnState(app, configured) {
  const el = $(app + "-state");
  if (!configured) {
    el.innerHTML = '<span class="dot"></span>not configured';
    el.className = "state off";
    return;
  }
  const ch = arrChoices[app];
  if (ch && ch.connected) {
    el.innerHTML = '<span class="dot"></span>connected';
    el.className = "state ok";
  } else if (arrConnecting(app)) {
    el.innerHTML = '<span class="dot"></span>connecting…';
    el.className = "state connecting";
  } else {
    el.innerHTML = '<span class="dot"></span>connect failed'
      + (ch && ch.error ? " — " + escapeHtml(ch.error) : "");
    el.className = "state err";
  }
}

function langSummary(options, selected) {
  const labels = options.filter(l => selected.has(l.code)).map(l => l.label);
  return labels.length ? labels.join(", ") : "All languages";
}

function renderLanguages(elementId, settingKey, o) {
  const options = o.language_options;
  const selected = new Set(o.settings[settingKey] || []);
  const container = $(elementId);
  const isOpen = openLangs.has(settingKey);
  container.classList.toggle("open", isOpen);
  const summary = langSummary(options, selected);
  container.innerHTML = `
    <button type="button" class="dd-trigger">
      <span class="cur ${selected.size ? "" : "none"}">${escapeHtml(summary)}</span>
      <span class="caret">▾</span>
    </button>
    <div class="dd-panel">
      ${options.map(l => `
        <label class="dd-opt">
          <input type="checkbox" value="${l.code}" ${selected.has(l.code) ? "checked" : ""}>
          ${escapeHtml(l.label)}
        </label>`).join("")}
    </div>`;

  container.querySelector(".dd-trigger").addEventListener("click", () => {
    const nowOpen = !openLangs.has(settingKey);
    openLangs.clear();  // only one language dropdown open at a time
    if (nowOpen) openLangs.add(settingKey);
    document.querySelectorAll(".dropdown").forEach(d => d.classList.remove("open"));
    container.classList.toggle("open", nowOpen);
  });

  const cur = container.querySelector(".cur");
  container.querySelectorAll(".dd-panel input").forEach(box => {
    box.addEventListener("change", async () => {
      const codes = [...container.querySelectorAll(".dd-panel input:checked")].map(b => b.value);
      try {
        await api("/api/settings", {method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({[settingKey]: codes})});
        selected.clear(); codes.forEach(c => selected.add(c));
        cur.textContent = langSummary(options, selected);
        cur.classList.toggle("none", codes.length === 0);
        toast(codes.length ? "Languages: " + codes.join(", ") : "All languages");
      } catch (e) { toast(e.message, true); box.checked = !box.checked; }
    });
  });
}

async function refresh() {
  // Don't re-render while the user is typing in a settings field or has a
  // language dropdown open (a rebuild would close it mid-selection).
  const active = document.activeElement;
  if (active && active.dataset && active.dataset.opt) return;
  if (openLangs.size) return;
  try { render(await api("/api/overview")); }
  catch (e) { toast("Failed to load: " + e.message, true); }
}

// Masonry layout: distribute the section cards into N independent columns
// (N by window width). Re-runs only when the column count changes, so
// expanding/collapsing a card never reshuffles the others.
let cardEls = null;
let lastColCount = 0;
function columnsForWidth() {
  const w = window.innerWidth;
  return w >= 1200 ? 3 : w >= 720 ? 2 : 1;
}
function layoutMasonry(force) {
  const container = $("cards");
  if (!container) return;
  if (!cardEls) cardEls = Array.from(container.querySelectorAll(".card"));
  const n = columnsForWidth();
  if (!force && n === lastColCount) return;
  lastColCount = n;
  const gap = 20;

  const cols = [];
  for (let i = 0; i < n; i++) {
    const c = document.createElement("div"); c.className = "col";
    cols.push(c);
  }

  // One column: just stack every card in DOM order.
  if (n === 1) {
    cols[0].append(...cardEls);
    container.replaceChildren(cols[0]);
    return;
  }

  // Three columns: each card goes to its assigned column (data-col).
  if (n >= 3) {
    cardEls.forEach(card => {
      const col = Math.min(Number(card.dataset.col) || 0, n - 1);
      cols[col].appendChild(card);
    });
    container.replaceChildren(...cols);
    return;
  }

  // Two columns: keep the same card order but split the sequence in two at
  // the point that best balances height, so reading down column 1 then
  // column 2 follows the exact same order as one column. Measure each card
  // at its real column width first (a detached column reports offsetHeight
  // 0, which is why balancing used to fall back to round-robin).
  const colWidth = (container.clientWidth - (n - 1) * gap) / n;
  container.replaceChildren(...cardEls);
  container.style.display = "block";
  cardEls.forEach(c => { c.style.width = colWidth + "px"; });
  const measured = cardEls.map(c => c.getBoundingClientRect().height + gap);
  cardEls.forEach(c => { c.style.width = ""; });
  container.style.display = "";

  const total = measured.reduce((a, b) => a + b, 0);
  let prefix = 0, best = Infinity, split = 1;
  for (let k = 1; k < cardEls.length; k++) {
    prefix += measured[k - 1];
    const worst = Math.max(prefix, total - prefix);
    if (worst < best) { best = worst; split = k; }
  }
  cols[0].append(...cardEls.slice(0, split));
  cols[1].append(...cardEls.slice(split));
  container.replaceChildren(...cols);
}
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => layoutMasonry(false), 150);
});

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

refresh().then(() => {
  layoutMasonry(true);
  $("cards").style.visibility = "";
  loadArrChoices("radarr"); loadArrChoices("sonarr");
});
setInterval(refresh, 15000);
</script>
</body>
</html>
"""
