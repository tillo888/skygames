// Wiring: load metadata, connect modules, handle Score heat and navigation.
import { api } from "./api.js";
import { state, update, subscribe, defaults, signature, isStale } from "./state.js";
import { initSetup, renderSetup } from "./setup.js";
import { initRules, renderRules } from "./rules.js";
import { renderResults, renderStale, onSelectionChange } from "./results.js";
import { renderHeats, renderLocked } from "./heats.js";
import { renderCompetitions } from "./competitions.js";
import { toast, h } from "./dom.js";

let me = { admin: false, admin_enabled: false };
const LOCKED = { heats: "Saved heats" }; // future: results, competitions, challenge admin

function renderAccount() {
  const el = $("account");
  if (window.SKYGAMES_DEMO) { el.replaceChildren(); return; }
  el.replaceChildren(me.admin
    ? h("span", {}, h("span", {}, "Admin "), h("button", { type: "button", onclick: async () => { await api.logout(); await refreshMe(); showView(state.view === "competitions" ? "competitions" : "analyzer"); toast("Signed out"); } }, "Sign out"))
    : me.admin_enabled ? h("button", { type: "button", onclick: () => showView("heats") }, "Sign in") : "");
  document.querySelectorAll(".nav button").forEach((b) => {
    b.querySelector(".lock")?.remove();
    if (LOCKED[b.dataset.view] && !me.admin) b.append(h("span", { class: "lock", title: "Admins only",
      html: '<svg width="11" height="12" viewBox="0 0 11 12" aria-hidden="true"><rect x="1" y="5" width="9" height="6.5" rx="1.2" fill="currentColor"/><path d="M3 5V3.6a2.5 2.5 0 0 1 5 0V5" fill="none" stroke="currentColor" stroke-width="1.4"/></svg><span class="sr-only">admins only</span>' }));
  });
}

async function refreshMe() {
  try { me = await api.me(); } catch { me = { admin: false, admin_enabled: false }; }
  renderAccount();
}

const $ = (id) => document.getElementById(id);

function status(msg, isError = false) {
  const el = $("status");
  el.textContent = msg || "";
  el.classList.toggle("error", isError);
}

function renderButton() {
  const btn = $("analyze-btn");
  const saved = !!state.heatId;
  btn.disabled = state.busy || !state.files.length || (saved && !isStale());
  btn.textContent = state.busy ? "Scoring…" : saved ? (isStale() ? "Re-score heat" : "Scored") : "Score heat";
}

function loadPayload(payload) {
  update({
    payload, heatId: payload.heat.id, name: payload.heat.name, task: payload.task.key,
    ruleValues: { ...defaults(), ...payload.rules.values },
    files: payload.flyers.map((f) => ({ file_id: f.file_id, flyer: f.flyer, file_name: f.file_name, color: f.color, ok: f.ok })),
    selected: null,
  });
  update({ scoredSignature: signature() });
}

async function score() {
  update({ busy: true });
  status("Scoring…");
  try {
    let payload;
    if (state.heatId) {
      const flyers = Object.fromEntries(state.files.map((f) => [f.file_id, f.flyer]));
      payload = await api.rescore(state.heatId, { name: state.name, task: state.task, rule_values: state.ruleValues, flyers });
    } else {
      payload = await api.createHeat({ name: state.name || "Untitled heat", task: state.task, ruleValues: state.ruleValues, files: state.files });
    }
    loadPayload(payload);
    const w = payload.ranking.find((r) => r.rank === 1);
    status(`Scored in ${payload.analyzed_ms} ms and saved.`);
    if (w) toast(`${w.flyer} wins ${payload.task.label.toLowerCase()}`);
  } catch (e) {
    status(e.message, true);
  } finally {
    update({ busy: false });
  }
}

function newHeat() {
  update({ heatId: null, payload: null, name: "", files: [], selected: null, scoredSignature: null, ruleValues: defaults() });
  status("");
  showView("analyzer");
}

async function openHeat(id) {
  showView("analyzer");
  status("Loading…");
  try { loadPayload(await api.getHeat(id)); status(""); }
  catch (e) { status(e.message, true); }
}

function showView(v) {
  update({ view: v });
  $("view-analyzer").hidden = v !== "analyzer";
  $("view-heats").hidden = v !== "heats";
  $("view-competitions").hidden = v !== "competitions";
  document.querySelector(".sidebar").hidden = v !== "analyzer";
  document.querySelector(".layout").style.gridTemplateColumns = v === "analyzer" ? "" : "1fr";
  document.querySelectorAll(".nav button").forEach((b) => b.setAttribute("aria-current", b.dataset.view === v ? "page" : "false"));
  if (LOCKED[v] && !me.admin) {
    renderLocked($(`view-${v}`), { title: LOCKED[v], adminEnabled: me.admin_enabled,
      onSignedIn: async () => { await refreshMe(); toast("Signed in"); showView(v); } });
    return;
  }
  if (v === "heats") renderHeats({ onOpen: openHeat });
  if (v === "competitions") renderCompetitions({ admin: me.admin });
}

async function init() {
  initSetup();
  initRules();
  $("analyze-btn").addEventListener("click", score);
  $("new-heat").addEventListener("click", newHeat);
  document.querySelectorAll(".nav button").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

  subscribe((s, patch) => {
    const keys = Object.keys(patch);
    if (keys.length === 1 && keys[0] === "selected") { onSelectionChange(); return; }
    if (patch._typing) { renderButton(); renderStale(); return; }
    if (!(keys.length === 1 && keys[0] === "name")) renderSetup();
    if (!keys.every((k) => k === "busy" || k === "name")) renderRules();
    renderButton();
    if ("payload" in patch) renderResults(); else renderStale();
    document.querySelector(".main").classList.toggle("busy", s.busy);
  });

  await refreshMe();
  try {
    const meta = await api.meta();
    update({ meta, ruleValues: Object.fromEntries(meta.params.map((p) => [p.path, p.default])),
             task: meta.tasks.some((t) => t.key === "distance") ? "distance" : meta.tasks[0]?.key });
  } catch (e) {
    status(`Can't reach the SkyGames server: ${e.message}`, true);
    return;
  }
  if (window.SKYGAMES_DEMO) {
    $("demo-badge").hidden = false;
    loadPayload(window.SKYGAMES_DEMO.payload);
    status("Preview: scoring and uploads need the SkyGames server.");
  } else {
    const id = new URLSearchParams(location.search).get("heat");
    if (id) openHeat(id);
    else if (location.hash === "#competitions") showView("competitions");
  }
}

init();
