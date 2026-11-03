"""Free-agent prices: the re-anchored curve and the player's record (8.9.0,
backlog #66).

* The curve sits on the quality big leaguers really have: a bench player
  (quality ~49, shown OVR ~45) asks about the minimum, not ~$5M.
* His big-league record counts as much as his ratings for a full-time
  regular (owner's call, "moderate"), less for a part-timer, not at all
  without big-league time; recent seasons count more, at most three.

The league averages come from a synthetic league (``_payloads`` patched),
so nothing reads a real league.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import contracts_service as cs
from services import performance_value as pv


def _bat(pa, obp, slg):
    """A batting line with these rates (singles only past the power)."""
    ab = round(pa * 0.9)
    on = round(obp * pa)
    tb = round(slg * ab)
    h = min(on, ab)
    return {"g": 150, "pa": pa, "ab": ab, "h": h, "bb": on - h, "hbp": 0,
            "sf": pa - ab - (on - h), "tb": tb}


def _pitch(outs, era, *, k9=8.0, bb9=3.0, hr9=1.1):
    ip = outs / 3
    return {"g": 30, "outs": outs, "er": round(era * ip / 9), "so": round(k9 * ip / 9),
            "bb": round(bb9 * ip / 9), "hbp": 0, "hr": round(hr9 * ip / 9)}


def _league():
    """Season ``lg-2026``: hitters OBP .300-.360 / SLG .380-.460, pitchers
    ERA 3.4-5.4, a spread for the norms."""
    seasons = {}
    for i in range(30):
        seasons[f"H{i}"] = {"lg-2026": _bat(500, 0.300 + i * 0.002, 0.380 + i * 0.0027)}
    for i in range(20):
        seasons[f"P{i}"] = {"lg-2026": _pitch(450, 3.4 + i * 0.1, k9=9.5 - i * 0.15)}
    for year in (2023, 2024, 2025):
        seasons[f"Y{year}"] = {f"lg-{year}": _bat(500, 0.33, 0.42)}
        for i in range(10):
            seasons[f"Y{year}-{i}"] = {f"lg-{year}": _bat(500, 0.300 + i * 0.006, 0.380 + i * 0.008)}
    return seasons


@pytest.fixture(autouse=True)
def league(monkeypatch):
    seasons = _league()
    monkeypatch.setattr(pv, "_NORMS", None)
    monkeypatch.setattr(pv, "_payloads", lambda: (("synthetic",), seasons, {}))
    # Hitters are priced on their weighted ratings in these tests.
    monkeypatch.setattr(cs, "_pitchers_priced_by_overall", lambda: False)


def _hitter(quality, history=None, current=None):
    p = SimpleNamespace(player_id="X", is_pitcher=False, primary_position="1B",
                        ch=quality, ph=quality, sp=quality, eye=quality, fa=quality, arm=quality)
    if history is not None:
        p.career_history = history
    if current is not None:
        p.season_stats = current
    return p


def _pitcher(quality, history):
    return SimpleNamespace(player_id="Z", is_pitcher=True, primary_position="P",
                           arm=quality, control=quality, movement=quality, endurance=quality,
                           career_history=history)


GOOD = _bat(550, 0.390, 0.540)   # OPS+ well above
BAD = _bat(550, 0.270, 0.330)    # well below


def test_a_bench_player_asks_about_the_minimum_and_a_regular_a_few_million():
    bench = cs.estimate_market_value_for_player(_hitter(49))
    regular = cs.estimate_market_value_for_player(_hitter(52.5))
    best = cs.estimate_market_value_for_player(_hitter(58))
    assert bench < 1_200_000
    assert 2_500_000 < regular < 5_000_000
    assert 10_000_000 < best < 20_000_000


def test_no_big_league_time_prices_on_ratings_alone():
    p = _hitter(53)
    assert pv.record(p) is None
    assert cs.priced_quality(p) == cs.priced_quality(p, use_stats=False)


def test_a_full_time_regular_moves_half_way_to_his_record():
    for line, up in ((GOOD, True), (BAD, False)):
        p = _hitter(53, history={"lg-2026": line})
        rec = pv.record(p)
        assert rec["share"] == 1.0
        earned = pv.QUALITY_CENTER + rec["z"] * pv.QUALITY_SD
        assert cs.priced_quality(p) == pytest.approx(53 + 0.5 * (earned - 53))
        with_record = cs.estimate_market_value_for_player(p)
        ratings_only = cs.estimate_market_value_for_player(p, use_stats=False)
        assert (with_record > ratings_only) is up


def test_a_part_timer_moves_less_than_a_regular_with_the_same_rates():
    full = _hitter(53, history={"lg-2026": GOOD})
    part = _hitter(53, history={"lg-2026": _bat(150, 0.390, 0.540)})
    assert pv.record(part)["share"] == pytest.approx(0.3)
    assert 53 < cs.priced_quality(part) < cs.priced_quality(full)


def test_a_poor_pitcher_record_lowers_his_price():
    good = _pitcher(53, {"lg-2026": _pitch(480, 3.0, k9=10.0)})
    bad = _pitcher(53, {"lg-2026": _pitch(480, 6.5, k9=5.5, hr9=1.8)})
    assert cs.priced_quality(good) > 53 > cs.priced_quality(bad)


def test_his_batting_line_never_prices_a_pitcher():
    p = _pitcher(53, {"lg-2026": GOOD})
    assert pv.record(p) is None


def test_recent_seasons_count_more_and_only_three_count():
    old_good = {"lg-2023": GOOD, "lg-2024": BAD, "lg-2025": BAD}
    assert pv.record(_hitter(53, history=old_good))["z"] < 0
    recent_good = {"lg-2023": BAD, "lg-2024": BAD, "lg-2025": GOOD}
    four = dict(recent_good, **{"lg-2026": BAD})
    shown = [s["label"] for s in pv.record(_hitter(53, history=four))["seasons"]]
    assert shown == ["2026", "2025", "2024"]


def test_this_season_counts_first_once_he_has_played():
    seasons = _league()
    current = {f"C{i}": _bat(300, 0.300 + i * 0.002, 0.380 + i * 0.0027) for i in range(30)}
    pv._NORMS = None
    pv._payloads = lambda: (("synthetic-current",), seasons, current)
    try:
        p = _hitter(53, history={"lg-2026": BAD}, current=_bat(300, 0.390, 0.540))
        rows = pv.record(p)["seasons"]
        assert rows[0]["label"] == "this season" and rows[1]["label"] == "2026"
    finally:
        pv._NORMS = None


def test_the_offer_dialog_says_why():
    note = pv.price_note(_hitter(53, history={"lg-2026": GOOD}))
    assert note["pct"] > 5
    assert note["text"].startswith("His record raises his price (about $")
    assert "on his ratings alone" in note["text"]
    assert "2026: 550 PA" in note["text"] and "OPS+" in note["text"]
    low = pv.price_note(_hitter(53, history={"lg-2026": BAD}))
    assert low["pct"] < -5 and "lowers" in low["text"]
    assert pv.price_note(_hitter(53)) is None


def test_no_stats_files_means_no_change(monkeypatch):
    monkeypatch.setattr(pv, "_payloads", lambda: (("empty",), {}, {}))
    monkeypatch.setattr(pv, "_NORMS", None)
    p = _hitter(53, history={"lg-2026": GOOD})
    assert pv.record(p) is None
    assert cs.priced_quality(p) == 53
