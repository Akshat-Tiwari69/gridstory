"""Lap comparison: synthetic laps for the maths, cached real sessions for the golden checks."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from fastf1.exceptions import DataNotLoadedError

from app.analysis import compare as cmp
from app.main import app
from app.models.f1 import Corner, LapData, LapRef, TelemetryDataset
from app.services import f1_data

client = TestClient(app)
livedata = pytest.mark.livedata
LENGTH = 4000.0
CORNERS = [Corner(number=i + 1, x=0, y=0, angle=0, distance=d)
           for i, d in enumerate((800.0, 1800.0, 2800.0, 3600.0))]


def synth(depth=(35, 35, 35, 35), brake_shift=0.0, speed_k=1.0, dt=0.125, skip_brake=False):
    """A lap sampled every `dt` s: 75 m/s base, a speed dip at each corner, brake before it."""
    d, t, rows = 0.0, 0.0, []
    while d < LENGTH:
        v = 75.0 - sum(dp * math.exp(-(((d - c.distance) / 60) ** 2))
                       for dp, c in zip(depth, CORNERS))
        v *= speed_k
        braking = any(c.distance - 180 - brake_shift <= d <= c.distance - 20 for c in CORNERS)
        past_apex = any(c.distance - 20 < d < c.distance + 15 for c in CORNERS)
        rows.append((d, t, v * 3.6, 0.0 if braking or past_apex else 100.0,
                     0 if skip_brake else int(braking), 4))
        d += v * dt
        t += dt
    # End exactly on the line so the lap time is the time at LENGTH, as in real timing.
    (d0, t0, *_), last = rows[-2], rows[-1]
    t_end = t0 + (LENGTH - d0) * (last[1] - t0) / (last[0] - d0)
    rows[-1] = (LENGTH, t_end, *last[2:])
    c = list(zip(*rows))
    return TelemetryDataset(
        distance=list(c[0]), time=list(c[1]), speed=list(c[2]), throttle=list(c[3]),
        brake=list(c[4]), gear=list(c[5]), rpm=[0.0] * len(rows), drs=[0] * len(rows),
        x=[0.0] * len(rows), y=[0.0] * len(rows),
    )


def ref(tel, driver="AAA", lap=1, requested=0, **kw):
    return LapRef(driver=driver, lap_number=lap, requested_lap=requested,
                  lap_time=tel.time[-1], label=f"{driver} L{lap}", **kw)


def run(tel_a, tel_b, corners=CORNERS, **kw):
    return cmp.compare_laps(ref(tel_a, "AAA", 1, **kw), tel_a, ref(tel_b, "BBB", 2), tel_b, corners)


def codes(result):
    return {w.code for w in result.warnings}


def test_identical_laps_give_zero_delta_and_no_findings():
    tel = synth()
    r = cmp.compare_laps(ref(tel), tel, ref(tel), tel, CORNERS)
    assert max(abs(x) for x in r.delta_s) == 0
    assert r.finish.delta_s == 0 and r.finish.within_tolerance
    assert r.findings == [] and all(s.gain_a_s == 0 for s in r.segments)
    assert "same_lap" in codes(r)


def test_reversed_selection_reverses_delta_and_gains():
    a, b = synth(), synth(depth=(35, 20, 35, 35), speed_k=1.01)
    ab, ba = run(a, b), run(b, a)
    assert np.allclose(ab.delta_s, -np.array(ba.delta_s), atol=1e-4)
    assert ab.finish.delta_s == pytest.approx(-ba.finish.delta_s, abs=1e-4)
    assert [s.gain_a_s for s in ab.segments] == pytest.approx([-s.gain_a_s for s in ba.segments],
                                                              abs=1e-4)
    assert ab.findings[0].segment_id == ba.findings[0].segment_id
    assert ab.findings[0].winner != ba.findings[0].winner


def test_delta_sign_and_finish_match_official_difference():
    slow, fast = synth(), synth(speed_k=1.02)
    r = run(slow, fast)  # B is faster, so B is ahead: delta = t_B - t_A < 0
    assert r.delta_s[-1] < 0
    assert r.finish.delta_s == pytest.approx(fast.time[-1] - slow.time[-1], abs=0.05)
    assert r.finish.within_tolerance and r.finish.official_delta_s < 0


def test_segments_tile_the_lap_and_sum_to_the_finish_delta():
    r = run(synth(), synth(depth=(35, 20, 35, 30), speed_k=1.01))
    segs = r.segments
    assert segs[0].start_m == 0
    assert segs[-1].end_m == pytest.approx(r.alignment.common_length_m, abs=0.1)
    assert all(x.end_m == y.start_m for x, y in zip(segs, segs[1:]))
    assert sum(s.gain_a_s for s in segs) == pytest.approx(r.finish.delta_s, abs=1e-3)
    assert {s.kind for s in segs} == {"corner", "straight"}


def test_close_corners_absorb_sub_grid_gaps():
    corners = [c.model_copy(update={"distance": d})
               for c, d in zip(CORNERS, (800.0, 1043.0, 1800.0, 2800.0))]
    r = run(synth(), synth(speed_k=1.02), corners)
    assert all(a.end_m == b.start_m for a, b in zip(r.segments, r.segments[1:]))
    assert sum(s.gain_a_s for s in r.segments) == pytest.approx(r.finish.delta_s, abs=1e-3)


def test_discrete_channels_choose_a_recorded_sample():
    sampled = cmp._nearest(np.array([0, 4, 5, 6, 10]), np.array([0, 10]), np.array([2, 6]))
    assert sampled.tolist() == [2, 2, 2, 6, 6]


def test_findings_are_the_biggest_visible_segments():
    r = run(synth(), synth(depth=(35, 15, 25, 35)))  # B carries more speed through T2 and T3
    by_gain = sorted(r.segments, key=lambda s: -abs(s.gain_a_s))
    visible = [s for s in by_gain if abs(s.gain_a_s) >= cmp.MIN_GAIN_S]
    assert len(visible) >= 2
    assert [f.segment_id for f in r.findings] == [s.id for s in visible[:cmp.MAX_FINDINGS]]
    top = r.findings[0]
    assert top.segment_id == "c2" and top.winner == "B"
    seg = next(s for s in r.segments if s.id == "c2")
    assert top.gain_s == pytest.approx(abs(seg.gain_a_s), abs=1e-3)
    assert "T2" in top.text and "BBB L2" in top.text and "more minimum speed" in top.text


def test_brake_point_difference_reported_when_above_sample_spacing():
    r = run(synth(), synth(brake_shift=40.0, depth=(35, 20, 35, 35)))
    cm = next(s for s in r.segments if s.id == "c1").corner
    assert cm.a.brake_on_m is not None and cm.brake_diff_m == pytest.approx(-40, abs=12)
    assert cm.brake_diff_significant


def test_differences_below_sampling_resolution_are_not_reported():
    # Brake points 3 m apart with ~9 m between samples, and 0.01 s overall: pure noise.
    a, b = synth(), synth(brake_shift=3.0, speed_k=1.0003)
    r = run(a, b)
    assert r.alignment.resolution_a_m > 3
    assert not any(s.corner.brake_diff_significant for s in r.segments if s.corner)
    assert abs(r.finish.delta_s) < cmp.MIN_GAIN_S * 2
    assert all("brakes" not in f.text for f in r.findings)
    quiet = run(a, synth(speed_k=1.0005))
    assert quiet.findings == []


def test_missing_brake_channel_is_not_invented():
    r = run(synth(), synth(skip_brake=True))
    assert "brake_missing" in codes(r)
    assert r.channels.brake_b is None and r.channels.brake_a is not None
    for s in r.segments:
        if s.corner:
            assert s.corner.b.brake_on_m is None and s.corner.brake_diff_m is None
    assert all("brakes" not in f.text for f in r.findings)


def test_missing_throttle_channel_is_not_invented():
    b = synth(speed_k=1.02)
    b = b.model_copy(update={"throttle": [0.0] * len(b.distance)})
    r = run(synth(), b)
    assert "throttle_missing" in codes(r) and r.channels.throttle_b is None
    assert all(s.corner.b.throttle_on_m is None for s in r.segments if s.corner)
    assert all("gets on the throttle" not in f.text for f in r.findings)


def test_missing_corners_fall_back_to_distance_segments_and_say_so():
    for corners in ([], [Corner(number=1, x=0, y=0, angle=0)]):
        r = run(synth(), synth(speed_k=1.02), corners)
        assert "corners_missing" in codes(r)
        assert {s.kind for s in r.segments} == {"distance"}
        assert all(s.corner is None for s in r.segments)
        assert sum(s.gain_a_s for s in r.segments) == pytest.approx(r.finish.delta_s, abs=1e-3)


def test_partial_corner_list_keeps_the_known_corners():
    corners = CORNERS[:2] + [Corner(number=3, x=0, y=0, angle=0, distance=None)]
    r = run(synth(), synth(), corners)
    assert "corners_partial" in codes(r)
    assert [s.corner_number for s in r.segments if s.kind == "corner"] == [1, 2]


def test_unequal_coverage_is_truncated_without_a_finish_claim():
    full = synth()
    n = int(len(full.distance) * 0.8)
    short = TelemetryDataset(**{k: v[:n] for k, v in full.model_dump().items()})
    r = run(full, short)
    assert r.alignment.method == "truncated_to_common_coverage"
    assert r.finish.delta_s is None and r.finish.within_tolerance is None
    assert "unequal_coverage" in codes(r)
    assert r.alignment.common_length_m == pytest.approx(short.distance[-1], abs=0.1)
    assert max(abs(x) for x in r.delta_s) < 1e-6  # same lap up to the cut


def test_small_length_drift_is_scaled_and_reported():
    a = synth()
    drift = a.model_copy(update={"distance": [x * 1.003 for x in a.distance]})
    r = run(a, drift)
    assert r.alignment.method == "scaled_to_mean_length"
    assert r.alignment.scale_a != 1 and r.alignment.scale_b != 1
    assert r.finish.delta_s == pytest.approx(0, abs=1e-3)


def test_bad_samples_are_dropped_and_reported_not_propagated():
    tel = synth()
    d = tel.model_dump()
    d["speed"][10] = float("nan")
    d["distance"][20] = float("inf")
    d["time"][30] = float("nan")
    for k in d:  # a repeated row and an out-of-order row
        d[k].insert(41, d[k][40])
        d[k].insert(60, d[k][50])
    r = run(TelemetryDataset(**d), tel)
    assert {"nonfinite_samples", "duplicate_samples"} <= codes(r)
    assert all(math.isfinite(x) for x in r.delta_s)
    assert abs(r.finish.error_s) < 0.05
    json.loads(r.model_dump_json())  # no NaN/inf leaks into the response


def test_too_little_telemetry_is_a_comparison_error():
    tiny = TelemetryDataset(**{k: v[:5] for k, v in synth().model_dump().items()})
    with pytest.raises(cmp.ComparisonError):
        run(tiny, synth())


def test_pit_laps_and_official_time_mismatch_warn():
    a, b = synth(), synth()
    r = cmp.compare_laps(ref(a, is_out_lap=True), a,
                         ref(b).model_copy(update={"lap_time": b.time[-1] + 1}), b, CORNERS)
    assert {"pit_lap", "telemetry_duration", "finish_delta_mismatch"} <= codes(r)
    assert r.finish.within_tolerance is False


# --- API / service: fallback-only data and selection rules ---------------------------------


def _laps(driver, times):
    return [LapData(lap_number=i + 1, driver=driver, lap_time=t, compound="SOFT", tyre_life=1.0,
                    position=1.0, is_personal_best=False, is_accurate=True, stint=1)
            for i, t in enumerate(times)]


@pytest.fixture
def archive_only(monkeypatch):
    """No FastF1 data at all: laps, telemetry and corners come through the TracingInsights path."""
    class Unloaded:
        @property
        def laps(self):
            raise DataNotLoadedError("not loaded")

        def get_circuit_info(self):
            raise DataNotLoadedError("not loaded")

    fast, slow = synth(speed_k=1.01), synth()
    tels = {("AAA", 1): slow, ("AAA", 2): fast, ("BBB", 1): slow}
    laps = _laps("AAA", [slow.time[-1], fast.time[-1]]) + _laps("BBB", [slow.time[-1]])
    event = type("Ev", (), {"year": 1999, "__getitem__": lambda self, k: 1})()
    fake_session = SimpleNamespace(event=event, name="Race")
    monkeypatch.setattr(f1_data, "_resolve", lambda *a: fake_session)
    monkeypatch.setattr(f1_data, "_get_session", lambda *a, **k: Unloaded())
    monkeypatch.setattr(f1_data.F1DataService, "_archive_key",
                        staticmethod(lambda *a: (1999, "Test GP", "Race")))
    monkeypatch.setattr(f1_data.ti, "laps", lambda *key: laps)
    monkeypatch.setattr(f1_data.ti, "drivers", lambda *key: [{"driver": "AAA"}])
    monkeypatch.setattr(f1_data.ti, "telemetry", lambda y, e, s, drv, lap: tels.get((drv, lap)))
    monkeypatch.setattr(f1_data.ti, "circuit",
                        lambda *key: SimpleNamespace(corners=CORNERS, rotation=0.0))
    f1_data._tel_cache.clear()
    yield
    f1_data._tel_cache.clear()


URL = "/api/v1/sessions/1999/Test/R/compare"


def test_fallback_only_same_driver_different_laps(archive_only):
    r = client.get(URL, params={"driver_a": "aaa", "lap_a": 1, "driver_b": "AAA", "lap_b": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lap_a"]["label"] == "AAA L1" and body["lap_b"]["label"] == "AAA L2"
    assert body["lap_b"]["requested_lap"] == 0  # 0 resolved to the fastest lap, number 2
    assert body["finish"]["within_tolerance"] and body["finish"]["delta_s"] < 0
    assert len(body["channels"]["distance"]) == len(body["delta_s"])
    assert body["findings"] and not body["warnings"]


def test_fallback_only_without_corners_still_compares(archive_only, monkeypatch):
    monkeypatch.setattr(f1_data.ti, "circuit", lambda *key: None)
    r = client.get(URL, params={"driver_a": "AAA", "driver_b": "BBB"})
    assert r.status_code == 200
    assert "corners_missing" in {w["code"] for w in r.json()["warnings"]}


@pytest.mark.parametrize("params, status, detail", [
    ({"driver_a": "AAA", "driver_b": "ZZZ"}, 404, "No laps for driver 'ZZZ'"),
    ({"driver_a": "AAA", "lap_a": 99, "driver_b": "BBB"}, 404, "has no lap 99"),
    ({"driver_a": "AAA", "driver_b": "BBB", "lap_b": -1}, 422, None),
    ({"driver_a": "A", "driver_b": "BBB"}, 422, None),
    ({"driver_a": "AAA"}, 422, None),
])
def test_invalid_selection(archive_only, params, status, detail):
    r = client.get(URL, params=params)
    assert r.status_code == status
    if detail:
        assert detail in r.json()["detail"]


def test_lap_without_official_time_is_rejected(archive_only, monkeypatch):
    laps = _laps("AAA", [None, 90.0])
    monkeypatch.setattr(f1_data.ti, "laps", lambda *key: laps)
    r = client.get(URL, params={"driver_a": "AAA", "lap_a": 1, "driver_b": "AAA", "lap_b": 2})
    assert r.status_code == 404 and "no official lap time" in r.json()["detail"]


def test_unusable_telemetry_maps_to_422(archive_only, monkeypatch):
    tiny = TelemetryDataset(**{k: v[:5] for k, v in synth().model_dump().items()})
    monkeypatch.setattr(f1_data.ti, "telemetry", lambda y, e, s, drv, lap: tiny)
    r = client.get(URL, params={"driver_a": "AAA", "driver_b": "BBB"})
    assert r.status_code == 422 and "no usable telemetry" in r.json()["detail"]


# --- golden checks against cached real sessions --------------------------------------------

BAHRAIN_Q = "/api/v1/sessions/2024/Bahrain/Q"


@livedata
def test_golden_bahrain_q_ver_vs_lec():
    r = client.get(BAHRAIN_Q + "/compare", params={"driver_a": "VER", "driver_b": "LEC"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["lap_a"]["label"], body["lap_a"]["lap_time"]) == ("VER L16", 89.179)
    assert (body["lap_b"]["label"], body["lap_b"]["lap_time"]) == ("LEC L12", 89.165)
    fin = body["finish"]
    assert fin["official_delta_s"] == pytest.approx(-0.014, abs=1e-6)  # LEC is faster
    assert fin["delta_s"] == pytest.approx(fin["official_delta_s"], abs=0.05)
    assert body["alignment"]["method"] == "scaled_to_mean_length"
    assert {w["code"] for w in body["warnings"]} == set()

    # The findings are the three biggest segments of the delta trace the client draws.
    dist, delta = body["channels"]["distance"], body["delta_s"]
    at = lambda m: float(np.interp(m, dist, delta))  # noqa: E731
    segs = {s["id"]: s for s in body["segments"]}
    for s in segs.values():
        assert s["gain_a_s"] == pytest.approx(at(s["end_m"]) - at(s["start_m"]), abs=2e-3)
    top3 = sorted(segs.values(), key=lambda s: -abs(s["gain_a_s"]))[:3]
    assert [f["segment_id"] for f in body["findings"][:3]] == [s["id"] for s in top3]
    for f, s in zip(body["findings"], top3):
        assert f["gain_s"] == pytest.approx(abs(s["gain_a_s"]), abs=1e-3)
        assert f["winner"] == ("A" if s["gain_a_s"] > 0 else "B")
        assert s["label"] in f["text"]

    swapped = client.get(BAHRAIN_Q + "/compare", params={"driver_a": "LEC", "driver_b": "VER"})
    assert swapped.json()["finish"]["delta_s"] == pytest.approx(-fin["delta_s"], abs=1e-3)


@livedata
def test_golden_same_driver_different_laps_and_legacy_route_untouched():
    laps = [x for x in client.get(BAHRAIN_Q + "/laps").json() if x["driver"] == "VER"]
    other = next(x["lap_number"] for x in laps if x["lap_time"] and x["lap_number"] != 16)
    r = client.get(BAHRAIN_Q + "/compare", params={
        "driver_a": "VER", "lap_a": other, "driver_b": "VER", "lap_b": 0})
    assert r.status_code == 200
    f = r.json()["finish"]
    assert f["delta_s"] == pytest.approx(f["official_delta_s"], abs=0.05)
    legacy = client.get(BAHRAIN_Q + "/telemetry/compare", params={"drivers": "VER,LEC"})
    assert set(legacy.json()["drivers"]) == {"VER", "LEC"}


def test_archive_fallback_race_comparison():
    """2025 China is only in the TracingInsights archive (see test_api)."""
    r = client.get("/api/v1/sessions/2025/China/R/compare",
                   params={"driver_a": "PIA", "driver_b": "PIA", "lap_b": 10, "lap_a": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lap_a"]["lap_number"] == 5 and body["lap_b"]["lap_number"] == 10
    assert abs(body["finish"]["error_s"] or 0) < 0.5
