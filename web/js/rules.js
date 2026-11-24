// Rules form, generated from the server's parameter list (backend/rules_ui.py).
import { h, fmt } from "./dom.js";
import { state, update, defaults } from "./state.js";

export function initRules() {
  document.getElementById("reset-rules").addEventListener("click", () => update({ ruleValues: defaults() }));
}

function setValue(path, v) {
  update({ ruleValues: { ...state.ruleValues, [path]: v } });
}

function visible(p) {
  if (p.tasks && !p.tasks.includes(state.task)) return false;
  if (p.show_if) return Object.entries(p.show_if).every(([k, v]) => state.ruleValues[k] === v);
  return true;
}

function field(p) {
  const id = "rule-" + p.path.replace(/\W/g, "-");
  const v = state.ruleValues[p.path];
  const changed = JSON.stringify(v) !== JSON.stringify(p.default);
  const book = changed ? h("span", { class: "rulebook" }, `Rulebook: ${describe(p, p.default)}`) : null;
  const help = p.help ? h("span", { class: "help" }, p.help) : null;

  if (p.type === "toggle") {
    return h("div", { class: "field" + (changed ? " changed" : "") },
      h("label", { class: "toggle", for: id },
        h("input", { type: "checkbox", id, checked: !!v, onchange: (e) => setValue(p.path, e.target.checked) }),
        h("span", {}, p.label)),
      help, book);
  }
  let control;
  if (p.type === "select") {
    control = h("select", { id, onchange: (e) => setValue(p.path, e.target.value) },
      p.options.map(([val, label]) => h("option", { value: val, selected: val === v }, label)));
  } else {
    const inp = h("input", { type: "number", id, step: p.step ?? "any", min: p.min, placeholder: p.placeholder || "",
      value: v === null || v === undefined ? "" : v, inputmode: "decimal",
      onchange: (e) => {
        const raw = e.target.value.trim();
        if (raw === "") return setValue(p.path, p.nullable ? null : p.default);
        const n = Number(raw);
        if (Number.isFinite(n)) setValue(p.path, n);
      } });
    control = p.unit ? h("div", { class: "input-unit" }, inp, h("span", { class: "unit" }, p.unit)) : inp;
  }
  return h("div", { class: "field" + (changed ? " changed" : "") }, h("label", { for: id }, p.label), control, help, book);
}

function describe(p, v) {
  if (v === null || v === undefined) return p.placeholder || "off";
  if (p.type === "toggle") return v ? "on" : "off";
  if (p.type === "select") return (p.options.find(([k]) => k === v) || [, v])[1];
  return `${fmt(v, Number.isInteger(v) ? 0 : 1)}${p.unit ? " " + p.unit : ""}`;
}

export function renderRules() {
  const host = document.getElementById("rules-form");
  const params = (state.meta?.params || []).filter(visible);
  const groups = new Map();
  for (const p of params) {
    const key = (p.advanced ? "adv:" : "") + p.group;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  }
  const main = [], adv = [];
  for (const [key, ps] of groups) {
    const g = h("div", { class: "rule-group" }, h("h3", {}, ps[0].group), ps.map(field));
    (key.startsWith("adv:") ? adv : main).push(g);
  }
  const advChanged = params.filter((p) => p.advanced).some((p) => JSON.stringify(state.ruleValues[p.path]) !== JSON.stringify(p.default));
  const wasOpen = host.querySelector("details")?.open;
  const det = h("details", { class: "advanced", open: wasOpen || advChanged || null },
    h("summary", {}, advChanged ? "Detection and GPS quality (changed)" : "Detection and GPS quality"), adv);
  const active = document.activeElement?.id;
  host.replaceChildren(...main, det);
  if (active) document.getElementById(active)?.focus();
}
