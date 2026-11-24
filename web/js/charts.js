// Dependency-free SVG line chart: one y-axis, hatched scoring-window band,
// markers, end labels, and a crosshair tooltip. Charts can share a hover
// position through onHover / setHover (used to sync the profile panels).
import { s, h, nearest, fmt } from "./dom.js";

let uid = 0;

function niceTicks(min, max, count = 5) {
  if (!(max > min)) { max = min + 1; }
  const span = max - min;
  const step0 = span / count;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((st) => span / st <= count) || 10 * mag;
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

export function lineChart(host, opts) {
  const id = ++uid;
  const o = { height: 260, xFmt: (v) => fmt(v), yFmt: (v) => fmt(v), valueFmt: (v) => fmt(v), markers: [], bands: [], ...opts };
  const wrap = h("div", { class: "chart" });
  const tip = h("div", { class: "tooltip", hidden: true });
  host.replaceChildren(wrap);
  wrap.append(tip);
  let svg, geom, hoverX = null;

  function extent() {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const se of o.series) {
      se.x.forEach((xv, i) => {
        const yv = se.y[i];
        if (xv == null || yv == null) return;
        if (xv < x0) x0 = xv; if (xv > x1) x1 = xv;
        if (yv < y0) y0 = yv; if (yv > y1) y1 = yv;
      });
    }
    if (o.yMin !== undefined) y0 = o.yMin;
    if (o.yMax !== undefined) y1 = o.yMax;
    if (o.xMin !== undefined) x0 = o.xMin;
    const pad = (y1 - y0) * 0.06 || 1;
    return { x0, x1, y0: o.yMin !== undefined ? y0 : y0 - pad, y1: o.yMax !== undefined ? y1 : y1 + pad };
  }

  function render() {
    const W = Math.max(280, wrap.clientWidth || host.clientWidth || 600), H = o.height;
    const m = { l: 58, r: o.rightPad ?? 18, t: 12, b: o.xTitle ? 40 : 26 };
    const e = extent();
    const xt = niceTicks(e.x0, e.x1, Math.max(3, Math.round(W / 110)));
    const yt = niceTicks(e.y0, e.y1, Math.max(3, Math.round(H / 55)));
    const X = (v) => m.l + (v - e.x0) / (e.x1 - e.x0 || 1) * (W - m.l - m.r);
    const Y = (v) => H - m.b - (v - e.y0) / (e.y1 - e.y0 || 1) * (H - m.t - m.b);
    geom = { W, H, m, e, X, Y };

    svg = s("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img", "aria-label": o.ariaLabel || "" });
    svg.append(s("defs", {}, s("pattern", { id: `hatch${id}`, width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" },
      s("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "rgba(19,35,59,.16)", "stroke-width": 2 })),
      s("clipPath", { id: `clip${id}` }, s("rect", { x: m.l, y: m.t - 2, width: W - m.l - m.r, height: H - m.t - m.b + 4 }))));

    const grid = s("g", { class: "grid" });
    yt.forEach((v) => grid.append(s("line", { x1: m.l, x2: W - m.r, y1: Y(v), y2: Y(v) })));
    svg.append(grid);

    for (const [b0, b1, label] of o.bands) {
      svg.append(s("rect", { x: X(b0), y: m.t, width: Math.max(0, X(b1) - X(b0)), height: H - m.t - m.b, fill: `url(#hatch${id})` }));
      if (label) svg.append(s("text", { x: X(b0) + 6, y: m.t + 14, class: "label", style: "fill:#4b5b72" }, label));
    }

    const axis = s("g", { class: "axis" });
    yt.forEach((v) => axis.append(s("text", { x: m.l - 8, y: Y(v) + 4, "text-anchor": "end" }, o.yFmt(v))));
    xt.forEach((v) => axis.append(s("text", { x: X(v), y: H - m.b + 16, "text-anchor": "middle" }, o.xFmt(v))));
    axis.append(s("line", { x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b, stroke: "#d6dee8" }));
    if (o.xTitle) axis.append(s("text", { class: "axis-title", x: m.l + (W - m.l - m.r) / 2, y: H - 4, "text-anchor": "middle" }, o.xTitle));
    if (o.yTitle) axis.append(s("text", { class: "axis-title", x: -(m.t + (H - m.t - m.b) / 2), y: 14, transform: "rotate(-90)", "text-anchor": "middle" }, o.yTitle));
    svg.append(axis);

    const plot = s("g", { "clip-path": `url(#clip${id})` });
    for (const se of o.series) {
      let d = "", pen = false;
      se.x.forEach((xv, i) => {
        const yv = se.y[i];
        if (xv == null || yv == null) { pen = false; return; }
        d += (pen ? "L" : "M") + X(xv).toFixed(1) + " " + Y(yv).toFixed(1);
        pen = true;
      });
      const dim = o.highlight && o.highlight !== se.name;
      plot.append(s("path", { d, class: "series" + (dim ? " dim" : ""), stroke: se.color,
        "stroke-dasharray": se.dash || null, "stroke-width": o.highlight === se.name ? 3 : (se.width || 2) }));
    }
    svg.append(plot);

    for (const mk of o.markers) {
      if (mk.x == null || mk.y == null) continue;
      const dim = o.highlight && mk.series && o.highlight !== mk.series;
      const g = s("g", { opacity: dim ? 0.25 : 1 });
      const cx = X(mk.x), cy = Y(mk.y);
      if (mk.shape === "square") g.append(s("rect", { x: cx - 5, y: cy - 5, width: 10, height: 10, fill: mk.color, stroke: "#fff", "stroke-width": 2 }));
      else if (mk.shape === "x") g.append(s("path", { d: `M${cx - 5} ${cy - 5}L${cx + 5} ${cy + 5}M${cx + 5} ${cy - 5}L${cx - 5} ${cy + 5}`, stroke: mk.color, "stroke-width": 3, "stroke-linecap": "round" }));
      else g.append(s("circle", { cx, cy, r: 5, fill: mk.color, stroke: "#fff", "stroke-width": 2 }));
      if (mk.label) g.append(s("text", { class: "label", x: cx + 8, y: cy - 8 }, mk.label));
      svg.append(g);
    }

    const hover = s("g", { class: "hover", visibility: "hidden" });
    svg.append(hover);
    const hit = s("rect", { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: "transparent" });
    hit.addEventListener("pointermove", (ev) => {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width);
      const xv = e.x0 + (px - m.l) / (W - m.l - m.r) * (e.x1 - e.x0);
      drawHover(xv, true);
      o.onHover?.(xv);
    });
    hit.addEventListener("pointerleave", () => { drawHover(null); o.onHover?.(null); });
    svg.append(hit);
    wrap.querySelector("svg")?.remove();
    wrap.prepend(svg);
    if (hoverX !== null) drawHover(hoverX);
  }

  function drawHover(xv, showTip = false) {
    hoverX = xv;
    const hover = svg.querySelector(".hover");
    if (xv === null || xv < geom.e.x0 || xv > geom.e.x1) { hover.setAttribute("visibility", "hidden"); tip.hidden = true; return; }
    const { X, Y, m, H, W } = geom;
    hover.replaceChildren(s("line", { class: "crosshair", x1: X(xv), x2: X(xv), y1: m.t, y2: H - m.b }));
    const rows = [];
    for (const se of o.series) {
      if (o.highlight && o.highlight !== se.name && !o.tooltipAll) continue;
      if (!se.x.length || xv < se.x[0] - 1e-9 || xv > se.x[se.x.length - 1] + 1e-9) continue;
      const i = nearest(se.x, xv);
      const yv = se.y[i];
      if (yv == null) continue;
      hover.append(s("circle", { cx: X(se.x[i]), cy: Y(yv), r: 4.5, fill: se.color, stroke: "#fff", "stroke-width": 2 }));
      rows.push(h("div", { class: "row" }, h("span", { class: "sw", style: { background: se.color } }), se.name, h("b", {}, o.valueFmt(yv, se))));
    }
    hover.setAttribute("visibility", "visible");
    tip.replaceChildren(h("div", { class: "t" }, o.tipTitle ? o.tipTitle(xv) : o.xFmt(xv)), ...rows);
    tip.hidden = rows.length === 0;
    if (!tip.hidden) {
      const scale = wrap.clientWidth / W;
      const left = X(xv) * scale;
      const tw = tip.offsetWidth;
      tip.style.left = `${left + 14 + tw > wrap.clientWidth ? left - tw - 14 : left + 14}px`;
      tip.style.top = `${m.t + 4}px`;
    }
  }

  const ro = new ResizeObserver(() => render());
  ro.observe(wrap);
  render();
  return {
    setHover: (xv) => { if (svg) drawHover(xv); },
    update: (patch) => { Object.assign(o, patch); render(); },
    destroy: () => ro.disconnect(),
  };
}
