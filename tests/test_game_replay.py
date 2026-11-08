"""Game replays (8.14.0, backlog #74): every played game keeps its
pitch-by-pitch record beside its box score.

The engine's bases trace (play_records["replay_bases"]) has to agree with
what the engine itself logged (the PA-start bases mask, the runs scored);
the replay document has to round-trip, encode to the same bytes every time
and stay small; and the savers have to put it beside the box score and keep
it out of anything else they store (the playoff bracket keeps a game's meta).
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.routers.boxscore as B
import playbalance.simulation as S
import scripts.physics_sim_season_kpis as kpis
from physics_sim.engine import simulate_matchup_from_files
from physics_sim.engine_generation import engine_profile
from services import game_replay as R

REPO = Path(__file__).resolve().parents[1]
CAL = REPO / "data" / "calibration"
PLAYERS = CAL / "players.csv"


def _play(seed: int, generation: int = 6):
    overrides = kpis.with_rating_centers(
        engine_profile(generation, development=True), PLAYERS, CAL
    )
    return simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL02", players_path=PLAYERS, base_dir=CAL,
        seed=seed, tuning_overrides=overrides,
    )


@pytest.fixture(scope="module")
def games():
    return [_play(seed, gen) for gen in (5, 6, 7) for seed in (3, 8, 21)]


def _mask(ids):
    return (1 if ids[0] else 0) | (2 if ids[1] else 0) | (4 if ids[2] else 0)


def test_every_entry_has_its_bases_and_they_match_the_engines_own_log(games):
    for result in games:
        trace = result.play_records["replay_bases"]
        assert sorted(trace) == list(range(len(result.pitch_log)))
        for index, entry in enumerate(result.pitch_log):
            record = trace[index]
            assert len(record["before"]) == 3
            if "bases_before" in entry:
                assert _mask(record["before"]) == entry["bases_before"], index
            if "after" in record:
                assert len(record["after"]) == 3


def test_the_runners_who_scored_add_up_to_the_score(games):
    for result in games:
        scored = [
            pid
            for record in result.play_records["replay_bases"].values()
            for pid in record.get("scored", [])
        ]
        score = result.metadata["score"]
        assert len(scored) == score["away"] + score["home"]


def test_a_plate_appearance_ends_with_the_bases_it_left(games):
    """The last entry of a plate appearance records the bases after it; the
    next plate appearance in the same half starts from them (a pinch runner
    aside, who takes the same base)."""
    for result in games:
        trace = result.play_records["replay_bases"]
        log = result.pitch_log
        for index in range(len(log) - 1):
            nxt = log[index + 1]
            if "pa_start" not in nxt or nxt.get("outs_before", 0) == 0:
                continue
            after = trace[index].get("after")
            assert after is not None, index
            assert _mask(after) == _mask(trace[index + 1]["before"]), index


def test_the_replay_round_trips_and_always_encodes_the_same(games):
    result = games[0]
    lookup = {
        pid: SimpleNamespace(first_name="Pat", last_name=pid, bats="R", throws="R",
                             primary_position="SS")
        for pid in {e["batter_id"] for e in result.pitch_log}
    }
    kwargs = dict(home_id="CAL02", away_id="CAL01", seed=3, game_date="2027-04-02",
                  engine_generation=5, players_lookup=lookup, park_name="Generic Park")
    replay = R.build_replay(result, **kwargs)
    blob = R.encode_replay(replay)
    assert blob == R.encode_replay(R.build_replay(result, **kwargs))
    decoded = R.decode_replay(base64.b64decode(blob))
    assert decoded == json.loads(json.dumps(replay))
    assert decoded["schema"] == R.SCHEMA
    assert len(decoded["pitches"]) == len(result.pitch_log)
    assert len(decoded["bases"]) == len(result.pitch_log)
    assert decoded["final"]["score"] == result.metadata["score"]
    assert [pid for pid, _ in decoded["lineups"]["away"]] == list(
        result.play_records["starting_positions"]["away"]
    )
    batter = result.pitch_log[0]["batter_id"]
    assert decoded["players"][batter]["name"] == f"Pat {batter}"
    # Small enough to keep one per game: a few tens of KB stored.
    assert len(base64.b64decode(blob)) < 60_000


def test_building_a_replay_leaves_the_game_alone(games):
    result = games[1]
    before = json.dumps(result.pitch_log, sort_keys=True, default=str)
    R.build_replay(result, home_id="H", away_id="A")
    assert json.dumps(result.pitch_log, sort_keys=True, default=str) == before


def test_the_replay_switch(monkeypatch):
    monkeypatch.setenv("NEXGEN_GAME_REPLAY", "0")
    assert not R.replay_enabled()
    monkeypatch.setenv("NEXGEN_GAME_REPLAY", "1")
    assert R.replay_enabled()


@pytest.fixture
def league(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(B, "get_data_dir", lambda: data)
    monkeypatch.setattr(S, "get_data_dir", lambda: data)
    monkeypatch.setattr(R, "get_data_dir", lambda: data)
    return data


def _blob(payload=None):
    return R.encode_replay(payload or {"schema": R.SCHEMA, "pitches": [{"outcome": "ball"}]})


def test_the_replay_is_saved_beside_the_box_score_and_served(league):
    box = S.save_boxscore_html("season", "<html/>", "2027-04-02_CAL01_at_CAL02")
    stored = R.save_game_replay(box, _blob())
    assert stored == "boxscores/season/2027-04-02_CAL01_at_CAL02.replay.json.gz"
    assert (league / stored).exists()
    served = B.get_game_replay(path=box)
    assert served["pitches"] == [{"outcome": "ball"}]


def test_a_game_without_a_replay_is_a_404(league):
    box = S.save_boxscore_html("season", "<html/>", "2026-09-01_CAL01_at_CAL02")
    with pytest.raises(HTTPException) as err:
        B.get_game_replay(path=box)
    assert err.value.status_code == 404


def test_the_replay_route_keeps_to_the_boxscores_tree(league):
    with pytest.raises(HTTPException) as err:
        B.get_game_replay(path="../players.csv")
    assert err.value.status_code == 400


def test_nothing_to_save_writes_nothing(league):
    assert R.save_game_replay("boxscores/season/x.html", None) is None
    assert R.save_game_replay("", _blob()) is None
    assert not (league / "boxscores").exists()


def test_pop_takes_the_replay_out_of_the_meta():
    meta = {"engine": "physics", R.META_KEY: "abc"}
    assert R.pop_encoded_replay(meta) == "abc"
    assert meta == {"engine": "physics"}
    assert R.pop_encoded_replay(meta) is None
    assert R.pop_encoded_replay(None) is None


def test_a_playoff_game_saves_its_replay_and_the_bracket_never_holds_it(league):
    from playbalance.playoffs import (
        Matchup, PlayoffBracket, PlayoffTeam, Round, SeriesConfig, simulate_next_game,
    )

    def home_wins(home, away, **kwargs):
        return (2, 1, "<html>box</html>", {"engine": "physics", R.META_KEY: _blob()})

    high = PlayoffTeam(team_id="H1", seed=1, league="LEAGUE", wins=90, run_diff=50)
    low = PlayoffTeam(team_id="L4", seed=4, league="LEAGUE", wins=80, run_diff=10)
    matchup = Matchup(high=high, low=low, config=SeriesConfig(length=3, pattern=[2, 1]))
    bracket = PlayoffBracket(year=2027, rounds=[Round(name="Final", matchups=[matchup])])
    simulate_next_game(bracket, simulate_game=home_wins, persist_cb=lambda b: None)

    game = matchup.games[0]
    assert R.META_KEY not in (game.meta or {})
    replay_file = league / R.replay_path_for_boxscore(game.boxscore)
    assert json.loads(gzip.decompress(replay_file.read_bytes()))["schema"] == R.SCHEMA


def test_the_runner_attaches_a_replay_and_survives_a_bad_result(monkeypatch, games):
    from playbalance.game_runner import _attach_game_replay

    kwargs = dict(home_id="CAL02", away_id="CAL01", home_name="", away_name="",
                  park_name=None, seed=3, date_token="2027-04-02", postseason=False,
                  generation=6, players_lookup={})
    meta: dict = {}
    _attach_game_replay(meta, games[0], **kwargs)
    assert R.decode_replay(base64.b64decode(meta[R.META_KEY]))["game"]["seed"] == 3

    broken: dict = {}
    _attach_game_replay(broken, SimpleNamespace(pitch_log=[{}], play_records=5), **kwargs)
    assert R.META_KEY not in broken

    monkeypatch.setenv("NEXGEN_GAME_REPLAY", "0")
    off: dict = {}
    _attach_game_replay(off, games[0], **kwargs)
    assert off == {}


def test_a_season_day_saves_each_games_replay_beside_its_box_score(league, monkeypatch):
    import types

    import api.routers.season as SEASON
    from services import boxscore_diagnostics as diag

    monkeypatch.setattr(diag, "_log_path", lambda data_dir=None: league / diag.LOG_FILENAME)
    monkeypatch.setattr(SEASON, "_schedule_path", lambda: league / "schedule.csv")
    monkeypatch.setattr(SEASON, "get_data_dir", lambda: league)
    monkeypatch.setattr(SEASON, "_sync_standings_from_stats", lambda *a, **k: None)
    monkeypatch.setattr(
        SEASON, "_reconcile_team_records_with_schedule", lambda *a, **k: None
    )
    played = {
        "date": "2027-04-02", "home": "CAL02", "away": "CAL01", "result": "3-2",
        "boxscore_html": "<html/>", "extra": {"engine": "physics", R.META_KEY: _blob()},
    }
    old = {
        "date": "2027-04-02", "home": "CAL04", "away": "CAL03", "result": "1-0",
        "boxscore_html": "<html/>", "extra": {"engine": "physics"},
    }
    SEASON._persist_post_sim_state(
        types.SimpleNamespace(schedule=[played, old]), ["2027-04-02"]
    )
    assert played["extra"] == {"engine": "physics"}
    kept = league / R.replay_path_for_boxscore(played["boxscore"])
    assert R.decode_replay(kept.read_bytes())["schema"] == R.SCHEMA
    assert not (league / R.replay_path_for_boxscore(old["boxscore"])).exists()
