"""SkyGames web app.  Run:  uvicorn backend.app:app --port 8000

Serves the API under /api and the front end (web/) at /.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import auth, service
from .auth import admin_only, can_open, remember_heat
from .service import BadRequest
from .store import Store

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.environ.get("SKYGAMES_DB", str(ROOT / "data" / "skygames_web.sqlite"))
MAX_FILE_MB = float(os.environ.get("SKYGAMES_MAX_FILE_MB", "25"))
MAX_FILES = int(os.environ.get("SKYGAMES_MAX_FILES", "12"))

store = Store(DB_PATH)


def _err(status: int, message: str):
    return JSONResponse({"error": message}, status_code=status)


def _heat_or_404(request: Request) -> dict:
    """A heat is visible to admins, and to the visitor who scored it (404 otherwise,
    so ids of other people's heats can't be probed)."""
    hid = request.path_params["hid"]
    h = store.get_heat(hid)
    if not h or not can_open(request, hid):
        raise HTTPException(404, "Heat not found")
    return h


async def get_meta(request: Request):
    return JSONResponse(service.meta())


@admin_only
async def list_heats(request: Request):
    return JSONResponse({"heats": store.list_heats()})


async def create_heat(request: Request):
    """multipart: name, task, rule_values (JSON), files[] (CSV), flyers[] (names, same order)."""
    form = await request.form(max_files=MAX_FILES)
    name = (form.get("name") or "").strip() or "Untitled heat"
    task = form.get("task") or "distance"
    if task not in {t["key"] for t in service.meta()["tasks"]}:
        return _err(400, f"Unknown task '{task}'")
    try:
        rule_values = json.loads(form.get("rule_values") or "{}")
    except json.JSONDecodeError:
        return _err(400, "rule_values must be JSON")
    uploads = form.getlist("files")
    if not uploads:
        return _err(400, "Add at least one CSV file.")
    given = [str(n) for n in form.getlist("flyers")]
    raw_names = [(given[i] if i < len(given) and given[i].strip() else Path(up.filename or "flyer").stem)
                 for i, up in enumerate(uploads)]
    files = []
    for up, flyer in zip(uploads, service.unique_names(raw_names)):
        data = await up.read()
        if len(data) > MAX_FILE_MB * 1024 * 1024:
            return _err(413, f"{up.filename} is larger than {MAX_FILE_MB:g} MB.")
        files.append({"flyer": flyer, "file_name": up.filename or "track.csv", "data": data})
    try:
        service.build_rules(rule_values)  # validate before storing anything
    except BadRequest as e:
        return _err(400, str(e))
    hid = store.create_heat(name, task, rule_values, files, "admin" if auth.is_admin(request) else "public")
    remember_heat(request, hid)
    payload = await run_in_threadpool(service.analyze, store, hid)
    return JSONResponse(payload, status_code=201)


async def get_heat(request: Request):
    h = _heat_or_404(request)
    if h["payload"] is None:
        return JSONResponse(await run_in_threadpool(service.analyze, store, h["id"]))
    return JSONResponse(h["payload"])


async def reanalyze(request: Request):
    """JSON: {name?, task?, rule_values?, flyers?: {file_id: name}} -> fresh results."""
    h = _heat_or_404(request)
    body = await request.json()
    task = body.get("task")
    if task and task not in {t["key"] for t in service.meta()["tasks"]}:
        return _err(400, f"Unknown task '{task}'")
    rule_values = body.get("rule_values")
    if rule_values is not None:
        try:
            service.build_rules(rule_values)
        except BadRequest as e:
            return _err(400, str(e))
    flyers = body.get("flyers")
    if flyers:
        ids = list(flyers)
        flyers = dict(zip(ids, service.unique_names([flyers[i] for i in ids])))
    store.update_heat(h["id"], name=(body.get("name") or "").strip() or None, task=task,
                      rule_values=rule_values, flyers=flyers)
    return JSONResponse(await run_in_threadpool(service.analyze, store, h["id"]))


@admin_only
async def delete_heat(request: Request):
    if not store.delete_heat(request.path_params["hid"]):
        return _err(404, "Heat not found")
    return JSONResponse({"deleted": True})


async def download(request: Request):
    h = _heat_or_404(request)
    kind = request.path_params["kind"]
    try:
        if kind == "zip":
            name, data = await run_in_threadpool(service.export_zip, store, h["id"])
            mime = "application/zip"
        else:
            name, data, mime = await run_in_threadpool(service.export_one, store, h["id"], kind)
    except BadRequest as e:
        return _err(400, str(e))
    return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


async def http_error(request: Request, exc: HTTPException):
    return _err(exc.status_code, exc.detail)


async def server_error(request: Request, exc: Exception):
    return _err(500, f"Server error: {exc}")


routes = [
    Route("/api/meta", get_meta),
    Route("/api/me", auth.me),
    Route("/api/login", auth.login, methods=["POST"]),
    Route("/api/logout", auth.logout, methods=["POST"]),
    Route("/api/heats", list_heats, methods=["GET"]),
    Route("/api/heats", create_heat, methods=["POST"]),
    Route("/api/heats/{hid}", get_heat, methods=["GET"]),
    Route("/api/heats/{hid}", delete_heat, methods=["DELETE"]),
    Route("/api/heats/{hid}/analyze", reanalyze, methods=["POST"]),
    Route("/api/heats/{hid}/download/{kind}", download, methods=["GET"]),
    Mount("/", StaticFiles(directory=str(ROOT / "web"), html=True), name="web"),
]

middleware = [Middleware(SessionMiddleware, secret_key=auth.SECRET_KEY, session_cookie="skygames",
                         max_age=14 * 24 * 3600, same_site="lax",
                         https_only=os.environ.get("SKYGAMES_HTTPS_ONLY", "0") == "1")]
app = Starlette(routes=routes, middleware=middleware,
                exception_handlers={HTTPException: http_error, Exception: server_error})
