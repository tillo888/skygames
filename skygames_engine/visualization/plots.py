"""PNG renderers (matplotlib, headless). Single-axis panels only: altitude,
speeds and glide each get their own y-axis panel sharing the time axis,
replacing v3.9's three overlaid y-axes, which were hard to read."""
from __future__ import annotations

import io
from typing import Dict, List

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, MUTED, GRID, BAND = "#1f1f1e", "#6b6a64", "#e4e3de", "#2a78d6"
SPEED_COLORS = {"h_kph": "#2a78d6", "v_kph": "#eb6834", "total_kph": "#6250d6"}
SPEED_LABELS = {"h_kph": "Horizontal", "v_kph": "Vertical", "total_kph": "Total"}


def _style(ax):
    ax.grid(True, color=GRID, linewidth=0.8)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.label.set_color(MUTED)
    ax.xaxis.label.set_color(MUTED)


def _png(fig, dpi) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def profile_png(flyer: str, s: dict, dpi: int = 160, glide_ylim=(0, 2)) -> bytes:
    t = s["t_s"]
    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(10, 8), sharex=True,
                                     gridspec_kw={"height_ratios": [2, 2, 1]})
    for ax in (a1, a2, a3):
        _style(ax)
        if s["window"]:
            ax.axvspan(*s["window"], color=BAND, alpha=0.08, linewidth=0)
    a1.plot(t, s["alt_ft"], color=INK, linewidth=2)
    a1.set_ylabel("Altitude (ft)")
    if s["window"]:
        a1.text(s["window"][0], a1.get_ylim()[1], " scoring window", va="top", fontsize=8, color=MUTED)
    for k in ("h_kph", "v_kph", "total_kph"):
        a2.plot(t, s[k], color=SPEED_COLORS[k], linewidth=2, label=SPEED_LABELS[k])
        mx = s["max"].get(k)
        if mx:
            a2.plot([mx["t_s"]], [mx["value"]], "o", color=SPEED_COLORS[k], markersize=6,
                    markeredgecolor="white", markeredgewidth=1.5)
            a2.annotate(f"max {SPEED_LABELS[k].lower()} {mx['value']:.0f}", (mx["t_s"], mx["value"]),
                        xytext=(6, 6), textcoords="offset points", fontsize=8, color=INK)
    a2.set_ylabel("Speed (km/h)")
    a2.legend(loc="lower right", frameon=False, fontsize=8, ncol=3)
    g = [None if v is None else min(max(v, glide_ylim[0]), glide_ylim[1]) for v in s["glide"]]
    a3.plot(t, g, color="#1baf7a", linewidth=2)
    a3.set_ylim(*glide_ylim)
    a3.set_ylabel("Glide ratio")
    if s["max"].get("glide"):
        mg = s["max"]["glide"]
        a3.annotate(f"max {mg['value']:.2f}", (mg["t_s"], min(mg["value"], glide_ylim[1])),
                    xytext=(6, -12), textcoords="offset points", fontsize=8, color=INK)
    a3.set_xlabel("Time since exit (s)")
    fig.suptitle(f"{flyer} — exit to opening", x=0.01, ha="left", color=INK, fontsize=12)
    fig.tight_layout()
    return _png(fig, dpi)


def along_track_png(title: str, items: List[Dict], target_m=None, dpi: int = 160) -> bytes:
    """items: {flyer, color, linestyle, series (along_track_series), speed_dt_s?}"""
    fig, ax = plt.subplots(figsize=(12, 6))
    _style(ax)
    for it in items:
        s = it["series"]
        if not s or not s["s_m"]:
            continue
        c = it["color"]
        lbl = it["flyer"] + (f" · {it['speed_dt_s']:.2f} s" if it.get("speed_dt_s") is not None else "")
        ax.plot(s["s_m"], s["alt_ft"], color=c, linestyle=it.get("linestyle", "-"), linewidth=2, label=lbl)
        for key, mk in (("s_A", "o"), ("s_B", "o"), ("s_open", "s")):
            x = s[key]
            if s["s_m"][0] <= x <= s["s_m"][-1]:
                y = float(np.interp(x, s["s_m"], s["alt_ft"]))
                ax.plot([x], [y], mk, color=c, markersize=7, markeredgecolor="white", markeredgewidth=1.5)
        if target_m and it.get("speed_dt_s") is not None:
            x = s["s_A"] + target_m
            if s["s_m"][0] <= x <= s["s_m"][-1]:
                y = float(np.interp(x, s["s_m"], s["alt_ft"]))
                ax.plot([x], [y], "X", color=c, markersize=9, markeredgecolor="white")
    ax.set_xlabel("Horizontal distance from exit along A→B (m)")
    ax.set_ylabel("Altitude (ft)")
    ax.set_title(title, loc="left", color=INK)
    ax.legend(loc="upper right", frameon=False, fontsize=9, ncol=2,
              title="● window top/bottom   ■ opening" + (f"   ✕ {target_m:g} m mark" if target_m else ""), title_fontsize=8)
    fig.tight_layout()
    return _png(fig, dpi)
