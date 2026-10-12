"""Release 5a (tooling): the KPI harness fixes.

- ``--tuning-overrides`` accepts a table for a dict-valued knob
  (``count_foul_scale``, ``count_swing_bonus``, the ``pitch_objective_*``
  tables): a partial table is merged over the default, an unknown entry is
  rejected, and the merged table reaches ``TuningConfig``. Scalars behave as
  before.
- ``simulate_matchup_from_files`` picks each lineup (vs LHP / vs RHP) for
  the hand of the starter who actually pitches. It used to read the staff's
  first pitcher (``starters[game_day % n]``) while ``simulate_game`` re-picks
  the starter from the usage state, so the lineup was wrong about one game
  in three on a fixture whose two lineups differ.
"""

from __future__ import annotations

import copy
import csv
import json
import random
import sys
from pathlib import Path

import pytest

import physics_sim.engine as engine
import scripts.kpi_extras as kx
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.models import PitcherRatings
from physics_sim.physics import _count_modifier
from physics_sim.usage import UsageState, usage_state_to_dict
from scripts import physics_sim_season_kpis as kpis

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
CALIBRATION_LEAGUE = REPO / "data" / "calibration_league"

TABLE_KNOBS = sorted(k for k, v in DEFAULT_TUNING.items() if isinstance(v, dict))


def _profile(tmp_path: Path, payload) -> Path:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- dict-valued tuning overrides ---------------------------------------------


def test_the_table_knobs_the_plan_names_are_tables():
    for key in ("count_foul_scale", "count_contact_scale", "count_swing_bonus"):
        assert key in TABLE_KNOBS
    assert any(key.startswith("pitch_objective_") for key in TABLE_KNOBS)


def test_partial_table_is_merged_over_the_default(tmp_path):
    before = copy.deepcopy(DEFAULT_TUNING)
    overrides = kpis.load_tuning_overrides_file(
        _profile(tmp_path, {"count_foul_scale": {"0-2": 1, "3-2": 0.9}, "hr_scale": 1})
    )
    assert overrides == {
        "count_foul_scale": {"0-2": 1.0, "1-2": 1.15, "2-2": 1.05, "3-2": 0.9},
        "hr_scale": 1.0,
    }
    assert isinstance(overrides["count_foul_scale"]["0-2"], float)
    # The default is neither changed nor shared with the result.
    overrides["count_foul_scale"]["1-2"] = 0.0
    assert DEFAULT_TUNING == before


def test_nested_table_keeps_the_entries_it_does_not_name(tmp_path):
    overrides = kpis.load_tuning_overrides_file(
        _profile(
            tmp_path,
            {
                "count_swing_bonus": {"0-2": {"zone": 0.0}},
                "pitch_objective_count_weights": {"3-1": {"attack": 1.2}},
            },
        )
    )
    bonus = overrides["count_swing_bonus"]
    assert bonus["0-2"] == {"zone": 0.0, "chase": 0.02}
    assert bonus["1-2"] == DEFAULT_TUNING["count_swing_bonus"]["1-2"]
    weights = overrides["pitch_objective_count_weights"]
    assert weights["3-1"] == {"attack": 1.2, "edge": 0.6, "chase": 0.2, "waste": 0.1}
    assert weights["0-2"] == DEFAULT_TUNING["pitch_objective_count_weights"]["0-2"]
    # Nested tables are copies too.
    assert weights["0-2"] is not DEFAULT_TUNING["pitch_objective_count_weights"]["0-2"]


def test_an_empty_table_is_the_default(tmp_path):
    overrides = kpis.load_tuning_overrides_file(
        _profile(tmp_path, {"count_contact_scale": {}})
    )
    assert overrides == {"count_contact_scale": DEFAULT_TUNING["count_contact_scale"]}


def _first_numeric_leaf(table: dict) -> tuple[list[str], float] | None:
    for key, value in table.items():
        if isinstance(value, dict):
            found = _first_numeric_leaf(value)
            if found is not None:
                return [key] + found[0], found[1]
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            return [key], float(value)
    return None


@pytest.mark.parametrize("knob", TABLE_KNOBS)
def test_every_table_knob_takes_a_one_leaf_override(knob, tmp_path):
    leaf = _first_numeric_leaf(DEFAULT_TUNING[knob])
    if leaf is None:
        # A table of labels (pitch_objective_intent_map) is not tunable here.
        entry = next(iter(DEFAULT_TUNING[knob]))
        with pytest.raises(ValueError, match="not a number in"):
            kpis.load_tuning_overrides_file(_profile(tmp_path, {knob: {entry: 1.0}}))
        return
    path, default = leaf
    payload: object = default + 0.125
    for key in reversed(path):
        payload = {key: payload}
    merged = kpis.load_tuning_overrides_file(_profile(tmp_path, {knob: payload}))[knob]
    expected = copy.deepcopy(DEFAULT_TUNING[knob])
    cursor = expected
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = default + 0.125
    assert merged == expected
    # ... and it is what the engine's tuning holds, not dropped or replaced
    # by a partial table.
    assert load_tuning(overrides={knob: merged}).values[knob] == expected


@pytest.mark.parametrize(
    "payload, message",
    [
        # An entry the default does not have, top level and nested.
        ({"count_foul_scale": {"0-0": 1.0}}, r"count_foul_scale\.0-0"),
        ({"count_swing_bonus": {"0-2": {"edge": 0.1}}}, r"count_swing_bonus\.0-2\.edge"),
        (
            {"pitch_objective_count_weights": {"3-1": {"putaway": 0.5}}},
            r"pitch_objective_count_weights\.3-1\.putaway",
        ),
        # Leaves must be numbers.
        ({"count_foul_scale": {"0-2": "high"}}, r"count_foul_scale\.0-2 must be a number"),
        ({"count_foul_scale": {"0-2": True}}, r"count_foul_scale\.0-2 must be a number"),
        ({"count_foul_scale": {"0-2": None}}, r"count_foul_scale\.0-2 must be a number"),
        ({"count_foul_scale": {"0-2": {"zone": 1.0}}}, r"count_foul_scale\.0-2 must be a number"),
        # A table knob needs a table, at every level.
        ({"count_foul_scale": 1.0}, r"count_foul_scale is a table"),
        ({"count_foul_scale": [1.0, 1.0]}, r"count_foul_scale is a table"),
        ({"count_swing_bonus": {"0-2": 0.1}}, r"count_swing_bonus\.0-2 is a table"),
        # A table of labels has no numeric leaves to tune.
        (
            {"pitch_objective_intent_map": {"attack": 1.0}},
            r"pitch_objective_intent_map\.attack is not a number",
        ),
        # Scalars: unchanged rules.
        ({"hr_scale": {"0-2": 1.0}}, r"hr_scale must be a number"),
        ({"hr_scale": "high"}, r"hr_scale must be a number"),
        ({"no_such_knob": {"0-2": 1.0}}, r"unknown tuning key\(s\) no_such_knob"),
    ],
)
def test_bad_table_overrides_are_rejected(payload, message, tmp_path):
    with pytest.raises(ValueError, match=message):
        kpis.load_tuning_overrides_file(_profile(tmp_path, payload))


def test_scalar_profiles_load_exactly_as_before(tmp_path):
    assert kpis.load_tuning_overrides_file(
        _profile(tmp_path, {"hr_scale": 1, "hitter_speed_center": 52.5})
    ) == {"hr_scale": 1.0, "hitter_speed_center": 52.5}
    legacy = kpis.load_tuning_overrides_file(
        REPO / "scripts" / "kpi_profiles" / "r4a_legacy.json"
    )
    assert legacy and all(isinstance(v, float) for v in legacy.values())


def test_merged_table_reaches_the_engine_tuning(tmp_path):
    overrides = kpis.load_tuning_overrides_file(
        _profile(tmp_path, {"count_foul_scale": {"0-2": 1.0}})
    )
    tuning = load_tuning(overrides=overrides)
    table = tuning.values["count_foul_scale"]
    # What the per-pitch code reads (physics.simulate_pitch).
    assert _count_modifier(table, count_key="0-2", default=1.0) == 1.0
    assert _count_modifier(table, count_key="1-2", default=1.0) == 1.15
    assert _count_modifier(
        load_tuning().values["count_foul_scale"], count_key="0-2", default=1.0
    ) == 1.2


class _Captured(Exception):
    pass


def test_cli_hands_the_merged_table_to_every_game(tmp_path, monkeypatch):
    profile = _profile(
        tmp_path, {"count_foul_scale": {"0-2": 1.0}, "foul_rate": 0.385}
    )
    seen = {}

    def fake_matchup(**kwargs):
        seen.update(kwargs)
        raise _Captured

    monkeypatch.setattr(kpis, "simulate_matchup_from_files", fake_matchup)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "physics_sim_season_kpis.py",
            "--base-dir", str(CALIBRATION),
            "--players", str(CALIBRATION / "players.csv"),
            "--tuning-overrides", str(profile),
        ],
    )
    with pytest.raises(_Captured):
        kpis.main()
    sent = seen["tuning_overrides"]
    assert sent["foul_rate"] == 0.385
    assert sent["count_foul_scale"] == {
        "0-2": 1.0, "1-2": 1.15, "2-2": 1.05, "3-2": 1.05,
    }
    assert load_tuning(overrides=sent).values["count_foul_scale"]["0-2"] == 1.0


def test_cli_rejects_a_bad_table_before_simulating(tmp_path, monkeypatch):
    profile = _profile(tmp_path, {"count_foul_scale": {"4-2": 1.0}})

    def no_sim(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("simulated with a rejected profile")

    monkeypatch.setattr(kpis, "run_sim", no_sim)
    monkeypatch.setattr(
        sys, "argv", ["physics_sim_season_kpis.py", "--tuning-overrides", str(profile)]
    )
    with pytest.raises(SystemExit) as exc:
        kpis.main()
    assert exc.value.code == 2


# --- the lineup is the one for the starter who pitches ------------------------


def _pitcher(pid: str, throws: str) -> PitcherRatings:
    return PitcherRatings(
        player_id=pid, bats=throws, throws=throws, role="SP", preferred_role="SP",
        velocity=50.0, control=50.0, movement=50.0, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=60.0, durability=50.0,
        fielding=50.0, arm=50.0, repertoire={"fb": 55.0},
    )


def _rotation():
    staff = [_pitcher(f"S{i}", "L" if i in (2, 4) else "R") for i in range(1, 6)]
    staff.append(_pitcher("R1", "R"))
    roles = {f"S{i}": f"SP{i}" for i in range(1, 6)}
    roles["R1"] = "MR"
    return staff, roles


def test_projected_starter_follows_the_usage_state_not_the_staff_order():
    staff, roles = _rotation()
    tuning = load_tuning()
    usage = UsageState()
    # Three game dates on calendar days 0, 1 and 3 (an off day on 2).
    for day in (0, 1):
        usage.advance_day(day=day, pitchers=staff, tuning=tuning)
    # The third game date is game_index 2 -> SP3, whatever the calendar day.
    projected = engine._projected_starter(
        staff, roles_by_id=roles, usage_state=usage, game_day=3, tuning=tuning
    )
    assert projected.player_id == "S3"
    # The harness's old pick, starters[game_day % n], was SP4 on day 3.
    assert staff[3 % 5].player_id == "S4"


def test_projected_starter_is_the_one_simulate_game_orders_first():
    staff, roles = _rotation()
    tuning = load_tuning()
    usage = UsageState()
    usage.advance_day(day=0, pitchers=staff, tuning=tuning)
    # SP2 threw yesterday's game on short rest: his turn (game_index 1) is
    # skipped for the next rested starter.
    usage.workload_for("S2").last_used_day = 0
    projected = engine._projected_starter(
        staff, roles_by_id=roles, usage_state=usage, game_day=1, tuning=tuning
    )
    # What simulate_game does: move the usage state to the day, then order.
    usage.advance_day(day=1, pitchers=staff, tuning=tuning)
    ordered = engine._order_pitchers_for_game(
        list(staff), roles_by_id=roles, usage_state=usage, game_day=1, tuning=tuning
    )
    assert projected is ordered[0]
    assert projected.player_id == "S3"


def test_projected_starter_leaves_the_usage_state_and_rng_alone():
    staff, roles = _rotation()
    tuning = load_tuning()
    usage = UsageState()
    usage.advance_day(day=0, pitchers=staff[:2], tuning=tuning)
    usage.workload_for("S1").fatigue_debt = 80.0
    usage.workload_for("S1").last_used_day = 0
    before = usage_state_to_dict(usage)
    known = set(usage.workloads)
    random.seed(77)
    rng = random.getstate()
    engine._projected_starter(
        staff, roles_by_id=roles, usage_state=usage, game_day=5, tuning=tuning
    )
    assert random.getstate() == rng
    assert usage_state_to_dict(usage) == before
    # Not even an empty workload was created for an arm it looked at.
    assert set(usage.workloads) == known
    assert (usage.current_day, usage.game_index) == (0, 0)


def test_projected_starter_without_a_usage_state_or_staff():
    staff, roles = _rotation()
    tuning = load_tuning()
    assert engine._projected_starter(
        [], roles_by_id={}, usage_state=None, game_day=None, tuning=tuning
    ) is None
    first = engine._projected_starter(
        staff, roles_by_id=roles, usage_state=None, game_day=None, tuning=tuning
    )
    assert first.player_id == "S1"


def _starter_hand(result, side: str, throws: dict[str, str]) -> str:
    (starter,) = [
        line["player_id"]
        for line in result.metadata["pitcher_lines"][side]
        if int(line.get("gs", 0) or 0) >= 1
    ]
    return "L" if throws[starter] == "L" else "R"


def _league_throws() -> dict[str, str]:
    with (CALIBRATION_LEAGUE / "players.csv").open(newline="", encoding="utf-8") as fh:
        return {row["player_id"]: row["throws"] for row in csv.DictReader(fh)}


# ALB (rotation R L R L R) and AUS (R L R L L) carry different vs-LHP and
# vs-RHP lineups; calendar days with off days in them, as in a season.
SERIES_DAYS = (0, 1, 2, 4, 5, 6, 8, 9, 11, 12)


def _series():
    usage = UsageState()
    rng = random.Random(5)
    for idx, day in enumerate(SERIES_DAYS):
        away, home = ("ALB", "AUS") if idx % 2 == 0 else ("AUS", "ALB")
        yield engine.simulate_matchup_from_files(
            away_team=away,
            home_team=home,
            players_path=CALIBRATION_LEAGUE / "players.csv",
            base_dir=CALIBRATION_LEAGUE,
            seed=rng.randrange(2**32),
            usage_state=usage,
            game_day=day,
        )


def _hand_matches(results, throws) -> list[bool]:
    matches = []
    for result in results:
        hands = result.metadata["lineup_hand"]
        matches.append(hands["away"] == _starter_hand(result, "home", throws))
        matches.append(hands["home"] == _starter_hand(result, "away", throws))
    return matches


def test_every_lineup_is_for_the_hand_of_the_starter_it_faces(monkeypatch):
    throws = _league_throws()
    assert all(_hand_matches(_series(), throws))

    # The pre-5a rule on the same series: the staff's first pitcher
    # (starters[game_day % n]) names the hand. It misses once the calendar
    # day and the rotation slot part ways, which is what this test guards.
    monkeypatch.setattr(
        engine, "_projected_starter",
        lambda pitchers, **_kw: pitchers[0] if pitchers else None,
    )
    legacy = _hand_matches(_series(), throws)
    assert not all(legacy)


def test_an_explicit_lineup_hand_is_still_honoured():
    result = engine.simulate_matchup_from_files(
        away_team="ALB",
        home_team="AUS",
        players_path=CALIBRATION_LEAGUE / "players.csv",
        base_dir=CALIBRATION_LEAGUE,
        seed=11,
        away_lineup_hand="L",
        home_lineup_hand="L",
    )
    assert result.metadata["lineup_hand"] == {"away": "L", "home": "L"}


def test_calibration_fixture_games_do_not_move(monkeypatch):
    # data/calibration's two lineup files are identical per club, so which
    # one is read cannot matter: the fix must leave its games byte-identical.
    for team in ("CAL01", "CAL02"):
        lineups = CALIBRATION / "lineups"
        assert (lineups / f"{team}_vs_lhp.csv").read_bytes() == (
            lineups / f"{team}_vs_rhp.csv"
        ).read_bytes()

    def play():
        usage = UsageState()
        out = []
        for day, seed in ((0, 101), (1, 102), (3, 103)):
            result = engine.simulate_matchup_from_files(
                away_team="CAL01",
                home_team="CAL02",
                players_path=CALIBRATION / "players.csv",
                base_dir=CALIBRATION,
                seed=seed,
                usage_state=usage,
                game_day=day,
            )
            out.append(
                (result.totals, json.dumps(result.pitch_log, sort_keys=True, default=str))
            )
        return out, usage_state_to_dict(usage)

    fixed = play()
    monkeypatch.setattr(
        engine, "_projected_starter",
        lambda pitchers, **_kw: pitchers[0] if pitchers else None,
    )
    assert play() == fixed


# --- lineup_hand_match_rate (report-only) -------------------------------------


def _hand_game(lineup_hand, away_starter, home_starter):
    from types import SimpleNamespace

    def lines(starter):
        return [{"player_id": starter, "gs": 1}, {"player_id": "RELIEF", "gs": 0}]

    meta = {
        "inning_runs": {"away": [0], "home": [0]},
        "score": {"away": 0, "home": 0},
        "innings": 1,
        "pitcher_lines": {"away": lines(away_starter), "home": lines(home_starter)},
        "batting_lines": {"away": [], "home": []},
        "fielding_lines": {"away": [], "home": []},
    }
    if lineup_hand is not None:
        meta["lineup_hand"] = lineup_hand
    return SimpleNamespace(totals={}, pitch_log=[], metadata=meta)


def _players_file(tmp_path: Path) -> Path:
    path = tmp_path / "players.csv"
    path.write_text(
        "player_id,bats,throws,primary_position,is_pitcher\n"
        "LEFTY,L,L,SP,1\n"
        "RIGHTY,R,R,SP,1\n"
        # No throws column value: reads as his batting hand, as the engine does.
        "LEGACY,L,,SP,1\n"
        "RELIEF,R,L,RP,1\n",
        encoding="utf-8",
    )
    return path


def test_lineup_hand_match_rate(tmp_path):
    acc = kx.ReportOnlyKpis(players_path=_players_file(tmp_path), games_per_team=162)
    # Away faces the home starter. Game 1: both right. Game 2: the away
    # lineup is the vs-RHP one against a lefty. Game 3: a legacy lefty.
    acc.add_game(_hand_game({"away": "R", "home": "L"}, "LEFTY", "RIGHTY"), away="A", home="H")
    acc.add_game(_hand_game({"away": "R", "home": "R"}, "RIGHTY", "LEFTY"), away="A", home="H")
    acc.add_game(_hand_game({"away": "L", "home": "R"}, "RIGHTY", "LEGACY"), away="A", home="H")
    report = acc.finalize({})
    assert report["metrics"]["lineup_hand_match_rate"] == pytest.approx(5 / 6)
    assert report["tables"]["r5_counts"]["lineup_hand"] == {"n": 6, "match": 5}


def test_lineup_hand_match_rate_is_none_without_the_metadata(tmp_path):
    acc = kx.ReportOnlyKpis(players_path=_players_file(tmp_path), games_per_team=162)
    acc.add_game(_hand_game(None, "LEFTY", "RIGHTY"), away="A", home="H")
    assert acc.finalize({})["metrics"]["lineup_hand_match_rate"] is None


def test_harness_run_reports_a_full_match_rate(monkeypatch):
    monkeypatch.setattr(kpis, "_team_ids", lambda *a, **k: ["ALB", "AUS"])
    monkeypatch.setattr(kpis, "_team_parks", lambda *a, **k: {})
    summary = kpis.run_sim(
        games_per_team=20,
        seed=3,
        players_path=CALIBRATION_LEAGUE / "players.csv",
        base_dir=CALIBRATION_LEAGUE,
    )
    report = summary["report_only"]
    assert "error" not in report
    assert report["metrics"]["lineup_hand_match_rate"] == 1.0
    assert report["tables"]["r5_counts"]["lineup_hand"]["n"] == 40
    # Report-only: never in the gated metrics.
    assert "lineup_hand_match_rate" not in summary["metrics"]
    assert "lineup_hand_match_rate" not in kpis.DEFAULT_TOLERANCES
