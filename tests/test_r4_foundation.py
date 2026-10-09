"""Release 4 foundation (W0): the league speed centre and its plumbing.

Nothing in the engine reads ``hitter_speed_center`` yet, so every test here
also pins "no behaviour change": the default changes nothing, the optional
``scale=`` of ``_advance_prob`` defaults to the old global scale, and a game
with the centre in its tuning is identical to one without.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import physics_sim.engine as engine
from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from services import league_rating_centers as centers

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
CALIBRATION_LEAGUE = REPO / "data" / "calibration_league"

PLAYER_FIELDS = ["player_id", "primary_position", "is_pitcher", "sp"]


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


def _small_league(root: Path) -> Path:
    _write_league(
        root,
        players=[
            {"player_id": "H1", "primary_position": "CF", "is_pitcher": "0", "sp": "60"},
            {"player_id": "H2", "primary_position": "SS", "is_pitcher": "0", "sp": "40"},
            {"player_id": "H3", "primary_position": "C", "is_pitcher": "0", "sp": ""},
            # An ACT pitcher by flag and one by position: both left out.
            {"player_id": "P1", "primary_position": "SP", "is_pitcher": "1", "sp": "99"},
            {"player_id": "P2", "primary_position": "RP", "is_pitcher": "0", "sp": "99"},
            # Fast, but in AAA / LOW: left out.
            {"player_id": "M1", "primary_position": "CF", "is_pitcher": "0", "sp": "95"},
            {"player_id": "M2", "primary_position": "LF", "is_pitcher": "0", "sp": "90"},
        ],
        rosters={
            "AAA": [("H1", "ACT"), ("H2", "act"), ("P1", "ACT"), ("M1", "AAA")],
            "BBB": [("H3", "ACT"), ("P2", "ACT"), ("M2", "LOW")],
            # A side file whose ids happen to be ACT-shaped is never a roster.
            "BBB_pitching": [("M2", "ACT")],
        },
    )
    return root


# --- the mean --------------------------------------------------------------


def test_mean_is_over_act_hitters_only(tmp_path):
    base = _small_league(tmp_path / "league")
    # H1 60, H2 40, H3 blank -> 50; pitchers and the AAA/LOW burners excluded.
    assert centers.active_hitter_mean_speed(base) == pytest.approx(50.0)


def test_mean_reads_another_players_file(tmp_path):
    base = _small_league(tmp_path / "league")
    other = tmp_path / "other.csv"
    with other.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PLAYER_FIELDS)
        writer.writeheader()
        writer.writerow({"player_id": "H1", "primary_position": "CF", "sp": "71"})
    assert centers.active_hitter_mean_speed(base, players_path=other) == 71.0


def test_fixture_centres_match_the_plan():
    assert centers.active_hitter_mean_speed(CALIBRATION) == pytest.approx(47.72)
    assert centers.active_hitter_mean_speed(CALIBRATION_LEAGUE) == pytest.approx(54.41)


def test_no_act_hitters_gives_none_and_writes_nothing(tmp_path):
    base = tmp_path / "league"
    _write_league(
        base,
        players=[
            {"player_id": "P1", "primary_position": "SP", "is_pitcher": "1", "sp": "50"},
            {"player_id": "M1", "primary_position": "CF", "is_pitcher": "0", "sp": "70"},
        ],
        rosters={"AAA": [("P1", "ACT"), ("M1", "AAA")]},
    )
    assert centers.active_hitter_mean_speed(base) is None
    assert centers.league_hitter_speed_center(base, season="2026") is None
    assert not (base / centers.RATING_CENTERS_FILENAME).exists()
    assert centers.active_hitter_mean_speed(tmp_path / "missing") is None


# --- once per season ---------------------------------------------------------


def _set_speed(base: Path, pid: str, sp: str) -> None:
    path = base / "players.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        if row["player_id"] == pid:
            row["sp"] = sp
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PLAYER_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_centre_is_fixed_for_the_season_and_stored(tmp_path):
    base = _small_league(tmp_path / "league")
    assert centers.league_hitter_speed_center(base, season="2026") == 50.0
    stored = json.loads((base / centers.RATING_CENTERS_FILENAME).read_text())
    assert stored["seasons"]["2026"]["hitter_speed_center"] == 50.0

    # Rosters change mid-season: the season's centre does not move, neither
    # from the process cache nor from the file (a fresh process / worker).
    _set_speed(base, "H1", "80")
    assert centers.league_hitter_speed_center(base, season="2026") == 50.0
    centers.clear_rating_center_cache()
    assert centers.league_hitter_speed_center(base, season="2026") == 50.0

    # The next season is a new key: recomputed from that season's rosters,
    # and the earlier season stays on file for reference.
    assert centers.league_hitter_speed_center(base, season="2027") == pytest.approx(
        56.67
    )
    stored = json.loads((base / centers.RATING_CENTERS_FILENAME).read_text())
    assert stored["seasons"]["2026"]["hitter_speed_center"] == 50.0
    assert stored["seasons"]["2027"]["hitter_speed_center"] == pytest.approx(56.67)


def test_file_keeps_the_last_five_seasons(tmp_path):
    base = _small_league(tmp_path / "league")
    for year in range(2020, 2028):
        centers.league_hitter_speed_center(base, season=str(year))
    stored = json.loads((base / centers.RATING_CENTERS_FILENAME).read_text())
    assert sorted(stored["seasons"]) == [str(y) for y in range(2023, 2028)]


def test_unknown_season_is_cached_in_process_but_never_stored(tmp_path):
    # Not the active league (and so no sim date): never written to the file,
    # so it cannot pin a later season that also lacks a date -- but held in
    # the process cache, so a mid-day roster change (an injury) cannot give
    # serial games a different centre than the parallel parent computed.
    base = _small_league(tmp_path / "league")
    assert centers.league_hitter_speed_center(base) == 50.0
    assert not (base / centers.RATING_CENTERS_FILENAME).exists()
    _set_speed(base, "H1", "80")
    assert centers.league_hitter_speed_center(base) == 50.0
    centers.clear_rating_center_cache()
    assert centers.league_hitter_speed_center(base) == pytest.approx(56.67)
    assert not (base / centers.RATING_CENTERS_FILENAME).exists()


def test_store_false_reads_but_never_fixes_the_centre(tmp_path):
    # Watch-a-game: a missing centre is computed live, not cached or written.
    base = _small_league(tmp_path / "league")
    assert centers.league_hitter_speed_center(base, season="2026", store=False) == 50.0
    assert not (base / centers.RATING_CENTERS_FILENAME).exists()
    _set_speed(base, "H1", "80")
    assert centers.league_hitter_speed_center(
        base, season="2026", store=False
    ) == pytest.approx(56.67)
    # Once the season fixes it, a replay reads the stored value.
    assert centers.league_hitter_speed_center(base, season="2026") == pytest.approx(56.67)
    _set_speed(base, "H1", "50")
    assert centers.league_hitter_speed_center(
        base, season="2026", store=False
    ) == pytest.approx(56.67)


def test_runtime_centre_files_are_never_seeded_into_new_leagues():
    import utils.path_utils as path_utils

    assert "rating_centers.json" in path_utils._SEED_EXCLUDE_FILES
    assert "pitcher_durability_center.json" in path_utils._SEED_EXCLUDE_FILES


@pytest.fixture
def active_league(tmp_path, monkeypatch):
    """A league the live getters resolve: NEXGEN_DATA_ROOT + a sim date."""
    import utils.path_utils as path_utils

    root = _small_league(tmp_path / "data")
    (root / "schedule.csv").write_text(
        "date,home,away,result,played,boxscore\n2026-04-01,AAA,BBB,,,\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    assert (path_utils.get_data_dir() / "players.csv").exists()
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def test_overrides_for_the_active_league(active_league):
    assert centers.get_rating_center_overrides() == {"hitter_speed_center": 50.0}
    stored = json.loads((active_league / centers.RATING_CENTERS_FILENAME).read_text())
    assert stored["seasons"] == {"2026": {"hitter_speed_center": 50.0}}


def test_overrides_are_empty_without_act_hitters(active_league):
    for name in ("AAA", "BBB"):
        (active_league / "rosters" / f"{name}.csv").write_text("", encoding="utf-8")
    assert centers.get_rating_center_overrides() == {}
    assert not (active_league / centers.RATING_CENTERS_FILENAME).exists()


# --- tuning key and engine helpers ------------------------------------------


def test_hitter_speed_center_is_registered_and_round_trips():
    assert DEFAULT_TUNING["hitter_speed_center"] == 50.0
    tuning = TuningConfig.from_overrides(overrides={"hitter_speed_center": "54.41"})
    assert tuning.values["hitter_speed_center"] == pytest.approx(54.41)
    assert tuning.get("hitter_speed_center") == pytest.approx(54.41)


def _old_advance_prob(speed, arm, tuning, extra=0.0):
    # 7.47.0 verbatim.
    base = 0.45 + (speed - 50.0) / 200.0 - (arm - 50.0) / 250.0 + extra
    base *= tuning.get("advancement_aggression_scale", 1.0)
    return max(0.05, min(0.95, base))


@pytest.mark.parametrize("overrides", [None, {"advancement_aggression_scale": 1.0}])
def test_advance_prob_without_scale_is_unchanged(overrides):
    tuning = load_tuning(overrides=overrides)
    for speed in (20.0, 47.5, 50.0, 63.0, 99.0):
        for arm in (20.0, 50.0, 80.0):
            for extra in (-0.2, 0.0, 0.05, 0.3):
                expected = _old_advance_prob(speed, arm, tuning, extra)
                assert engine._advance_prob(speed, arm, tuning, extra) == expected
                assert engine._advance_prob(speed, arm, tuning, extra, scale=None) == expected


def test_advance_prob_scale_replaces_the_global_scale():
    tuning = load_tuning()
    assert tuning.get("advancement_aggression_scale") == pytest.approx(1.6)
    raw = 0.45 + (60.0 - 50.0) / 200.0 - (55.0 - 50.0) / 250.0
    assert engine._advance_prob(60.0, 55.0, tuning, scale=1.0) == pytest.approx(raw)
    assert engine._advance_prob(60.0, 55.0, tuning, scale=0.5) == pytest.approx(raw * 0.5)
    assert engine._advance_prob(99.0, 20.0, tuning, scale=10.0) == 0.95
    assert engine._advance_prob(1.0, 99.0, tuning, scale=0.0) == 0.05


def test_centred_speed():
    assert engine._centred_speed(63.0, load_tuning()) == 63.0
    tuning = load_tuning(overrides={"hitter_speed_center": 54.41})
    assert engine._centred_speed(54.41, tuning) == pytest.approx(50.0)
    assert engine._centred_speed(70.0, tuning) == pytest.approx(65.59)


def test_centre_moves_only_the_centred_terms():
    # Since Release 4 W1 the steal-attempt curve reads the centre. With the
    # steal attempt rate at zero, a different centre must leave the game
    # byte-identical: no other 4a term (race-against-the-throw speed terms
    # read raw speed) and no 4b term at its default may read it.
    def play(overrides):
        return engine.simulate_matchup_from_files(
            away_team="CAL01",
            home_team="CAL02",
            players_path=CALIBRATION / "players.csv",
            base_dir=CALIBRATION,
            seed=20261009,
            tuning_overrides=overrides,
        )

    base = play({"steal_freq_scale": 0.0})
    for centre in (40.0, 62.5):
        centred = play({"steal_freq_scale": 0.0, "hitter_speed_center": centre})
        assert centred.totals == base.totals
        assert json.dumps(centred.pitch_log, sort_keys=True, default=str) == json.dumps(
            base.pitch_log, sort_keys=True, default=str
        )
    # And with steals on, the centre does move steal decisions: a league
    # centred at 40 reads every runner as faster and attempts more steals.
    def attempts(overrides):
        return sum(
            play_seed(seed, overrides).totals.get(key, 0)
            for seed in range(1, 6)
            for key in ("sb", "cs")
        )

    def play_seed(seed, overrides):
        return engine.simulate_matchup_from_files(
            away_team="CAL01",
            home_team="CAL02",
            players_path=CALIBRATION / "players.csv",
            base_dir=CALIBRATION,
            seed=seed,
            tuning_overrides=overrides,
        )

    assert attempts({"hitter_speed_center": 40.0}) > attempts(None)


# --- live callers ------------------------------------------------------------


class _Captured(Exception):
    pass


def _capture_physics_call(monkeypatch, *, centre_overrides, stored_overrides):
    import physics_sim.data_loader as loader
    import playbalance.game_runner as gr
    from utils import league_settings as ls

    batters = {f"B{i}": SimpleNamespace(player_id=f"B{i}") for i in range(18)}
    arms = {f"P{i}": SimpleNamespace(player_id=f"P{i}") for i in range(2)}
    monkeypatch.setattr(loader, "load_players_by_id", lambda path: (batters, arms))
    monkeypatch.setattr(gr, "get_physics_tuning_overrides", lambda: dict(stored_overrides))
    monkeypatch.setattr(gr, "get_injury_tuning_overrides", lambda: {})
    calls = []

    def fake_centres():
        calls.append(1)
        return dict(centre_overrides)

    monkeypatch.setattr(gr, "get_rating_center_overrides", fake_centres)
    monkeypatch.setattr(
        ls, "load_league_settings", lambda path=None: {"extra_innings_runner": True}
    )
    seen = {}

    def fake_simulate_game(**kwargs):
        seen.update(kwargs)
        raise _Captured

    monkeypatch.setattr(engine, "simulate_game", fake_simulate_game)

    def state(offset):
        return SimpleNamespace(
            lineup=[
                SimpleNamespace(player_id=f"B{i + offset}", position="CF")
                for i in range(9)
            ],
            bench=[],
            pitchers=[
                SimpleNamespace(
                    player_id=f"P{offset // 9}", assigned_pitching_role="SP1"
                )
            ],
            team=None,
        )

    def run():
        with pytest.raises(_Captured):
            gr._run_physics_game(
                home_id="H", away_id="A", home_state=state(0), away_state=state(9),
                players_file=str(CALIBRATION / "players.csv"), roster_dir="rosters",
                seed=1, date_token=None, tracker=None, players_lookup={},
                persist_stats=False, postseason=False,
            )

    return run, seen, calls


def test_centre_reaches_game_runner_tuning(monkeypatch):
    run, seen, calls = _capture_physics_call(
        monkeypatch,
        centre_overrides={"hitter_speed_center": 54.41},
        stored_overrides={"hitter_speed_center": 40.0, "hr_scale": 1.0},
    )
    run()
    # The season's measured centre wins over a stored override.
    assert seen["tuning_overrides"]["hitter_speed_center"] == 54.41
    assert seen["tuning_overrides"]["hr_scale"] == 1.0
    assert seen["tuning_overrides"]["extra_innings_runner"] == 1.0
    assert calls == [1]


def test_parallel_worker_uses_the_parents_centre(monkeypatch):
    from playbalance import parallel_day

    run, seen, calls = _capture_physics_call(
        monkeypatch,
        centre_overrides={"hitter_speed_center": 99.0},
        stored_overrides={},
    )
    payload = parallel_day.build_payload(
        home="H", away="A", seed=1, date="2026-04-01", home_starter=None,
        away_starter=None, data_root="x", league_id=None, usage_in={},
        rating_centers={"hitter_speed_center": 47.72},
    )
    # The payload crosses a process boundary as JSON.
    payload = json.loads(json.dumps(payload))
    journal = parallel_day.GameJournal(
        usage_in=None, rating_centers=payload["rating_centers"]
    )
    with parallel_day.journal_capture(journal):
        run()
    assert seen["tuning_overrides"]["hitter_speed_center"] == 47.72
    assert calls == []  # the worker never recomputes the centre


def test_worker_job_hands_the_centre_to_its_journal(tmp_path, monkeypatch):
    from playbalance import game_runner, parallel_day

    seen = []

    def fake_scores(home, away, **kwargs):
        seen.append(parallel_day.active_journal().rating_centers)
        return 1, 0, "", {}

    monkeypatch.setattr(game_runner, "_resolve_game_engine", lambda _=None: "physics")
    monkeypatch.setattr(game_runner, "simulate_game_scores", fake_scores)
    payload = parallel_day.build_payload(
        home="AAA", away="BBB", seed=1, date="2026-04-02",
        home_starter=None, away_starter=None, data_root=str(tmp_path),
        league_id=None, usage_in={},
        rating_centers={"hitter_speed_center": 54.41},
    )
    parallel_day.simulate_game_job(payload)
    assert seen == [{"hitter_speed_center": 54.41}]


def test_parallel_day_computes_the_centre_once_in_the_parent():
    # The fan-out reads the centre before submitting any game.
    import inspect

    from playbalance import season_simulator

    source = inspect.getsource(season_simulator)
    fan_out = source.index("rating_centers = get_rating_center_overrides()")
    assert fan_out < source.index("pool.submit(parallel_day.simulate_game_job")
    assert "rating_centers=rating_centers" in source


def test_payload_without_centres_is_backward_compatible():
    from playbalance import parallel_day

    payload = parallel_day.build_payload(
        home="H", away="A", seed=1, date="2026-04-01", home_starter=None,
        away_starter=None, data_root="x", league_id=None, usage_in={},
    )
    assert payload["rating_centers"] is None
    assert parallel_day.GameJournal().rating_centers is None


def test_watch_a_game_layers_the_league_getters(monkeypatch):
    from api.ws import sim as ws_sim

    monkeypatch.setattr(
        "services.physics_tuning_settings.get_physics_tuning_overrides",
        lambda: {"hr_scale": 1.0, "hitter_speed_center": 40.0},
    )
    monkeypatch.setattr(
        "services.injury_settings.get_injury_tuning_overrides",
        lambda: {"injuries_enabled": 0.0},
    )
    calls = []

    def centres(*, store=True):
        calls.append(store)
        return {"hitter_speed_center": 54.41}

    monkeypatch.setattr(
        "services.league_rating_centers.get_rating_center_overrides", centres
    )
    assert ws_sim._league_tuning_overrides() == {
        "hr_scale": 1.0,
        "injuries_enabled": 0.0,
        "hitter_speed_center": 54.41,
    }
    # A replay reads the season's centre but never fixes it.
    assert calls == [False]


# --- KPI harness ---------------------------------------------------------------


@pytest.fixture
def kpis():
    from scripts import physics_sim_season_kpis

    return physics_sim_season_kpis


def test_harness_passes_the_fixture_centre(kpis, monkeypatch):
    assert kpis.fixture_hitter_speed_center(
        CALIBRATION / "players.csv", CALIBRATION
    ) == pytest.approx(47.72)
    seen = {}

    def fake_matchup(**kwargs):
        seen.update(kwargs)
        raise _Captured

    monkeypatch.setattr(kpis, "simulate_matchup_from_files", fake_matchup)
    with pytest.raises(_Captured):
        kpis.run_sim(162, 1, CALIBRATION / "players.csv", None, CALIBRATION)
    assert seen["tuning_overrides"] == {"hitter_speed_center": pytest.approx(47.72)}

    seen.clear()
    with pytest.raises(_Captured):
        kpis.run_sim(
            162, 1, CALIBRATION / "players.csv", {"park_factor_scale": 0.0}, CALIBRATION
        )
    assert seen["tuning_overrides"] == {
        "hitter_speed_center": pytest.approx(47.72),
        "park_factor_scale": 0.0,
    }


def test_explicit_centre_override_wins(kpis):
    merged = kpis.with_rating_centers(
        {"hitter_speed_center": 50.0},
        CALIBRATION_LEAGUE / "players.csv",
        CALIBRATION_LEAGUE,
    )
    assert merged == {"hitter_speed_center": 50.0}


def test_tuning_overrides_file_rejects_unknown_keys(kpis, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"hr_scale": 1.0, "steal_speed_centre": 55}))
    with pytest.raises(ValueError, match="steal_speed_centre"):
        kpis.load_tuning_overrides_file(bad)

    not_number = tmp_path / "str.json"
    not_number.write_text(json.dumps({"hr_scale": "high"}))
    with pytest.raises(ValueError, match="hr_scale"):
        kpis.load_tuning_overrides_file(not_number)

    not_dict = tmp_path / "list.json"
    not_dict.write_text("[1, 2]")
    with pytest.raises(ValueError, match="JSON object"):
        kpis.load_tuning_overrides_file(not_dict)

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"hr_scale": 1, "hitter_speed_center": 52.5}))
    assert kpis.load_tuning_overrides_file(good) == {
        "hr_scale": 1.0,
        "hitter_speed_center": 52.5,
    }


def test_cli_rejects_unknown_override_before_simulating(kpis, tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"no_such_knob": 1.0}))

    def no_sim(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("simulated with a rejected profile")

    monkeypatch.setattr(kpis, "run_sim", no_sim)
    monkeypatch.setattr(
        sys, "argv", ["physics_sim_season_kpis.py", "--tuning-overrides", str(bad)]
    )
    with pytest.raises(SystemExit) as exc:
        kpis.main()
    assert exc.value.code == 2


def test_r4b_profile_is_a_valid_profile(kpis):
    profile = REPO / "scripts" / "kpi_profiles" / "r4b.json"
    overrides = kpis.load_tuning_overrides_file(profile)
    assert isinstance(overrides, dict)


def test_gate_sets(kpis, monkeypatch):
    assert "running" in kpis.GATE_SETS
    monkeypatch.setitem(kpis.GATE_SETS, "test", ["sb_pct", "babip", "missing"])
    failures = [
        {"metric": "babip", "value": 0.25},
        {"metric": "ops", "value": 0.9},
    ]
    picked = kpis.gate_set_failures(
        "test",
        metrics={"sb_pct": 0.78, "babip": 0.25},
        tolerances={"sb_pct": 0.05, "babip": 0.015, "missing": 0.01},
        failures=failures,
    )
    assert [row["metric"] for row in picked] == ["babip", "missing"]
    assert "not computed" in picked[1]["reason"]
    assert math.isnan(picked[1]["value"])

    monkeypatch.setitem(kpis.GATE_SETS, "test", ["untoleranced"])
    picked = kpis.gate_set_failures("test", metrics={}, tolerances={}, failures=[])
    assert "no tolerance" in picked[0]["reason"]

    # A tolerance with no benchmark or target, or a NaN value, is not a pass.
    monkeypatch.setitem(kpis.GATE_SETS, "test", ["nobench", "nanm", "ok"])
    picked = kpis.gate_set_failures(
        "test",
        metrics={"nobench": 5.0, "nanm": float("nan"), "ok": 1.0},
        tolerances={"nobench": 1.0, "nanm": 1.0, "ok": 1.0},
        failures=[],
        references={"nanm", "ok"},
    )
    assert [row["metric"] for row in picked] == ["nobench", "nanm"]
    assert "no benchmark or target" in picked[0]["reason"]
    assert "not computed" in picked[1]["reason"]


def test_kpi_extras_loads_speed(tmp_path):
    from scripts import kpi_extras

    extras = kpi_extras.ReportOnlyKpis(
        players_path=CALIBRATION / "players.csv", games_per_team=162
    )
    assert extras.sp["CAL-0001"] == 48.0
    # Every hitter has a speed; pitchers' blank sp is simply absent.
    hitters = {
        pid for pid, pos in extras.primary_pos.items() if pos not in {"P", "SP", "RP"}
    }
    assert hitters and hitters <= set(extras.sp)
