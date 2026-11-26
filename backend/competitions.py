"""Competitions and registrations: storage, validation and HTTP routes.

Public: list competitions, register for one.
Admin:  create / edit / delete competitions, see and export registrations.
"""
from __future__ import annotations

import csv
import io
import json
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

import yaml
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .auth import admin_only, is_admin

SEED = Path(__file__).resolve().parents[1] / "config" / "competitions.yaml"
DISCIPLINES = ("distance", "speed_course", "max_horizontal_speed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS competitions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    disciplines TEXT NOT NULL DEFAULT '[]',
    payment_url TEXT NOT NULL DEFAULT '',
    spots INTEGER,
    registration_open INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS registrations (
    id TEXT PRIMARY KEY,
    competition_id TEXT NOT NULL REFERENCES competitions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    whatsapp TEXT NOT NULL DEFAULT '',
    total_jumps INTEGER NOT NULL,
    tracking_jumps INTEGER NOT NULL,
    license TEXT NOT NULL,
    disciplines TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Invalid(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso_date(v, label):
    try:
        return date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise Invalid(f"{label} must be a date like 2026-12-01.") from None


def _int(v, label, lo=0, hi=1_000_000):
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        raise Invalid(f"{label} must be a whole number.") from None
    if not lo <= n <= hi:
        raise Invalid(f"{label} must be between {lo:,} and {hi:,}.")
    return n


def _text(v, label, lo=1, hi=200):
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    if len(s) < lo:
        raise Invalid(f"{label} is required.")
    if len(s) > hi:
        raise Invalid(f"{label} is too long (max {hi} characters).")
    return s


def clean_competition(body: dict) -> dict:
    start = _iso_date(body.get("start_date"), "Start date")
    end = _iso_date(body.get("end_date") or start, "End date")
    if end < start:
        raise Invalid("End date can't be before the start date.")
    disc = [d for d in body.get("disciplines") or [] if d in DISCIPLINES]
    if not disc:
        raise Invalid("Pick at least one discipline.")
    pay = str(body.get("payment_url") or "").strip()
    if pay and not re.match(r"^https?://\S+$", pay):
        raise Invalid("Payment link must start with https://")
    spots = body.get("spots")
    spots = None if spots in (None, "", 0, "0") else _int(spots, "Spots", 1, 10_000)
    return {"name": _text(body.get("name"), "Name", 2, 120), "location": _text(body.get("location"), "Location", 0, 120),
            "start_date": start, "end_date": end, "disciplines": disc, "payment_url": pay, "spots": spots,
            "registration_open": bool(body.get("registration_open", True)),
            "notes": _text(body.get("notes"), "Notes", 0, 2000)}


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def _phone(v, label, required=True):
    s = re.sub(r"[\s().-]", "", str(v or ""))
    if not s:
        if required:
            raise Invalid(f"{label} is required.")
        return ""
    if s.startswith("00"):
        s = "+" + s[2:]
    if not re.fullmatch(r"\+?\d{7,15}", s):
        raise Invalid(f"{label} should be a number with country code, like +55 11 91234 5678.")
    return s


def clean_registration(body: dict, comp: dict) -> dict:
    """Checked in the order the form shows the fields."""
    name = _text(body.get("name"), "Name", 2, 80)
    email = _text(body.get("email"), "Email", 3, 120).lower()
    if not EMAIL_RE.match(email):
        raise Invalid("Email doesn't look right. Check for typos.")
    phone = _phone(body.get("phone"), "Phone")
    whatsapp = _phone(body.get("whatsapp"), "WhatsApp", required=False) or phone
    total = _int(body.get("total_jumps"), "Total jumps", 0, 100_000)
    tracking = _int(body.get("tracking_jumps"), "Tracking jumps", 0, 100_000)
    if tracking > total:
        raise Invalid("Tracking jumps can't be more than total jumps.")
    lic = _text(body.get("license"), "License country or federation", 2, 80)
    disc = [d for d in body.get("disciplines") or [] if d in comp["disciplines"]]
    if not disc:
        raise Invalid("Pick at least one discipline.")
    return {"name": name, "email": email, "phone": phone, "whatsapp": whatsapp, "total_jumps": total,
            "tracking_jumps": tracking, "license": lic, "disciplines": disc}


class Competitions:
    def __init__(self, db, lock: threading.Lock):
        self.db, self.lock = db, lock
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(registrations)")}
        for col in ("email", "phone", "whatsapp"):   # databases from before contact fields
            if col not in cols:
                self.db.execute(f"ALTER TABLE registrations ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        if not self.db.execute("SELECT 1 FROM competitions LIMIT 1").fetchone() and SEED.exists():
            for c in (yaml.safe_load(SEED.read_text(encoding="utf-8")) or {}).get("competitions", []):
                self.create(clean_competition(c))

    def _row(self, r) -> dict:
        d = dict(r)
        d["disciplines"] = json.loads(d["disciplines"])
        d["registration_open"] = bool(d["registration_open"])
        return d

    def create(self, c: dict) -> str:
        cid = uuid.uuid4().hex[:10]
        with self.lock, self.db:
            self.db.execute("INSERT INTO competitions (id, name, location, start_date, end_date, disciplines, payment_url, "
                            "spots, registration_open, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (cid, c["name"], c["location"], c["start_date"], c["end_date"], json.dumps(c["disciplines"]),
                             c["payment_url"], c["spots"], int(c["registration_open"]), c["notes"], _now()))
        return cid

    def update(self, cid: str, c: dict) -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE competitions SET name=?, location=?, start_date=?, end_date=?, disciplines=?, "
                            "payment_url=?, spots=?, registration_open=?, notes=? WHERE id=?",
                            (c["name"], c["location"], c["start_date"], c["end_date"], json.dumps(c["disciplines"]),
                             c["payment_url"], c["spots"], int(c["registration_open"]), c["notes"], cid))

    def delete(self, cid: str) -> bool:
        with self.lock, self.db:
            return self.db.execute("DELETE FROM competitions WHERE id=?", (cid,)).rowcount > 0

    def get(self, cid: str) -> Optional[dict]:
        r = self.db.execute("SELECT * FROM competitions WHERE id=?", (cid,)).fetchone()
        return self._row(r) if r else None

    def list(self) -> List[dict]:
        rows = self.db.execute("SELECT c.*, (SELECT COUNT(*) FROM registrations r WHERE r.competition_id=c.id) AS registered "
                               "FROM competitions c ORDER BY start_date").fetchall()
        return [self._row(r) for r in rows]

    def register(self, cid: str, reg: dict) -> str:
        rid = uuid.uuid4().hex[:10]
        with self.lock, self.db:
            self.db.execute("INSERT INTO registrations (id, competition_id, name, email, phone, whatsapp, total_jumps, "
                            "tracking_jumps, license, disciplines, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (rid, cid, reg["name"], reg["email"], reg["phone"], reg["whatsapp"], reg["total_jumps"],
                             reg["tracking_jumps"], reg["license"],
                             json.dumps(reg["disciplines"]), _now()))
        return rid

    def registrations(self, cid: str) -> List[dict]:
        rows = self.db.execute("SELECT * FROM registrations WHERE competition_id=? ORDER BY created_at", (cid,)).fetchall()
        return [{**dict(r), "disciplines": json.loads(r["disciplines"])} for r in rows]

    def count(self, cid: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM registrations WHERE competition_id=?", (cid,)).fetchone()[0]

    def delete_registration(self, rid: str) -> bool:
        with self.lock, self.db:
            return self.db.execute("DELETE FROM registrations WHERE id=?", (rid,)).rowcount > 0


# ------------------------------------------------------------------ HTTP
_reg_attempts: dict = defaultdict(deque)
REG_LIMIT, REG_WINDOW = 10, 3600


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def _err(status, msg):
    return JSONResponse({"error": msg}, status_code=status)


def _status(c: dict) -> str:
    today = date.today().isoformat()
    if c["end_date"] < today:
        return "past"
    if not c["registration_open"]:
        return "closed"
    if c["spots"] and c.get("registered", 0) >= c["spots"]:
        return "full"
    return "open"


def _public(c: dict, admin: bool) -> dict:
    out = {k: c[k] for k in ("id", "name", "location", "start_date", "end_date", "disciplines", "spots",
                             "registration_open", "notes")}
    out["status"] = _status(c)
    out["spots_left"] = max(0, c["spots"] - c.get("registered", 0)) if c["spots"] else None
    if admin:
        out["payment_url"] = c["payment_url"]
        out["registered"] = c.get("registered", 0)
    return out


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


def routes(comps: Competitions) -> List[Route]:
    async def list_comps(request: Request):
        admin = is_admin(request)
        return JSONResponse({"competitions": [_public(c, admin) for c in comps.list()]})

    async def register(request: Request):
        c = comps.get(request.path_params["cid"])
        if not c:
            return _err(404, "Competition not found.")
        c["registered"] = comps.count(c["id"])
        st = _status(c)
        if st != "open":
            return _err(409, {"past": "This competition has finished.", "closed": "Registration is closed.",
                              "full": "This competition is full."}[st])
        body = await _body(request)
        if body.get("website"):  # honeypot field, invisible to people
            return JSONResponse({"id": "ok", "payment_url": c["payment_url"]}, status_code=201)
        ip, now = _ip(request), time.monotonic()
        q = _reg_attempts[ip]
        while q and now - q[0] > REG_WINDOW:
            q.popleft()
        if len(q) >= REG_LIMIT:
            return _err(429, "Too many registrations from this connection. Try again later.")
        try:
            reg = clean_registration(body, c)
        except Invalid as e:
            return _err(400, str(e))
        q.append(now)
        rid = comps.register(c["id"], reg)
        return JSONResponse({"id": rid, "competition": c["name"], "payment_url": c["payment_url"]}, status_code=201)

    @admin_only
    async def create(request: Request):
        try:
            cid = comps.create(clean_competition(await _body(request)))
        except Invalid as e:
            return _err(400, str(e))
        return JSONResponse(_public({**comps.get(cid), "registered": 0}, True), status_code=201)

    @admin_only
    async def update(request: Request):
        cid = request.path_params["cid"]
        if not comps.get(cid):
            return _err(404, "Competition not found.")
        try:
            comps.update(cid, clean_competition(await _body(request)))
        except Invalid as e:
            return _err(400, str(e))
        return JSONResponse(_public({**comps.get(cid), "registered": comps.count(cid)}, True))

    @admin_only
    async def delete(request: Request):
        return JSONResponse({"deleted": True}) if comps.delete(request.path_params["cid"]) else _err(404, "Competition not found.")

    @admin_only
    async def regs(request: Request):
        cid = request.path_params["cid"]
        if not comps.get(cid):
            return _err(404, "Competition not found.")
        return JSONResponse({"registrations": comps.registrations(cid)})

    @admin_only
    async def regs_csv(request: Request):
        c = comps.get(request.path_params["cid"])
        if not c:
            return _err(404, "Competition not found.")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Name", "Email", "Phone", "WhatsApp", "Total jumps", "Tracking jumps", "License country / federation", "Disciplines", "Registered (UTC)"])
        for r in comps.registrations(c["id"]):
            # leading = + - @ would run as formulas in Excel
            safe = [("'" + v) if isinstance(v, str) and v[:1] in "=+-@" else v for v in
                    (r["name"], r["email"], r["phone"], r["whatsapp"], r["total_jumps"], r["tracking_jumps"], r["license"], ", ".join(r["disciplines"]), r["created_at"])]
            w.writerow(safe)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", c["name"]).strip("_") or "competition"
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}_registrations.csv"'})

    @admin_only
    async def delete_reg(request: Request):
        return JSONResponse({"deleted": True}) if comps.delete_registration(request.path_params["rid"]) else _err(404, "Registration not found.")

    return [
        Route("/api/competitions", list_comps, methods=["GET"]),
        Route("/api/competitions", create, methods=["POST"]),
        Route("/api/competitions/{cid}", update, methods=["PUT"]),
        Route("/api/competitions/{cid}", delete, methods=["DELETE"]),
        Route("/api/competitions/{cid}/registrations", register, methods=["POST"]),
        Route("/api/competitions/{cid}/registrations", regs, methods=["GET"]),
        Route("/api/competitions/{cid}/registrations.csv", regs_csv, methods=["GET"]),
        Route("/api/registrations/{rid}", delete_reg, methods=["DELETE"]),
    ]
