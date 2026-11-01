from scripts.export_demo import COMPARE_TOP_DRIVERS, comparison_pairs


def _lap(driver, t):
    return {"driver": driver, "lap_time": t}


def _result(abbr, team):
    return {"driver": {"abbreviation": abbr, "team": team}}


def test_pairs_cover_fastest_drivers_and_teammates_in_both_orders():
    codes = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]
    laps = [_lap(c, 90 + i) for i, c in enumerate(codes)] + [_lap("AAA", None), _lap("GGG", 99)]
    teams = dict(zip(codes, ["T1", "T2", "T3", "T4", "T5", "T6", "T6"]))
    results = {"drivers": [_result(c, teams[c]) for c in codes]}

    pairs = comparison_pairs(laps, results)

    top = codes[:COMPARE_TOP_DRIVERS]
    assert {(a, b) for a in top for b in top if a != b} <= set(pairs)
    assert ("FFF", "GGG") in pairs and ("GGG", "FFF") in pairs  # teammates outside the top five
    assert ("AAA", "GGG") not in pairs and ("AAA", "AAA") not in pairs
    assert pairs[0][0] == "AAA"  # fastest driver first: the demo's "fastest" shortcut
    assert len(pairs) == len(set(pairs))


def test_drivers_without_a_timed_lap_are_skipped():
    laps = [_lap("AAA", 90.0), _lap("BBB", 91.0), _lap("CCC", None)]
    results = {"drivers": [_result("AAA", "T"), _result("BBB", "U"), _result("CCC", "T")]}
    assert comparison_pairs(laps, results) == [("AAA", "BBB"), ("BBB", "AAA")]
