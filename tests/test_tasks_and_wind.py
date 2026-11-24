import json
import xml.dom.minidom

import pytest

from skygames_engine import analyze_file, analyze_heat, load_rules, render_heat_artifacts
from skygames_engine.config import rules_fingerprint
from skygames_engine.ranking import rank_entries
from skygames_engine.wind import ManualWindProvider, WindCache, WindProfile
from synth import Jumper, simulate, to_flysight1


def test_radial_vs_projection_close_for_straight_flight():
    data = to_flysight1(simulate(Jumper("S", heading_wander_deg=0, seed=7)))
    a = analyze_file(data, "S", "x", load_rules()).scores["speed_course"]
    b = analyze_file(data, "S", "x", load_rules(overrides={"tasks": {"speed_course": {"measure": "radial_from_start"}}})).scores["speed_course"]
    assert a.valid and b.valid
    assert a.score == pytest.approx(b.score, abs=0.05)


def test_averaging_never_exceeds_single_sample_peak():
    data = to_flysight1(simulate(Jumper("S", seed=8)))
    raw = analyze_file(data, "S", "x", load_rules()).scores["max_horizontal_speed"].score
    avg = analyze_file(data, "S", "x", load_rules(overrides={"tasks": {"max_horizontal_speed": {"averaging_s": 3}}})
                       ).scores["max_horizontal_speed"].score
    assert avg <= raw and avg > raw - 5


def test_ranking_ties_and_dnf():
    r = rank_entries([{"flyer": "a", "score": 10}, {"flyer": "b", "score": 12}, {"flyer": "c", "score": None},
                      {"flyer": "d", "score": 12}], "desc")
    assert [(e["flyer"], e["rank"]) for e in r] == [("b", 1), ("d", 1), ("a", 3), ("c", None)]


def test_rules_validation_rejects_bad_values():
    with pytest.raises(Exception):
        load_rules(overrides={"window": {"top_ft": 4000}})          # below bottom
    with pytest.raises(Exception):
        load_rules(overrides={"window": {"topp_ft": 11000}})        # typo'd key
    assert rules_fingerprint(load_rules()) != rules_fingerprint(load_rules(overrides={"window": {"top_ft": 10000}}))


def _wind(u, v):
    return WindProfile([0, 3000, 6000], [u] * 3, [v] * 3)


def test_zero_wind_adjustment_is_identity(rules):
    data = to_flysight1(simulate(Jumper("W", seed=9)))
    r = analyze_file(data, "W", "x", rules, wind_provider=ManualWindProvider(_wind(0, 0)))
    for k in r.scores:
        assert r.scores_wind[k].score == pytest.approx(r.scores[k].score, rel=1e-6)


def test_wind_adjustment_removes_tailwind(rules):
    """Same flyer, with and without a 10 m/s tailwind: air-relative scores agree."""
    calm = to_flysight1(simulate(Jumper("C", heading_deg=90, heading_wander_deg=0, seed=10)))
    tail = to_flysight1(simulate(Jumper("C", heading_deg=90, heading_wander_deg=0, seed=10, wind_east_ms=10)))
    rc = analyze_file(calm, "C", "x", rules)
    rt = analyze_file(tail, "C", "x", rules, wind_provider=ManualWindProvider(_wind(10, 0)))
    assert rt.scores["distance"].score > rc.scores["distance"].score + 400       # ground score inflated
    assert rt.scores_wind["distance"].score == pytest.approx(rc.scores["distance"].score, rel=0.002)
    assert rt.scores_wind["speed_course"].score == pytest.approx(rc.scores["speed_course"].score, abs=0.1)
    assert rt.scores_wind["max_horizontal_speed"].score == pytest.approx(rc.scores["max_horizontal_speed"].score, abs=1.5)


def test_wind_from_direction_convention():
    p = WindProfile.from_speed_dir([0, 1000], [10, 10], [270, 270])   # westerly: blows toward east
    u, v = p.at(500)
    assert u == pytest.approx(10) and v == pytest.approx(0, abs=1e-9)


def test_wind_cache_roundtrip():
    c = WindCache(":memory:")
    k = WindCache.make_key("open_meteo", 29.06, -81.31, "2025-08-16T09:00", 0.25)
    assert k == "open_meteo|29.0|-81.25|2025-08-16T09:00"
    c.put(k, _wind(3, 4))
    assert c.get(k).u_ms == [3, 3, 3]


def test_heat_end_to_end(rules, fs1_heat):
    bad = ("Broken", b"time,lat\n1,2\n", "broken.csv")
    heat = analyze_heat(fs1_heat + [bad], "distance", rules, heat_name='Heat "1" & <finals>')
    assert heat.winner["flyer"] == "Mart"
    assert heat.ranking[-1]["flyer"] == "Broken" and heat.ranking[-1]["rank"] is None
    arts = render_heat_artifacts(heat)
    kml = next(v for k, v in arts.items() if k.endswith(".kml"))
    xml.dom.minidom.parseString(kml)                       # valid XML despite quotes/ampersand
    gj = json.loads(next(v for k, v in arts.items() if k.endswith(".geojson")))
    assert sum(f["properties"]["kind"] == "track" for f in gj["features"]) == 5
    assert sum(k.endswith("_profile.png") for k in arts) == 5
    res = json.loads(next(v for k, v in arts.items() if k.endswith("_results.json")))
    assert res["rules_version"] == "2026.1" and res["rules_fingerprint"]
