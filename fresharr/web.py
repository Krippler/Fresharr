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
                 "languages: %s; anime languages: %s",
                 snapshot["run_interval_days"],
                 ", ".join(n for n, e in snapshot["sources"].items() if e["enabled"])
                 or "none",
                 ", ".join(snapshot["languages"]) or "all",
                 ", ".join(snapshot["anime_languages"]) or "all")
        return jsonify(snapshot)

    @app.post("/api/run")
    def run_now():
        if scheduler.running:
            return jsonify({"error": "A run is already in progress"}), 409
        scheduler.request_run()
        return jsonify({"requested": True})

    return app


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
  .cat { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em;
         color: #5f9c6d; margin-top: .8rem; }
  .cat:first-child { margin-top: 0; }
  .source { display: flex; align-items: center; gap: .9rem;
            padding: .6rem 0; border-top: 1px solid #232b34; }
  .cat + .source { border-top: none; }
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
  input[type=text], input[type=password], input[type=number] {
    font: inherit; background: #232b34; color: #dde3ea;
    border: 1px solid #333d49; border-radius: 7px; padding: .35rem .6rem;
    width: 100%; }
  .optgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
             gap: .6rem .8rem; margin-top: .5rem; }
  .opt { display: flex; flex-direction: column; gap: .2rem; }
  .opt > span { font-size: .75rem; color: #8b96a5; }
  .opt small { color: #6b7684; font-size: .72rem; }
  .conns { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
           gap: 1.2rem; }
  .conn h3 { font-size: .95rem; margin-bottom: .4rem; }
  .conn .state { font-size: .75rem; margin-left: .4rem; }
  .state.ok { color: #7bd88f; } .state.off { color: #6b7684; }
  .srcopts { margin-top: .4rem; }
  .srcopts .optgrid { margin-top: .2rem; }
  .langgroup { margin-top: .6rem; }
  .langgroup .k { color: #8b96a5; font-size: .75rem; text-transform: uppercase;
                  letter-spacing: .06em; display: block; margin-bottom: .4rem; }
  .langs { display: flex; flex-wrap: wrap; gap: .4rem; }
  .lang { border: 1px solid #333d49; border-radius: 99px; padding: .25rem .75rem;
          cursor: pointer; font-size: .85rem; color: #8b96a5; user-select: none; }
  .lang.on { background: #2f6b3d; border-color: #3a8049; color: #eafff0; }
  .lang input { display: none; }
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
      Runs happen at a <strong>random time</strong> around your chosen interval
      &mdash; never less than 18 hours apart &mdash; so the discovery sites
      aren't hit at one predictable hour. Daily is the most frequent schedule.
    </p>
  </div>

  <div class="card">
    <h2>Connections</h2>
    <p class="muted">Changes save as you leave each field and apply on the
      next run. Clear a field to fall back to the container's environment
      default.</p>
    <div class="conns">
      <div class="conn"><h3>Radarr <span class="muted">(movies)</span><span class="state" id="radarr-state"></span></h3>
        <div class="optgrid" id="conn-radarr"></div>
      </div>
      <div class="conn"><h3>Sonarr <span class="muted">(TV)</span><span class="state" id="sonarr-state"></span></h3>
        <div class="optgrid" id="conn-sonarr"></div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Discovery sites</h2>
    <div id="sources"></div>
  </div>

  <div class="card">
    <h2>Limits</h2>
    <div class="optgrid" id="general"></div>
  </div>

  <div class="card">
    <h2>Original language</h2>
    <p class="muted">
      Only add titles whose original language is selected. Nothing selected =
      all languages. Applies when a source reports the language (TMDB, Trakt,
      AniList, MyAnimeList); titles with unknown language always pass.
    </p>
    <div class="langgroup"><span class="k">Movies &amp; TV</span>
      <div class="langs" id="langs-main"></div>
    </div>
    <div class="langgroup"><span class="k">Anime</span>
      <div class="langs" id="langs-anime"></div>
    </div>
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

  const groups = new Map();
  o.sources.forEach(s => {
    if (!groups.has(s.category)) groups.set(s.category, []);
    groups.get(s.category).push(s);
  });
  $("sources").innerHTML = [...groups.entries()].map(([cat, list]) =>
    `<div class="cat">${cat}</div>` + list.map(s => `
    <div class="source">
      <div class="info">
        <span class="name">${s.label}</span>
        ${!s.configured ? `<span class="badge">needs ${s.requires.replaceAll("_", " ").toLowerCase()} below</span>` : ""}
        <div class="desc">${s.description}</div>
        <div class="srcopts"><div class="optgrid">
          ${s.options.map(optionInput).join("")}
        </div></div>
      </div>
      <label class="switch">
        <input type="checkbox" data-source="${s.name}"
               ${s.enabled ? "checked" : ""} ${!s.configured && !s.enabled ? "disabled" : ""}>
        <span class="slider"></span>
      </label>
    </div>`).join("")).join("");

  $("conn-radarr").innerHTML = o.connections.radarr.map(optionInput).join("");
  $("conn-sonarr").innerHTML = o.connections.sonarr.map(optionInput).join("");
  $("general").innerHTML = o.general_options.map(optionInput).join("");
  setState("radarr-state", o.arr.radarr);
  setState("sonarr-state", o.arr.sonarr);
  wireOptionInputs();

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

  renderLanguages("langs-main", "languages", o);
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

function optionInput(opt) {
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

function wireOptionInputs() {
  document.querySelectorAll("[data-opt]").forEach(input => {
    input.addEventListener("change", async () => {
      try {
        await api("/api/settings", {method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({options: {[input.dataset.opt]: input.value}})});
        toast("Saved");
        refresh();
      } catch (e) { toast(e.message, true); }
    });
  });
}

function setState(elementId, configured) {
  const el = $(elementId);
  el.textContent = configured ? "configured" : "not configured";
  el.className = "state " + (configured ? "ok" : "off");
}

function renderLanguages(elementId, settingKey, o) {
  const selected = new Set(o.settings[settingKey] || []);
  const container = $(elementId);
  container.innerHTML = o.language_options.map(l => `
    <label class="lang ${selected.has(l.code) ? "on" : ""}">
      <input type="checkbox" value="${l.code}" ${selected.has(l.code) ? "checked" : ""}>
      ${l.label}
    </label>`).join("");
  container.querySelectorAll("input").forEach(box => {
    box.addEventListener("change", async () => {
      const codes = [...container.querySelectorAll("input:checked")].map(b => b.value);
      try {
        await api("/api/settings", {method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({[settingKey]: codes})});
        box.closest(".lang").classList.toggle("on", box.checked);
        toast(codes.length ? "Languages: " + codes.join(", ") : "All languages");
      } catch (e) { toast(e.message, true); box.checked = !box.checked; }
    });
  });
}

async function refresh() {
  // Don't re-render while the user is typing in a settings field
  const active = document.activeElement;
  if (active && active.dataset && active.dataset.opt) return;
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
