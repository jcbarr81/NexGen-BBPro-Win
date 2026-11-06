"""Backlog #51: promotion bars are relative to the league's own players.

The old fixed bars (55 / 65 / 72 on a flat rating average) sat in engine
points, where big leaguers average about 52: nobody reached 65, so the 2027
rollover in alpha-test called up no one and in-season call-ups had no
candidates. The bars are now points in the league's own population at the
player's role, on the shared overall.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import services.inseason_callups as callups
import services.prospect_promotion as pp


def _player(pid, score, *, pitcher=False):
    return SimpleNamespace(player_id=pid, score=score, is_pitcher=pitcher,
                           primary_position="P" if pitcher else "SS")


@pytest.fixture(autouse=True)
def plain_scores(monkeypatch):
    monkeypatch.setattr(pp, "_player_overall", lambda p: float(p.score))
    monkeypatch.setattr(callups, "_player_overall", lambda p: float(p.score))


def _league(act_scores, aaa_scores, *, pitcher=False, prefix="H"):
    players, levels = {}, []
    for level, scores in (("ACT", act_scores), ("AAA", aaa_scores)):
        for i, score in enumerate(scores):
            pid = f"{prefix}{level}{i}"
            players[pid] = _player(pid, score, pitcher=pitcher)
            levels.append((pid, level))
    return players, levels


def test_bars_sit_at_the_leagues_own_share_points():
    players, levels = _league(range(40, 80), range(30, 70))  # 40 of each
    bars = pp.promotion_bars(players, levels)[False]
    assert bars.ready == 60  # median big leaguer
    assert bars.bluechip == 70  # top quarter of big leaguers
    assert bars.low_to_aaa == 60  # top quarter of AAA


def test_hitters_and_pitchers_are_judged_separately():
    hitters, h_levels = _league(range(40, 80), range(30, 70))
    pitchers, p_levels = _league(range(50, 90), range(40, 80), pitcher=True, prefix="P")
    bars = pp.promotion_bars({**hitters, **pitchers}, h_levels + p_levels)
    assert bars[False].ready == 60 and bars[True].ready == 70


def test_a_thin_level_falls_back_to_fixed_bars():
    players, levels = _league([50] * 5, [45] * 5)
    bars = pp.promotion_bars(players, levels)[True]
    fallback = pp.FALLBACK_BARS[True]
    assert (bars.low_to_aaa, bars.ready, bars.bluechip) == (
        fallback["low_to_aaa"], fallback["ready"], fallback["bluechip"]
    )


BARS = pp.RoleBars(low_to_aaa=51.0, ready=52.0, bluechip=55.0)


@pytest.mark.parametrize(
    "level,age,overall,expected",
    [
        ("AAA", 24, 52.0, "ACT"),  # league median, 23+: ready
        ("AAA", 22, 52.0, None),  # median but young: stays
        ("AAA", 20, 55.0, "ACT"),  # top quarter: any age
        ("AAA", 30, 51.9, None),
        ("LOW", 19, 51.0, "AAA"),  # top quarter of AAA
        ("LOW", 19, 50.9, None),
        ("LOW", 22, 30.0, "AAA"),  # 22 moves up whatever
        ("ACT", 30, 99.0, None),
    ],
)
def test_the_rules(level, age, overall, expected):
    assert pp.evaluate_promotion(
        current_level=level, age=age, overall=overall, bars=BARS
    ) == expected


def test_a_aaa_player_better_than_most_big_leaguers_is_a_call_up_candidate():
    # The alpha-test shape: big leaguers ~52, nobody near the old bar of 65.
    players, levels = _league([48 + (i % 9) for i in range(40)], [47] * 30)
    players["UP"] = _player("UP", 54.0)
    players["YOUNG"] = _player("YOUNG", 53.0)
    bars = pp.promotion_bars(players, levels)
    roster = SimpleNamespace(aaa=["UP", "YOUNG"])
    ages = {"UP": 26, "YOUNG": 21}
    original = callups._player_age
    callups._player_age = lambda p: ages.get(p.player_id)
    try:
        eligible = callups._eligible_aaa(roster, players, bars)
    finally:
        callups._player_age = original
    assert [pid for pid, _, _ in eligible] == ["UP"]


def test_an_owners_ready_prospects_are_one_news_line(tmp_path, monkeypatch):
    lines = []
    monkeypatch.setattr(
        "utils.news_logger.log_news_event", lambda message, **kw: lines.append(message)
    )

    def entry(pid, overall, to_level="ACT", from_level="AAA"):
        return {
            "first_name": pid, "last_name": "X", "player_id": pid,
            "primary_position": "SS", "team_id": "OKL", "age": 24,
            "from_level": from_level, "to_level": to_level, "overall": overall,
        }

    pp._announce_suggestions(
        [entry("A", 53.2), entry("B", 56.0), entry("C", 52.0, "AAA", "LOW")], tmp_path
    )
    assert len(lines) == 2
    assert lines[0].startswith("OKL: 2 prospects are ready for the majors: SS B X")
    assert "SS A X (age 24, OVR 53)" in lines[0]
    assert "C X" in lines[1] and "is ready for AAA" in lines[1]
