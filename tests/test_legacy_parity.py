"""The refactor must reproduce v3.9 results with the default rules."""
import numpy as np
import pytest

from legacy_harness import legacy_analyze
from skygames_engine import analyze_file, load_rules
from synth import HEAT, Jumper, simulate, to_flysight1

# Legacy did no quality filtering; switch the new filters off for a pure algorithm comparison.
PARITY = load_rules(overrides={"data_quality": {"max_h_acc_m": None, "max_v_acc_m": None,
                                                "min_num_sv": None, "max_accel_ms2": None}})

EXTRA = [Jumper("Slow", h_ms=30, v_ms=45, seed=21), Jumper("Fast", h_ms=70, v_ms=28, seed=22, rate_hz=20),
         Jumper("Hz2", seed=23, rate_hz=2), Jumper("LowDeploy", deploy_alt_ft=2000, seed=24),
         Jumper("Turning", heading_wander_deg=60, seed=25)]


@pytest.mark.parametrize("j", HEAT + EXTRA, ids=lambda j: j.name)
def test_matches_v39(j):
    data = to_flysight1(simulate(j))
    old = legacy_analyze(data)
    new = analyze_file(data, j.name, "x.csv", PARITY)
    assert new.ok, new.error
    ev = new.events
    assert ev.exit_idx == old["exit_idx"]
    assert ev.open_idx == old["open_idx"]
    assert abs(ev.A.t - (old["p11"]["time"] - old["exit_time"]).total_seconds() - new.track.t[ev.exit_idx]) < 1e-5  # µs rounding of timedelta
    assert new.scores["distance"].score == pytest.approx(old["straight_m"], abs=1e-6)
    assert new.summary["max_glide"] == pytest.approx(old["max_glide"], abs=1e-9)
    assert new.scores["max_horizontal_speed"].score == pytest.approx(old["max_h_kph"], abs=1e-9)
    assert new.summary["opening_alt_ft"] == pytest.approx(old["opening_alt_ft"], abs=1e-9)
    if old["time_to_1000m_s"] is None:
        assert not new.scores["speed_course"].valid
    else:
        assert new.scores["speed_course"].score == pytest.approx(old["time_to_1000m_s"], abs=1e-6)
