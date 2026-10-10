"""Release 4 (F4): the battery rating centres (audit decision 2).

The W1 running-game terms were calibrated on the two fixtures, whose
batteries sit at 51-60, while a real league's sit at 50, so a live league
stole and threw wild pitches far more often than the fixtures. Those terms
now read each battery rating against the league's ACT mean:

- ``services.league_rating_centers`` computes the ACT pitchers' control /
  hold_runner / arm and the ACT catchers' arm / fa means alongside the W0
  speed centre, once per season, in the same file and cache; a W0-era file
  (speed only) gets the missing centres added without its speed centre
  being recomputed.
- ``engine._centred_rating`` re-expresses a rating so the centre reads 50;
  the steal attempt deterrents and success logit, the WP/PB rates, the
  dropped-third-strike rate and the D3K throw read through it. Runner and
  batter speed in the race terms stay raw.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

import physics_sim.engine as engine
from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from physics_sim.engine import BaseState
from physics_sim.models import BatterRatings
from services import league_rating_centers as centers

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
CALIBRATION_LEAGUE = REPO / "data" / "calibration_league"

BATTERY_KEYS = (
    "pitcher_control_center",
    "pitcher_hold_center",
    "pitcher_arm_center",
    "catcher_arm_center",
    "catcher_fa_center",
)
PLAYER_FIELDS = [
    "player_id", "primary_position", "is_pitcher", "sp",
    "control", "hold_runner", "arm", "fa",
]


@pytest.fixture(autouse=True)
def _fresh_cache():
    centers.clear_rating_center_cache()
    yield
    centers.clear_rating_center_cache()


def _write_league(root: Path, players: list[dict], rosters: dict[str, list[tuple]]):
    root.mkdir(parents=True, exist_ok=True)
    with (root / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PLAYER_FIELDS)
        writer.writeheader()
        for row in players:
            writer.writerow({key: row.get(key, "") for key in PLAYER_FIELDS})
    (root / "rosters").mkdir(exist_ok=True)
    for name, rows in rosters.items():
        with (root / "rosters" / f"{name}.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            csv.writer(fh).writerows(rows)


def _player(pid, pos, *, pitcher="0", sp="50", control="", hold="", arm="", fa=""):
    return {
        "player_id": pid, "primary_position": pos, "is_pitcher": pitcher,
        "sp": sp, "control": control, "hold_runner": hold, "arm": arm, "fa": fa,
    }


def _league(root: Path, *, catchers: bool = True) -> Path:
    players = [
        # A hitter with a strong arm and glove: not a catcher, left out of
        # the catcher centres.
        _player("H1", "CF", sp="60", arm="90", fa="90"),
        # ACT pitchers by flag and by position; their sp is not a hitter's.
        _player("P1", "SP", pitcher="1", sp="99", control="62", hold="70", arm="80"),
        _player("P2", "RP", sp="99", control="41", hold="", arm="61"),
        # Far above average, but not on an ACT roster.
        _player("P3", "SP", pitcher="1", control="99", hold="99", arm="99"),
    ]
    rosters = {
        "AAA": [("H1", "ACT"), ("P1", "act"), ("P3", "AAA")],
        "BBB": [("P2", "ACT")],
    }
    if catchers:
        players += [
            _player("C1", "C", sp="40", arm="60", fa="70"),
            _player("C2", "c", sp="50", arm="45", fa=""),
            _player("C3", "C", arm="99", fa="99"),
        ]
        rosters["AAA"] += [("C1", "ACT"), ("C3", "LOW")]
        rosters["BBB"] += [("C2", "ACT")]
        # A side file whose ids look ACT is never a roster.
        rosters["BBB_pitching"] = [("C3", "ACT"), ("P3", "ACT")]
    _write_league(root, players, rosters)
    return root


EXPECTED = {
    "hitter_speed_center": 50.0,  # H1 60, C1 40, C2 50
    "pitcher_control_center": 51.5,  # P1 62, P2 41
    "pitcher_hold_center": 60.0,  # P1 70, P2 blank -> 50
    "pitcher_arm_center": 70.5,  # P1 80, P2 61
    "catcher_arm_center": 52.5,  # C1 60, C2 45
    "catcher_fa_center": 60.0,  # C1 70, C2 blank -> 50
}


def _set(base: Path, pid: str, **ratings) -> None:
    path = base / "players.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if row["player_id"] == pid:
            row.update(ratings)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PLAYER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _stored(base: Path) -> dict:
    return json.loads((base / centers.RATING_CENTERS_FILENAME).read_text())


# --- the means -------------------------------------------------------------------


def test_centres_are_over_the_act_pitchers_and_catchers():
    assert centers.RATING_CENTER_KEYS == ("hitter_speed_center",) + BATTERY_KEYS


def test_centres_of_a_small_league(tmp_path):
    base = _league(tmp_path / "league")
    assert centers.active_rating_centers(base) == EXPECTED
    assert centers.active_hitter_mean_speed(base) == EXPECTED["hitter_speed_center"]


def test_a_league_without_catchers_leaves_the_catcher_keys_out(tmp_path):
    base = _league(tmp_path / "league", catchers=False)
    found = centers.league_rating_centers(base, season="2026")
    assert "catcher_arm_center" not in found
    assert "catcher_fa_center" not in found
    assert found["pitcher_control_center"] == 51.5
    assert set(_stored(base)["seasons"]["2026"]) == set(found)


def test_missing_files_give_no_centres(tmp_path):
    assert centers.active_rating_centers(tmp_path / "missing") == {}
    assert centers.league_rating_centers(tmp_path / "missing", season="2026") == {}


def test_fixture_battery_centres():
    cal = centers.active_rating_centers(CALIBRATION)
    assert cal["pitcher_control_center"] == pytest.approx(51.31)
    assert cal["pitcher_hold_center"] == pytest.approx(50.37)
    assert cal["pitcher_arm_center"] == pytest.approx(55.83)
    assert cal["catcher_arm_center"] == pytest.approx(55.10)
    assert cal["catcher_fa_center"] == pytest.approx(54.67)
    league = centers.active_rating_centers(CALIBRATION_LEAGUE)
    assert league["pitcher_control_center"] == pytest.approx(53.57)
    assert league["pitcher_hold_center"] == pytest.approx(51.33)
    assert league["pitcher_arm_center"] == pytest.approx(59.66)
    assert league["catcher_arm_center"] == pytest.approx(56.33)
    assert league["catcher_fa_center"] == pytest.approx(56.35)


# --- once per season -------------------------------------------------------------


def test_all_centres_are_fixed_for_the_season_and_stored(tmp_path):
    base = _league(tmp_path / "league")
    assert centers.league_rating_centers(base, season="2026") == EXPECTED
    assert _stored(base)["seasons"] == {"2026": EXPECTED}

    # Ratings change mid-season: neither the cache nor the file moves.
    _set(base, "P1", control="99", hold_runner="99", arm="99")
    _set(base, "C1", arm="99", fa="99")
    assert centers.league_rating_centers(base, season="2026") == EXPECTED
    centers.clear_rating_center_cache()
    assert centers.league_rating_centers(base, season="2026") == EXPECTED

    # The next season recomputes, and the earlier one stays on file.
    nxt = centers.league_rating_centers(base, season="2027")
    assert nxt["pitcher_control_center"] == pytest.approx(70.0)
    assert nxt["catcher_fa_center"] == pytest.approx(74.5)
    stored = _stored(base)["seasons"]
    assert stored["2026"] == EXPECTED and stored["2027"] == nxt


def test_a_w0_file_gets_the_missing_centres_for_the_same_season(tmp_path):
    base = _league(tmp_path / "league")
    w0 = {
        "version": 1,
        "seasons": {
            "2025": {"hitter_speed_center": 44.0},
            "2026": {"hitter_speed_center": 47.25},
        },
    }
    (base / centers.RATING_CENTERS_FILENAME).write_text(json.dumps(w0))
    found = centers.league_rating_centers(base, season="2026")
    # The stored speed centre is kept (not recomputed to 50.0) and the
    # battery centres are computed and added to the same season.
    assert found == {**EXPECTED, "hitter_speed_center": 47.25}
    stored = _stored(base)["seasons"]
    assert stored["2026"] == found
    assert stored["2025"] == {"hitter_speed_center": 44.0}
    # Fixed from now on, like the speed centre.
    _set(base, "C1", fa="99")
    centers.clear_rating_center_cache()
    assert centers.league_rating_centers(base, season="2026") == found


def test_the_speed_getter_still_stores_only_the_speed_centre(tmp_path):
    # W0's getter fixes its own key only; the battery centres are added by
    # the first call that asks for them.
    base = _league(tmp_path / "league")
    assert centers.league_hitter_speed_center(base, season="2026") == 50.0
    assert _stored(base)["seasons"] == {"2026": {"hitter_speed_center": 50.0}}
    _set(base, "C2", sp="80")
    assert centers.league_rating_centers(base, season="2026") == EXPECTED
    assert _stored(base)["seasons"] == {"2026": EXPECTED}


def test_store_false_reads_but_never_fixes_a_centre(tmp_path):
    base = _league(tmp_path / "league")
    assert centers.league_rating_centers(base, season="2026", store=False) == EXPECTED
    assert not (base / centers.RATING_CENTERS_FILENAME).exists()
    _set(base, "P2", control="61")
    live = centers.league_rating_centers(base, season="2026", store=False)
    assert live["pitcher_control_center"] == pytest.approx(61.5)
    assert not (base / centers.RATING_CENTERS_FILENAME).exists()

    # A W0-era file: the stored speed centre is read, the battery centres
    # are computed live and neither written nor cached.
    w0 = {"version": 1, "seasons": {"2026": {"hitter_speed_center": 47.25}}}
    (base / centers.RATING_CENTERS_FILENAME).write_text(json.dumps(w0))
    found = centers.league_rating_centers(base, season="2026", store=False)
    assert found["hitter_speed_center"] == 47.25
    assert found["pitcher_control_center"] == pytest.approx(61.5)
    assert _stored(base) == w0
    _set(base, "P2", control="41")
    again = centers.league_rating_centers(base, season="2026", store=False)
    assert again["pitcher_control_center"] == pytest.approx(51.5)


def test_unknown_season_is_cached_but_never_stored(tmp_path):
    base = _league(tmp_path / "league")
    assert centers.league_rating_centers(base) == EXPECTED
    assert not (base / centers.RATING_CENTERS_FILENAME).exists()
    _set(base, "P2", control="61")
    assert centers.league_rating_centers(base) == EXPECTED
    centers.clear_rating_center_cache()
    assert centers.league_rating_centers(base)["pitcher_control_center"] == 61.5
    assert not (base / centers.RATING_CENTERS_FILENAME).exists()


@pytest.fixture
def active_league(tmp_path, monkeypatch):
    import utils.path_utils as path_utils

    root = _league(tmp_path / "data")
    (root / "schedule.csv").write_text(
        "date,home,away,result,played,boxscore\n2026-04-01,AAA,BBB,,,\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    path_utils._DATA_DIR_CACHE.clear()
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def test_overrides_carry_every_centre(active_league):
    assert centers.get_rating_center_overrides() == EXPECTED
    assert _stored(active_league)["seasons"] == {"2026": EXPECTED}


def test_watch_a_game_overrides_never_store(active_league):
    assert centers.get_rating_center_overrides(store=False) == EXPECTED
    assert not (active_league / centers.RATING_CENTERS_FILENAME).exists()


# --- tuning keys -----------------------------------------------------------------


@pytest.mark.parametrize("key", BATTERY_KEYS)
def test_battery_keys_are_registered_and_round_trip(key):
    assert DEFAULT_TUNING[key] == 50.0
    assert TuningConfig.from_overrides(overrides={key: "56.35"}).get(key) == 56.35
    assert load_tuning(overrides={key: 53.0}).get(key) == 53.0


def test_harness_meta_records_every_centre(tmp_path):
    from scripts import physics_sim_season_kpis as kpis

    merged = kpis.with_rating_centers(
        {"catcher_fa_center": 50.0}, CALIBRATION / "players.csv", CALIBRATION
    )
    assert set(merged) == set(centers.RATING_CENTER_KEYS)
    assert merged["catcher_fa_center"] == 50.0
    assert merged["pitcher_arm_center"] == pytest.approx(55.83)
    assert kpis.fixture_rating_centers(
        CALIBRATION_LEAGUE / "players.csv", CALIBRATION_LEAGUE
    ) == centers.active_rating_centers(CALIBRATION_LEAGUE)


# --- the engine reads the battery centred ----------------------------------------


def test_centred_rating_helper():
    tuning = load_tuning(overrides={"catcher_fa_center": 56.0})
    assert engine._centred_rating(56.0, "catcher_fa_center", tuning) == 50.0
    assert engine._centred_rating(66.0, "catcher_fa_center", tuning) == 60.0
    # Every centre defaults to 50, where nothing changes.
    for key in BATTERY_KEYS:
        assert engine._centred_rating(63.0, key, load_tuning()) == 63.0
    # The speed helper is the same re-expression.
    speed = load_tuning(overrides={"hitter_speed_center": 54.0})
    assert engine._centred_speed(60.0, speed) == engine._centred_rating(
        60.0, "hitter_speed_center", speed
    )


CENTRES = {
    "pitcher_control_center": 56.0,
    "pitcher_hold_center": 58.0,
    "pitcher_arm_center": 61.0,
    "catcher_arm_center": 57.0,
    "catcher_fa_center": 55.0,
}


def _at_centre():
    return load_tuning(overrides=dict(CENTRES))


def test_steal_attempt_at_the_centre_reads_as_fifty():
    def rate(tuning, hold, p_arm, c_arm, c_fa, sp=62.0):
        return engine._steal_attempt_rate(
            speed=sp, base_rate=0.03, pitcher_hold=hold, pitcher_arm=p_arm,
            catcher_arm=c_arm, catcher_fielding=c_fa, tuning=tuning,
        )

    at_fifty = rate(load_tuning(), 50.0, 50.0, 50.0, 50.0)
    at_centre = rate(_at_centre(), 58.0, 61.0, 57.0, 55.0)
    assert at_centre == pytest.approx(at_fifty)
    # Raw ratings above 50 deterred attempts before F4.
    assert rate(load_tuning(), 58.0, 61.0, 57.0, 55.0) < at_fifty
    # Each deterrent still reads its gap from the centre.
    assert rate(_at_centre(), 68.0, 61.0, 57.0, 55.0) == pytest.approx(
        rate(load_tuning(), 60.0, 50.0, 50.0, 50.0)
    )


def test_steal_success_at_the_centre_reads_as_fifty():
    def success(tuning, hold, p_arm, c_arm, c_fa, sp=50.0):
        return engine._steal_success_prob(
            speed=sp, pitcher_hold=hold, pitcher_arm=p_arm, catcher_arm=c_arm,
            catcher_fielding=c_fa, tuning=tuning,
        )

    for sp in (40.0, 50.0, 75.0):
        assert success(_at_centre(), 58.0, 61.0, 57.0, 55.0, sp) == pytest.approx(
            success(load_tuning(), 50.0, 50.0, 50.0, 50.0, sp)
        )
    assert success(load_tuning(), 58.0, 61.0, 57.0, 55.0) < success(
        load_tuning(), 50.0, 50.0, 50.0, 50.0
    )
    # The runner's speed reads against the league's hitter mean too: a 70 in
    # a league centred at 60 succeeds like a 60 in a league centred at 50.
    fast_league = load_tuning(overrides={"hitter_speed_center": 60.0})
    assert success(fast_league, 50.0, 50.0, 50.0, 50.0, 70.0) == pytest.approx(
        success(load_tuning(), 50.0, 50.0, 50.0, 50.0, 60.0)
    )
    assert success(fast_league, 50.0, 50.0, 50.0, 50.0, 70.0) < success(
        load_tuning(), 50.0, 50.0, 50.0, 50.0, 70.0
    )


def test_missed_pitch_rates_at_the_centre_read_as_fifty():
    tuning = _at_centre()
    assert engine._missed_pitch_rates(56.0, 55.0, 0.3, tuning) == pytest.approx(
        engine._missed_pitch_rates(50.0, 50.0, 0.3, load_tuning())
    )
    wp, pb = engine._missed_pitch_rates(56.0, 55.0, 0.0, tuning)
    assert wp == pytest.approx(DEFAULT_TUNING["wild_pitch_rate"])
    assert pb == pytest.approx(DEFAULT_TUNING["passed_ball_rate"])
    # The exponential ratios still hold around the centre, and the clip
    # applies to the centred rating.
    wp36, _ = engine._missed_pitch_rates(36.0, 55.0, 0.0, tuning)
    wp76, _ = engine._missed_pitch_rates(76.0, 55.0, 0.0, tuning)
    assert wp36 / wp76 == pytest.approx(math.e)
    assert engine._missed_pitch_rates(0.0, 55.0, 0.0, tuning) == (
        engine._missed_pitch_rates(26.0, 55.0, 0.0, tuning)
    )


def test_k_reach_at_the_centre_reads_as_fifty():
    tuning = _at_centre()
    for sp in (35.0, 50.0, 70.0):
        centred = engine._k_reach_prob(batter_speed=sp, catcher_arm=57.0, tuning=tuning)
        raw = engine._k_reach_prob(
            batter_speed=sp, catcher_arm=50.0, tuning=load_tuning()
        )
        assert centred == pytest.approx(raw)
    # Batter speed is a race term: raw.
    fast_league = load_tuning(overrides={"hitter_speed_center": 60.0})
    assert engine._k_reach_prob(
        batter_speed=70.0, catcher_arm=50.0, tuning=fast_league
    ) == pytest.approx(DEFAULT_TUNING["k_reach_base"] + 20.0 / 200.0)


class _Draws:
    """Stands in for ``random``: scripted draws, then 0.999 (nothing happens)."""

    def __init__(self, draws):
        self._draws = list(draws)

    def random(self):
        return self._draws.pop(0) if self._draws else 0.999


def _batter(pid: str, speed: float = 50.0) -> BatterRatings:
    return BatterRatings(
        player_id=pid, bats="R", primary_position="CF", other_positions=[],
        contact=50.0, power=50.0, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=50.0, speed=speed, eye=50.0,
        height=72.0, durability=50.0,
    )


def _ball_gets_away(monkeypatch, draw, tuning, control, fa):
    """Whether a strike-three pitch in the zone (no miss) gets away."""
    monkeypatch.setattr(engine, "random", _Draws([draw]))
    result = engine._resolve_dropped_third_strike(
        bases=BaseState(), outs=0, batter=_batter("B"),
        pitcher_control=control, catcher_fielding=fa, catcher_arm=50.0,
        tuning=tuning, location=(0.0, 2.5), zone_bottom=1.5, zone_top=3.5,
    )
    # Not dropped: an ordinary strikeout with no WP/PB draw at all.
    return result != (False, 1, 0, None, [], False)


def test_dropped_third_strike_rate_at_the_centre_reads_as_fifty(monkeypatch):
    k_rate = DEFAULT_TUNING["k_in_dirt_rate"]
    below, above = k_rate * 0.97, k_rate * 1.03
    tuning = _at_centre()
    assert _ball_gets_away(monkeypatch, below, tuning, 56.0, 55.0)
    assert not _ball_gets_away(monkeypatch, above, tuning, 56.0, 55.0)
    assert _ball_gets_away(monkeypatch, below, load_tuning(), 50.0, 50.0)
    # Raw 56 / 55 at the default centres: fewer balls get away.
    assert not _ball_gets_away(monkeypatch, below, load_tuning(), 56.0, 55.0)


def test_pickoffs_ignore_the_battery_centres(monkeypatch):
    def pickoff(tuning):
        monkeypatch.setattr(engine, "random", _Draws([0.0, 0.0]))
        bases = BaseState(first=_batter("R1", 80.0))
        return engine._attempt_pickoff(
            bases=bases, pitcher_hold=70.0, pitcher_arm=70.0, defense_arm=50.0,
            tuning=tuning,
        )

    assert pickoff(load_tuning(overrides={k: 80.0 for k in BATTERY_KEYS})) == (
        pickoff(load_tuning())
    )


def _play(seed, overrides=None):
    return engine.simulate_matchup_from_files(
        away_team="CAL01",
        home_team="CAL02",
        base_dir=CALIBRATION,
        players_path=CALIBRATION / "players.csv",
        seed=seed,
        tuning_overrides=dict(overrides) if overrides else None,
    )


def test_the_battery_centres_move_the_running_game():
    """A caller that drops the battery centres changes the running game."""

    def running(centre):
        total = 0
        for seed in range(1, 7):
            game = _play(seed, {key: centre for key in BATTERY_KEYS})
            totals = game.totals
            total += totals["sb"] + totals["cs"] + totals["wp"] + totals["pb"]
        return total

    assert running(40.0) < running(60.0)
