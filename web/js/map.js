// Top-view map: satellite tiles (Esri World Imagery) + SVG flight paths.
// No map library; Web Mercator math is ~20 lines. Works without internet
// (tracks still draw on a plain background).
import { h, s, fmt } from "./dom.js";

const TILE = 256;
const TILE_URL = (z, x, y) => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${y}/${x}`;
const AB = "#e34948";

const wx = (lon, z) => (lon + 180) / 360 * TILE * 2 ** z;
const wy = (lat, z) => { const r = lat * Math.PI / 180; return (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * TILE * 2 ** z; };

export function trackMap(host, { jumps, selected = null, onSelect = () => {}, task }) {
  const el = h("div", { class: "map", tabindex: "0", "aria-label": "Map of freefall paths. Drag to pan, scroll to zoom." });
  const tiles = h("div", { class: "tiles" });
  const svg = s("svg", { class: "overlay" });
  const demo = !!window.SKYGAMES_DEMO; // preview page: remote imagery is blocked there
  const plainPref = demo || (() => { try { return localStorage.getItem("sg-map-plain") === "1"; } catch { return false; } })();
  if (plainPref) el.classList.add("plain");
  const modeBtn = h("button", { class: "wide", type: "button", onclick: () => toggleMode() }, plainPref ? "Satellite" : "Plain");
  const controls = h("div", { class: "map-controls" },
    h("button", { type: "button", "aria-label": "Zoom in", onclick: () => zoomBy(0.5) }, "+"),
    h("button", { type: "button", "aria-label": "Zoom out", onclick: () => zoomBy(-0.5) }, "−"),
    h("button", { type: "button", "aria-label": "Fit all flyers", title: "Fit all flyers", onclick: () => { fit(); render(); } }, "⤢"),
    demo ? null : modeBtn);
  const legend = h("div", { class: "map-legend" },
    h("div", { class: "row" }, h("span", { class: "ab" }), "Straight line A→B (window top to bottom)"),
    h("div", { class: "row" }, svgIcon("circle"), "Exit"), h("div", { class: "row" }, svgIcon("square"), "Opening"),
    task === "speed_course" ? h("div", { class: "row" }, svgIcon("x"), "Speed course finish") : null);
  el.append(...[tiles, svg, controls, legend, demo ? null : h("div", { class: "map-attrib" }, "Imagery © Esri, Maxar, Earthstar Geographics")].filter(Boolean));
  host.replaceChildren(el);

  let z = 14, cx = 0, cy = 0; // centre in world px at zoom z
  let sel = selected;

  function toggleMode() {
    const plain = el.classList.toggle("plain");
    modeBtn.textContent = plain ? "Satellite" : "Plain";
    try { localStorage.setItem("sg-map-plain", plain ? "1" : "0"); } catch { /* storage blocked */ }
    render();
  }

  function bounds() {
    let a = 90, b = -90, c = 180, d = -180;
    for (const j of jumps) j.track.lat.forEach((la, i) => {
      const lo = j.track.lon[i];
      if (la < a) a = la; if (la > b) b = la; if (lo < c) c = lo; if (lo > d) d = lo;
    });
    return { s: a, n: b, w: c, e: d };
  }

  function fit() {
    const W = el.clientWidth || 800, H = el.clientHeight || 480;
    const bb = bounds();
    let best = 3;
    for (let zz = 19; zz >= 3; zz -= 0.25) {
      const dx = wx(bb.e, zz) - wx(bb.w, zz), dy = wy(bb.s, zz) - wy(bb.n, zz);
      if (dx < W - 120 && dy < H - 110) { best = zz; break; }
    }
    z = best;
    cx = (wx(bb.e, z) + wx(bb.w, z)) / 2;
    cy = (wy(bb.s, z) + wy(bb.n, z)) / 2;
  }

  function zoomBy(dz, ax = null, ay = null) {
    const W = el.clientWidth, H = el.clientHeight;
    const nz = Math.min(19, Math.max(3, z + dz));
    const k = 2 ** (nz - z);
    const px = ax ?? W / 2, py = ay ?? H / 2;
    const wxp = cx - W / 2 + px, wyp = cy - H / 2 + py; // world point under cursor
    cx = wxp * k - px + W / 2; cy = wyp * k - py + H / 2; z = nz;
    render();
  }

  function render() {
    const W = el.clientWidth, H = el.clientHeight;
    const ox = cx - W / 2, oy = cy - H / 2;
    const P = (lat, lon) => [wx(lon, z) - ox, wy(lat, z) - oy];

    // tiles
    if (!el.classList.contains("plain")) {
      const tz = Math.min(19, Math.floor(z)), scale = 2 ** (z - tz), size = TILE * scale;
      const n = 2 ** tz;
      const x0 = Math.floor(ox / size), x1 = Math.floor((ox + W) / size), y0 = Math.floor(oy / size), y1 = Math.floor((oy + H) / size);
      const imgs = [];
      for (let tx = x0; tx <= x1; tx++) for (let ty = y0; ty <= y1; ty++) {
        if (ty < 0 || ty >= n) continue;
        const img = h("img", { alt: "", src: TILE_URL(tz, ((tx % n) + n) % n, ty), draggable: "false" });
        img.onerror = () => { img.style.visibility = "hidden"; };
        Object.assign(img.style, { left: `${tx * size - ox}px`, top: `${ty * size - oy}px`, width: `${size}px`, height: `${size}px` });
        imgs.push(img);
      }
      tiles.replaceChildren(...imgs);
    }

    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("width", W); svg.setAttribute("height", H);
    const plain = el.classList.contains("plain");
    const layers = { halo: s("g"), lines: s("g"), ab: s("g"), marks: s("g"), labels: s("g") };
    const order = [...jumps].sort((a, b) => (a.flyer === sel) - (b.flyer === sel)); // selected on top
    for (const j of order) {
      const dim = sel && sel !== j.flyer;
      const pts = j.track.lat.map((la, i) => P(la, j.track.lon[i]).map((v) => v.toFixed(1)).join(",")).join(" ");
      if (!plain) layers.halo.append(s("polyline", { points: pts, fill: "none", stroke: "#fff", "stroke-opacity": dim ? 0.15 : 0.55, "stroke-width": sel === j.flyer ? 7 : 5.5, "stroke-linejoin": "round" }));
      const line = s("polyline", { points: pts, fill: "none", stroke: j.color, "stroke-width": sel === j.flyer ? 4.5 : 3, "stroke-linejoin": "round", "stroke-linecap": "round", opacity: dim ? 0.35 : 1, style: "cursor:pointer" });
      line.addEventListener("click", (e) => { e.stopPropagation(); onSelect(j.flyer); });
      line.append(s("title", {}, j.flyer));
      layers.lines.append(line);
      // hit area
      const hit = s("polyline", { points: pts, fill: "none", stroke: "transparent", "stroke-width": 14, style: "cursor:pointer" });
      hit.addEventListener("click", (e) => { e.stopPropagation(); onSelect(j.flyer); });
      layers.lines.append(hit);

      const n = j.track.lat.length - 1;
      const [ex, ey] = P(j.track.lat[0], j.track.lon[0]);
      const [qx, qy] = P(j.track.lat[n], j.track.lon[n]);
      const op = dim ? 0.35 : 1;
      layers.marks.append(s("circle", { cx: ex, cy: ey, r: 5.5, fill: "#fff", stroke: j.color, "stroke-width": 3, opacity: op }));
      layers.marks.append(s("rect", { x: qx - 5.5, y: qy - 5.5, width: 11, height: 11, fill: j.color, stroke: "#fff", "stroke-width": 2, opacity: op }));
      layers.labels.append(s("text", { class: "map-label", x: qx + 10, y: qy + 4, opacity: op }, j.flyer));

      if (j.A && j.B) {
        const [ax, ay] = P(j.A.lat, j.A.lon), [bx, by] = P(j.B.lat, j.B.lon);
        layers.ab.append(s("line", { x1: ax, y1: ay, x2: bx, y2: by, stroke: "#fff", "stroke-width": 4.5, "stroke-opacity": dim ? 0.2 : 0.8 }));
        layers.ab.append(s("line", { x1: ax, y1: ay, x2: bx, y2: by, stroke: AB, "stroke-width": 2.5, "stroke-dasharray": "7 5", opacity: dim ? 0.35 : 1 }));
        for (const [px, py] of [[ax, ay], [bx, by]]) layers.marks.append(s("circle", { cx: px, cy: py, r: 4, fill: AB, stroke: "#fff", "stroke-width": 1.5, opacity: op }));
        if (j.distance_m != null && (!sel || sel === j.flyer)) {
          const mx = (ax + bx) / 2, my = (ay + by) / 2;
          const ang = Math.atan2(by - ay, bx - ax) * 180 / Math.PI;
          const rot = ang > 90 || ang < -90 ? ang + 180 : ang;
          layers.labels.append(s("text", { class: "map-label", x: mx, y: my - 7, "text-anchor": "middle", transform: `rotate(${rot.toFixed(1)} ${mx} ${my})` }, `${fmt(j.distance_m, 1)} m`));
        }
      }
      if (j.speed_mark) {
        const [sx, sy] = P(j.speed_mark.lat, j.speed_mark.lon);
        layers.marks.append(s("path", { d: `M${sx - 6} ${sy - 6}L${sx + 6} ${sy + 6}M${sx + 6} ${sy - 6}L${sx - 6} ${sy + 6}`, stroke: "#fff", "stroke-width": 5, "stroke-linecap": "round", opacity: op }));
        layers.marks.append(s("path", { d: `M${sx - 6} ${sy - 6}L${sx + 6} ${sy + 6}M${sx + 6} ${sy - 6}L${sx - 6} ${sy + 6}`, stroke: j.color, "stroke-width": 3, "stroke-linecap": "round", opacity: op }));
      }
    }
    svg.replaceChildren(layers.halo, layers.lines, layers.ab, layers.marks, layers.labels);
  }

  // pan + zoom
  let drag = null;
  el.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".map-controls, .map-legend")) return;
    drag = { x: e.clientX, y: e.clientY, cx, cy, moved: false };
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) { drag.moved = true; el.classList.add("dragging"); }
    cx = drag.cx - dx; cy = drag.cy - dy; render();
  });
  el.addEventListener("pointerup", (e) => {
    const was = drag; drag = null; el.classList.remove("dragging");
    if (was && !was.moved && e.target === svg) onSelect(null);
  });
  el.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = el.getBoundingClientRect();
    zoomBy(e.deltaY < 0 ? 0.5 : -0.5, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  el.addEventListener("dblclick", (e) => { const r = el.getBoundingClientRect(); zoomBy(1, e.clientX - r.left, e.clientY - r.top); });
  el.addEventListener("keydown", (e) => {
    const step = 80, k = e.key;
    if (k === "+" || k === "=") zoomBy(0.5); else if (k === "-") zoomBy(-0.5);
    else if (k.startsWith("Arrow")) { cx += k === "ArrowRight" ? step : k === "ArrowLeft" ? -step : 0; cy += k === "ArrowDown" ? step : k === "ArrowUp" ? -step : 0; render(); }
    else return;
    e.preventDefault();
  });

  const ro = new ResizeObserver(() => render());
  ro.observe(el);
  requestAnimationFrame(() => { fit(); render(); });
  fit(); render();

  return {
    select: (name) => { sel = name; render(); },
    destroy: () => ro.disconnect(),
  };
}

function svgIcon(kind) {
  const c = "#13233b";
  const inner = kind === "circle" ? s("circle", { cx: 7, cy: 7, r: 4.5, fill: "#fff", stroke: c, "stroke-width": 2.5 })
    : kind === "square" ? s("rect", { x: 2.5, y: 2.5, width: 9, height: 9, fill: c })
    : s("path", { d: "M3 3L11 11M11 3L3 11", stroke: c, "stroke-width": 2.5, "stroke-linecap": "round" });
  return s("svg", { width: 14, height: 14, viewBox: "0 0 14 14" }, inner);
}
