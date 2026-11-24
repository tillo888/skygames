# SkyGames Analyzer (v4)

A web app for scoring GPS-measured slick-tracking competitions. Upload one
CSV per flyer, pick the discipline (distance, 1 km speed course, max
horizontal speed) and get the leaderboard, a top-view map, a side view and
each flyer's speed profile. Change any rule and re-score without
uploading again. Every heat is saved.

## Run it on your laptop
```bash
cd skygames
python3 -m venv .venv && source .venv/bin/activate     # once
pip install -r requirements.txt                        # once
uvicorn backend.app:app --port 8000
```
Open http://localhost:8000. Heats are stored in `data/skygames_web.sqlite`.

## Put it online
The app is a single Python service, so any host that runs Docker or Python works.

**Render (simplest):** push this folder to a GitHub repo → render.com → New →
Blueprint → pick the repo. `render.yaml` creates the service plus a 1 GB disk
for saved heats. Without the disk, saved heats are lost on every deploy.

**Railway / Fly.io / any VPS:** use the `Dockerfile`. Mount a volume at
`/data` (heats are saved there). The `PORT` variable is respected.

Settings (environment variables):

| Variable | |
|---|---|
| `SKYGAMES_ADMIN_PASSWORD` | admin password for Saved heats and the results tabs. Unset = locked for everyone |
| `SKYGAMES_SECRET_KEY` | long random string that signs sign-in cookies (Render generates it) |
| `SKYGAMES_HTTPS_ONLY` | `1` in production so the cookie is only sent over HTTPS |
| `SKYGAMES_DB` | database path (default `data/skygames_web.sqlite`, `/data/...` in Docker) |
| `SKYGAMES_MAX_FILE_MB`, `SKYGAMES_MAX_FILES` | upload limits (25 MB, 12 files) |

Never put the password in the code: this repository is public.

## Who can see what
* **Analyzer: everyone.** Visitors can score heats and reopen the ones they scored
  (remembered in their browser for 14 days).
* **Saved heats and results: admins only.** Admins see every heat, including
  public uploads (marked "Public upload"), and can delete them.

## How it's split up
```
config/rules.yaml        every competition rule and analysis parameter
skygames_engine/         scoring (no web code): parser, core, tasks/, wind/, visualization/
backend/                 web server
  app.py                 routes (/api/...) + serves web/
  service.py             runs the engine for a heat, builds downloads
  store.py               SQLite: heats + original CSVs
  rules_ui.py            which rules appear in the Analyzer form (one line each)
web/                     front end, plain ES modules, no build step
  js/setup.js            heat name, discipline, files
  js/rules.js            rules form (generated from rules_ui.py)
  js/results.js          leaderboard, panels, downloads
  js/map.js              satellite map + flight paths
  js/charts.js           side view and speed profile charts
  js/heats.js            saved heats
  js/api.js, state.js, dom.js, main.js
tools/build_preview.py   one-file preview page with a heat embedded
tests/                   pytest: v3.9 parity, parser, tasks, wind, API
```

### Common changes
* **A rule value** (e.g. window top): edit `config/rules.yaml`, bump `rules_version`.
* **Show another rule in the Analyzer**: add one entry to `backend/rules_ui.py`.
* **A new discipline**: add `skygames_engine/tasks/<name>.py` (copy `distance.py`)
  and a `tasks.<name>` block in the schema and rules.yaml. It appears in the
  discipline picker automatically.

## API
| Method | Path | |
|---|---|---|
| GET | `/api/meta` | disciplines + rule form definition |
| GET | `/api/heats` | saved heats |
| POST | `/api/heats` | multipart `name`, `task`, `rule_values` (JSON), `files[]`, `flyers[]` → results |
| GET | `/api/heats/{id}` | results |
| POST | `/api/heats/{id}/analyze` | JSON `{name?, task?, rule_values?, flyers?}` → re-scored results |
| DELETE | `/api/heats/{id}` | delete heat and files |
| GET | `/api/heats/{id}/download/{kml\|geojson\|json\|zip}` | downloads |

## Command line (no server)
```bash
python -m skygames_engine analyze --task distance --name "Load 3" -o out/ *.csv
```

## Tests
```bash
python -m pytest
```
`tests/test_legacy_parity.py` proves the scores match the original v3.9 program.

See `docs/AUDIT.md` (issues found in v3.9) and `docs/ARCHITECTURE.md`
(structure, database plan for competitions/registration/challenge series).
