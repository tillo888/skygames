# SkyGames platform architecture

## Principles
* **The engine knows nothing about the web.** `skygames_engine/` is a plain
  Python package with no database, HTTP or UI code. The website, the CLI, a
  future desktop/offline analyzer and the tests all call the same functions.
* **Every number comes from `config/rules.yaml`.** Results store
  `rules_version` + `rules_fingerprint` so any score can be traced and re-run.
* **One discipline per module.** Tasks share one interface and never import each other.
* **Raw GPS score is the official score.** Wind-adjusted scores are stored
  beside it, never instead of it.

## Folder structure

```
skygames/
├── config/
│   └── rules.yaml                 # all competition + analysis parameters
├── skygames_engine/               # PHASE 1 (done) - pure analysis library
│   ├── config/                    # schema.py (pydantic), load_rules(), overrides, fingerprint
│   ├── parser/                    # formats.py (FlySight 1/2, generic CSV, units)
│   │                              # validate.py (cleaning, quality filters, AGL) errors.py
│   ├── core/                      # track.py (Track), geo.py, smoothing.py,
│   │                              # events.py (exit, opening, window A/B)
│   ├── tasks/                     # base.py (TaskEvaluator/TaskResult), registry.py
│   │   ├── max_horizontal_speed.py
│   │   ├── distance.py
│   │   └── speed_course.py
│   ├── wind/                      # profile.py, providers.py (manual, Open-Meteo),
│   │                              # cache.py (SQLite), adjust.py (air-relative track)
│   ├── visualization/             # series.py (JSON for web charts), kml.py (+GeoJSON),
│   │                              # plots.py (PNG export), colors.py
│   ├── ranking.py                 # winners, ties, DNF
│   ├── pipeline.py                # analyze_file / analyze_heat / render_heat_artifacts
│   └── cli.py                     # python -m skygames_engine analyze ...
├── backend/                       # PHASE 2 - FastAPI app
│   ├── app/main.py
│   ├── app/api/{analyzer,results,competitions,registrations,challenge,rules}.py
│   ├── app/models/                # SQLAlchemy models (schema below)
│   ├── app/services/              # storage (files), scoring jobs, wind jobs
│   └── migrations/                # Alembic; includes import of legacy skygames.db
├── web/                           # PHASE 3 - front end (React + MapLibre + uPlot)
│   └── src/pages/{Results,Competitions,Rules,Analyzer,Challenge}
├── tests/                         # pytest: parity with v3.9, parser, tasks, wind, pipeline
└── docs/                          # AUDIT.md, ARCHITECTURE.md
```

## Task interface

```python
class TaskEvaluator:
    key: str                                   # "distance", ...
    def evaluate(self, track: Track, events: JumpEvents, rules: Rules) -> TaskResult

@dataclass
class TaskResult:
    task: str; score: float | None; unit: str; valid: bool
    reason: str; details: dict; quality_flags: list[str]
```

To add a discipline: create `tasks/<name>.py` with `@register` and add a
`tasks.<name>` block to the schema and to rules.yaml. Nothing else changes.

## Wind design
`air_relative_track()` subtracts the integrated wind drift from positions
and the wind vector from velocities. The **unchanged** task evaluators then
run on that track, so every discipline gets a wind-adjusted score without
knowing wind exists. Profiles come from a provider (manual entry by judges,
or Open-Meteo pressure-level model data at the window entry point and hour),
cached by 0.25° grid cell + hour.

## Database schema (phase 2, PostgreSQL; SQLite for local/offline)

```
users            id, email, name, role(admin|judge|athlete), created_at
athletes         id, user_id?, display_name, country, home_dz
competitions     id, name, location, dz_elevation_m, start_date, end_date,
                 status(draft|open|closed|finished), rules_version, registration_deadline
disciplines      key(PK: max_horizontal_speed|distance|speed_course), label, unit, rank_order
rounds           id, competition_id, discipline_key, kind(qualifier|heat|final|training),
                 number, name, scheduled_at
registrations    id, competition_id, athlete_id, disciplines[], status(pending|confirmed|withdrawn),
                 created_at   UNIQUE(competition_id, athlete_id)
files            id, sha256 UNIQUE, original_name, storage_key, size, uploaded_by, uploaded_at
jumps            id, round_id?, challenge_entry_id?, athlete_id, file_id,
                 exit_time_utc, opening_time_utc, exit_alt_ft, opening_alt_ft,
                 summary JSONB, warnings JSONB, ground_elevation_m
                 UNIQUE(round_id, athlete_id, file_id)        -- no more duplicate rows
scores           id, jump_id, task_key, score, valid, reason, details JSONB, quality_flags JSONB,
                 wind_adjusted BOOL, wind_profile_id?, rules_version, rules_fingerprint,
                 engine_version, computed_at
                 UNIQUE(jump_id, task_key, wind_adjusted, rules_fingerprint)
wind_profiles    id, provider, lat, lon, valid_time, levels JSONB
challenge_series id, name, season, discipline_key, rules_version, starts_at, ends_at
challenge_entries id, series_id, athlete_id, jump_id, dz_name, submitted_at,
                 status(pending|verified|rejected), public BOOL
```

Rankings are queries over `scores`, not stored tables, so re-scoring with a
new rules version re-ranks automatically while keeping the old scores.

## API (phase 2)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/analyze` | multipart CSVs + task + optional rule overrides → ranking + chart/map JSON (no login; the "train at your DZ" analyzer) |
| GET | `/api/analyze/{id}/artifacts/{file}` | KML, GeoJSON, PNG, results JSON |
| GET | `/api/rules`, `/api/rules/{version}` | rules for the Rules & Disciplines page |
| GET | `/api/competitions?status=` | upcoming / past |
| POST | `/api/competitions/{id}/registrations` | register |
| POST | `/api/rounds/{id}/jumps` | judges upload a heat (stored, scored) |
| GET | `/api/results/competitions/{id}` | leaderboard per round / discipline |
| POST | `/api/challenge/{series}/entries` | public upload (wind-adjusted, AGL rules) |
| GET | `/api/challenge/{series}/leaderboard?wind=adjusted\|raw` | global comparison |

## Phases (status)
1. **Engine (this delivery):** refactor + tests + CLI. Parity with v3.9 proven on synthetic data.
2. **Analyzer web app (done):** Starlette (the framework FastAPI is built on) + SQLite heat store + front end. Next: SQLAlchemy/PostgreSQL and accounts for the other tabs.
3. **Remaining tabs:** Results, Upcoming competitions + registration, Rules & disciplines, Challenge series.
4. **Challenge series:** accounts, public uploads, wind lookups as a background job.
