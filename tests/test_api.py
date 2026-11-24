"""End-to-end API test against a real uvicorn server (no extra test deps)."""
import io
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile

import pytest

os.environ.setdefault("SKYGAMES_DB", ":memory:")
os.environ["SKYGAMES_ADMIN_PASSWORD"] = "test-pass"
import http.cookiejar
uvicorn = pytest.importorskip("uvicorn")


@pytest.fixture(scope="module")
def base():
    from backend.app import app
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    th.join(5)


def browser():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


_default = browser()


def call(base, method, path, data=None, headers=None, who=None):
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    try:
        with (who or _default).open(req) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def multipart(fields, files):
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields:
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (fn, data) in files:
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\n'
                  f'Content-Type: text/csv\r\n\r\n'.encode() + data + b"\r\n")
    out.write(f"--{b}--\r\n".encode())
    return out.getvalue(), {"Content-Type": f"multipart/form-data; boundary={b}"}


def test_full_flow(base, fs1_heat):
    st, body, _ = call(base, "GET", "/api/meta")
    meta = json.loads(body)
    assert st == 200 and {t["key"] for t in meta["tasks"]} == {"distance", "speed_course", "max_horizontal_speed"}
    assert any(p["path"] == "window.top_ft" and p["default"] == 11000 for p in meta["params"])

    fields = [("name", "API heat"), ("task", "distance"), ("rule_values", "{}")] + [("flyers", n) for n, _, _ in fs1_heat]
    data, hdr = multipart(fields, [("files", (fn, b)) for _, b, fn in fs1_heat])
    st, body, _ = call(base, "POST", "/api/heats", data, hdr)
    assert st == 201, body
    p = json.loads(body)
    hid = p["heat"]["id"]
    assert p["ranking"][0]["flyer"] == "Mart" and p["ranking"][0]["rank"] == 1
    assert len(p["map"]) == 5 and set(p["charts"]["profiles"]) == {n for n, _, _ in fs1_heat}
    assert all(f["color"] for f in p["flyers"])

    # change the rules + task + a name, no re-upload
    fid = p["flyers"][0]["file_id"]
    req = json.dumps({"task": "speed_course", "rule_values": {"window.top_ft": 10000},
                      "flyers": {fid: "Bamba R."}}).encode()
    st, body, _ = call(base, "POST", f"/api/heats/{hid}/analyze", req, {"Content-Type": "application/json"})
    p2 = json.loads(body)
    assert st == 200 and p2["task"]["key"] == "speed_course"
    assert p2["rules"]["values"]["window.top_ft"] == 10000
    assert any(f["flyer"] == "Bamba R." for f in p2["flyers"])
    assert p2["rules"]["fingerprint"] != p["rules"]["fingerprint"]

    # invalid rules come back as a readable 400
    bad = json.dumps({"rule_values": {"window.top_ft": 3000}}).encode()
    st, body, _ = call(base, "POST", f"/api/heats/{hid}/analyze", bad, {"Content-Type": "application/json"})
    assert st == 400 and "Window" in json.loads(body)["error"]

    # saved heats are admin-only
    st, _, _ = call(base, "GET", "/api/heats")
    assert st == 401
    st, _, _ = call(base, "DELETE", f"/api/heats/{hid}")
    assert st == 401
    admin = browser()
    st, _, _ = call(base, "POST", "/api/login", json.dumps({"password": "nope"}).encode(), {"Content-Type": "application/json"}, admin)
    assert st == 401
    st, _, _ = call(base, "POST", "/api/login", json.dumps({"password": "test-pass"}).encode(), {"Content-Type": "application/json"}, admin)
    assert st == 200
    st, body, _ = call(base, "GET", "/api/heats", who=admin)
    assert any(h["id"] == hid and h["summary"]["winner"] and h["created_by"] == "public" for h in json.loads(body)["heats"])

    # another visitor can't open someone else's heat
    st, _, _ = call(base, "GET", f"/api/heats/{hid}", who=browser())
    assert st == 404

    st, kml, hd = call(base, "GET", f"/api/heats/{hid}/download/kml")
    assert st == 200 and kml.startswith(b"<?xml") and "attachment" in hd["content-disposition"]
    st, z, _ = call(base, "GET", f"/api/heats/{hid}/download/zip")
    names = zipfile.ZipFile(io.BytesIO(z)).namelist()
    assert "rules_used.yaml" in names and sum(n.startswith("original_files/") for n in names) == 5
    assert any(n.endswith("_profile.png") for n in names)

    st, _, _ = call(base, "DELETE", f"/api/heats/{hid}", who=admin)
    assert st == 200
    st, _, _ = call(base, "GET", f"/api/heats/{hid}", who=admin)
    assert st == 404


def test_bad_file_is_reported_not_fatal(base, fs1_heat):
    files = [("files", ("junk.csv", b"time,lat\n1,2\n"))] + [("files", (fn, b)) for _, b, fn in fs1_heat[:2]]
    data, hdr = multipart([("name", "Mixed"), ("task", "distance")], files)
    st, body, _ = call(base, "POST", "/api/heats", data, hdr)
    p = json.loads(body)
    assert st == 201
    junk = next(f for f in p["flyers"] if f["file_name"] == "junk.csv")
    assert not junk["ok"] and junk["error"]["code"] == "MISSING_COLUMNS"
    assert p["ranking"][-1]["rank"] is None


def test_front_end_served(base):
    st, body, _ = call(base, "GET", "/")
    assert st == 200 and b"<html" in body.lower()
