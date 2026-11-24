// Small DOM + formatting helpers shared by every module.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const SVGNS = "http://www.w3.org/2000/svg";
export function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function fmt(v, digits = 0) {
  if (v === null || v === undefined || !isFinite(v)) return "–";
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export const UNIT_LABEL = { m: "m", s: "s", kph: "km/h" };
export const SCORE_DIGITS = { m: 1, s: 2, kph: 1 };

export function fmtScore(v, unit) {
  return fmt(v, SCORE_DIGITS[unit] ?? 1);
}

export function fmtBytes(n) {
  return n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`;
}

export function toast(msg, ms = 2600) {
  document.querySelectorAll(".toast").forEach((x) => x.remove());
  const t = h("div", { class: "toast", role: "status" }, msg);
  document.body.append(t);
  setTimeout(() => t.remove(), ms);
}

export function confirmDialog(title, text, okLabel = "Delete") {
  const d = document.getElementById("confirm");
  d.querySelector("#confirm-title").textContent = title;
  d.querySelector("#confirm-text").textContent = text;
  d.querySelector("#confirm-ok").textContent = okLabel;
  return new Promise((resolve) => {
    const done = (v) => { d.close(); resolve(v); };
    d.querySelector("#confirm-ok").onclick = () => done(true);
    d.querySelector("#confirm-cancel").onclick = () => done(false);
    d.oncancel = () => resolve(false);
    d.showModal();
  });
}

// binary search: index of the x value nearest to target in a sorted array
export function nearest(xs, target) {
  let lo = 0, hi = xs.length - 1;
  if (hi < 0) return -1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] < target) lo = mid; else hi = mid;
  }
  return Math.abs(xs[lo] - target) <= Math.abs(xs[hi] - target) ? lo : hi;
}
