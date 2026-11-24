// Results view: header + downloads, leaderboard, map, side view, profile, notes.
import { h, fmt, fmtScore, UNIT_LABEL } from "./dom.js";
import { state, update, isStale } from "./state.js";
import { api } from "./api.js";
import { lineChart } from "./charts.js";
import { trackMap } from "./map.js";

const SPEED_KEYS = ["h_kph", "v_kph", "total_kph"];
const speedStyle = (color) => ({
  h_kph: { name: "Horizontal", color, dash: null, width: 2.5 },
  v_kph: { name: "Vertical", color: "#4b5b72", dash: "6 4", width: 2 },
  total_kph: { name: "Total", color: "#13233b", dash: "1.5 3.5", width: 2 },
});
let handles = { map: null, charts: [], side: null, profile: [] };
let refs = {};

function interp(xs, ys, x) {
  if (!xs.length || x < xs[0] || x > xs[xs.length - 1]) return null;
  let i = xs.findIndex((v) => v >= x);
  if (i <= 0) return ys[0];
  const t = (x - xs[i - 1]) / (xs[i] - xs[i - 1] || 1);
  return ys[i - 1] + t * (ys[i] - ys[i - 1]);
}

export function renderResults() {
  const host = document.getElementById("results");
  const empty = document.getElementById("empty-state");
  [...handles.charts, ...handles.profile].forEach((c) => c.destroy()); handles.map?.destroy();
  handles = { map: null, charts: [], side: null, profile: [] };
  const p = state.payload;
  empty.hidden = !!p;
  host.hidden = !p;
  if (!p) { host.replaceChildren(); return; }

  const unit = p.task.unit;
  const byName = Object.fromEntries(p.flyers.map((f) => [f.flyer, f]));
  const okFlyers = p.flyers.filter((f) => f.ok);
  const sel = state.selected && byName[state.selected]?.ok ? state.selected : null;

  refs = { p, byName, okFlyers, stale: h("div", { class: "banner stale", hidden: true },
    "Rules, discipline or names changed since these results. Press Re-score heat to update."),
    profile: h("div") };
  refs.profile.append(profilePanel(p, byName, defaultFlyer(sel)));
  host.replaceChildren(header(p), refs.stale, leaderboard(p, unit, byName, sel), mapPanel(p, sel),
    sideView(p, okFlyers, sel), refs.profile, notesPanel(p));
  renderStale();
}

function defaultFlyer(sel) {
  const { p, okFlyers } = refs;
  return sel || p.ranking.find((r) => r.rank === 1)?.flyer || okFlyers[0]?.flyer;
}

export function renderStale() {
  if (refs.stale) refs.stale.hidden = !isStale();
}

function header(p) {
  const when = new Date(p.heat.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  const dl = (kind, label, primary) => {
    const url = api.downloadUrl(p.heat.id, kind);
    return url ? h("a", { class: "btn small" + (primary ? "" : ""), href: url, download: "" }, label)
      : h("button", { class: "btn small", disabled: true, title: "Available when running the SkyGames server" }, label);
  };
  return h("div", { class: "results-head" },
    h("div", {}, h("h1", {}, p.heat.name),
      h("div", { class: "sub" }, `${p.task.label} · ${p.flyers.length} flyer${p.flyers.length > 1 ? "s" : ""} · ${when} · rules ${p.rules.version}`)),
    h("div", { class: "downloads" }, dl("kml", "Google Earth (KML)", true), dl("zip", "All files (ZIP)"), dl("geojson", "GeoJSON"), dl("json", "Results JSON")));
}

function leaderboard(p, unit, byName, sel) {
  const ul = UNIT_LABEL[unit] || unit;
  const rows = p.ranking;
  const lead = rows.find((r) => r.rank === 1);
  const second = rows.find((r) => r.rank === 2);
  const best = lead?.score;
  const windRank = Object.fromEntries((p.ranking_wind || []).map((r) => [r.flyer, r]));
  const hasWind = !!p.ranking_wind;

  let top;
  if (lead) {
    const f = byName[lead.flyer];
    const ties = rows.filter((r) => r.rank === 1).map((r) => r.flyer);
    const facts = [];
    if (second) facts.push(`${fmtScore(second.behind_leader, unit)} ${ul} ${p.task.rank === "asc" ? "faster than" : "ahead of"} ${second.flyer}`);
    if (f.summary.window_time_s) facts.push(`${fmt(f.summary.window_time_s, 1)} s in the window`);
    if (f.summary.max_glide) facts.push(`max glide ${fmt(f.summary.max_glide, 2)}`);
    top = h("div", { class: "board-lead" },
      h("div", { class: "place" }, ties.length > 1 ? `Tied for first: ${ties.join(", ")}` : "Winner"),
      h("div", { class: "who" }, h("span", { class: "swatch", style: { background: f.color } }), lead.flyer),
      h("div", { class: "score" }, fmtScore(lead.score, unit), h("small", {}, ul)),
      h("div", { class: "facts" }, facts.map((t) => h("span", {}, t))));
  } else {
    top = h("div", { class: "board-lead" }, h("div", { class: "place" }, "No valid scores in this heat"),
      h("div", { class: "who" }, "Check the notes below"));
  }

  const head = h("tr", {}, h("th", {}, "#"), h("th", {}, "Flyer"), h("th", {}, `${p.task.label} (${ul})`),
    h("th", {}, "Behind"), hasWind ? h("th", {}, "Wind removed") : null,
    h("th", { class: "opt" }, "In window"), h("th", { class: "opt" }, "Max horiz."), h("th", { class: "opt" }, "Max glide"),
    h("th", { class: "opt" }, "Opening"));

  const body = rows.map((r) => {
    const f = byName[r.flyer];
    const sm = f?.summary || {};
    const frac = r.score != null && best ? (p.task.rank === "asc" ? best / r.score : r.score / best) : 0;
    const flags = [...(r.quality_flags || [])];
    const w = windRank[r.flyer];
    const tr = h("tr", { "data-flyer": r.flyer, "aria-selected": String(sel === r.flyer), tabindex: f?.ok ? "0" : "-1",
      onclick: () => f?.ok && update({ selected: sel === r.flyer ? null : r.flyer }),
      onkeydown: (e) => { if (e.key === "Enter" && f?.ok) update({ selected: sel === r.flyer ? null : r.flyer }); } },
      h("td", { class: "rank" }, r.rank ?? "–"),
      h("td", { class: "flyer" }, h("div", { class: "wrap" }, h("span", { class: "swatch", style: { background: f?.color || "#d6dee8" } }), r.flyer),
        flags.map((fl) => h("span", { class: "flag" }, fl))),
      r.score != null
        ? h("td", { class: "scorecell" }, fmtScore(r.score, unit), h("span", { class: "bar" }, h("i", { style: { width: `${Math.round(frac * 100)}%`, background: f.color } })))
        : h("td", { class: "dnf", colspan: hasWind ? 7 : 6 }, `Not scored: ${r.reason || "no valid jump"}`),
    );
    if (r.score != null) {
      tr.append(...[
        h("td", { class: "muted" }, r.rank === 1 ? "–" : `${fmtScore(r.behind_leader, unit)}`),
        hasWind ? h("td", {}, w?.score != null ? `${fmtScore(w.score, unit)} (#${w.rank})` : "–") : null,
        h("td", { class: "opt" }, sm.window_time_s ? `${fmt(sm.window_time_s, 1)} s` : "–"),
        h("td", { class: "opt" }, `${fmt(sm.max_h_kph, 1)} km/h`),
        h("td", { class: "opt" }, fmt(sm.max_glide, 2)),
        h("td", { class: "opt" }, `${fmt(sm.opening_alt_ft)} ft`)].filter(Boolean));
    }
    return tr;
  });
  return h("section", { class: "board", "aria-label": "Leaderboard" }, top,
    h("div", { class: "table-scroll" }, h("table", {}, h("thead", {}, head), h("tbody", {}, body))),
    hasWind ? h("div", { class: "panel-body wind-note" }, "Wind removed: scores recomputed relative to the air mass using model winds aloft. Official ranking uses GPS scores.") : null);
}

function mapPanel(p, sel) {
  const body = h("div");
  const panel = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Top view"), h("span", { class: "aside" }, "Exit to opening. Click a path to focus that flyer.")),
    h("div", { style: { marginTop: "12px" } }, body));
  queueMicrotask(() => {
    handles.map = trackMap(body, { jumps: p.map, selected: sel, task: p.task.key, onSelect: (name) => update({ selected: name }) });
  });
  return panel;
}

function sideView(p, okFlyers, sel) {
  const series = [], markers = [];
  const target = p.task.key === "speed_course" ? p.rules.values["tasks.speed_course.target_distance_m"] : null;
  for (const f of okFlyers) {
    const a = p.charts.along_track[f.flyer];
    if (!a) continue;
    series.push({ name: f.flyer, color: f.color, x: a.s_m, y: a.alt_ft });
    for (const [key, shape] of [["s_A", "circle"], ["s_B", "circle"], ["s_open", "square"]]) {
      markers.push({ series: f.flyer, color: f.color, shape, x: a[key], y: interp(a.s_m, a.alt_ft, a[key]) });
    }
    const sc = f.scores.speed_course;
    if (target && sc?.valid) {
      const x = a.s_A + target;
      markers.push({ series: f.flyer, color: f.color, shape: "x", x, y: interp(a.s_m, a.alt_ft, x) });
    }
  }
  const top = p.rules.values["window.top_ft"], bot = p.rules.values["window.bottom_ft"];
  const chartHost = h("div");
  const legend = h("div", { class: "legend" }, okFlyers.map((f) => h("span", {}, h("i", { style: { borderColor: f.color } }), f.flyer)),
    h("span", {}, "● window top and bottom"), h("span", {}, "■ opening"), target ? h("span", {}, "✕ speed course finish") : null);
  const sec = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Side view"), h("span", { class: "aside" }, `Altitude against distance flown along each flyer's A→B line. Window ${fmt(top)}–${fmt(bot)} ft.`)),
    h("div", { class: "panel-body" }, chartHost), legend);
  queueMicrotask(() => handles.charts.push(handles.side = lineChart(chartHost, {
    height: 340, series, markers, highlight: sel, tooltipAll: true,
    xTitle: "Horizontal distance from exit along A→B (m)", yTitle: "Altitude (ft)",
    xFmt: (v) => fmt(v), yFmt: (v) => fmt(v), valueFmt: (v) => `${fmt(v)} ft`, tipTitle: (x) => `${fmt(x)} m from exit`,
    ariaLabel: "Altitude versus horizontal distance for each flyer",
  })));
  return sec;
}

function profilePanel(p, byName, flyer) {
  const f = byName[flyer];
  const chips = h("div", { class: "chips", role: "group", "aria-label": "Flyer" },
    p.flyers.filter((x) => x.ok).map((x) => h("button", { class: "chip", type: "button", "aria-pressed": String(x.flyer === flyer),
      onclick: () => update({ selected: x.flyer }) }, h("span", { class: "swatch", style: { background: x.color } }), x.flyer)));
  const sec = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Speed profile"), h("span", { class: "aside" }, "Exit to opening. Hatched band is the scoring window."), h("div", { class: "tools" }, chips)));
  if (!f) return sec;
  const pr = p.charts.profiles[flyer];
  const sm = f.summary;
  const sc = f.scores[p.task.key];
  const unit = p.task.unit;
  const stat = (v, u, k) => h("div", { class: "stat" }, h("div", { class: "v" }, v, u ? h("small", {}, u) : null), h("div", { class: "k" }, k));
  const stats = h("div", { class: "profile-stats" },
    stat(sc?.valid ? fmtScore(sc.score, unit) : "–", UNIT_LABEL[unit], p.task.label),
    p.task.key === "max_horizontal_speed" ? null : stat(fmt(pr.max.h_kph?.value, 1), "km/h", "Max horizontal"),
    stat(fmt(pr.max.v_kph?.value, 1), "km/h", "Max vertical"),
    stat(fmt(pr.max.total_kph?.value, 1), "km/h", "Max total"),
    stat(fmt(pr.max.glide?.value, 2), "", "Max glide"),
    stat(fmt(sm.freefall_time_s, 1), "s", "Freefall"),
    stat(fmt(sm.exit_alt_ft), "ft", "Exit"),
    stat(fmt(sm.opening_alt_ft), "ft", "Opening"));
  const hosts = [h("div"), h("div"), h("div")];
  const SP = speedStyle(f.color);
  const legend = h("div", { class: "legend", style: { padding: "0 0 4px" } },
    SPEED_KEYS.map((k) => h("span", {}, h("i", { style: { borderColor: SP[k].color, borderTopStyle: SP[k].dash ? (k === "total_kph" ? "dotted" : "dashed") : "solid" } }), SP[k].name)),
    h("span", {}, h("i", { class: "hatch" }), "scoring window"));
  sec.append(h("div", { class: "panel-body" }, stats, legend, hosts[0], hosts[1], hosts[2]));

  const band = pr.window ? [[pr.window[0], pr.window[1]]] : [];
  const charts = [];
  const sync = (x) => charts.forEach((c) => c.setHover(x));
  const tFmt = (x) => `${fmt(x, 1)} s after exit`;
  queueMicrotask(() => {
    const mk = (key) => pr.max[key] ? [{ x: pr.max[key].t_s, y: pr.max[key].value, color: SP[key].color, label: `max ${fmt(pr.max[key].value)}` }] : [];
    charts.push(lineChart(hosts[0], {
      height: 250, bands: band, onHover: sync, tipTitle: tFmt, yTitle: "Speed (km/h)", yMin: 0,
      series: SPEED_KEYS.map((k) => ({ ...SP[k], x: pr.t_s, y: pr[k] })),
      markers: [...mk("h_kph"), ...mk("v_kph"), ...mk("total_kph")], valueFmt: (v) => `${fmt(v, 1)} km/h`,
      ariaLabel: `Horizontal, vertical and total speed for ${flyer}`,
    }));
    charts.push(lineChart(hosts[1], {
      height: 170, bands: band, onHover: sync, tipTitle: tFmt, yTitle: "Altitude (ft)",
      series: [{ name: "Altitude", color: "#13233b", x: pr.t_s, y: pr.alt_ft }], valueFmt: (v) => `${fmt(v)} ft`,
    }));
    charts.push(lineChart(hosts[2], {
      height: 170, bands: band, onHover: sync, tipTitle: tFmt, yTitle: "Glide ratio", xTitle: "Time since exit (s)",
      yMin: 0, yMax: Math.min(3, Math.max(1, Math.ceil((pr.max.glide?.value || 1) * 4) / 4 + 0.25)),
      series: [{ name: "Glide", color: "#1baf7a", x: pr.t_s, y: pr.glide }], valueFmt: (v) => fmt(v, 2),
      markers: pr.max.glide ? [{ x: pr.max.glide.t_s, y: pr.max.glide.value, color: "#1baf7a", label: `max ${fmt(pr.max.glide.value, 2)}` }] : [],
    }));
    handles.profile.push(...charts);
  });
  return sec;
}

function notesPanel(p) {
  const items = [];
  for (const f of p.flyers) {
    if (f.error) items.push([f.flyer, `${f.error.message}${f.error.hint ? " " + f.error.hint : ""}`]);
    for (const w of f.warnings || []) items.push([f.flyer, w]);
  }
  if (!items.length) return null;
  return h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Data notes")),
    h("div", { class: "panel-body" }, h("ul", { class: "notes" }, items.map(([who, t]) => h("li", {}, h("span", { class: "who" }, who), h("span", {}, t))))));
}

export function onSelectionChange() {
  // update in place so the map keeps its pan/zoom
  if (!state.payload || !refs.p) return;
  const sel = state.selected && refs.byName[state.selected]?.ok ? state.selected : null;
  handles.map?.select(sel);
  handles.side?.update({ highlight: sel });
  document.querySelectorAll(".board tbody tr").forEach((tr) => {
    tr.setAttribute("aria-selected", String(!!sel && tr.dataset.flyer === sel));
  });
  handles.profile.forEach((c) => c.destroy()); handles.profile = [];
  refs.profile.replaceChildren(profilePanel(refs.p, refs.byName, defaultFlyer(sel)));
}
