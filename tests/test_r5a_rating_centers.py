"""Release 5a (tooling): the rating centres Release 5 will read.

``services.league_rating_centers`` gains, next to the Release 4 speed and
battery centres and delivered the same way (the season's
``rating_centers.json``, the live game's tuning, the KPI harness):

- ``hitter_contact_center`` / ``hitter_eye_center``: ACT hitters' means;
- ``pitcher_movement_center`` / ``pitcher_grade_center``: ACT pitchers' mean
  movement and mean pitch grade (each pitcher's average over his pitches);
- ``hitter_vl_center_l/_r/_s``: ACT hitters' mean ``vl`` by batting side,
  the all-hitter mean for a side with fewer than 10 hitters;
- ``hitter_bats_share_l/_r/_s``: the share of ACT hitters on each side.

Nothing in the engine reads them yet, so a game with any value for them is
identical to one without.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import physics_sim.engine as engine
from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from services import league_rating_centers as centers

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
CALIBRATION_LEAGUE = REPO / "data" / "calibration_league"

R4_KEYS = (
    "hitter_speed_center",
    "pitcher_control_center",
    "pitcher_hold_center",
    "pitcher_arm_center",
    "catcher_arm_center",
    "catcher_fa_center",
)
CENTER_KEYS = (
    "hitter_contact_center",
    "hitter_eye_center",
    "pitcher_movement_center",
    "pitcher_grade_center",
    "hitter_vl_center_l",
    "hitter_vl_center_r",
    "hitter_vl_center_s",
)
SHARE_KEYS = ("hitter_bats_share_l", "hitter_bats_share_r", "hitter_bats_share_s")
R5A_KEYS = CENTER_KEYS + SHARE_KEYS

PLAYER_FIELDS = [
    "player_id", "primary_position", "is_pitcher", "bats", "sp", "ch", "eye",
    "vl", "control", "movement", "hold_runner", "arm", "fa",
    "fb", "sl", "si", "cb", "cu", "scb", "kn",
]


@pytest.fixture(autouse=True)
def _fresh_cache():
    centers.clear_rating_center_cache()
    yield
    centers.clear_rating_center_cache()


def _write_players(root: Path, players: list[dict]) -> None:
    with (root / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PLAYER_FIELDS)
        writer.writeheader()
        for row in players:
            writer.writerow({key: row.get(key, "") for key in PLAYER_FIELDS})


def _write_league(root: Path, players: list[dict], rosters: dict[str, list[tuple]]):
    root.mkdir(parents=True, exist_ok=True)
    _write_players(root, players)
    (root / "rosters").mkdir(exist_ok=True)
    for name, rows in rosters.items():
        with (root / "rosters" / f"{name}.csv").open(
            "w", newline="", encoding="utf-8"
        ) as fh:
            csv.writer(fh).writerows(rows)


def _hitter(pid, bats, *, ch="50", eye="50", vl="50", pos="CF"):
    return {
        "player_id": pid, "primary_position": pos, "is_pitcher": "0",
        "bats": bats, "ch": ch, "eye": eye, "vl": vl,
    }


def _pitcher(pid, *, movement="50", vl="", **pitches):
    return {
        "player_id": pid, "primary_position": "SP", "is_pitcher": "1",
        "bats": "R", "movement": movement, "vl": vl, **pitches,
    }


def _league(root: Path) -> Path:
    """12 right-handed, 10 left-handed and 3 switch ACT hitters, 4 ACT
    pitchers, and minor leaguers who must not count."""
    players = []
    # R: vl 60 x 12; ch 40..62 step 2 (mean 51); eye = ch + 4 (mean 55).
    for i in range(12):
        players.append(
            _hitter(f"R{i}", "R", ch=str(40 + 2 * i), eye=str(44 + 2 * i), vl="60")
        )
    # L: vl 40 x 10; ch 50, eye blank -> reads as Contact (50).
    for i in range(10):
        players.append(_hitter(f"L{i}", "L" if i else "l", ch="50", eye="", vl="40"))
    # S: three hitters, vl 90: too few for a centre of their own.
    for i in range(3):
        players.append(_hitter(f"S{i}", "S", ch="56", eye="56", vl="90"))
    players += [
        # fb 60, sl 40 -> 50; a blank and a 0 pitch are not thrown.
        _pitcher("P1", movement="60", fb="60", sl="40", cb="0", cu=""),
        _pitcher("P2", movement="40", fb="70"),
        # No pitches listed: counts for movement, not for the grade.
        _pitcher("P3", movement="56"),
        # A pitcher's vl is never a hitter's.
        _pitcher("P4", movement="", vl="99", fb="55", si="65", kn="75"),
        # Not on an ACT roster.
        _hitter("M1", "S", ch="99", eye="99", vl="99"),
        _pitcher("M2", movement="99", fb="99"),
    ]
    act = [(p["player_id"], "ACT") for p in players if p["player_id"][0] != "M"]
    _write_league(
        root,
        players,
        {
            "AAA": act[:15] + [("M1", "AAA")],
            "BBB": act[15:] + [("M2", "LOW")],
            # A side file is never a roster.
            "BBB_pitching": [("M1", "ACT"), ("M2", "ACT")],
        },
    )
    return root


# Hitter means: ch (12*51 + 10*50 + 3*56) / 25 = 51.2; eye (12*55 + 10*50 +
# 3*56) / 25 = 53.12; vl overall (12*60 + 10*40 + 3*90) / 25 = 55.6.
EXPECTED = {
    "hitter_contact_center": 51.2,
    "hitter_eye_center": 53.12,
    "pitcher_movement_center": 51.5,  # 60, 40, 56, blank -> 50
    "pitcher_grade_center": 61.67,  # P1 50, P2 70, P4 65; P3 has none
    "hitter_vl_center_l": 40.0,
    "hitter_vl_center_r": 60.0,
    "hitter_vl_center_s": 55.6,  # 3 switch hitters: the all-hitter mean
    "hitter_bats_share_l": 0.4,
    "hitter_bats_share_r": 0.48,
    "hitter_bats_share_s": 0.12,
}


def _stored(base: Path) -> dict:
    return json.loads((base / centers.RATING_CENTERS_FILENAME).read_text())


# --- the keys ------------------------------------------------------------------


def test_the_release_4_keys_keep_their_place_and_the_5a_keys_follow():
    assert centers.RATING_CENTER_KEYS[:6] == R4_KEYS
    assert set(centers.RATING_CENTER_KEYS[6:]) == set(R5A_KEYS)
    assert len(centers.RATING_CENTER_KEYS) == len(set(centers.RATING_CENTER_KEYS)) == 16
    assert tuple(centers.HITTER_VL_CENTER_KEYS.values()) == CENTER_KEYS[4:]
    assert tuple(centers.HITTER_BATS_SHARE_KEYS.values()) == SHARE_KEYS


@pytest.mark.parametrize("key", CENTER_KEYS)
def test_centres_are_registered_at_fifty(key):
    assert DEFAULT_TUNING[key] == 50.0
    # from_overrides drops a key that is not registered.
    assert TuningConfig.from_overrides(overrides={key: "53.25"}).get(key) == 53.25
    assert load_tuning().get(key) == 50.0


@pytest.mark.parametrize("key", SHARE_KEYS)
def test_shares_are_registered_at_zero_meaning_unknown(key):
    assert DEFAULT_TUNING[key] == 0.0
    assert load_tuning(overrides={key: 0.2385}).get(key) == 0.2385
    assert load_tuning().get(key) == 0.0


# --- the means -------------------------------------------------------------------


def test_centres_of_a_small_league(tmp_path):
    base = _league(tmp_path / "league")
    found = centers.active_rating_centers(base)
    assert {key: found[key] for key in R5A_KEYS} == EXPECTED
    assert list(found) == [k for k in centers.RATING_CENTER_KEYS if k in found]


def test_a_side_with_ten_hitters_gets_its_own_vl_centre(tmp_path):
    base = _league(tmp_path / "league")
    # Nine left-handed hitters: one short, so the side reads the overall
    # mean; the tenth gave it its own (EXPECTED above).
    with (base / "rosters" / "BBB.csv").open(newline="", encoding="utf-8") as fh:
        rows = [row for row in csv.reader(fh) if row[0] != "L9"]
    with (base / "rosters" / "BBB.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    found = centers.active_rating_centers(base)
    overall = round((12 * 60 + 9 * 40 + 3 * 90) / 24, 2)
    assert found["hitter_vl_center_l"] == overall == 56.25
    assert found["hitter_vl_center_s"] == overall
    assert found["hitter_vl_center_r"] == 60.0
    assert found["hitter_bats_share_l"] == 0.375
    assert found["hitter_bats_share_r"] == 0.5
    assert found["hitter_bats_share_s"] == 0.125


def test_shares_sum_to_one_whatever_the_rounding(tmp_path):
    players = [_hitter(f"H{i}", "LRS"[i % 3]) for i in range(3)]
    base = tmp_path / "league"
    _write_league(base, players, {"AAA": [(p["player_id"], "ACT") for p in players]})
    found = centers.active_rating_centers(base)
    shares = [found[key] for key in SHARE_KEYS]
    assert shares == [0.3333, 0.3333, 0.3334]
    assert sum(shares) == pytest.approx(1.0, abs=1e-12)
    for fixture in (CALIBRATION, CALIBRATION_LEAGUE):
        fx = centers.active_rating_centers(fixture)
        assert sum(fx[key] for key in SHARE_KEYS) == pytest.approx(1.0, abs=1e-12)


def test_a_blank_or_unknown_batting_side_bats_right(tmp_path):
    players = [_hitter("H1", ""), _hitter("H2", "B"), _hitter("H3", "L")]
    base = tmp_path / "league"
    _write_league(base, players, {"AAA": [(p["player_id"], "ACT") for p in players]})
    found = centers.active_rating_centers(base)
    assert [found[key] for key in SHARE_KEYS] == [0.3333, 0.6667, 0.0]


def test_a_league_without_hitters_or_pitches_leaves_those_keys_out(tmp_path):
    base = tmp_path / "league"
    players = [_pitcher("P1", movement="62")]
    _write_league(base, players, {"AAA": [("P1", "ACT")]})
    found = centers.league_rating_centers(base, season="2026")
    # No hitter: no contact / eye / vl centre and no shares. No pitch
    # grades: no grade centre. The engine keeps its defaults for them.
    assert found["pitcher_movement_center"] == 62.0
    assert not set(found) & (set(R5A_KEYS) - {"pitcher_movement_center"})
    assert set(_stored(base)["seasons"]["2026"]) == set(found)
    assert centers.active_rating_centers(tmp_path / "missing") == {}


def test_fixture_centres_match_the_plan():
    # RELEASE5_PLAN 0.8: hitter vl means L/R/S 49.9/49.1/49.4 (calibration)
    # and 45.0/53.6/49.4 (league fixture).
    cal = centers.active_rating_centers(CALIBRATION)
    assert cal["hitter_vl_center_l"] == pytest.approx(49.86)
    assert cal["hitter_vl_center_r"] == pytest.approx(49.05)
    assert cal["hitter_vl_center_s"] == pytest.approx(49.35)
    assert cal["hitter_contact_center"] == pytest.approx(48.81)
    assert cal["hitter_eye_center"] == pytest.approx(48.41)
    assert cal["pitcher_movement_center"] == pytest.approx(52.96)
    assert cal["pitcher_grade_center"] == pytest.approx(54.76)
    assert [cal[key] for key in SHARE_KEYS] == [0.3846, 0.5128, 0.1026]
    league = centers.active_rating_centers(CALIBRATION_LEAGUE)
    assert league["hitter_vl_center_l"] == pytest.approx(44.97)
    assert league["hitter_vl_center_r"] == pytest.approx(53.58)
    assert league["hitter_vl_center_s"] == pytest.approx(49.42)
    assert league["hitter_contact_center"] == pytest.approx(50.68)
    assert league["hitter_eye_center"] == pytest.approx(50.23)
    assert league["pitcher_movement_center"] == pytest.approx(56.41)
    assert league["pitcher_grade_center"] == pytest.approx(58.08)
    assert [league[key] for key in SHARE_KEYS] == [0.2385, 0.6513, 0.1102]
    # The Release 4 centres did not move.
    assert cal["hitter_speed_center"] == pytest.approx(47.72)
    assert league["catcher_fa_center"] == pytest.approx(56.35)


# --- once per season -------------------------------------------------------------


def _set(base: Path, pid: str, **ratings) -> None:
    with (base / "players.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if row["player_id"] == pid:
            row.update(ratings)
    _write_players(base, rows)


def test_new_keys_are_fixed_for_the_season_and_stored(tmp_path):
    base = _league(tmp_path / "league")
    found = centers.league_rating_centers(base, season="2026")
    assert {key: found[key] for key in R5A_KEYS} == EXPECTED
    assert _stored(base)["seasons"]["2026"] == found

    # Ratings and batting sides change mid-season: nothing moves.
    _set(base, "R0", ch="99", eye="99", vl="99", bats="L")
    _set(base, "P2", movement="99", fb="99")
    assert centers.league_rating_centers(base, season="2026") == found
    centers.clear_rating_center_cache()
    assert centers.league_rating_centers(base, season="2026") == found

    # The next season recomputes; the earlier one stays on file.
    nxt = centers.league_rating_centers(base, season="2027")
    assert nxt["hitter_bats_share_l"] == 0.44
    assert nxt["pitcher_grade_center"] != found["pitcher_grade_center"]
    stored = _stored(base)["seasons"]
    assert stored["2026"] == found and stored["2027"] == nxt


def test_an_existing_season_file_gains_the_keys_without_changing_a_value(tmp_path):
    base = _league(tmp_path / "league")
    # A Release 4 file: values that the current rosters would NOT reproduce,
    # so a recompute would show.
    r4_season = {
        "hitter_speed_center": 47.25,
        "pitcher_control_center": 53.5,
        "pitcher_hold_center": 51.25,
        "pitcher_arm_center": 59.5,
        "catcher_arm_center": 56.25,
        "catcher_fa_center": 56.5,
    }
    before = {
        "version": 1,
        "seasons": {"2025": {"hitter_speed_center": 44.0}, "2026": dict(r4_season)},
    }
    (base / centers.RATING_CENTERS_FILENAME).write_text(json.dumps(before))
    assert centers.active_rating_centers(base)["hitter_speed_center"] == 50.0

    found = centers.league_rating_centers(base, season="2026")
    assert found == {**r4_season, **EXPECTED}
    stored = _stored(base)["seasons"]
    assert stored["2026"] == {**r4_season, **EXPECTED}
    assert {key: stored["2026"][key] for key in r4_season} == r4_season
    assert stored["2025"] == {"hitter_speed_center": 44.0}

    # Fixed from now on, like every other centre, and across a restart.
    _set(base, "L1", vl="99", bats="S")
    centers.clear_rating_center_cache()
    assert centers.league_rating_centers(base, season="2026") == found
    assert _stored(base)["seasons"]["2026"] == {**r4_season, **EXPECTED}


def test_a_partly_stored_season_keeps_what_it_has(tmp_path):
    base = _league(tmp_path / "league")
    partial = {"hitter_vl_center_l": 12.5, "hitter_bats_share_r": 0.0}
    (base / centers.RATING_CENTERS_FILENAME).write_text(
        json.dumps({"version": 1, "seasons": {"2026": partial}})
    )
    found = centers.league_rating_centers(base, season="2026")
    # A stored 0.0 share is a value, not a gap.
    assert found["hitter_bats_share_r"] == 0.0
    assert found["hitter_vl_center_l"] == 12.5
    assert found["hitter_vl_center_r"] == EXPECTED["hitter_vl_center_r"]
    assert _stored(base)["seasons"]["2026"] == found


def test_store_false_reads_but_never_adds_the_keys(tmp_path):
    base = _league(tmp_path / "league")
    r4_file = {"version": 1, "seasons": {"2026": {"hitter_speed_center": 47.25}}}
    (base / centers.RATING_CENTERS_FILENAME).write_text(json.dumps(r4_file))
    found = centers.league_rating_centers(base, season="2026", store=False)
    assert found["hitter_speed_center"] == 47.25
    assert {key: found[key] for key in R5A_KEYS} == EXPECTED
    assert _stored(base) == r4_file
    # Not cached either: a later roster is read live.
    _set(base, "S0", bats="R")
    again = centers.league_rating_centers(base, season="2026", store=False)
    assert again["hitter_bats_share_s"] == 0.08


# --- delivery: live tuning and the KPI harness ------------------------------------


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


def test_live_overrides_carry_the_new_keys_into_the_tuning(active_league):
    overrides = centers.get_rating_center_overrides()
    assert {key: overrides[key] for key in R5A_KEYS} == EXPECTED
    assert _stored(active_league)["seasons"]["2026"] == overrides
    # Every key survives TuningConfig (an unregistered one would be dropped).
    tuning = load_tuning(overrides=overrides)
    for key, value in EXPECTED.items():
        assert tuning.get(key) == value


def test_watch_a_game_overrides_never_store(active_league):
    overrides = centers.get_rating_center_overrides(store=False)
    assert {key: overrides[key] for key in R5A_KEYS} == EXPECTED
    assert not (active_league / centers.RATING_CENTERS_FILENAME).exists()


def test_game_runner_reads_the_same_getter():
    # The live game layers get_rating_center_overrides() into its tuning
    # (tests/test_r4_foundation.py covers the layering and the parallel-day
    # workers); the new keys ride in that dict.
    from playbalance import game_runner

    assert game_runner.get_rating_center_overrides is centers.get_rating_center_overrides


class _Captured(Exception):
    pass


def test_harness_passes_and_records_the_new_keys(monkeypatch):
    from scripts import physics_sim_season_kpis as kpis

    fixture = centers.active_rating_centers(CALIBRATION_LEAGUE)
    assert set(fixture) == set(centers.RATING_CENTER_KEYS)
    assert kpis.fixture_rating_centers(
        CALIBRATION_LEAGUE / "players.csv", CALIBRATION_LEAGUE
    ) == fixture
    merged = kpis.with_rating_centers(
        {"hitter_vl_center_l": 50.0},
        CALIBRATION_LEAGUE / "players.csv",
        CALIBRATION_LEAGUE,
    )
    assert merged == {**fixture, "hitter_vl_center_l": 50.0}

    seen = {}

    def fake_matchup(**kwargs):
        seen.update(kwargs)
        raise _Captured

    monkeypatch.setattr(kpis, "simulate_matchup_from_files", fake_matchup)
    with pytest.raises(_Captured):
        kpis.run_sim(
            162, 1, CALIBRATION_LEAGUE / "players.csv", None, CALIBRATION_LEAGUE
        )
    assert seen["tuning_overrides"] == fixture
    # A profile may pin one, like any other knob.
    assert kpis.RATING_CENTER_KEYS == centers.RATING_CENTER_KEYS


# --- nothing reads them yet --------------------------------------------------------


def _play(overrides):
    return engine.simulate_matchup_from_files(
        away_team="ALB",
        home_team="AUS",
        players_path=CALIBRATION_LEAGUE / "players.csv",
        base_dir=CALIBRATION_LEAGUE,
        seed=20261011,
        tuning_overrides=overrides,
    )


def test_a_game_is_identical_whatever_the_new_keys_hold():
    base = _play(None)
    fixture = {
        key: value
        for key, value in centers.active_rating_centers(CALIBRATION_LEAGUE).items()
        if key in R5A_KEYS
    }
    wild = {key: 85.0 for key in CENTER_KEYS}
    wild.update(hitter_bats_share_l=0.9, hitter_bats_share_r=0.05, hitter_bats_share_s=0.05)
    for overrides in (fixture, wild):
        game = _play(overrides)
        assert game.totals == base.totals
        assert json.dumps(game.pitch_log, sort_keys=True, default=str) == json.dumps(
            base.pitch_log, sort_keys=True, default=str
        )
        assert game.metadata["score"] == base.metadata["score"]


# Keys a Release 5 model now reads, and only while its switch is on (the
# game-identity test above still holds at the defaults). Plate discipline
# (swing_model, tests/test_r5_discipline.py): the swing decision reads eye
# and, through the contact hook, contact against the league centre.
READ_BY_R5_MODELS = {"hitter_eye_center", "hitter_contact_center"}
# Contact (contact_model, tests/test_r5_contact.py): the contact roll reads
# contact and the pitch-quality mix (control, movement, pitch grade) against
# the league centres; the protect term and the BABIP edge read contact.
READ_BY_R5_MODELS |= {"pitcher_movement_center", "pitcher_grade_center"}


def test_no_engine_module_reads_the_new_keys():
    # 5a registers the keys only; the engine starts reading them with the
    # Release 5 models. Until then a reference in physics_sim (outside the
    # registration in config.py) would be a behaviour change slipped in.
    for path in (REPO / "physics_sim").glob("*.py"):
        if path.name == "config.py":
            continue
        text = path.read_text(encoding="utf-8")
        for key in R5A_KEYS:
            if key in READ_BY_R5_MODELS:
                continue
            assert key not in text, f"{path.name} reads {key}"
