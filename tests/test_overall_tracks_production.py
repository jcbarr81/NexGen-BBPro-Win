"""The overall rating tracks production and is shared (audit H8 + M14).

Production comes from ``tests/fixtures/calibration_seed1_player_lines.csv``:
one 162-game harness season (seed 1) on the wide-rated calibration fixture,
dumped per player by ``scripts/dump_season_player_lines.py``. A stored dump
keeps the test fast and deterministic; regenerate it after an engine change.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

import services.cpu_trade_evaluator as trade
import services.prospect_promotion as promotion
import services.roster_auto_assign as auto_assign
import utils.rating_display as rating_display
from api.routers._rating_presentation import compute_overall
from utils.player_overall import player_overall_score
from utils.rating_display import overall_rating

ROOT = Path(__file__).resolve().parents[1]
CAL_PLAYERS = ROOT / "data" / "calibration" / "players.csv"
LINES = ROOT / "tests" / "fixtures" / "calibration_seed1_player_lines.csv"
PITCHES = ("fb", "cu", "cb", "sl", "si", "scb", "kn")


@pytest.fixture
def calibration_league(monkeypatch):
    """Point the display distribution at the calibration fixture."""

    monkeypatch.setattr(rating_display, "_rating_source_path", lambda: CAL_PLAYERS)
    rating_display._load_distributions.cache_clear()
    yield
    rating_display._load_distributions.cache_clear()


def _pearson(xs, ys):
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    return cov / math.sqrt(vx * vy)


def _rows():
    with CAL_PLAYERS.open(newline="", encoding="utf-8") as handle:
        players = {row["player_id"]: row for row in csv.DictReader(handle)}
    with LINES.open(newline="", encoding="utf-8") as handle:
        lines = list(csv.DictReader(handle))
    return players, lines


def _display_ovr(row):
    is_pitcher = row["is_pitcher"] == "1"
    result = compute_overall(
        lambda key: row.get(key) or None,
        is_pitcher=is_pitcher,
        position=row.get("primary_position") or None,
    )
    return result["overall_display"]


def test_hitter_ovr_tracks_ops_plus(calibration_league):
    players, lines = _rows()
    hitting = [ln for ln in lines if ln["line_type"] == "hitting"]

    def total(key):
        return sum(int(ln[key]) for ln in hitting)

    def obp(s):
        den = int(s["ab"]) + int(s["bb"]) + int(s["hbp"]) + int(s["sf"])
        return (int(s["h"]) + int(s["bb"]) + int(s["hbp"])) / den

    def slg(s):
        bases = int(s["h"]) + int(s["b2"]) + 2 * int(s["b3"]) + 3 * int(s["hr"])
        return bases / int(s["ab"])

    league = {k: total(k) for k in ("ab", "h", "b2", "b3", "hr", "bb", "hbp", "sf")}
    lg_obp, lg_slg = obp(league), slg(league)
    ovr, ops_plus = [], []
    for ln in hitting:
        if int(ln["pa"]) < 200:
            continue
        ovr.append(_display_ovr(players[ln["player_id"]]))
        ops_plus.append(100 * (obp(ln) / lg_obp + slg(ln) / lg_slg - 1))
    assert len(ovr) > 250
    assert _pearson(ovr, ops_plus) >= 0.6


def test_pitcher_ovr_tracks_fip_minus(calibration_league):
    players, lines = _rows()
    pitching = [ln for ln in lines if ln["line_type"] == "pitching"]

    def total(key):
        return sum(int(ln[key]) for ln in pitching)

    def fip_core(s, prefix="p_"):
        return (
            13 * int(s[prefix + "hr"])
            + 3 * (int(s[prefix + "bb"]) + int(s[prefix + "hbp"]))
            - 2 * int(s[prefix + "so"])
        ) / (int(s[prefix + "outs"]) / 3)

    league = {f"p_{k}": total(f"p_{k}") for k in ("hr", "bb", "hbp", "so", "outs", "er")}
    lg_era = 9 * league["p_er"] / (league["p_outs"] / 3)
    constant = lg_era - fip_core(league)
    ovr, fip_minus = [], []
    for ln in pitching:
        if int(ln["p_outs"]) < 120:  # 40 IP, the audit's M14 cut
            continue
        ovr.append(_display_ovr(players[ln["player_id"]]))
        fip_minus.append(100 * (fip_core(ln) + constant) / lg_era)
    assert len(ovr) > 250
    assert _pearson(ovr, fip_minus) <= -0.6


def _pitcher(pitches, grade=55, **extra):
    attrs = {key: 0 for key in PITCHES}
    attrs.update({key: grade for key in pitches})
    attrs.update(
        player_id="P1",
        is_pitcher=True,
        primary_position="P",
        preferred_pitching_role="MR",
        control=55,
        movement=52,
        endurance=40,
        hold_runner=50,
        arm=50,
        fa=50,
    )
    attrs.update(extra)
    return SimpleNamespace(**attrs)


def test_pitch_count_does_not_move_the_overall(calibration_league):
    two = _pitcher(("fb", "sl"))
    five = _pitcher(("fb", "sl", "cu", "cb", "si"))
    pairs = [
        (overall_rating(two), overall_rating(five)),
        (auto_assign._overall_score(two), auto_assign._overall_score(five)),
        (
            trade._overall_score(two, potential=False),
            trade._overall_score(five, potential=False),
        ),
    ]
    for field in ("overall_raw", "overall_display"):
        shown = [
            compute_overall(
                lambda key, p=p: getattr(p, key, None),
                is_pitcher=True,
                position="P",
            )[field]
            for p in (two, five)
        ]
        pairs.append(tuple(shown))
    for a, b in pairs:
        assert abs(a - b) <= 1


def _as_player(row):
    """A loader-shaped player: numeric ratings, unthrown pitches as 0."""

    attrs = {}
    for key, value in row.items():
        try:
            attrs[key] = int(value) if value != "" else 0
        except ValueError:
            attrs[key] = value
    attrs["is_pitcher"] = row["is_pitcher"] == "1"
    return SimpleNamespace(**attrs)


def test_cpu_assign_trade_and_promotion_use_the_shared_overall():
    players = [_as_player(row) for row in _rows()[0].values()]
    assert len(players) > 700
    for player in players:
        shared = player_overall_score(player)
        assert auto_assign._overall_score(player) == pytest.approx(shared)
        assert trade._overall_score(player, potential=False) == pytest.approx(shared)
        assert overall_rating(player) == int(round(shared))
        assert promotion._player_overall(player) == int(round(shared))


def test_inert_ratings_are_out_and_eye_is_in():
    base = dict(
        is_pitcher=False, primary_position="2B", ch=55, ph=55, eye=50, sp=50,
        fa=50, arm=50, sc=50, pl=50, vl=50, gf=50,
    )
    score = player_overall_score(SimpleNamespace(**base))
    for key in ("sc", "pl", "vl", "gf"):
        moved = player_overall_score(SimpleNamespace(**{**base, key: 90}))
        assert moved == pytest.approx(score), key
    assert player_overall_score(SimpleNamespace(**{**base, "eye": 80})) > score

    pitcher = _pitcher(("fb", "sl", "cu"))
    p_score = player_overall_score(pitcher)
    for key in ("arm", "fa", "hold_runner", "endurance"):
        moved = player_overall_score(_pitcher(("fb", "sl", "cu"), **{key: 90}))
        assert moved == pytest.approx(p_score), key


def test_endurance_only_adjusts_starters():
    low = player_overall_score(
        _pitcher(("fb", "sl"), preferred_pitching_role="SP", endurance=35)
    )
    high = player_overall_score(
        _pitcher(("fb", "sl"), preferred_pitching_role="SP", endurance=70)
    )
    assert high > low
    assert high - low <= 6.0


def test_defense_follows_the_mlb_spectrum():
    def gain(position):
        base = dict(is_pitcher=False, primary_position=position, ch=50, ph=50,
                    eye=50, sp=50, fa=50, arm=50)
        plain = player_overall_score(SimpleNamespace(**base))
        glove = player_overall_score(SimpleNamespace(**{**base, "fa": 70, "arm": 70}))
        return glove - plain

    assert gain("SS") > gain("2B") > gain("LF") > gain("1B") > gain("DH") == 0
    assert gain("CF") > gain("3B") > gain("RF")
    # Modest: an elite glove at SS is worth less than +10 contact and power.
    assert gain("SS") < 9.0


def test_all_fifty_hitter_and_pitcher_score_alike():
    hitter = SimpleNamespace(is_pitcher=False, primary_position="2B", ch=50,
                             ph=50, eye=50, sp=50, fa=50, arm=50)
    pitcher = _pitcher(("fb", "sl"), grade=50, control=50, movement=50)
    assert player_overall_score(hitter) == pytest.approx(50.0)
    assert player_overall_score(pitcher) == pytest.approx(50.0)


def _write_league(path, pitchers):
    fields = ["player_id", "is_pitcher", "primary_position",
              "preferred_pitching_role", "control", "movement", "endurance",
              "fb", "sl"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for idx, (co, mo) in enumerate(pitchers):
            writer.writerow({
                "player_id": f"P{idx}", "is_pitcher": "1",
                "primary_position": "P", "preferred_pitching_role": "MR",
                "control": co, "movement": mo, "endurance": 30,
                "fb": 55, "sl": 50,
            })


def test_compressed_league_shows_raw_overall(tmp_path, monkeypatch):
    # alpha-like compressed staff: overalls within ~2 points of each other.
    path = tmp_path / "players.csv"
    _write_league(path, [(50 + i % 5, 52 + i % 4) for i in range(60)])
    monkeypatch.setattr(rating_display, "_rating_source_path", lambda: path)
    rating_display._load_distributions.cache_clear()
    try:
        for co, mo in ((50, 52), (54, 55)):
            row = {"control": co, "movement": mo, "fb": 55, "sl": 50,
                   "preferred_pitching_role": "MR", "endurance": 30}
            result = compute_overall(row.get, is_pitcher=True, position="P")
            assert result["overall_display"] == result["overall_raw"]
    finally:
        rating_display._load_distributions.cache_clear()


def test_wide_league_percentile_scales_overall(tmp_path, monkeypatch):
    path = tmp_path / "players.csv"
    _write_league(path, [(30 + i, 30 + i) for i in range(50)])
    monkeypatch.setattr(rating_display, "_rating_source_path", lambda: path)
    rating_display._load_distributions.cache_clear()
    try:
        row = {"control": 75, "movement": 75, "fb": 55, "sl": 50,
               "preferred_pitching_role": "MR", "endurance": 30}
        result = compute_overall(row.get, is_pitcher=True, position="P")
        # Top of the league: the percentile leg lifts the display above raw.
        assert result["overall_display"] > result["overall_raw"]
    finally:
        rating_display._load_distributions.cache_clear()
