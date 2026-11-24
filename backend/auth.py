"""Admin sign-in.

The Analyzer is public. Everything that shows or changes saved results
(saved heats, and the future Results / Competitions / Challenge admin pages)
needs an admin session.

Set on the server (never in the code or the repository):
  SKYGAMES_ADMIN_PASSWORD  the admin password. If unset, admin pages stay locked.
  SKYGAMES_SECRET_KEY      long random string that signs the session cookie.
"""
from __future__ import annotations

import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from functools import wraps

from starlette.requests import Request
from starlette.responses import JSONResponse

ADMIN_PASSWORD = os.environ.get("SKYGAMES_ADMIN_PASSWORD", "")
SECRET_KEY = os.environ.get("SKYGAMES_SECRET_KEY") or secrets.token_urlsafe(32)  # random = sign-outs on restart
MAX_TRIES, WINDOW_S = 5, 600
_failures: dict = defaultdict(deque)
OWN_HEATS_LIMIT = 30


def is_admin(request: Request) -> bool:
    return bool(ADMIN_PASSWORD) and request.session.get("admin") is True


def remember_heat(request: Request, hid: str) -> None:
    """Visitors can reopen and re-score the heats they scored themselves."""
    own = [h for h in request.session.get("heats", []) if h != hid]
    request.session["heats"] = (own + [hid])[-OWN_HEATS_LIMIT:]


def can_open(request: Request, hid: str) -> bool:
    return is_admin(request) or hid in request.session.get("heats", [])


def admin_only(handler):
    @wraps(handler)
    async def inner(request: Request):
        if not ADMIN_PASSWORD:
            return JSONResponse({"error": "Admin sign-in isn't set up on this server.", "locked": True}, 403)
        if not is_admin(request):
            return JSONResponse({"error": "Sign in as an admin to see this.", "locked": True}, 401)
        return await handler(request)
    return inner


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


async def login(request: Request):
    if not ADMIN_PASSWORD:
        return JSONResponse({"error": "Admin sign-in isn't set up on this server."}, 403)
    ip, now = _client(request), time.monotonic()
    q = _failures[ip]
    while q and now - q[0] > WINDOW_S:
        q.popleft()
    if len(q) >= MAX_TRIES:
        return JSONResponse({"error": "Too many attempts. Try again in 10 minutes."}, 429)
    try:
        body = await request.json()
    except Exception:
        body = {}
    pw = str(body.get("password", ""))
    if not hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode()):
        q.append(now)
        return JSONResponse({"error": "Wrong password."}, 401)
    q.clear()
    request.session["admin"] = True
    return JSONResponse({"admin": True})


async def logout(request: Request):
    request.session.pop("admin", None)
    return JSONResponse({"admin": False})


async def me(request: Request):
    return JSONResponse({"admin": is_admin(request), "admin_enabled": bool(ADMIN_PASSWORD)})
