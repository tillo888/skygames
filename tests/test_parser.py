import pytest

from skygames_engine import analyze_file, load_rules
from skygames_engine.parser import FileValidationError, parse_track
from synth import Jumper, simulate, to_flysight1, to_flysight2


def _df():
    return simulate(Jumper("P", seed=3))


def test_flysight1_and_2_give_same_scores(rules):
    df = _df()
    a = analyze_file(to_flysight1(df), "P", "a.csv", rules)
    b = analyze_file(to_flysight2(df), "P", "b.csv", rules)
    assert a.ok and b.ok
    assert b.track.meta["format"] == "flysight2"
    assert a.scores["distance"].score == pytest.approx(b.scores["distance"].score, rel=1e-6)


def test_generic_csv_in_feet_and_knots(rules):
    df = _df()
    g = df.rename(columns={"hMSL": "alt_ft", "velN": "vn_kt", "velE": "ve_kt", "velD": "vd_kt",
                           "lat": "latitude", "lon": "longitude"})
    g["alt_ft"] = g["alt_ft"] / 0.3048
    for c in ("vn_kt", "ve_kt", "vd_kt"):
        g[c] = g[c] / 0.514444
    g["time"] = g["time"].dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    gb = g.to_csv(index=False).encode()
    ref = analyze_file(to_flysight1(df), "P", "a.csv", rules)
    got = analyze_file(gb, "P", "g.csv", rules, column_units={"vn": "kt", "ve": "kt", "vd": "kt"})
    assert got.ok, got.error
    assert got.scores["distance"].score == pytest.approx(ref.scores["distance"].score, rel=1e-3)


def test_feet_heuristic_warns(rules):
    df = _df()
    df["hMSL"] = df["hMSL"] / 0.3048
    g = df.rename(columns={"hMSL": "altitude"})
    tr = parse_track(g.to_csv(index=False).encode(), "P", "x", rules)
    assert any("feet" in w for w in tr.warnings)


@pytest.mark.parametrize("payload,code", [
    (b"", "EMPTY_FILE"),
    (b"time,lat,lon\n2025-01-01T00:00:00Z,1,2\n", "MISSING_COLUMNS"),
])
def test_bad_files_fail_fast(rules, payload, code):
    with pytest.raises(FileValidationError) as e:
        parse_track(payload, "x", "x", rules)
    assert e.value.code == code


def test_hop_n_pop_rejected(rules):
    data = to_flysight1(simulate(Jumper("Low", exit_alt_m=1500, deploy_alt_ft=3000, seed=4)))
    r = analyze_file(data, "Low", "x", rules)
    assert not r.ok and r.error["code"] == "TOO_LOW"


def test_agl_mode_high_dropzone():
    """A DZ at 1,600 m MSL: MSL rules miss the opening band, AGL scores it."""
    data = to_flysight1(simulate(Jumper("Hi", exit_alt_m=1600 + 4100, ground_m=1600, deploy_alt_ft=3600 + 5249, seed=5)))
    msl = analyze_file(data, "Hi", "x", load_rules())
    agl = analyze_file(data, "Hi", "x", load_rules(overrides={"altitude_reference": {"mode": "AGL"}}))
    assert not msl.ok
    assert agl.ok and agl.scores["distance"].valid
    assert agl.track.ground_elevation_m == pytest.approx(1600, abs=2)


def test_spike_filter_removes_glitch(rules):
    df = _df()
    df.loc[300, "velE"] += 90  # one-sample 90 m/s glitch inside the window
    r = analyze_file(to_flysight1(df), "P", "x", rules)
    clean = analyze_file(to_flysight1(_df()), "P", "x", rules)
    assert any("spike" in w for w in r.warnings)
    assert r.scores["max_horizontal_speed"].score == pytest.approx(clean.scores["max_horizontal_speed"].score, abs=2)
