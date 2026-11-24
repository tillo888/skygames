import json

from test_api import base, browser, call  # noqa: F401  (reuse the live server fixture)

J = {"Content-Type": "application/json"}


def _post(base, path, body, who=None, method="POST"):
    st, b, _ = call(base, method, path, json.dumps(body).encode(), J, who)
    return st, json.loads(b) if b else None


def _admin(base):
    a = browser()
    st, _ = _post(base, "/api/login", {"password": "test-pass"}, a)
    assert st == 200
    return a


def test_seeded_events_are_public(base):
    st, b, _ = call(base, "GET", "/api/competitions", who=browser())
    comps = json.loads(b)["competitions"]
    assert st == 200
    assert [c["name"] for c in comps][:2] == ["Skygames Boituva", "Skygames Castellón"]
    assert comps[0]["start_date"] == "2026-12-01" and comps[1]["end_date"] == "2027-08-12"
    assert "payment_url" not in comps[0] and "registered" not in comps[0]   # admin-only fields


def test_register_validate_and_admin_views(base):
    admin = _admin(base)
    st, c = _post(base, "/api/competitions", {"name": "Test Cup", "location": "Eloy, USA", "start_date": "2030-05-01",
                                              "end_date": "2030-05-03", "disciplines": ["distance", "speed_course"],
                                              "payment_url": "https://pay.example/skygames", "spots": 2}, admin)
    assert st == 201, c
    cid = c["id"]
    visitor = browser()

    bad = [({"name": "A"}, "Name"),
           ({"name": "Ana Lopez", "total_jumps": "lots"}, "Total jumps"),
           ({"name": "Ana Lopez", "total_jumps": 100, "tracking_jumps": 200, "license": "ES"}, "Tracking jumps"),
           ({"name": "Ana Lopez", "total_jumps": 300, "tracking_jumps": 50, "license": "RFAE Spain", "disciplines": ["freestyle"]}, "discipline")]
    for body, word in bad:
        st, r = _post(base, f"/api/competitions/{cid}/registrations", body, visitor)
        assert st == 400 and word.lower() in r["error"].lower(), (body, r)

    ok = {"name": "Ana Lopez", "total_jumps": 300, "tracking_jumps": 50, "license": "RFAE Spain", "disciplines": ["distance"]}
    st, r = _post(base, f"/api/competitions/{cid}/registrations", ok, visitor)
    assert st == 201 and r["payment_url"] == "https://pay.example/skygames"
    st, _ = _post(base, f"/api/competitions/{cid}/registrations", {**ok, "name": "=HYPERLINK(1)"}, visitor)
    assert st == 201
    st, r = _post(base, f"/api/competitions/{cid}/registrations", {**ok, "name": "Third Flyer"}, visitor)
    assert st == 409 and "full" in r["error"]

    # visitors can't read registrations or edit events
    assert call(base, "GET", f"/api/competitions/{cid}/registrations", who=visitor)[0] == 401
    assert _post(base, f"/api/competitions/{cid}", {"name": "x"}, visitor, "PUT")[0] == 401

    st, b, _ = call(base, "GET", f"/api/competitions/{cid}/registrations", who=admin)
    regs = json.loads(b)["registrations"]
    assert [r["name"] for r in regs] == ["Ana Lopez", "=HYPERLINK(1)"] and regs[0]["tracking_jumps"] == 50
    st, csvb, hd = call(base, "GET", f"/api/competitions/{cid}/registrations.csv", who=admin)
    text = csvb.decode("utf-8-sig")
    assert st == 200 and "Ana Lopez,300,50,RFAE Spain,distance" in text and "'=HYPERLINK(1)" in text

    # close registration
    st, c2 = _post(base, f"/api/competitions/{cid}", {**c, "registration_open": False}, admin, "PUT")
    assert st == 200 and c2["status"] == "closed"
    st, _ = _post(base, f"/api/competitions/{cid}/registrations", {**ok, "name": "Late Flyer"}, visitor)
    assert st == 409

    assert call(base, "DELETE", f"/api/competitions/{cid}", who=admin)[0] == 200
    st, b, _ = call(base, "GET", "/api/competitions", who=admin)
    assert cid not in [x["id"] for x in json.loads(b)["competitions"]]


def test_bad_competition_rejected(base):
    admin = _admin(base)
    st, r = _post(base, "/api/competitions", {"name": "Bad", "start_date": "2030-05-05", "end_date": "2030-05-01",
                                              "disciplines": ["distance"]}, admin)
    assert st == 400 and "before" in r["error"]
    st, r = _post(base, "/api/competitions", {"name": "Bad", "start_date": "2030-05-05", "disciplines": ["distance"],
                                              "payment_url": "javascript:alert(1)"}, admin)
    assert st == 400 and "https" in r["error"]
