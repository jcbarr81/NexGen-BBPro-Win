"""Release 5: the real game path at the defaults.

The four area test files pin games played through
``physics_sim.engine.simulate_matchup_from_files``, the KPI harness's entry.
A league's games do not go through it. They go through
``playbalance.game_runner.simulate_game_scores``: the rotation tracker picks
the starters, the saved vs-LHP / vs-RHP lineup file sets the nine (or the
lineup auto-fill does, for a club that has none), the league's stored tuning
and its rating centres are merged over the defaults, and the usage store
carries rest from one day to the next.

These tests play the same six dated games in a scratch league through that
path, once with every club's lineup files and once with none (the auto-fill
path), and pin what the engine was handed and what it played. Every Release
5 area is switched off at the defaults, so the digests are the engine's
before Release 5: they were computed on the Release 5a tree (2b1a37952,
exported with ``git archive``; :func:`live_games` only needs modules that
tree has) and are equal on the integrated branch.

RE-BASELINE only when the default random stream changes on purpose.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LEAGUE = "r5live"
# (date, home, away, seed): four clubs, three days, every club at home and
# on the road, so the rotation and the rest state move.
GAMES = (
    ("2026-04-01", "DET", "ALB", 9101),
    ("2026-04-01", "LOU", "OKL", 9102),
    ("2026-04-02", "ALB", "DET", 9103),
    ("2026-04-02", "OKL", "LOU", 9104),
    ("2026-04-03", "LOU", "ALB", 9105),
    ("2026-04-03", "DET", "OKL", 9106),
)
PITCH_KEYS = ("fb", "cu", "cb", "sl", "si", "scb", "kn")


def build_league(root: Path, repo: Path, *, lineups: bool) -> Path:
    """A scratch league under ``root`` from the league KPI fixture.

    The league's own files go in BEFORE anything resolves the data dir: a
    league folder missing teams.csv, players.csv or users.txt is seeded with
    a copy of the repo's ``data/`` (sample schedule and season files
    included) the first time it is resolved.
    """
    fixture = repo / "data" / "calibration_league"
    data = root / "leagues" / LEAGUE / "data"
    data.mkdir(parents=True)
    (root / "players.csv").write_text("player_id\n", encoding="utf-8")
    with (fixture / "players.csv").open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        # The harness reads a blank pitch grade as "does not throw it"; the
        # league loader wants a number.
        for key in PITCH_KEYS:
            if key in row and row[key] == "":
                row[key] = "0"
    with (data / "players.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    shutil.copy(fixture / "teams.csv", data / "teams.csv")
    (data / "users.txt").write_text("", encoding="utf-8")
    shutil.copytree(fixture / "rosters", data / "rosters")
    if lineups:
        shutil.copytree(fixture / "lineups", data / "lineups")
    return data


def _fresh_process_state() -> None:
    """Drop the in-process caches a new process would not have."""
    from playbalance import game_runner, usage_store
    from utils import path_utils
    from utils.pitcher_recovery import PitcherRecoveryTracker
    from utils.roster_loader import load_roster

    usage_store.clear_cache()
    game_runner._teams_by_id.cache_clear()
    PitcherRecoveryTracker._instance = None
    load_roster.cache_clear()
    path_utils._DATA_DIR_CACHE.clear()


def _canon(value):
    if isinstance(value, float):
        return float.__repr__(value)
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def digest(payload) -> str:
    blob = json.dumps(_canon(payload), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def live_games(root: Path, repo: Path = REPO, *, lineups: bool) -> list[dict]:
    """Play ``GAMES`` in a scratch league through ``simulate_game_scores``.

    Returns one dict per game: what the engine was handed (lineups, bench,
    positions, staff, roles, park, seed, day, assigned starters, rest
    policy, tuning overrides), what it returned (pitch log, totals,
    metadata) and the score the runner reported. Sets and restores the
    league environment itself, so it also runs outside pytest.
    """
    import physics_sim.engine as engine
    from playbalance import game_runner
    from utils import path_utils

    data = build_league(root, repo, lineups=lineups)
    saved_env = {k: os.environ.get(k) for k in ("NEXGEN_DATA_ROOT", "NEXGEN_ACTIVE_LEAGUE")}
    os.environ["NEXGEN_DATA_ROOT"] = str(root)
    os.environ.pop("NEXGEN_ACTIVE_LEAGUE", None)
    _fresh_process_state()
    token = path_utils.set_request_league(LEAGUE)
    real_game = engine.simulate_game
    captured: list[dict] = []

    def ids(players):
        return [p.player_id for p in players]

    def game(**kwargs):
        result = real_game(**kwargs)
        captured.append(
            {
                "handed": {
                    "away_lineup": ids(kwargs["away_lineup"]),
                    "home_lineup": ids(kwargs["home_lineup"]),
                    "away_positions": kwargs["away_lineup_positions"],
                    "home_positions": kwargs["home_lineup_positions"],
                    # The bench is built from a set; its order is not part
                    # of the game.
                    "away_bench": sorted(ids(kwargs["away_bench"])),
                    "home_bench": sorted(ids(kwargs["home_bench"])),
                    "away_pitchers": ids(kwargs["away_pitchers"]),
                    "home_pitchers": ids(kwargs["home_pitchers"]),
                    "away_roles": kwargs["away_pitcher_roles"],
                    "home_roles": kwargs["home_pitcher_roles"],
                    "park": kwargs["park_name"],
                    "seed": kwargs["seed"],
                    "game_day": kwargs["game_day"],
                    "away_starter": kwargs["away_starter_id"],
                    "home_starter": kwargs["home_starter_id"],
                    "postseason": kwargs["postseason"],
                    "away_rest_policy": kwargs["away_rest_policy"],
                    "home_rest_policy": kwargs["home_rest_policy"],
                },
                "tuning_overrides": dict(kwargs["tuning_overrides"] or {}),
                "played": {
                    "pitch_log": result.pitch_log,
                    "totals": result.totals,
                    "meta": result.metadata,
                },
            }
        )
        return result

    engine.simulate_game = game
    try:
        assert path_utils.get_data_dir().resolve() == data.resolve()
        for date, home, away, seed in GAMES:
            before = len(captured)
            home_runs, away_runs, _html, meta = game_runner.simulate_game_scores(
                home, away, seed=seed, game_date=date, engine="physics"
            )
            assert len(captured) == before + 1
            captured[-1]["game"] = {"date": date, "home": home, "away": away}
            captured[-1]["reported"] = {
                "home_runs": home_runs, "away_runs": away_runs, "meta": meta,
            }
    finally:
        engine.simulate_game = real_game
        path_utils.reset_request_league(token)
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _fresh_process_state()
    # Nothing was seeded in from the repo's own data/.
    seeded = {p.name for p in data.iterdir()}
    assert not seeded & {"schedule.csv", "season_state.json", "leagues"}, sorted(seeded)
    return captured


def game_digests(games: list[dict]) -> list[str]:
    """One digest per game: what the engine was handed, what it played and
    the score reported. The tuning overrides are checked on their own."""
    return [
        digest({k: game[k] for k in ("game", "handed", "played", "reported")})
        for game in games
    ]


# sha256, floats at full precision, one per game of ``GAMES``. Computed on
# the Release 5a tree (see the module docstring) and equal on this branch.
# Day one is the same game in both modes: nobody is tired yet, and the
# fixture's lineup files were written by the same auto-fill.
PINNED = {
    "lineup_files": [
        "790b72110a439240d64c6d25f5f757b9d54bdb6db76388419603d67f594fc14d",
        "f9052b02a85aaf3726dbf894e4875be2a514b4380d7baaf078b4375920d786e0",
        "f90888ccd48f60a6a8a86f9bf0bc5f8df60a1b569c46bbf2e5b3f8a14c0c6037",
        "9e39134a6d809b4cc6043559d3a2fcd74cb206f2a457baaee114ff75b23feeba",
        "312a571e3dc3466dde6e587185a140c335622c4fc71b262615372f1980667708",
        "446051238b7fee407cf021e69a64543fe67db59066f8e102e35e644cab3973e3",
    ],
    "auto_fill": [
        "790b72110a439240d64c6d25f5f757b9d54bdb6db76388419603d67f594fc14d",
        "2331eb8b866a606ec9869280eb01a19396e9535b9c2bee1a0b203b1f01c5f2c3",
        "eb5259de228b84e3f9af81f8ff09b4e85e16be0c8f8a9045e3c9fe8c4c28888e",
        "3492cfeb72e0a3a80d2891cca2d5a2a59eb414f79ce38478d7277e45d0215bdd",
        "cdc10a9f2c7fc71d44a4d935ec213ea16e71b33c57ad0ea1d6cc62c7bb8870e3",
        "ad9fb065e3eef4af35546a3eb52310ed0113784fef4be6cc07b7f6d7672c2982",
    ],
}


@pytest.fixture(scope="module")
def played(tmp_path_factory):
    return {
        "lineup_files": live_games(tmp_path_factory.mktemp("with"), lineups=True),
        "auto_fill": live_games(tmp_path_factory.mktemp("without"), lineups=False),
    }


@pytest.mark.parametrize("mode", ["lineup_files", "auto_fill"])
def test_live_games_at_the_defaults_match_the_pinned_digests(played, mode):
    if os.environ.get("PYTHONHASHSEED") != "0":
        # game_runner seeds the bullpen's tie-break order from hash() of a
        # tuple of strings, so a live game is only reproducible under a
        # fixed hash seed (AGENTS.md: run tests with PYTHONHASHSEED=0;
        # scripts/run_tests_isolated.py and the parallel-day workers set it).
        pytest.skip("live-path digests are pinned under PYTHONHASHSEED=0")
    got = game_digests(played[mode])
    assert got == PINNED[mode], f"got {got}"
    # Six different games.
    assert len(set(got)) == len(GAMES)


def test_the_two_modes_really_take_different_lineup_paths(played, tmp_path):
    fixture = REPO / "data" / "calibration_league" / "lineups"

    def saved(team, hand):
        with (fixture / f"{team}_vs_{hand}.csv").open(newline="") as fh:
            return [row["player_id"] for row in csv.DictReader(fh)]

    for game in played["lineup_files"]:
        for side in ("home", "away"):
            team = game["game"][side]
            lineup = game["handed"][f"{side}_lineup"]
            # The saved file for the opposing starter's hand, unless a
            # tired regular was given the day off.
            options = [saved(team, "lhp"), saved(team, "rhp")]
            assert max(len(set(lineup) & set(option)) for option in options) >= 7
    first = played["lineup_files"][0]["handed"]
    assert first["home_lineup"] in (saved("DET", "lhp"), saved("DET", "rhp"))
    # With no files the auto-fill builds a nine for every club; the league
    # fixture's own lineups were built by the same auto-fill, so on day one
    # (nobody tired yet) it lands on the same nine.
    auto = played["auto_fill"][0]["handed"]
    assert len(auto["home_lineup"]) == len(auto["away_lineup"]) == 9
    assert sorted(auto["home_lineup"]) == sorted(first["home_lineup"])


def test_live_games_carry_the_league_centres_and_no_release_5_switch(played):
    from physics_sim.config import DEFAULT_TUNING, load_tuning

    switches = (
        "swing_model", "command_model", "umpire_model", "hbp_model", "ibb_model",
        "contact_model", "two_strike_protect_contact", "contact_babip_per10",
        "platoon_vl_center_enabled", "platoon_power_after_knee",
        "handedness_balance_strength", "handedness_rhb_scale",
        "handedness_switch_bonus", "reliever_fresh_bonus", "home_field_edge",
        "tto_pass2_weight", "pitch_objective_fbo_requires_risp",
        "pitch_objective_late_close_strength", "foul_territory_scale",
        "eye_control_blend", "hbp_same_hand_scale", "hbp_opposite_hand_scale",
    )
    for games in played.values():
        assert len(games) == len(GAMES)
        for game in games:
            overrides = game["tuning_overrides"]
            # A live game always carries its league's rating centres...
            assert overrides["hitter_vl_center_r"] != 50.0
            assert overrides["catcher_fa_center"] != 50.0
            assert overrides["hitter_bats_share_r"] > 0.5
            # ...and, with nothing stored for the league, no switched-on
            # Release 5 term.
            tuning = load_tuning(overrides)
            for key in switches:
                assert tuning.get(key) == DEFAULT_TUNING[key], key


def test_live_games_use_the_rotation_and_the_rest_state(played):
    for games in played.values():
        by_team: dict[str, list[str]] = {}
        for game in games:
            handed = game["handed"]
            for side in ("home", "away"):
                starter = handed[f"{side}_starter"]
                # The tracker's assigned starter leads the staff he is
                # handed with.
                assert starter and handed[f"{side}_pitchers"][0] == starter
                by_team.setdefault(game["game"][side], []).append(starter)
            assert handed["game_day"] is not None
        # Three days, three different starters for every club.
        assert all(len(set(starters)) == 3 for starters in by_team.values())
        days = [game["handed"]["game_day"] for game in games]
        assert days == sorted(days) and len(set(days)) == 3
