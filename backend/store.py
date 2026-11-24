"""Heats and their original files, in SQLite.

Original CSVs are kept so a heat can be re-scored with different rules
without uploading again. Swap this module for PostgreSQL later without
touching the API or the engine."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS heats (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    task TEXT NOT NULL,
    rule_values TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '{}',
    payload TEXT,
    created_by TEXT NOT NULL DEFAULT 'public'
);
CREATE TABLE IF NOT EXISTS heat_files (
    id TEXT PRIMARY KEY,
    heat_id TEXT NOT NULL REFERENCES heats(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    flyer TEXT NOT NULL,
    file_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    data BLOB NOT NULL,
    UNIQUE (heat_id, sha256)
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(SCHEMA)
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(heats)")}
        if "created_by" not in cols:  # databases from before admin sign-in
            self._db.execute("ALTER TABLE heats ADD COLUMN created_by TEXT NOT NULL DEFAULT 'public'")
        self._lock = threading.Lock()

    # heats --------------------------------------------------------------------
    def create_heat(self, name: str, task: str, rule_values: dict, files: List[dict],
                    created_by: str = "public") -> str:
        hid = uuid.uuid4().hex[:12]
        now = _now()
        with self._lock, self._db:
            self._db.execute("INSERT INTO heats (id, name, task, rule_values, created_at, updated_at, created_by) "
                             "VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (hid, name, task, json.dumps(rule_values), now, now, created_by))
            seen = set()
            for i, f in enumerate(files):
                sha = hashlib.sha256(f["data"]).hexdigest()
                if sha in seen:
                    continue  # same file uploaded twice in one heat
                seen.add(sha)
                self._db.execute("INSERT INTO heat_files (id, heat_id, position, flyer, file_name, sha256, data) "
                                 "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                 (uuid.uuid4().hex[:12], hid, i, f["flyer"], f["file_name"], sha, f["data"]))
        return hid

    def update_heat(self, hid: str, *, name=None, task=None, rule_values=None, flyers: Optional[dict] = None,
                    summary=None, payload=None):
        sets, args = ["updated_at = ?"], [_now()]
        for col, val in (("name", name), ("task", task)):
            if val is not None:
                sets.append(f"{col} = ?"); args.append(val)
        for col, val in (("rule_values", rule_values), ("summary", summary), ("payload", payload)):
            if val is not None:
                sets.append(f"{col} = ?"); args.append(json.dumps(val, default=str))
        with self._lock, self._db:
            self._db.execute(f"UPDATE heats SET {', '.join(sets)} WHERE id = ?", (*args, hid))
            for fid, flyer in (flyers or {}).items():
                self._db.execute("UPDATE heat_files SET flyer = ? WHERE id = ? AND heat_id = ?", (flyer, fid, hid))

    def get_heat(self, hid: str) -> Optional[dict]:
        r = self._db.execute("SELECT * FROM heats WHERE id = ?", (hid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["rule_values"] = json.loads(d["rule_values"])
        d["summary"] = json.loads(d["summary"])
        d["payload"] = json.loads(d["payload"]) if d["payload"] else None
        return d

    def files(self, hid: str) -> List[dict]:
        rows = self._db.execute("SELECT id, flyer, file_name, data FROM heat_files WHERE heat_id = ? "
                                "ORDER BY position", (hid,)).fetchall()
        return [dict(r) for r in rows]

    def list_heats(self) -> List[dict]:
        rows = self._db.execute("SELECT id, name, task, created_at, updated_at, summary, created_by FROM heats "
                                "ORDER BY updated_at DESC").fetchall()
        return [{**dict(r), "summary": json.loads(r["summary"])} for r in rows]

    def delete_heat(self, hid: str) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM heats WHERE id = ?", (hid,))
        return cur.rowcount > 0
