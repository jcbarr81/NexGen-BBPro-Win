"""Release 6a (tooling): the rating centres generation 6 will read.

``services.league_rating_centers.unstored_rating_centers`` works out, for
the KPI harness only:

- ``fielder_fa_center_<pos>`` / ``fielder_arm_center_<pos>`` (1B, 2B, 3B,
  SS, LF, CF, RF): the lineup regulars' mean fielding and arm by the
  position the saved lineup plays them at;
- ``pitcher_gf_usage_center``: the pitchers' ground-ball rating, weighted by
  expected workload like the other pitcher usage centres;
- ``hitter_gf_center`` / ``hitter_pull_center``: the lineup regulars' mean
  ground-ball and pull ratings.

Every key is registered at 50.0. They are not in a legacy or generation 5
league's ``rating_centers.json``, not in such a league game's tuning and
not a centre such a game refuses to start without.

Release 6a (fielding) wired the fielder centres in: the engine's fielding
switches read them, with the pitchers' ``fielder_fa_center_p``, and a
generation 6 season stores them (tests/test_r6a_fielding_centers.py).
Release 6a (power) wired ``hitter_gf_center`` in the same way: the
line-drive credit on doubles reads it (off below generation 6) and a
generation 6 season stores it (tests/test_r6a_power_centers.py). The other
two batted-ball centres are still read by nothing.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

import scripts.physics_sim_season_kpis as kpis
from physics_sim.centred_ratings import (
    CENTRED_RATING_KEYS,
    MODEL_CENTER_KEYS,
    REQUIRED_CENTER_KEYS,
    require_rating_centers,
)
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile
from services import league_rating_centers as centers
from tests.r5_flip_support import (  # noqa: F401  (league is a fixture)
    game_tuning,
    league,
    write_schedule,
)

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
POSITIONS = ("1B", "2B", "3B", "SS", "LF", "CF", "RF")
FA_KEYS = tuple(f"fielder_fa_center_{p.lower()}" for p in POSITIONS)
ARM_KEYS = tuple(f"fielder_arm_center_{p.lower()}" for p in POSITIONS)
OTHER_KEYS = ("pitcher_gf_usage_center", "hitter_gf_center", "hitter_pull_center")
# Release 6a (fielding) added the pitchers' fielding centre after the arms.
ALL_KEYS = FA_KEYS + ARM_KEYS + ("fielder_fa_center_p",) + OTHER_KEYS

PLAYER_FIELDS = [
    "player_id", "primary_position", "is_pitcher", "bats", "ch", "ph", "sp",
    "gf", "pl", "fa", "arm", "endurance", "control", "movement", "fb", "sl",
    "role", "preferred_pitching_role",
]
LINEUP = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH")


@pytest.fixture(autouse=True)
def _fresh_cache():
    centers.clear_rating_center_cache()
    yield
    centers.clear_rating_center_cache()


def _hitter(pid, pos, *, fa="50", arm="50", gf="50", pl="50", ch="50", ph="50"):
    return {
        "player_id": pid, "primary_position": pos, "is_pitcher": "0", "bats": "R",
        "ch": ch, "ph": ph, "sp": "50", "gf": gf, "pl": pl, "fa": fa, "arm": arm,
    }


def _pitcher(pid, *, gf, endurance="50", role="SP"):
    return {
        "player_id": pid, "primary_position": "P", "is_pitcher": "1", "bats": "R",
        "gf": gf, "fa": "50", "arm": "50", "endurance": endurance,
        "control": "50", "movement": "50", "fb": "50", "sl": "50",
        "role": role, "preferred_pitching_role": role,
    }


def _write_league(root: Path, players, rosters, lineups=None, staffs=None) -> Path:
    """A league directory: players.csv, rosters/<team>.csv (ACT rows),
    optional saved lineups ({(team, hand): [(player, position), ...]}) and
    pitching staffs ({team: [(player, label), ...]})."""
    (root / "rosters").mkdir(parents=True, exist_ok=True)
    (root / "lineups").mkdir(exist_ok=True)
    with (root / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PLAYER_FIELDS)
        writer.writeheader()
        for row in players:
            writer.writerow({key: row.get(key, "") for key in PLAYER_FIELDS})
    for team, ids in rosters.items():
        with (root / "rosters" / f"{team}.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            csv.writer(fh).writerows((pid, "ACT") for pid in ids)
    for (team, hand), rows in (lineups or {}).items():
        with (root / "lineups" / f"{team}_vs_{hand}.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            writer = csv.writer(fh)
            writer.writerow(["order", "player_id", "position"])
            writer.writerows(
                (order, pid, pos) for order, (pid, pos) in enumerate(rows, start=1)
            )
    for team, rows in (staffs or {}).items():
        with (root / "rosters" / f"{team}_pitching.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            csv.writer(fh).writerows(rows)
    return root


def _club(prefix: str, fa_by_pos: dict, arm_by_pos: dict | None = None):
    """Nine hitters, one per lineup position, with the given fa (and arm)."""
    arm_by_pos = arm_by_pos or {}
    return [
        _hitter(
            f"{prefix}{pos}", pos, fa=str(fa_by_pos.get(pos, 50)),
            arm=str(arm_by_pos.get(pos, 50)),
        )
        for pos in LINEUP
    ]


def _as_listed(prefix: str):
    return [(f"{prefix}{pos}", pos) for pos in LINEUP]


# --- registered, and nothing more --------------------------------------------------


def test_every_key_is_registered_at_50_and_named_by_the_module():
    assert centers.FIELDER_CENTER_POSITIONS == POSITIONS
    assert tuple(centers.FIELDER_FA_CENTER_KEYS.values()) == FA_KEYS
    assert tuple(centers.FIELDER_ARM_CENTER_KEYS.values()) == ARM_KEYS
    assert centers.UNSTORED_CENTER_KEYS == ALL_KEYS
    for key in ALL_KEYS:
        assert DEFAULT_TUNING[key] == 50.0, key
    # from_overrides keeps a registered key (an unregistered one is dropped
    # without a word).
    tuning = load_tuning({key: 61.5 for key in ALL_KEYS})
    assert all(tuning.get(key) == 61.5 for key in ALL_KEYS)


def test_they_are_not_stored_centres_and_no_game_requires_them():
    assert not set(ALL_KEYS) & set(centers.RATING_CENTER_KEYS)
    assert not set(ALL_KEYS) & set(centers.RELATIVE_CENTER_KEYS)
    assert not set(ALL_KEYS) & set(centers.PITCHER_USAGE_CENTER_KEYS)
    assert not set(ALL_KEYS) & set(MODEL_CENTER_KEYS)
    assert not set(ALL_KEYS) & set(MODEL_CENTER_KEYS.values())
    assert not set(ALL_KEYS) & CENTRED_RATING_KEYS
    assert not set(ALL_KEYS) & REQUIRED_CENTER_KEYS
    # A generation 5 game with every centre it needs and none of these starts.
    overrides = dict(engine_profile(5))
    overrides.update({key: 50.0 for key in REQUIRED_CENTER_KEYS})
    require_rating_centers(load_tuning(overrides))


def test_nothing_in_the_engine_reads_them_yet():
    """The Release 6 build branches remove a key from here as they wire it
    in (and add the test of what reads it). The fielder centres are wired
    (tests/test_r6a_fielding_spray_range.py and test_r6a_fielding_errors.py),
    and so is ``hitter_gf_center``: the line-drive credit on doubles reads
    it (tests/test_r6a_power_doubles.py, test_r6a_power_centers.py).
    Release 6b wired the last two: the batted-ball kernel reads them
    (physics._batted_ball_kernel, under switches generation 7 turns on;
    tests/test_r7_centers.py), and only there and in the check that they
    were delivered."""
    pattern = re.compile(
        r"pitcher_gf_usage_center|hitter_pull_center"
    )
    readers = {"config.py", "physics.py", "centred_ratings.py"}
    for path in sorted((REPO / "physics_sim").glob("*.py")):
        if path.name in readers:
            continue
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name
    for folder in ("playbalance", "api", "utils"):
        for path in sorted((REPO / folder).rglob("*.py")):
            assert not pattern.search(path.read_text(encoding="utf-8")), path


# --- the fielder centres -----------------------------------------------------------


def test_fielders_are_averaged_by_the_position_the_lineup_plays_them_at(tmp_path):
    """Club A's lineup moves its second baseman to short against lefties."""
    club_a = _club("A", {"SS": 70, "2B": 40, "CF": 60}, {"SS": 64, "2B": 44})
    club_b = _club("B", {"SS": 50, "2B": 50, "CF": 40}, {"SS": 50, "2B": 50})
    swapped = [
        (pid, {"SS": "2B", "2B": "SS"}.get(pos, pos)) for pid, pos in _as_listed("A")
    ]
    root = _write_league(
        tmp_path,
        club_a + club_b,
        {"A": [p["player_id"] for p in club_a], "B": [p["player_id"] for p in club_b]},
        lineups={
            ("A", "rhp"): _as_listed("A"), ("A", "lhp"): swapped,
            ("B", "rhp"): _as_listed("B"), ("B", "lhp"): _as_listed("B"),
        },
    )
    out = centers.unstored_rating_centers(root)
    # SS spots: A's SS (70) once, A's 2B (40) once, B's SS (50) twice.
    assert out["fielder_fa_center_ss"] == pytest.approx((70 + 40 + 50 + 50) / 4)
    assert out["fielder_fa_center_2b"] == pytest.approx((40 + 70 + 50 + 50) / 4)
    assert out["fielder_arm_center_ss"] == pytest.approx((64 + 44 + 50 + 50) / 4)
    # An everyday centre fielder counts twice, like an everyday hitter.
    assert out["fielder_fa_center_cf"] == pytest.approx((60 + 60 + 40 + 40) / 4)
    # The catcher and the DH are no fielder centre (and this league has no
    # pitcher for the two pitcher centres).
    assert set(out) == set(ALL_KEYS) - {
        "pitcher_gf_usage_center", "fielder_fa_center_p"
    }
    regulars = centers._regular_fielder_ids(
        root / "lineups",
        centers._active_ids_by_team(root / "rosters"),
        {p["player_id"]: p for p in club_a + club_b},
        {p["player_id"]: 50.0 for p in club_a + club_b},
    )
    assert sorted(regulars["SS"]) == ["A2B", "ASS", "BSS", "BSS"]
    assert sorted(regulars["CF"]) == ["ACF", "ACF", "BCF", "BCF"]
    assert set(regulars) == set(POSITIONS)


def test_a_club_with_no_saved_lineup_falls_back_to_primary_positions(tmp_path):
    """Its best hitter (by lineup value) at each primary position; a bench
    player and the saved-lineup club are unaffected."""
    club_a = _club("A", {"SS": 70, "LF": 30})
    # A better and a worse shortstop on the club with no lineup files.
    club_b = _club("B", {"SS": 40, "LF": 60}) + [
        _hitter("Bbench", "SS", fa="90", ch="20", ph="20"),
        _hitter("Bstar", "LF", fa="80", ch="90", ph="90"),
    ]
    root = _write_league(
        tmp_path,
        club_a + club_b,
        {"A": [p["player_id"] for p in club_a], "B": [p["player_id"] for p in club_b]},
        lineups={("A", "rhp"): _as_listed("A"), ("A", "lhp"): _as_listed("A")},
    )
    out = centers.unstored_rating_centers(root)
    # SS: A's 70 twice; B's regular SS (40) twice, not the weak-hitting 90.
    assert out["fielder_fa_center_ss"] == pytest.approx((70 + 70 + 40 + 40) / 4)
    # LF: B's best hitter listed in left is the star (80), not the 60.
    assert out["fielder_fa_center_lf"] == pytest.approx((30 + 30 + 80 + 80) / 4)


def test_a_lineup_a_game_would_not_play_as_saved_is_not_used(tmp_path):
    """Eight hitters, a repeated hitter or a hitter off the ACT roster: the
    game rebuilds the lineup, so the centre reads primary positions."""
    club = _club("A", {"SS": 70, "2B": 40})
    ids = [p["player_id"] for p in club]
    swapped = [
        (pid, {"SS": "2B", "2B": "SS"}.get(pos, pos)) for pid, pos in _as_listed("A")
    ]
    broken = {
        "short": swapped[:8],
        "repeat": swapped[:8] + [swapped[0]],
        "stranger": swapped[:8] + [("ghost", "DH")],
    }
    for name, rows in broken.items():
        root = _write_league(
            tmp_path / name, club, {"A": ids},
            lineups={("A", "rhp"): rows, ("A", "lhp"): rows},
        )
        out = centers.unstored_rating_centers(root)
        assert out["fielder_fa_center_ss"] == 70.0, name
        assert out["fielder_fa_center_2b"] == 40.0, name
    # The same swap in a usable file IS read.
    root = _write_league(
        tmp_path / "usable", club, {"A": ids},
        lineups={("A", "rhp"): swapped, ("A", "lhp"): swapped},
    )
    out = centers.unstored_rating_centers(root)
    assert out["fielder_fa_center_ss"] == 40.0
    assert out["fielder_fa_center_2b"] == 70.0


def test_a_blank_lineup_position_and_a_blank_rating(tmp_path):
    club = _club("A", {"SS": 70})
    club[LINEUP.index("3B")]["fa"] = ""  # a blank rating counts as 50
    rows = [(pid, "" if pos == "SS" else pos) for pid, pos in _as_listed("A")]
    root = _write_league(
        tmp_path, club, {"A": [p["player_id"] for p in club]},
        lineups={("A", "rhp"): rows, ("A", "lhp"): rows},
    )
    out = centers.unstored_rating_centers(root)
    assert out["fielder_fa_center_ss"] == 70.0  # read at his primary position
    assert out["fielder_fa_center_3b"] == 50.0


def test_a_position_nobody_plays_reads_every_position_s_mean(tmp_path):
    """Release 6a (fielding): it used to be left out; the engine now
    refuses a game on a fielder centre that was not delivered, so a
    position no regular plays reads the mean over the regulars at every
    position."""
    club = [
        p for p in _club("A", {"SS": 62, "CF": 56}) if p["primary_position"] != "RF"
    ]
    root = _write_league(tmp_path, club, {"A": [p["player_id"] for p in club]})
    out = centers.unstored_rating_centers(root)
    everyone = round((50 * 4 + 62 + 56) / 6, 2)
    assert out["fielder_fa_center_rf"] == everyone
    assert out["fielder_arm_center_rf"] == 50.0
    assert out["fielder_fa_center_cf"] == 56.0
    assert centers.unstored_rating_centers(tmp_path / "nowhere") == {}


def test_only_act_players_count(tmp_path):
    club = _club("A", {"SS": 70})
    minor = _hitter("AAA1", "SS", fa="10", ch="99", ph="99")
    root = _write_league(
        tmp_path, club + [minor], {"A": [p["player_id"] for p in club]}
    )
    with (root / "rosters" / "A.csv").open("a", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(("AAA1", "AAA"))
    assert centers.unstored_rating_centers(root)["fielder_fa_center_ss"] == 70.0


# --- the batted-ball centres --------------------------------------------------------


def test_hitter_gf_and_pull_are_the_lineup_regulars_means(tmp_path):
    """An everyday hitter counts twice, a platoon hitter once, the bench
    never: the regulars of the Contact / Eye / Power centres."""
    club = _club("A", {})
    for i, row in enumerate(club):
        row["gf"], row["pl"] = str(40 + i), str(60 - i)
    platoon = _hitter("Aplatoon", "DH", gf="90", pl="10")
    bench = _hitter("Abench", "1B", gf="0.5", pl="99")
    everyday = _as_listed("A")
    versus_left = everyday[:8] + [("Aplatoon", "DH")]
    root = _write_league(
        tmp_path, club + [platoon, bench],
        {"A": [p["player_id"] for p in club] + ["Aplatoon", "Abench"]},
        lineups={("A", "rhp"): everyday, ("A", "lhp"): versus_left},
    )
    gf = [40 + i for i in range(9)] + [40 + i for i in range(8)] + [90]
    pl = [60 - i for i in range(9)] + [60 - i for i in range(8)] + [10]
    out = centers.unstored_rating_centers(root)
    assert out["hitter_gf_center"] == round(sum(gf) / len(gf), 2)
    assert out["hitter_pull_center"] == round(sum(pl) / len(pl), 2)


def test_pitcher_gf_is_weighted_by_expected_workload(tmp_path):
    """Five rotation starters count 2.5 times a reliever, as in the other
    pitcher usage centres."""
    starters = [_pitcher(f"SP{i}", gf="60", endurance="80") for i in range(5)]
    relievers = [_pitcher(f"RP{i}", gf="40", endurance="20", role="RP") for i in range(7)]
    hitters = _club("A", {})
    ids = [p["player_id"] for p in hitters + starters + relievers]
    staff = [(f"SP{i}", f"SP{i + 1}") for i in range(5)] + [
        (f"RP{i}", "MR") for i in range(7)
    ]
    root = _write_league(
        tmp_path, hitters + starters + relievers, {"A": ids}, staffs={"A": staff}
    )
    expected = (5 * 2.5 * 60 + 7 * 1.0 * 40) / (5 * 2.5 + 7)
    out = centers.unstored_rating_centers(root)
    assert out["pitcher_gf_usage_center"] == round(expected, 2)
    assert out["pitcher_gf_usage_center"] != round((5 * 60 + 7 * 40) / 12, 2)
    # The same weights the harness's Monte Carlo draws pitchers with.
    loads = centers.active_pitcher_workloads(root)
    assert sorted(w for _row, w in loads) == [1.0] * 7 + [2.5] * 5
    assert {row["player_id"] for row, w in loads if w == 2.5} == {
        f"SP{i}" for i in range(5)
    }
    # The stored usage centres are computed exactly as before.
    stored = centers.active_rating_centers(root)
    assert set(centers.PITCHER_USAGE_CENTER_KEYS) <= set(stored)
    assert "pitcher_gf_usage_center" not in stored


def test_the_calibration_fixture_values():
    out = centers.unstored_rating_centers(CALIBRATION)
    assert tuple(out) == ALL_KEYS  # every key, in the registered order
    assert all(30.0 < value < 70.0 for value in out.values())
    assert out == centers.unstored_rating_centers(CALIBRATION)  # no state
    # Shortstops are better gloves than left fielders, and their mean is
    # not the all-hitter mean: the reason the centre is by position.
    assert out["fielder_fa_center_ss"] > out["fielder_fa_center_lf"] + 3.0
    players = CALIBRATION / "players.csv"
    assert centers.unstored_rating_centers(CALIBRATION, players_path=players) == out


# --- the harness supplies them, a league does not ------------------------------------


def test_the_harness_supplies_them_with_the_stored_centres():
    players = CALIBRATION / "players.csv"
    extra = kpis.fixture_unstored_rating_centers(players, CALIBRATION)
    assert extra == centers.unstored_rating_centers(CALIBRATION)
    merged = kpis.with_rating_centers({"hr_scale": 0.9}, players, CALIBRATION)
    for key in ALL_KEYS:
        assert merged[key] == extra[key], key
    stored = kpis.fixture_rating_centers(players, CALIBRATION)
    for key, value in stored.items():
        assert merged[key] == value, key
    assert merged["hr_scale"] == 0.9
    # An explicit centre still wins, so an experiment can pin one.
    pinned = kpis.with_rating_centers({"hitter_gf_center": 44.0}, players, CALIBRATION)
    assert pinned["hitter_gf_center"] == 44.0
    # The engine is told they were delivered.
    assert set(ALL_KEYS) <= load_tuning(merged).delivered


def test_a_game_with_them_is_the_game_without_them():
    """Nothing reads them: any value plays the identical game, on the legacy
    engine and on generation 5."""
    from physics_sim.engine import simulate_matchup_from_files

    players = CALIBRATION / "players.csv"

    def play(overrides):
        result = simulate_matchup_from_files(
            away_team="CAL01", home_team="CAL02", players_path=players,
            base_dir=CALIBRATION, seed=7, tuning_overrides=overrides,
        )
        return result.totals, result.pitch_log, result.metadata

    stored = kpis.fixture_rating_centers(players, CALIBRATION)
    for profile in ({}, engine_profile(5)):
        base = {**stored, **profile}
        plain = play(base)
        assert play({**base, **{key: 50.0 for key in ALL_KEYS}}) == plain
        assert play({**base, **{key: 73.0 for key in ALL_KEYS}}) == plain


def test_active_rating_centers_does_not_return_them():
    stored = centers.active_rating_centers(CALIBRATION)
    assert not set(stored) & set(ALL_KEYS)
    assert set(stored) <= set(centers.RATING_CENTER_KEYS)


def test_a_league_game_is_not_given_them_and_does_not_store_them(league, monkeypatch):
    write_schedule(league, 2026)
    tuning = game_tuning(monkeypatch, "2026-04-01")
    assert tuning["swing_model"] == 1.0  # a generation 5 season
    assert not set(tuning) & set(ALL_KEYS)
    stored = json.loads((league / centers.RATING_CENTERS_FILENAME).read_text())
    entry = stored["seasons"]["2026"]
    assert not set(entry) & set(ALL_KEYS)
    assert not set(centers.league_rating_centers()) & set(ALL_KEYS)
    assert not set(centers.get_rating_center_overrides()) & set(ALL_KEYS)
    # Working them out for a report writes nothing either.
    before = (league / centers.RATING_CENTERS_FILENAME).read_text()
    assert set(centers.unstored_rating_centers(league)) == set(ALL_KEYS)
    assert (league / centers.RATING_CENTERS_FILENAME).read_text() == before
