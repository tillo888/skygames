# skygames_analyzer_app_v3_7.py
# Streamlit offline app for SkyGames freefall analysis (Version 3.7)
# - Robust exit/opening detection tuned to your latest data
# - Light gray theme across all widgets, darker buttons
# - Individual graphs (Exit→Opening) with vertical scoring-window band + max annotations
# - Combined "Altitude vs Along-Track Distance (Exit→Opening)" plot with window + 1 km mark for Speed
# - KML: per-flyer colored freefall paths; RED A→B line + distance annotation; 1 km mark with Δt for Speed
# - Event controls: Save (export ZIP), Import (ZIP), Clear (with confirmation + backup ZIP)
# - Database of heats and jumps with key metrics

import os
import io
import re
import json
import zipfile
import shutil
import tempfile
import sqlite3
import colorsys
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

# ----------------------------- Constants -----------------------------

FT_PER_M = 3.280839895
M_PER_FT = 1/FT_PER_M

WIN_TOP_FT = 11000.0
WIN_BOT_FT = 5000.0

FREEFALL_KPH = 100.0
FREEFALL_MS = FREEFALL_KPH / 3.6

OPEN_MIN_FT = 1500.0
OPEN_MAX_FT = 4500.0

SPEED_TARGET_M = 1000.0

CATEGORIES = [
    "Distance Qualifiers",
    "Speed Qualifiers",
    "Distance Heats",
    "Speed Heats",
]

# ----------------------------- UI Theme -----------------------------

st.set_page_config(page_title="SkyGames - Freefall Analyzer", layout="wide")
st.markdown("""
<style>
html, body, [data-testid="stAppViewContainer"] { background-color: #f2f2f2 !important; color: #000 !important; }
[data-testid="stSidebar"] { background-color: #ececec !important; color: #000 !important; }
h1, h2, h3, h4, h5, h6, p, label, span, div { color: #000 !important; }
.stTextInput input, .stNumberInput input, textarea, .stDateInput input, .stTimeInput input {
  background-color: #f7f7f7 !important; color: #000 !important; border: 1px solid #d0d0d0 !important;
}
[data-testid="stSelectbox"] > div, [data-testid="stMultiSelect"] > div {
  background-color: #f7f7f7 !important; color: #000 !important; border: 1px solid #d0d0d0 !important;
}
[data-baseweb="select"] * { color: #000 !important; }
[data-baseweb="popover"] { background-color: #ffffff !important; color: #000 !important; border: 1px solid #cfcfcf !important; }
[data-testid="stFileUploader"] { color: #000 !important; }
[data-testid="stFileUploaderDropzone"] {
  background-color: #f7f7f7 !important;
  border: 1px solid #d0d0d0 !important;
  color: #000 !important;
}
[data-testid="stFileUploader"] svg, [data-testid="stFileUploader"] svg * {
  fill: #000 !important; color: #000 !important;
}
[data-testid="stFileUploader"] button { background-color: #c8c8c8 !important; color: #000 !important; border: 1px solid #a6a6a6 !important; }
[data-testid="stFileUploader"] button:hover { background-color: #bfbfbf !important; }
.stButton > button, .stDownloadButton > button, button[kind="primary"] {
  background-color: #c8c8c8 !important; color: #000 !important; border: 1px solid #a6a6a6 !important;
}
.stButton > button:hover, .stDownloadButton > button:hover, button[kind="primary"]:hover { background-color: #bfbfbf !important; }
[data-baseweb="tab-list"] { background-color: #e6e6e6 !important; border-bottom: 1px solid #cfcfcf !important; }
[data-baseweb="tab"] { color: #000 !important; }
[data-testid="stTable"], [data-testid="stDataFrame"] { color: #000 !important; }
[data-testid="stDataFrame"] div[role="grid"] {
  background-color: #ffffff !important; color: #000 !important; border: 1px solid #b5b5b5 !important;
}
[data-testid="stDataFrame"] div[role="columnheader"],
[data-testid="stDataFrame"] thead tr th { background-color: #efefef !important; color: #000 !important; border-bottom: 1px solid #b5b5b5 !important; }
[data-testid="stDataFrame"] div[role="row"] { border-bottom: 1px solid #dcdcdc !important; }
[data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th { border-right: 1px solid #dcdcdc !important; }
[data-testid="stTable"] table { background-color: #ffffff !important; color: #000 !important; border: 1px solid #b5b5b5 !important; }
[data-testid="stTable"] th { background-color: #efefef !important; color: #000 !important; border-bottom: 1px solid #b5b5b5 !important; }
[data-testid="stTable"] td, [data-testid="stTable"] th { border-right: 1px solid #dcdcdc !important; }
</style>
""", unsafe_allow_html=True)

st.title("SkyGames - Freefall Analyzer (Offline)")
st.caption("Import a heat (multiple CSVs), analyze freefall, and save results locally.")

# ----------------------------- Colors -----------------------------

def distinct_colors(n: int):
    try:
        cmap = plt.get_cmap("tab20" if n > 10 else "tab10")
        return [cmap(i % cmap.N)[:3] for i in range(n)]
    except Exception:
        return [colorsys.hsv_to_rgb(i / max(1, n), 0.65, 0.95) for i in range(n)]

def rgb_to_kml_argb(rgb, alpha=255):
    r, g, b = [int(round(255.0 * x)) for x in rgb]
    return f"{alpha:02x}{b:02x}{g:02x}{r:02x}"

# ----------------------------- DB -----------------------------

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def db_conn(path="skygames.db"):
    return sqlite3.connect(path, check_same_thread=False)

def db_init(conn):
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS heats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        category TEXT,
        uploaded_at TEXT
    )""")
    c.execute("""
    CREATE TABLE IF NOT EXISTS jumps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        heat_id INTEGER,
        flyer_name TEXT,
        file_name TEXT,
        max_glide REAL,
        straight_dist_window_m REAL,
        time_to_1000m_s REAL,
        max_horizontal_kph REAL,
        opening_alt_ft REAL,
        exit_time_utc TEXT,
        opening_time_utc TEXT,
        kml_path TEXT,
        indiv_plot_path TEXT,
        FOREIGN KEY (heat_id) REFERENCES heats(id)
    )""")
    conn.commit()

# ----------------------------- Geo/Math -----------------------------

def haversine_m(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2
    R = 6371000.0
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi/2.0)**2 + cos(phi1) * cos(phi2) * sin(dlambda/2.0)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def ll_to_local_m(lat0, lon0, lat, lon):
    from math import radians, cos
    R = 6371000.0
    x = R * (np.radians(lon - lon0)) * cos(np.radians(lat0))
    y = R * np.radians(lat - lat0)
    return x, y

# ----------------------------- Analysis -----------------------------

def load_clean_csv(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(file_bytes))
    df.columns = [c.strip() for c in df.columns]
    mask_units = (df['lat'].astype(str).str.contains(r'(deg)', na=False)) | (df['time'].isna())
    df = df.loc[~mask_units].copy()
    df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    for c in ['lat','lon','hMSL','velN','velE','velD']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['time','lat','lon','hMSL']).sort_values('time').reset_index(drop=True)
    df['alt_m'] = df['hMSL']
    df['alt_ft'] = df['alt_m'] * FT_PER_M
    df['spd_horiz_ms'] = np.sqrt(df['velN']**2 + df['velE']**2)
    df['vs_down'] = df['velD']  # positive down
    df['glide'] = df['spd_horiz_ms'] / np.maximum(np.abs(df['vs_down']), 0.5)
    df['spd_horiz_kph'] = df['spd_horiz_ms'] * 3.6
    df['vs_down_kph'] = df['vs_down'] * 3.6
    df['spd_total_kph'] = np.sqrt(df['spd_horiz_ms']**2 + df['vs_down']**2) * 3.6
    return df

def smooth_series(s, sec, times):
    if len(s) < 3:
        return s.copy()
    t = (times.view('int64') / 1e9).astype(float)
    dt = np.median(np.diff(t))
    win = max(1, int(round(sec / max(dt, 1e-3))))
    return s.rolling(win, center=True, min_periods=max(1, win // 2)).median()

def detect_exit(df):
    """
    EXIT near peak altitude using smoothed vertical speed (positive = down):
    - Must cross >=100 kph down (27.78 m/s) and sustain ~0.6 s
    - In the previous ~6 s, require either: (a) any near-zero segment (<= 5 m/s, for >=0.3 s), OR (b) a rapid dv/dt ramp (> 8 m/s^2 over ~0.4-0.5 s)
    - Pick the earliest valid point after peak altitude
    """
    vs = smooth_series(df['vs_down'], 0.5, df['time']).astype(float)
    gl = smooth_series(df['glide'], 0.5, df['time']).astype(float)
    alt = smooth_series(df['alt_m'], 0.5, df['time']).astype(float)
    t = (df['time'].view('int64')/1e9).astype(float)

    idx_peak = int(vs.index[np.nanargmax(alt.values)])
    N = len(df)

    def sustained(i, thr=100/3.6, dur=0.6):
        t0 = t[i]; j=i
        while j < N and (t[j]-t0) < dur:
            if vs.iloc[j] < thr: return False
            j += 1
        return True

    best = None; best_score = None
    for i in range(idx_peak+1, N):
        if vs.iloc[i] >= (100/3.6) and sustained(i, thr=100/3.6, dur=0.6):
            # check near-zero in last 6 s
            tstart = t[i] - 6.0
            j2 = i
            near_ok = False
            # criterion (a): near-zero for >=0.3 s
            run = None
            while j2>0 and t[j2] >= tstart:
                if vs.iloc[j2] <= (5/3.6):
                    if run is None: run = j2_start = j2
                    if (t[j2_start] - t[j2]) >= 0.3:
                        near_ok = True; break
                else:
                    run = None
                j2 -= 1
            # criterion (b): ramp rate
            if not near_ok:
                k = i
                while k>0 and (t[i]-t[k]) < 0.5:
                    k -= 1
                if t[i] > t[k]:
                    dv = vs.iloc[i] - vs.iloc[k]
                    if dv / (t[i]-t[k]) > 8.0:
                        near_ok = True
            if not near_ok: 
                continue

            score = (i - idx_peak) + 0.1*max(gl.iloc[i], 0)
            if best is None or score < best_score:
                best, best_score = i, score

    if best is not None:
        return int(best)

    # Fallback: first time after peak reaching 100 kph down
    for i in range(idx_peak+1, N):
        if vs.iloc[i] >= (100/3.6):
            return int(i)
    return None

def detect_opening(df, start_idx):
    """
    Opening = first time descending where:
    - Altitude within 1500-4500 ft
    - Vertical speed drops below 100 kph down (27.78 m/s) and is sustained for >= 1.5 s
    - Immediately before (last ~3 s), the vertical speed was >= 100 kph down at least once
    """
    if start_idx is None: return None
    vs = smooth_series(df['vs_down'], 0.6, df['time']).astype(float)
    alt_ft = (smooth_series(df['alt_m'], 0.6, df['time']) * FT_PER_M).astype(float)
    t = (df['time'].view('int64')/1e9).astype(float)
    N = len(df)

    THR = 100/3.6
    for i in range(start_idx+1, N):
        if OPEN_MIN_FT <= alt_ft.iloc[i] <= OPEN_MAX_FT and vs.iloc[i] < THR:
            # sustain
            t0 = t[i]; j=i; ok=True
            while j < N and (t[j]-t0)<1.5:
                if not (OPEN_MIN_FT <= alt_ft.iloc[j] <= OPEN_MAX_FT and vs.iloc[j] < THR*1.05):
                    ok=False; break
                j += 1
            if not ok: 
                continue
            # prior high-speed evidence
            tstart = t[i] - 3.0
            k=i; was_fast=False
            while k>start_idx and t[k] >= tstart:
                if vs.iloc[k] >= THR:
                    was_fast=True; break
                k -= 1
            if not was_fast:
                continue
            return int(i)
    return None

def interpolate_crossing_time(df, start_idx, end_idx, target_ft):
    target_m = target_ft * M_PER_FT
    for i in range(start_idx, end_idx):
        a1 = df.loc[i, 'alt_m']; a2 = df.loc[i+1, 'alt_m']
        if a1 >= target_m and a2 < target_m:
            t1 = df.loc[i, 'time'].value
            t2 = df.loc[i+1, 'time'].value
            w = (a1 - target_m) / (a1 - a2) if a1 != a2 else 0.0
            t_cross = pd.to_datetime(int(t1 + w*(t2 - t1)), unit='ns', utc=True)
            lat = float(df.loc[i,'lat'] + w*(df.loc[i+1,'lat']-df.loc[i,'lat']))
            lon = float(df.loc[i,'lon'] + w*(df.loc[i+1,'lon']-df.loc[i,'lon']))
            return {'time': t_cross, 'lat': lat, 'lon': lon, 'alt_m': float(target_m)}, i
    return None, None

def find_window_points(df, ei, oi):
    p11, i11 = interpolate_crossing_time(df, ei, oi, WIN_TOP_FT)
    p5 , i5  = interpolate_crossing_time(df, ei, oi, WIN_BOT_FT)
    return p11, p5

# ----------------------------- Along-AB Series -----------------------------

def series_from_exit_to_open(df, pA, pB, exit_time, open_time):
    """Project samples from EXIT->OPEN onto A->B direction. Return seg with s_rel, alt_ft,
       and distances (s_A_rel, s_B_rel, s_open_rel)."""
    if pA is None or pB is None or exit_time is None or open_time is None:
        return pd.DataFrame(columns=['time','s_rel','alt_ft']), None, None, None
    # Unit direction along A->B
    lat0, lon0 = pA['lat'], pA['lon']
    Ax, Ay = 0.0, 0.0
    Bx, By = ll_to_local_m(lat0, lon0, pB['lat'], pB['lon'])
    AB = np.array([Bx - Ax, By - Ay])
    L = np.linalg.norm(AB)
    if L <= 0:
        return pd.DataFrame(columns=['time','s_rel','alt_ft']), None, None, None
    ABu = AB / L

    # Helper: project any lat/lon to along-track s (meters) from A
    def s_from_latlon(lat, lon):
        x, y = ll_to_local_m(lat0, lon0, float(lat), float(lon))
        return float(np.dot(np.array([x - Ax, y - Ay]), ABu))

    # Samples Exit->Open
    seg_eo = df[(df['time'] >= exit_time) & (df['time'] <= open_time)][['time','lat','lon','alt_ft']].copy()
    if seg_eo.empty:
        return pd.DataFrame(columns=['time','s_rel','alt_ft']), None, None, None

    # Closest samples to exit/open
    exit_row = df.iloc[(df['time']-exit_time).abs().argsort()[:1]].iloc[0]
    open_row = df.iloc[(df['time']-open_time).abs().argsort()[:1]].iloc[0]

    s_exit = s_from_latlon(exit_row['lat'], exit_row['lon'])
    s_open = s_from_latlon(open_row['lat'], open_row['lon'])
    s_A = s_from_latlon(pA['lat'], pA['lon'])
    s_B = s_from_latlon(pB['lat'], pB['lon'])

    s_vals = [s_from_latlon(r['lat'], r['lon']) - s_exit for _, r in seg_eo.iterrows()]
    seg_eo = seg_eo.assign(s_rel=s_vals).sort_values('time').reset_index(drop=True)

    s_A_rel = s_A - s_exit
    s_B_rel = s_B - s_exit
    s_open_rel = s_open - s_exit

    seg_eo = seg_eo[(seg_eo['s_rel'] >= 0) & (seg_eo['s_rel'] <= s_open_rel + 1e-6)]
    return seg_eo[['time','s_rel','alt_ft']], float(s_A_rel), float(s_B_rel), float(s_open_rel)

# ----------------------------- Plotting -----------------------------

def figure_individual(df, flyer, exit_time, open_time, t11, t5, output_path):
    d = df[(df['time']>=exit_time) & (df['time']<=open_time)].copy()
    d['t_sec'] = (d['time'] - exit_time).dt.total_seconds()
    d_win = d[(d['time']>=t11) & (d['time']<=t5)].copy() if (t11 and t5 and t5>t11) else d.copy()

    def idxmax(series): return int(series.idxmax()) if not series.empty else None
    idx_g = idxmax(d_win['glide']); idx_h = idxmax(d_win['spd_horiz_kph']); idx_v = idxmax(d_win['vs_down_kph']); idx_t = idxmax(d_win['spd_total_kph'])

    fig, ax = plt.subplots(figsize=(10,6))
    ax.grid(True, which='major', linestyle='-'); ax.minorticks_on(); ax.grid(True, which='minor', linestyle=':', alpha=0.5)
    ax.plot(d['t_sec'], d['alt_ft']); ax.set_xlabel('Time (s)'); ax.set_ylabel('Altitude (ft)')
    if t11 and t5 and t5>t11: x1=(t11-exit_time).total_seconds(); x2=(t5-exit_time).total_seconds(); ax.axvspan(x1, x2, alpha=0.15)

    ax2=ax.twinx(); ax2.plot(d['t_sec'], d['spd_horiz_kph'], label='H kph'); ax2.plot(d['t_sec'], d['vs_down_kph'], label='V kph'); ax2.plot(d['t_sec'], d['spd_total_kph'], label='Total kph'); ax2.set_ylabel('Speed (kph)')
    ax3=ax.twinx(); ax3.spines["right"].set_position(("axes", 1.1)); ax3.plot(d['t_sec'], np.clip(d['glide'],0,2), label='Glide'); ax3.set_ylim(0,2); ax3.set_ylabel('Glide ratio')

    def ann(df_, idx, ax_, val, txt):
        if idx is None: return
        row=df_.loc[idx]; x=(row['time']-exit_time).total_seconds(); ax_.scatter([x],[val], s=30, zorder=5); ax_.annotate(txt,(x,val),xytext=(5,10),textcoords='offset points',arrowprops=dict(arrowstyle='->'))
    if not d_win.empty:
        if idx_g is not None: rg=d_win.loc[idx_g]; ann(d_win, idx_g, ax3, np.clip(rg['glide'],0,2), f"Max Glide {rg['glide']:.2f}")
        if idx_h is not None: rh=d_win.loc[idx_h]; ann(d_win, idx_h, ax2, rh['spd_horiz_kph'], f"Max H {rh['spd_horiz_kph']:.1f} kph")
        if idx_v is not None: rv=d_win.loc[idx_v]; ann(d_win, idx_v, ax2, rv['vs_down_kph'], f"Max V {rv['vs_down_kph']:.1f} kph")
        if idx_t is not None: rt=d_win.loc[idx_t]; ann(d_win, idx_t, ax2, rt['spd_total_kph'], f"Max Total {rt['spd_total_kph']:.1f} kph")
    ax.set_title(f"{flyer} - Exit to Opening"); plt.tight_layout(); fig.savefig(output_path, dpi=160); plt.close(fig)

def figure_alt_vs_along(along_map, sA_map, sB_map, sOpen_map, heat_title, flyer_colors, speed_marks, output_path):
    fig, ax = plt.subplots(figsize=(12,6))
    ax.grid(True, which='major', linestyle='-'); ax.minorticks_on(); ax.grid(True, which='minor', linestyle=':', alpha=0.5)

    for flyer, seg in along_map.items():
        if seg is None or seg.empty: 
            continue
        c = flyer_colors.get(flyer, None)
        ax.plot(seg['s_rel'], seg['alt_ft'], label=f"{flyer}", color=c)

        sA = sA_map.get(flyer); sB = sB_map.get(flyer); sO = sOpen_map.get(flyer)
        if isinstance(sA, (float,int)):
            yA = float(np.interp(sA, seg['s_rel'], seg['alt_ft'])) if (seg['s_rel'].min()<=sA<=seg['s_rel'].max()) else 11000.0
            ax.scatter([sA], [yA], color=c, s=40, zorder=5); ax.annotate("Entry (11k ft)", (sA, yA), xytext=(6,6), textcoords="offset points")
        if isinstance(sB, (float,int)):
            yB = float(np.interp(sB, seg['s_rel'], seg['alt_ft'])) if (seg['s_rel'].min()<=sB<=seg['s_rel'].max()) else 5000.0
            ax.scatter([sB], [yB], color=c, s=40, zorder=5); ax.annotate("Exit (5k ft)", (sB, yB), xytext=(6,6), textcoords="offset points")
        if isinstance(sO, (float,int)):
            yO = float(np.interp(sO, seg['s_rel'], seg['alt_ft'])) if (seg['s_rel'].min()<=sO<=seg['s_rel'].max()) else seg['alt_ft'].iloc[-1]
            ax.scatter([sO], [yO], color=c, s=30, marker='s', zorder=5); ax.annotate("Opening", (sO, yO), xytext=(6,6), textcoords="offset points")

        sm = speed_marks.get(flyer)
        if sm and isinstance(sA, (float,int)):
            x1k = sA + 1000.0
            if seg['s_rel'].min() <= x1k <= seg['s_rel'].max():
                y1k = float(np.interp(x1k, seg['s_rel'], seg['alt_ft']))
                ax.scatter([x1k], [y1k], color=c, s=50, marker='x', zorder=6)
                dt = sm.get('dt_s')
                label = "1 km" + (f" (Δt={dt:.2f}s)" if isinstance(dt,(float,int)) else "")
                ax.annotate(label, (x1k, y1k), xytext=(8,10), textcoords="offset points", arrowprops=dict(arrowstyle='->'))

    ax.set_xlabel("Horizontal distance from EXIT along A→B (m)"); ax.set_ylabel("Altitude (ft)"); ax.set_title(f"Altitude vs Along-Track Distance (Exit→Opening) - {heat_title}")
    ax.legend(loc="best", ncol=2); plt.tight_layout(); fig.savefig(output_path, dpi=160); plt.close(fig)

# ----------------------------- KML -----------------------------

def kml_coord_line(df): return "\n".join([f"{r.lon},{r.lat},{r.alt_m}" for _, r in df.iterrows()])

def build_kml(heat_name, per_flyer_segments, per_flyer_window_pts, output_path, flyer_colors, dist_labels, speed_marks):
    parts = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>')
    parts.append('<kml xmlns="http://www.opengis.net/kml/2.2">')
    parts.append('<Document>')
    parts.append(f"<name>{heat_name} - Freefall Tracks (Exit to Opening)</name>")
    parts.append("<description>Per-flyer colored freefall paths; window markers; straight-line distance; speed 1000 m marks.</description>")

    parts.append('<Style id="ab-line">')
    parts.append('<LineStyle><color>ff0000ff</color><width>4</width></LineStyle>')
    parts.append('<IconStyle><color>ff0000ff</color></IconStyle>')
    parts.append('<LabelStyle><color>ff0000ff</color></LabelStyle>')
    parts.append('</Style>')

    for flyer in per_flyer_segments.keys():
        rgb = flyer_colors.get(flyer, (1.0,1.0,1.0))
        kml_col = f"{int(255):02x}{int(255*rgb[2]):02x}{int(255*rgb[1]):02x}{int(255*rgb[0]):02x}"
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", flyer)
        parts.append(f"<Style id=\"line-{safe_id}\">")
        parts.append(f"<LineStyle><color>{kml_col}</color><width>4</width></LineStyle>")
        parts.append(f"<IconStyle><color>{kml_col}</color></IconStyle>")
        parts.append(f"<LabelStyle><color>{kml_col}</color></LabelStyle>")
        parts.append("</Style>")

    for flyer, seg in per_flyer_segments.items():
        p11, p5 = per_flyer_window_pts.get(flyer, (None, None))
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", flyer)
        parts.append(f"<Folder><name>{flyer}</name>")

        parts.append("<Placemark>"); parts.append(f"<name>{flyer} freefall</name>"); parts.append(f"<styleUrl>#line-{safe_id}</styleUrl>")
        parts.append("<LineString><tessellate>1</tessellate><coordinates>")
        parts.append(kml_coord_line(seg))
        parts.append("</coordinates></LineString></Placemark>")

        parts.append("<Placemark>"); parts.append(f"<name>{flyer} EXIT</name>"); parts.append(f"<styleUrl>#line-{safe_id}</styleUrl>")
        parts.append(f"<Point><coordinates>{seg.iloc[0].lon},{seg.iloc[0].lat},{seg.iloc[0].alt_m}</coordinates></Point></Placemark>")
        parts.append("<Placemark>"); parts.append(f"<name>{flyer} OPENING</name>"); parts.append(f"<styleUrl>#line-{safe_id}</styleUrl>")
        parts.append(f"<Point><coordinates>{seg.iloc[-1].lon},{seg.iloc[-1].lat},{seg.iloc[-1].alt_m}</coordinates></Point></Placemark>")

        if p11 and p5:
            parts.append("<Placemark>"); parts.append(f"<name>{flyer} window start (11000 ft)</name>"); parts.append(f"<styleUrl>#line-{safe_id}</styleUrl>")
            parts.append(f"<Point><coordinates>{p11['lon']},{p11['lat']},{p11['alt_m']}</coordinates></Point></Placemark>")
            parts.append("<Placemark>"); parts.append(f"<name>{flyer} window end (5000 ft)</name>"); parts.append(f"<styleUrl>#line-{safe_id}</styleUrl>")
            parts.append(f"<Point><coordinates>{p5['lon']},{p5['lat']},{p5['alt_m']}</coordinates></Point></Placemark>")

            dist_m = dist_labels.get(flyer)
            if dist_m is None:
                try: dist_m = float(haversine_m(p11['lat'], p11['lon'], p5['lat'], p5['lon']))
                except Exception: dist_m = None

            name_txt = f"{flyer} A→B straight-line" + (f" ({dist_m:.1f} m)" if isinstance(dist_m, (float,int)) else "")
            parts.append("<Placemark>"); parts.append(f"<name>{name_txt}</name>"); parts.append(f"<styleUrl>#ab-line</styleUrl>")
            parts.append("<LineString><tessellate>1</tessellate><coordinates>")
            parts.append(f"{p11['lon']},{p11['lat']},{p11['alt_m']}")
            parts.append(f"{p5['lon']},{p5['lat']},{p5['alt_m']}")
            parts.append("</coordinates></LineString></Placemark>")

            if isinstance(dist_m, (float,int)):
                mid_lat = (p11['lat'] + p5['lat'])/2.0; mid_lon = (p11['lon'] + p5['lon'])/2.0; mid_alt = (p11['alt_m'] + p5['alt_m'])/2.0
                parts.append("<Placemark>"); parts.append(f"<name>A→B distance: {dist_m:.1f} m</name>"); parts.append(f"<styleUrl>#ab-line</styleUrl>")
                parts.append(f"<Point><coordinates>{mid_lon},{mid_lat},{mid_alt}</coordinates></Point>")
                parts.append("</Placemark>")

        sm = speed_marks.get(flyer)
        if sm:
            dt = sm.get('dt_s'); dt_txt = f" (Δt={dt:.2f} s)" if isinstance(dt,(float,int)) else ""
            parts.append("<Placemark>"); parts.append(f"<name>{flyer} 1000 m mark{dt_txt}</name>"); parts.append(f"<styleUrl>#line-{safe_id}</styleUrl>")
            parts.append(f"<Point><coordinates>{sm['lon']},{sm['lat']},{sm.get('alt_m', 0)}</coordinates></Point>")
            parts.append("</Placemark>")

        parts.append("</Folder>")

    parts.append("</Document></kml>")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

# ----------------------------- App -----------------------------

def ensure_outputs_dir(heat_name: str):
    out_root = os.path.join("outputs", heat_name.replace(" ", "_"))
    ensure_dir(out_root)
    return out_root

def connect_ready_db():
    conn = db_conn()
    db_init(conn)
    return conn

conn = connect_ready_db()
tab_upload, tab_heats = st.tabs(["➕ Import Heat", "📊 Heats & Reports"])

with tab_upload:
    st.header("Import Heat")
    heat_name = st.text_input("Heat name", placeholder="e.g., Distance Heat 1")
    category = st.selectbox("Category", CATEGORIES, index=0, help="Colors and metrics depend on this selection.")
    uploaded = st.file_uploader("Upload CSV files for this heat (one per flyer)", type=["csv"], accept_multiple_files=True)
    st.info("Name each file with the flyer's name somewhere (or set explicitly below).")
    manual_names = {}
    if uploaded:
        st.subheader("Map files to flyers")
        for f in uploaded:
            default = os.path.splitext(os.path.basename(f.name))[0]
            manual_names[f.name] = st.text_input(f"Flyer name for file: {f.name}", value=default)

    if st.button("Analyze & Save", type="primary", disabled=not (heat_name and uploaded)):
        ts = datetime.utcnow().isoformat()
        cur = conn.cursor()
        cur.execute("INSERT OR IGNORE INTO heats (name, category, uploaded_at) VALUES (?, ?, ?)", (heat_name, category, ts))
        conn.commit()
        cur.execute("SELECT id FROM heats WHERE name = ?", (heat_name,))
        heat_id = cur.fetchone()[0]

        out_root = ensure_outputs_dir(heat_name)

        series_map = {}; opening_pts_map = {}; segs_for_kml = {}; window_pts_for_kml = {}
        along_map = {}; sA_map = {}; sB_map = {}; sOpen_map = {}
        flyer_colors = {}; dist_labels = {}; speed_marks = {}

        for f in uploaded:
            try:
                flyer = manual_names.get(f.name, os.path.splitext(os.path.basename(f.name))[0])
                b = f.read(); df = load_clean_csv(b)
                ei = detect_exit(df); oi = detect_opening(df, ei)
                if ei is None or oi is None:
                    st.warning(f"{flyer}: could not detect exit/opening; skipped."); continue
                exit_time = df.loc[ei,'time']; open_time = df.loc[oi,'time']
                p11, p5 = find_window_points(df, ei, oi)
                if not p11 or not p5:
                    st.warning(f"{flyer}: window crossing not found; using exit→opening span for plots.")
                    t11, t5 = exit_time, open_time
                else:
                    t11, t5 = p11['time'], p5['time']

                # Individual plot
                indiv_path = os.path.join(out_root, f"{flyer}_individual.png")
                figure_individual(df, flyer, exit_time, open_time, t11, t5, indiv_path)

                # KML inputs
                d = df[(df['time']>=exit_time) & (df['time']<=open_time)].copy()
                seg_kml = d[['lat','lon','alt_m']].copy(); segs_for_kml[flyer] = seg_kml
                window_pts_for_kml[flyer] = (p11, p5)

                # Combined plot inputs (Exit→Open projection; annotate A/B)
                if p11 and p5:
                    seg_along, sA_rel, sB_rel, sOpen_rel = series_from_exit_to_open(df, p11, p5, exit_time, open_time)
                    along_map[flyer] = seg_along; sA_map[flyer]=sA_rel; sB_map[flyer]=sB_rel; sOpen_map[flyer]=sOpen_rel
                else:
                    along_map[flyer] = pd.DataFrame(columns=['time','s_rel','alt_ft'])

                # Metrics inside window (A→B)
                if p11 and p5 and (t5>t11):
                    seg_win = df[(df['time']>=t11) & (df['time']<=t5)].copy()
                else:
                    seg_win = d.copy()

                max_glide = float(seg_win['glide'].max()) if not seg_win.empty else float('nan')
                max_h_kph = float(seg_win['spd_horiz_kph'].max()) if not seg_win.empty else float('nan')
                straight_m = float(haversine_m(p11['lat'], p11['lon'], p5['lat'], p5['lon'])) if (p11 and p5) else None
                dist_labels[flyer] = straight_m

                # Speed 1 km mark from A along A→B with Δt
                if ("Speed" in category) and p11 and p5:
                    lat0, lon0 = p11['lat'], p11['lon']
                    Ax, Ay = 0.0, 0.0
                    Bx, By = ll_to_local_m(lat0, lon0, p5['lat'], p5['lon'])
                    AB = np.array([Bx - Ax, By - Ay]); Ltmp = np.linalg.norm(AB)
                    if Ltmp > 0:
                        ABu = AB / Ltmp
                        seg_speed = df[(df['time'] >= p11['time']) & (df['time'] <= p5['time'])][['time','lat','lon','alt_m']].copy()
                        if not seg_speed.empty:
                            alongs = []
                            for _, r in seg_speed.iterrows():
                                x, y = ll_to_local_m(lat0, lon0, float(r['lat']), float(r['lon']))
                                alongs.append(float(np.dot(np.array([x - Ax, y - Ay]), ABu)))
                            for i in range(1, len(alongs)):
                                s0, s1 = alongs[i-1], alongs[i]
                                if s0 < SPEED_TARGET_M <= s1 and 0 <= s1 <= Ltmp:
                                    r0 = seg_speed.iloc[i-1]; r1 = seg_speed.iloc[i]
                                    w = (SPEED_TARGET_M - s0) / (s1 - s0) if s1 != s0 else 0.0
                                    t_hit = pd.to_datetime(int(r0['time'].value + w*(r1['time'].value - r0['time'].value)), unit='ns', utc=True)
                                    lat = float(r0['lat'] + w*(r1['lat'] - r0['lat'])); lon = float(r0['lon'] + w*(r1['lon'] - r0['lon'])); alt_m = float(r0['alt_m'] + w*(r1['alt_m'] - r0['alt_m']))
                                    dt_1000 = (t_hit - p11['time']).total_seconds()
                                    speed_marks[flyer] = {'lat':lat, 'lon':lon, 'alt_m':alt_m, 'dt_s':dt_1000}
                                    break

                # Persist metrics
                cur.execute("""
                INSERT INTO jumps (heat_id, flyer_name, file_name, max_glide, straight_dist_window_m, time_to_1000m_s,
                                   max_horizontal_kph, opening_alt_ft, exit_time_utc, opening_time_utc,
                                   kml_path, indiv_plot_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    heat_id, flyer, f.name,
                    max_glide,
                    straight_m if ("Distance" in category) else None,
                    (speed_marks.get(flyer, {}).get('dt_s') if "Speed" in category else None),
                    max_h_kph,
                    float(df.loc[oi,'alt_ft']),
                    exit_time.isoformat(), open_time.isoformat(),
                    None, indiv_path
                ))
                conn.commit()
                st.success(f"Processed: {flyer}")
            except Exception as e:
                st.error(f"Error processing {f.name}: {e}")

        # Assign distinct colors
        flyers = list(segs_for_kml.keys())
        cols = distinct_colors(len(flyers)) if flyers else []
        for i, fl in enumerate(flyers): flyer_colors[fl] = cols[i]

        # Combined plot
        combined_path = os.path.join(out_root, f"{heat_name.replace(' ','_')}_alt_vs_along.png")
        figure_alt_vs_along(along_map, sA_map, sB_map, sOpen_map, f"{heat_name} ({category})", flyer_colors, speed_marks, combined_path)

        # KML
        kml_path = os.path.join(out_root, f"{heat_name.replace(' ','_')}.kml")
        build_kml(heat_name, segs_for_kml, window_pts_for_kml, kml_path, flyer_colors, dist_labels, speed_marks)

        cur.execute("UPDATE jumps SET kml_path = ? WHERE heat_id = ?", (kml_path, heat_id)); conn.commit()

        st.success("Heat analysis complete.")
        st.write("Artifacts directory:", out_root)
        if os.path.exists(combined_path):
            with open(combined_path, "rb") as fdat:
                st.download_button("Download Altitude vs Along-Track image", data=fdat.read(),
                                   file_name=os.path.basename(combined_path), mime="image/png")
        if os.path.exists(kml_path):
            with open(kml_path, "rb") as fdat:
                st.download_button("Download KML", data=fdat.read(),
                                   file_name=os.path.basename(kml_path), mime="application/vnd.google-earth.kml+xml")

with tab_heats:
    st.header("Heats & Reports")
    cur = conn.cursor()
    df_heats = pd.read_sql_query("SELECT * FROM heats ORDER BY uploaded_at DESC", conn)
    st.subheader("All Heats"); st.dataframe(df_heats, use_container_width=True)

    heat_select = st.selectbox("Select a heat", ["-- Select --"] + df_heats['name'].tolist())
    if heat_select and heat_select != "-- Select --":
        cur.execute("SELECT id, category FROM heats WHERE name = ?", (heat_select,))
        row = cur.fetchone(); heat_id = row[0]; cat = row[1]
        st.markdown(f"**Category:** {cat}")

        df_jumps = pd.read_sql_query("""
            SELECT flyer_name,
                   ROUND(max_glide, 2) AS max_glide,
                   straight_dist_window_m,
                   time_to_1000m_s,
                   ROUND(max_horizontal_kph, 1) AS max_horizontal_kph,
                   ROUND(opening_alt_ft, 0) AS opening_alt_ft,
                   indiv_plot_path
            FROM jumps WHERE heat_id = ?
        """, conn, params=(heat_id,))
        st.subheader("Heat Metrics"); st.dataframe(df_jumps, use_container_width=True)

        st.subheader("Individual Graphs")
        for _, r in df_jumps.iterrows():
            if r['indiv_plot_path'] and os.path.exists(r['indiv_plot_path']):
                st.image(r['indiv_plot_path'], caption=f"{r['flyer_name']} - Individual Graph", use_container_width=True)

        out_root = os.path.join("outputs", heat_select.replace(" ", "_"))
        combined_img = os.path.join(out_root, f"{heat_select.replace(' ','_')}_alt_vs_along.png")
        if os.path.exists(combined_img):
            st.subheader("Combined Altitude vs Along-Track Distance")
            st.image(combined_img, use_container_width=True)
        kml_path = os.path.join(out_root, f"{heat_select.replace(' ','_')}.kml")
        if os.path.exists(kml_path):
            with open(kml_path, "rb") as f:
                st.download_button("Download KML for this heat", data=f.read(), file_name=os.path.basename(kml_path))

        st.subheader("Event Controls")
        col1, col2, col3 = st.columns([1,1,1])

        with col1:
            if st.button("💾 Save Event (export ZIP)"):
                tmpdir = tempfile.mkdtemp()
                export_root = os.path.join(tmpdir, "export"); os.makedirs(export_root, exist_ok=True)
                src = os.path.join("outputs", heat_select.replace(" ", "_"))
                if os.path.isdir(src): shutil.copytree(src, os.path.join(export_root, "outputs"), dirs_exist_ok=True)
                heat_row = pd.read_sql_query("SELECT * FROM heats WHERE id = ?", conn, params=(heat_id,))
                jump_rows = pd.read_sql_query("SELECT * FROM jumps WHERE heat_id = ?", conn, params=(heat_id,))
                meta = {"heats": heat_row.to_dict(orient="records"), "jumps": jump_rows.to_dict(orient="records")}
                with open(os.path.join(export_root, "event.json"), "w", encoding="utf-8") as f: json.dump(meta, f, indent=2)
                zip_path = os.path.join(tmpdir, f"{heat_select.replace(' ','_')}_event.zip")
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                    for root, _, files in os.walk(export_root):
                        for fn in files:
                            full = os.path.join(root, fn); arc = os.path.relpath(full, export_root); z.write(full, arcname=arc)
                with open(zip_path, "rb") as f:
                    st.download_button("Download Event ZIP", f.read(), file_name=os.path.basename(zip_path))

        with col2:
            up = st.file_uploader("Import Event ZIP", type=["zip"], key="event_zip_upload")
            if up is not None:
                tmpdir = tempfile.mkdtemp()
                zip_tmp = os.path.join(tmpdir, "in.zip")
                with open(zip_tmp, "wb") as f: f.write(up.read())
                with zipfile.ZipFile(zip_tmp, "r") as z: z.extractall(tmpdir)
                event_json = os.path.join(tmpdir, "event.json")
                if os.path.exists(event_json):
                    with open(event_json, "r", encoding="utf-8") as f: meta = json.load(f)
                    out_src = os.path.join(tmpdir, "outputs")
                    out_dst = os.path.join("outputs", heat_select.replace(" ", "_"))
                    if os.path.isdir(out_src): os.makedirs(os.path.dirname(out_dst), exist_ok=True); shutil.copytree(out_src, out_dst, dirs_exist_ok=True)
                    if meta.get("heats"):
                        h = meta["heats"][0]
                        cur.execute("INSERT OR IGNORE INTO heats (id, name, category, uploaded_at) VALUES (?, ?, ?, ?)", (h["id"], h["name"], h["category"], h["uploaded_at"]))
                    if meta.get("jumps"):
                        for j in meta["jumps"]:
                            cur.execute("""
                                INSERT OR REPLACE INTO jumps
                                (id, heat_id, flyer_name, file_name, max_glide, straight_dist_window_m, time_to_1000m_s,
                                 max_horizontal_kph, opening_alt_ft, exit_time_utc, opening_time_utc, kml_path, indiv_plot_path)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (j["id"], j["heat_id"], j["flyer_name"], j["file_name"], j["max_glide"], j["straight_dist_window_m"],
                                  j["time_to_1000m_s"], j["max_horizontal_kph"], j["opening_alt_ft"], j["exit_time_utc"], j["opening_time_utc"], j["kml_path"], j["indiv_plot_path"]))
                    conn.commit()
                    st.success("Event imported. Re-select the heat to refresh.")

        with col3:
            if "confirm_clear" not in st.session_state: st.session_state.confirm_clear = False
            if st.button("🧹 Clear Event"): st.session_state.confirm_clear = True
            if st.session_state.confirm_clear:
                st.warning("This will delete the selected heat, its files, and all its jumps.")
                tmpdir = tempfile.mkdtemp(); export_root = os.path.join(tmpdir, "export"); os.makedirs(export_root, exist_ok=True)
                src = os.path.join("outputs", heat_select.replace(" ", "_"))
                if os.path.isdir(src): shutil.copytree(src, os.path.join(export_root, "outputs"), dirs_exist_ok=True)
                heat_row = pd.read_sql_query("SELECT * FROM heats WHERE id = ?", conn, params=(heat_id,))
                jump_rows = pd.read_sql_query("SELECT * FROM jumps WHERE heat_id = ?", conn, params=(heat_id,))
                meta = {"heats": heat_row.to_dict(orient="records"), "jumps": jump_rows.to_dict(orient="records")}
                with open(os.path.join(export_root, "event.json"), "w", encoding="utf-8") as f: json.dump(meta, f, indent=2)
                zip_path = os.path.join(tmpdir, f"{heat_select.replace(' ','_')}_event_backup.zip")
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
                    for root, _, files in os.walk(export_root):
                        for fn in files:
                            full = os.path.join(root, fn); arc = os.path.relpath(full, export_root); z.write(full, arcname=arc)
                with open(zip_path, "rb") as f:
                    st.download_button("⬇️ Download Backup ZIP (optional)", f.read(), file_name=os.path.basename(zip_path))
                c1, c2 = st.columns([1,1])
                with c1:
                    if st.button("✅ Confirm Delete"):
                        target = os.path.join("outputs", heat_select.replace(" ", "_"))
                        if os.path.isdir(target): shutil.rmtree(target, ignore_errors=True)
                        cur.execute("DELETE FROM jumps WHERE heat_id = ?", (heat_id,))
                        cur.execute("DELETE FROM heats WHERE id = ?", (heat_id,))
                        conn.commit()
                        st.success("Event deleted."); st.session_state.confirm_clear = False
                with c2:
                    if st.button("❌ Cancel"): st.session_state.confirm_clear = False
