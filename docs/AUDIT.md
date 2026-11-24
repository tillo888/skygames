# Audit: `skygames_analyzer_app_v3_9.py`

Scope: the 778-line Streamlit script, its `requirements.txt`, and `skygames.db`
(7 heats, 35 jump rows). Line numbers refer to the uploaded v3.9 file.

## 1. What exists today

| Area | Function / block (lines) | What it does | Where it went |
|---|---|---|---|
| Constants | 29–48 | ft/m, window 11k/5k ft, freefall 100 km/h, opening band 1.5–4.5k ft, 1,000 m target, 4 categories | `config/rules.yaml` |
| UI theme | 52–95 | 40 lines of CSS overrides | dropped (web front end, phase 2) |
| Colours | `distinct_colors`, `rgb_to_kml_argb` (102–111) | tab10/tab20 colours, KML ARGB | `visualization/colors.py` (CVD-checked fixed order) |
| DB | `db_conn`, `db_init` (115–147) | SQLite `heats`, `jumps` | phase 2 (`backend/`), new schema in ARCHITECTURE.md |
| Geo | `haversine_m`, `ll_to_local_m` (151–166) | great circle; local metres | `core/geo.py` (vectorised) |
| Ingestion | `load_clean_csv` (170–187) | FlySight 1 only, drops units row, derives speeds/glide | `parser/formats.py` + `parser/validate.py` |
| Smoothing | `smooth_series` (189–195) | rolling median, window in samples | `core/smoothing.py` |
| Exit | `detect_exit` (197–259) | after peak altitude: ≥100 km/h down sustained 0.6 s, plus near-zero run or accel ramp in the prior 6 s | `core/events.py::detect_exit` |
| Opening | `detect_opening` (261–295) | first point in 1.5–4.5k ft band below 100 km/h, sustained 1.5 s, fast within prior 3 s | `core/events.py::detect_opening` |
| Window | `interpolate_crossing_time`, `find_window_points` (297–314) | interpolated 11k (A) and 5k (B) crossings | `core/events.py::altitude_crossing` |
| Along-track | `series_from_exit_to_open` (318–360) | project exit→opening onto A→B | `visualization/series.py::along_track_series` |
| Plots | `figure_individual`, `figure_alt_vs_along` (364–422) | matplotlib PNGs | `visualization/plots.py` + JSON series for the web |
| KML | `build_kml` (426–502) | per-flyer track, markers, red A→B line, 1 km mark | `visualization/kml.py` (+ GeoJSON) |
| **Distance score** | inline, line 585 | haversine A→B | `tasks/distance.py` |
| **Speed score** | inline, lines 589–611 | first time the A→B projection reaches 1,000 m | `tasks/speed_course.py` |
| **Max H speed** | inline, line 584 | max single-sample horizontal speed in window | `tasks/max_horizontal_speed.py` |
| Event save/import/clear | 699–777 | ZIP export/import, delete | phase 2 API |

**Not implemented in v3.9:** any ranking or winner, Max Horizontal Speed as a
selectable task, wind lookup, data-quality checks, FlySight 2 files,
competitions/registration/challenge data.

## 2. Bugs and fragile areas

Ordered by impact on results.

### Will break or silently change scores
1. **Crashes on current pandas.** `df['time'].view('int64')` (lines 192, 207, 271)
   was removed in pandas 3. `requirements.txt` is unpinned, so a fresh install
   fails on the first file. *Fixed:* time handled as seconds-since-start.
2. **Smoothing window is a coin flip at 5 Hz.** `round(0.5 / dt)` with
   `dt ≈ 0.2` gives exactly 2.5 samples. Float noise in the epoch timestamps
   decides whether it rounds to 2 or 3 samples, so the detected exit can move
   by a sample. *Fixed:* deterministic half-down rounding, which matches what
   v3.9 produced on every test file.
3. **Altitude is MSL, not AGL.** The window (11k/5k ft) and opening band
   (1.5–4.5k ft) are measured above sea level. At DeLand (~25 m elevation)
   that's ~80 ft of error. At a 1,600 m drop zone no opening is found at all.
   The online challenge can't work this way. *Now configurable:*
   `altitude_reference.mode` (MSL default for parity; AGL with auto-detected
   or entered ground elevation). Test: `test_agl_mode_high_dropzone`.
4. **Max horizontal speed is a single raw GPS sample.** One velocity glitch
   wins the round. *Added:* spike filter (on by default, `max_accel_ms2`)
   and an optional `averaging_s` (0 = legacy behaviour).
5. **Heat category drives the score.** `"Speed" in category` / `"Distance" in
   category` string matching. Your DB shows the effect: heat 8 `" Speed"` and
   heat 7 `"Distance" Actually Speed` were saved as *Distance Qualifiers*, so no
   speed times were computed. *Fixed:* task is an explicit key; all three
   tasks are scored for every jump, and the heat ranks on the chosen one.
6. **Re-running a heat duplicates jumps.** `INSERT OR IGNORE` on the heat, then
   a plain `INSERT` for every jump. Heat 4 in your DB has every jump twice
   (ids 13–16 = 17–20). Phase 2 schema adds a unique key per (heat, flyer, file hash).

### Ambiguous rules (now explicit config, legacy default kept)
7. **Speed course direction is defined by where the flyer ends.** Distance
   is measured along A→B, and B is only known at 5,000 ft. Option
   `measure: radial_from_start` (straight-line distance from A) added.
   **Please confirm which one the rulebook means.**
8. Speed score is void if A→B is shorter than 1 km or 1 km is reached after
   5,000 ft (`must_finish_in_window`).
9. The exit "near-zero" threshold is `5/3.6` = 5 km/h in code, but the
   docstring says 5 m/s. Kept 5 km/h (`near_zero_kph: 5`) for parity.
10. Exit selection uses `score = (i − peak) + 0.1·glide`. For any real glide
    ratio that's simply "earliest valid sample", so the code now says so.

### Robustness / maintainability
11. `detect_exit` was O(N²): the near-zero scan re-ran for every sample after
    peak. Now vectorised pre-filter + early exit; a 5-file heat parses, detects and scores all three tasks in under 0.2 s.
12. No input validation: missing columns raised a raw `KeyError`. Units were
    assumed (m, m/s). Feet or knots files would score silently wrong.
13. If the window wasn't found, max glide/H speed silently used the whole
    exit→opening span, while the stored score looked like a window score.
    Now the task score is invalid with a reason, and `summary.stats_scope` says which span was used.
14. Flyer and heat names went unescaped into KML XML and file paths (a `&` or `"` broke
    the KML; heat 7's name produced a path with quotes in it).
15. `kml_path` and image paths are stored relative to the working directory.
    Event import writes into the *currently selected* heat's folder, with ID collisions possible.
16. The "Clear event" confirmation rebuilds a backup ZIP on every rerun.
17. `requirements.txt` lists unused packages (`openpyxl, reportlab, plotly,
    fpdf`) and two stdlib back-ports that shouldn't be installed
    (`shutilwhich`, `zipfile36`).
18. File header says v3.7. Rule changes were not versioned, so old results
    can't be traced to the parameters that produced them. Now every result
    stores `rules_version` + a fingerprint of the effective rules.

## 3. Verification

`tests/test_legacy_parity.py` loads v3.9's own functions (shimmed for
pandas 3) and compares the engine against them. Ten synthetic jumps: 2 Hz,
5 Hz, 10 Hz and 20 Hz loggers, slow and fast flyers, a low deployment, a turning
flight. Matched: exit index, opening index, window times, distance (1e-6 m),
max glide, max horizontal speed, opening altitude, and time-to-1000 m (1e-6 s).

**Still to do:** run the same comparison on your real CSVs from the DB
(Sat_1_Bamba, gps_00129–135, ANDUBS…). The stored values are the expected
results.
