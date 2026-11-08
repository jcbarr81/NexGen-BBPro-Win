"""Game viewer plays (backlog #74 step 2): a stored replay converts to timed
plays that end exactly where the engine did.

The converter (services/replay_plays.py) fills in timing; the engine's
record decides who is out, who is safe, where everyone ends and who
scores. check_plays holds it to that, and these tests hold check_plays to
catching a play that breaks it.
"""

from __future__ import annotations

import copy
import gzip
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.routers.boxscore as B
import playbalance.simulation as S
from scripts.check_replay_plays import play_game
from services import game_replay as R
from services import replay_plays as RP


@pytest.fixture(scope="module")
def replays():
    return [play_game(seed, gen) for gen in (5, 6, 7) for seed in (41, 42)]


@pytest.fixture(scope="module")
def docs(replays):
    return [RP.build_plays(replay) for replay in replays]


def test_every_converted_game_passes_the_checker(docs):
    for doc in docs:
        assert RP.check_plays(doc) == []


def test_one_play_per_stored_entry_and_the_scoreboard_adds_up(replays, docs):
    for replay, doc in zip(replays, docs):
        plays = doc["plays"]
        assert len(plays) == len(replay["pitches"])
        assert plays[-1]["score"] == replay["final"]["score"]
        assert doc["schema"] == RP.SCHEMA


def test_key_plays_are_the_ones_where_something_happened(docs):
    for doc in docs:
        for play in doc["plays"]:
            if play["pa_end"]:
                assert play["key"]
            if not play["key"]:
                assert play["bases_before"] == play["bases_after"]
                assert not play["scored"]
                assert play["outs_after"] == play["outs"]


def test_every_key_play_moves_and_says_what_happened(docs):
    for doc in docs:
        for play in doc["plays"]:
            assert play["text"]
            assert play["dur"] > 0
            if play["key"]:
                assert play["ball"] or play["runners"], play["text"]


def test_building_plays_is_deterministic_and_leaves_the_replay_alone(replays):
    replay = replays[0]
    before = json.dumps(replay, sort_keys=True)
    first = RP.build_plays(replay)
    assert json.dumps(RP.build_plays(replay), sort_keys=True) == json.dumps(first, sort_keys=True)
    assert json.dumps(replay, sort_keys=True) == before


def _first(doc, predicate):
    return next(play for play in doc["plays"] if predicate(play))


def test_the_checker_catches_a_runner_on_the_wrong_base(docs):
    doc = copy.deepcopy(docs[2])
    play = _first(doc, lambda p: any(r["to"] in (1, 2, 3) and r["from"] != r["to"]
                                     for r in p["runners"]))
    runner = next(r for r in play["runners"] if r["to"] in (1, 2, 3) and r["from"] != r["to"])
    runner["to"] = 1 + runner["to"] % 3
    assert any("runners end at" in p for p in RP.check_plays(doc))


def test_the_checker_catches_a_runner_beating_the_throw_he_is_out_on(docs):
    doc = copy.deepcopy(docs[2])
    play = _first(doc, lambda p: any(r.get("out_at") for r in p["runners"]))
    runner = next(r for r in play["runners"] if r.get("out_at"))
    out = next(c for c in play["cues"] if c["type"] == "out" and c.get("who") == runner["who"])
    runner["path"][-1][0] = out["t"] - 0.5
    for point in runner["path"][:-1]:
        point[0] = min(point[0], out["t"] - 0.5)
    assert any("before the out" in p for p in RP.check_plays(doc))


def test_the_checker_catches_a_throw_beating_a_safe_runner(docs):
    doc = copy.deepcopy(docs[2])
    play = _first(doc, lambda p: any(r["to"] in (2, 3) and r["from"] != r["to"]
                                     for r in p["runners"]))
    runner = next(r for r in play["runners"] if r["to"] in (2, 3) and r["from"] != r["to"])
    play["throws"].append({"t": runner["path"][-1][0] - 1.0, "base": runner["to"], "by": "SS"})
    assert any("but he is safe" in p for p in RP.check_plays(doc))


def test_the_checker_catches_a_wrong_score_and_lost_outs(docs):
    doc = copy.deepcopy(docs[0])
    doc["plays"][-1]["score"] = {"away": 99, "home": 0}
    mid = next(p for p in doc["plays"] if p["outs_after"] > p["outs"] and p["outs_after"] < 3)
    mid["outs_after"] = mid["outs"]
    problems = RP.check_plays(doc)
    assert any("final score" in p for p in problems)
    assert any("outs" in p for p in problems)


def test_the_field_carries_the_parks_fence(docs):
    field = docs[0]["field"]
    assert len(field["fence"]["distances"]) == 5
    assert field["bases"]["2"][1] == pytest.approx(127.28, abs=0.01)
    assert set(field["positions"]) == set(RP.POSITIONS)


def test_a_called_third_strike_reads_right(docs):
    texts = [p["text"] for doc in docs for p in doc["plays"]]
    assert any("is called out on strikes" in t for t in texts)
    assert not any("strikes out called" in t for t in texts)


@pytest.fixture
def league(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(B, "get_data_dir", lambda: data)
    monkeypatch.setattr(S, "get_data_dir", lambda: data)
    monkeypatch.setattr(R, "get_data_dir", lambda: data)
    return data


def _request(encoding: str = ""):
    return SimpleNamespace(headers={"accept-encoding": encoding})


def test_the_plays_route_serves_the_viewer_document(league, replays):
    box = S.save_boxscore_html("season", "<html/>", "2027-04-02_CAL01_at_CAL02")
    R.save_game_replay(box, R.encode_replay(replays[1]))
    plain = B.get_game_plays(_request(), path=box)
    doc = json.loads(plain.body)
    assert doc["schema"] == RP.SCHEMA
    assert len(doc["plays"]) == len(replays[1]["pitches"])
    zipped = B.get_game_plays(_request("gzip, deflate, br"), path=box)
    assert zipped.headers["content-encoding"] == "gzip"
    assert json.loads(gzip.decompress(zipped.body)) == doc
    assert len(zipped.body) < len(plain.body) / 4


def test_the_plays_route_404s_for_an_old_game(league):
    box = S.save_boxscore_html("season", "<html/>", "2026-09-01_CAL01_at_CAL02")
    with pytest.raises(HTTPException) as err:
        B.get_game_plays(_request("gzip"), path=box)
    assert err.value.status_code == 404
