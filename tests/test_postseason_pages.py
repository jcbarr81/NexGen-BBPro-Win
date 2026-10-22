"""8.4.0: postseason totals on the player profile, the club page and the
leaders page (services/postseason_stats.py).

An alpha-test owner asked: "Is there any way to see the playoff stat
totals?" Since 8.1.1 playoff games keep their own totals
(``postseason_stats.json``, archived with each season at the rollover); these
tests build a league with two archived postseasons, their brackets and the
career ledger, and read them back.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

PLAYERS_HEADER = "player_id,first_name,last_name,birthdate,primary_position,is_pitcher\n"


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def _bat(g, ab, h, b2, hr, bb, so, rbi=0):
    """A hitter's cumulative line, as the game writer stores it."""
    b1 = h - b2 - hr
    pa = ab + bb
    tb = b1 + 2 * b2 + 4 * hr
    obp = (h + bb) / pa if pa else 0.0
    slg = tb / ab if ab else 0.0
    return {
        "g": g, "pa": pa, "ab": ab, "h": h, "b1": b1, "b2": b2, "b3": 0, "hr": hr,
        "bb": bb, "so": so, "rbi": rbi, "r": 1, "2b": b2, "3b": 0,
        "tb": tb, "avg": h / ab if ab else 0.0, "obp": obp, "slg": slg, "ops": obp + slg,
    }


def _pit(g, gs, outs, er, h, bb, so, w=0, l=0, sv=0):
    return {
        "g": g, "gs": gs, "outs": outs, "ip": outs / 3.0, "er": er, "r": er, "h": h,
        "bb": bb, "so": so, "hr": 0, "hbp": 0, "w": w, "l": l, "sv": sv, "bf": outs + h + bb,
        "era": er * 27.0 / outs if outs else 0.0, "whip": 0.0, "fip": 0.0, "cg": 0,
    }


def _games(home, away, scores):
    """Games of a series, ``scores`` as (home runs, away runs)."""
    return [{"home": home, "away": away, "result": f"{h}-{a}"} for h, a in scores]


def _matchup(high, low, games, winner, seeds=(1, 2)):
    return {
        "high": {"team_id": high, "seed": seeds[0], "league": "AL"},
        "low": {"team_id": low, "seed": seeds[1], "league": "AL"},
        "games": games,
        "winner": winner,
    }


BRACKET_2026 = {
    "year": 2026,
    "champion": "COL",
    "runner_up": "OKL",
    "rounds": [
        {"name": "AL DS", "matchups": [
            _matchup("COL", "SEA", _games("COL", "SEA", [(5, 3), (2, 4), (6, 1), (3, 2)]), "COL"),
        ]},
        {"name": "NL DS", "matchups": [
            _matchup("OKL", "BOS", _games("OKL", "BOS", [(4, 1), (2, 1), (7, 0)]), "OKL"),
        ]},
        {"name": "AL CS", "matchups": [
            _matchup("COL", "TEX", _games("COL", "TEX", [(1, 0), (2, 0), (3, 0), (4, 0)]), "COL"),
        ]},
        {"name": "WS", "matchups": [
            _matchup("COL", "OKL", _games("COL", "OKL", [(1, 2), (3, 2), (4, 2), (5, 2), (6, 2)]), "COL"),
        ]},
    ],
}

BRACKET_2025 = {
    "year": 2025,
    "champion": "OKL",
    "runner_up": "TEX",
    "rounds": [
        {"name": "AL DS", "matchups": [
            _matchup("TEX", "COL", _games("TEX", "COL", [(5, 3), (4, 2), (6, 1)]), "TEX"),
        ]},
        {"name": "WS", "matchups": [
            _matchup("OKL", "TEX", _games("OKL", "TEX", [(5, 3), (4, 2), (6, 1), (2, 1)]), "OKL"),
        ]},
    ],
}

POST_2026 = {
    "players": {
        "H1": _bat(13, 48, 18, 4, 3, 5, 9, rbi=11),   # COL, qualifies (13 G -> 40 PA)
        "H2": _bat(4, 8, 6, 2, 1, 0, 1, rbi=3),       # COL, 8 PA: hot but short
        "H3": _bat(13, 45, 12, 2, 1, 2, 10),         # traded OKL -> COL in season
        "H4": _bat(3, 10, 4, 0, 0, 0, 2),            # BOS, 3 G -> 9 PA: qualifies
        "P1": _pit(4, 4, 75, 5, 15, 4, 22, w=3),      # COL, 25 IP
        "P2": _pit(5, 0, 6, 0, 2, 1, 4, sv=3),        # COL, 2 IP
    },
    "teams": {
        "COL": {"g": 13, "w": 11, "l": 2, "r": 50, "ra": 20},
        "OKL": {"g": 8, "w": 4, "l": 4, "r": 30, "ra": 28},
        "SEA": {"g": 4, "w": 1, "l": 3, "r": 10, "ra": 16},
        "BOS": {"g": 3, "w": 0, "l": 3, "r": 2, "ra": 13},
        "TEX": {"g": 4, "w": 0, "l": 4, "r": 0, "ra": 10},
    },
}

POST_2025 = {
    "players": {
        "H1": _bat(3, 12, 3, 1, 0, 1, 4, rbi=1),
        "P1": _pit(1, 1, 18, 4, 6, 2, 5, l=1),
    },
    "teams": {
        "COL": {"g": 3, "w": 0, "l": 3, "r": 6, "ra": 15},
        "TEX": {"g": 7, "w": 3, "l": 4, "r": 25, "ra": 24},
        "OKL": {"g": 4, "w": 4, "l": 0, "r": 17, "ra": 7},
    },
}

LEDGER = {
    "players": {
        "H1": {"seasons": {"alpha-test-2025": {"g": 150, "team": "COL"},
                           "alpha-test-2026": {"g": 155, "team": "COL"}}},
        "H2": {"seasons": {"alpha-test-2026": {"g": 40, "team": "COL"}}},
        "H3": {"seasons": {"alpha-test-2026": {"g": 150, "team": "OKL/COL"}}},
        "H4": {"seasons": {"alpha-test-2026": {"g": 100, "team": "BOS"}}},
        "P1": {"seasons": {"alpha-test-2025": {"g": 30, "team": "COL"},
                           "alpha-test-2026": {"g": 31, "team": "COL"}}},
        "P2": {"seasons": {"alpha-test-2026": {"g": 60, "team": "COL"}}},
    }
}


@pytest.fixture
def league(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    # Sentinels so get_data_dir() resolves this root, never a real league.
    _write(root / "players.csv", PLAYERS_HEADER
           + "H1,Al,Hitter,1999-10-01,CF,0\n"
           + "H2,Bo,Short,2000-01-01,1B,0\n"
           + "H3,Cy,Traded,1995-05-05,SS,0\n"
           + "P1,Di,Starter,1996-03-03,P,1\n"
           + "P2,Ed,Closer,1997-04-04,P,1\n"
           + "Z9,Zed,Neverplayed,1998-01-01,LF,0\n")
    _write(root / "teams.csv",
           "team_id,name,city,abbreviation,division,stadium,primary_color,"
           "secondary_color,owner_id\n"
           "COL,Rockies,Denver,COL,AL West,Park,#000,#fff,\n")
    _write(root / "users.txt", "commish,pass,admin,\ncol_owner,pass,owner,COL\n")
    _write(root / "schedule.csv", "date,home,away,result,played,boxscore\n")
    _write(root / "career_index.json", {
        "version": 1,
        "league": {"id": "alpha-test"},
        "current": {"season_id": "alpha-test-2027", "league_year": 2027},
        "seasons": [
            {"season_id": "alpha-test-2025", "league_year": 2025},
            {"season_id": "alpha-test-2026", "league_year": 2026},
        ],
    })
    careers = root / "careers"
    _write(careers / "alpha-test-2025" / "postseason_stats.json", POST_2025)
    _write(careers / "alpha-test-2025" / "playoffs_2025.json", BRACKET_2025)
    _write(careers / "alpha-test-2026" / "postseason_stats.json", POST_2026)
    _write(careers / "alpha-test-2026" / "playoffs_2026.json", BRACKET_2026)
    # H4 retired after 2026: he is only in that season's archived players.
    _write(careers / "alpha-test-2026" / "players.csv", PLAYERS_HEADER
           + "H4,Ike,Retired,1985-06-06,3B,0\n")
    _write(careers / "career_players.json", LEDGER)
    # The new season has no playoff game yet.
    _write(root / "postseason_stats.json", {"players": {}, "teams": {}, "history": []})
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def test_lists_the_archived_postseasons_newest_first(league):
    from services.postseason_stats import list_postseasons

    listed = list_postseasons()
    assert [(p["year"], p["label"], p["current"]) for p in listed] == [
        (2026, "2026", False), (2025, "2025", False),
    ]


def test_the_current_season_is_listed_once_a_playoff_game_is_played(league):
    from services.postseason_stats import club_postseasons, list_postseasons

    _write(league / "postseason_stats.json", {
        "players": {"H1": _bat(2, 8, 3, 0, 1, 0, 1)},
        "teams": {"COL": {"g": 2, "w": 1, "l": 1, "r": 7, "ra": 6}},
    })
    _write(league / "playoffs_2027.json", {"year": 2027, "rounds": [
        {"name": "AL DS", "matchups": [
            _matchup("COL", "SEA", _games("COL", "SEA", [(5, 3), (2, 3)]), None)]},
    ]})
    _write(league / "rosters" / "COL.csv", "H1,ACT\n")
    listed = list_postseasons()
    assert (listed[0]["year"], listed[0]["current"]) == (2027, True)
    latest = club_postseasons("COL")[0]
    assert latest["year"] == 2027
    assert latest["result"] == "Playing AL Division Series"
    assert [h["player_id"] for h in latest["top_hitters"]] == ["H1"]


def test_a_players_lines_and_career_total(league):
    from services.postseason_stats import player_postseason_lines

    lines, career = player_postseason_lines("H1", birthdate="1999-10-01")
    assert [(e["label"], e["team"], e["age"]) for e in lines] == [
        ("2025", "COL", 25), ("2026", "COL", 26),
    ]
    # Counting stats summed; rates recomputed from the totals.
    assert career["g"] == 16 and career["ab"] == 60 and career["h"] == 21
    assert career["hr"] == 3 and career["2b"] == 5
    assert career["avg"] == pytest.approx(21 / 60)
    assert career["obp"] == pytest.approx((21 + 6) / 66)
    tb = (21 - 5 - 3) + 2 * 5 + 4 * 3
    assert career["tb"] == tb
    assert career["slg"] == pytest.approx(tb / 60)
    assert career["ops"] == pytest.approx(career["obp"] + career["slg"])


def test_a_pitchers_career_rates_are_recomputed(league):
    from services.postseason_stats import player_postseason_lines

    lines, career = player_postseason_lines("P1")
    assert len(lines) == 2
    assert career["outs"] == 93 and career["er"] == 9
    assert career["ip"] == pytest.approx(31.0)
    assert career["era"] == pytest.approx(9 * 9 / 31.0)
    assert career["whip"] == pytest.approx((21 + 6) / 31.0)
    assert "avg" not in career  # no batting line, no invented batting rate


def test_a_player_who_never_played_a_postseason_has_none(league):
    from services.postseason_stats import player_postseason_lines

    assert player_postseason_lines("Z9") == ([], {})


def test_a_traded_player_is_credited_to_his_postseason_club(league):
    from services.postseason_stats import _postseason_club, load_postseason

    assert load_postseason(2026)["clubs"]["H3"] == "COL"
    # The last of his clubs that is in the bracket; else the last one.
    assert _postseason_club("BAL/CHA", {"BAL", "COL"}) == "BAL"
    assert _postseason_club("BAL/CHA", {"COL"}) == "CHA"


def test_how_far_each_club_went(league):
    from services.postseason_stats import club_postseasons

    col = club_postseasons("COL")
    assert [(r["year"], r["result"]) for r in col] == [
        (2026, "Won World Series"), (2025, "Lost AL Division Series"),
    ]
    run = col[0]
    assert (run["w"], run["l"], run["r"], run["ra"], run["g"]) == (11, 2, 50, 20, 13)
    assert run["champion"] is True and run["seed"] == 1
    assert [(s["round_title"], s["opponent"], s["wins"], s["losses"]) for s in run["series"]] == [
        ("AL Division Series", "SEA", 3, 1),
        ("AL Championship Series", "TEX", 4, 0),
        ("World Series", "OKL", 4, 1),
    ]
    assert club_postseasons("OKL")[0]["result"] == "Lost World Series"
    assert club_postseasons("BOS")[0]["result"] == "Lost NL Division Series"
    assert club_postseasons("NYY") == []


def test_a_clubs_top_players_in_its_run(league):
    from services.postseason_stats import club_postseasons

    run = club_postseasons("COL")[0]
    hitters = run["top_hitters"]
    # H1 and H3 reached 13 games x 3.1 = 40 PA; H2's 8 PA trail them.
    assert [h["player_id"] for h in hitters] == ["H1", "H3", "H2"]
    assert [h["qualified"] for h in hitters] == [True, True, False]
    assert hitters[0]["last_name"] == "Hitter"
    pitchers = run["top_pitchers"]
    assert [p["player_id"] for p in pitchers] == ["P1", "P2"]
    assert [p["qualified"] for p in pitchers] == [True, False]


def test_the_single_league_final_is_not_counted_twice(league):
    from services.postseason_stats import club_postseasons

    cs = _matchup("CHI", "SAN", _games("CHI", "SAN", [(3, 1), (4, 1), (5, 1), (6, 1)]), "CHI")
    _write(league / "careers" / "alpha-test-2026" / "playoffs_2026.json", {
        "year": 2026, "champion": "CHI", "rounds": [
            {"name": "LEAGUE CS", "matchups": [cs]},
            {"name": "Final", "matchups": [cs]},
        ]})
    chi = club_postseasons("CHI")[0]
    assert chi["result"] == "Won Championship Series"
    assert len(chi["series"]) == 1
    assert club_postseasons("SAN")[0]["result"] == "Lost Championship Series"


def _leaders(**kw):
    from api.routers.leaders import league_leaders

    args = {"limit": 5, "postseason": False, "season": None}
    args.update(kw)
    return league_leaders(**args)


def _board(payload, side, key):
    return next(b for b in payload[side] if b["key"] == key)


def test_postseason_leaders_qualify_on_their_clubs_games(league):
    out = _leaders(postseason=True, season="2026")
    assert out["postseason"] is True and out["season"] == 2026
    q = out["qualifiers"]
    assert (q["min_pa"], q["min_ip"], q["max_team_games"]) == (40, 13, 13)
    assert (q["pa_per_team_game"], q["ip_per_team_game"]) == (3.1, 1.0)
    avg = _board(out, "batting", "avg")["leaders"]
    ids = [row["player"]["player_id"] for row in avg]
    # H4 (.400) played for a club out after 3 games: 10 PA >= 9 qualifies.
    # H2 (.750 in 8 PA) did not reach COL's 40.
    assert ids == ["H4", "H1", "H3"]
    assert avg[0]["player"]["last_name"] == "Retired"
    assert avg[0]["player"]["team_id"] == "BOS"
    era = _board(out, "pitching", "era")["leaders"]
    assert [row["player"]["player_id"] for row in era] == ["P1"]
    # Saves are not held to the innings minimum (as in the regular season).
    sv = _board(out, "pitching", "sv")["leaders"]
    assert [row["player"]["player_id"] for row in sv] == ["P2"]


def test_postseason_leaders_default_to_the_latest_and_404_on_unknown(league):
    from fastapi import HTTPException

    assert _leaders(postseason=True)["season"] == 2026
    assert _leaders(postseason=True, season="2025")["season"] == 2025
    with pytest.raises(HTTPException) as err:
        _leaders(postseason=True, season="1999")
    assert err.value.status_code == 404


def test_profile_postseason_rows(league, monkeypatch):
    from services import player_profile_view_model as vm

    hitter = SimpleNamespace(player_id="H1", birthdate="1999-10-01")
    rows = vm._collect_postseason_rows(hitter, is_pitcher=False)
    assert [label for label, _ in rows] == ["2025", "2026", "Career"]
    by = dict(rows)
    assert by["2026"]["team"] == "COL" and by["2026"]["age"] == 26
    assert by["2026"]["k"] == 9  # the profile's K column
    assert by["Career"]["h"] == 21
    assert by["Career"]["avg"] == pytest.approx(round(21 / 60, 3))

    pitcher = dict(vm._collect_postseason_rows(
        SimpleNamespace(player_id="P1", birthdate="1996-03-03"), is_pitcher=True))
    assert pitcher["Career"]["era"] == pytest.approx(round(81 / 31.0, 2))
    assert pitcher["2025"]["l"] == 1

    nobody = SimpleNamespace(player_id="Z9", birthdate="1998-01-01")
    assert vm._collect_postseason_rows(nobody, is_pitcher=False) == []


def test_endpoints_need_a_signed_in_member(league):
    from fastapi.testclient import TestClient

    from api.app import create_app

    client = TestClient(create_app())
    paths = (
        "/teams/COL/postseason",
        "/league/leaders/postseasons",
        "/league/leaders?postseason=true&season=2026",
    )
    for path in paths:
        assert client.get(path).status_code == 401, path
    for user in ("col_owner", "commish"):
        login = client.post("/auth/login", json={"username": user, "password": "pass"})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        for path in paths:
            res = client.get(path, headers=headers)
            assert res.status_code == 200, (path, res.text)
        years = client.get("/league/leaders/postseasons", headers=headers).json()
        assert years["latest"] == 2026
        assert [p["year"] for p in years["postseasons"]] == [2026, 2025]
        # Any member reads any club's history.
        okl = client.get("/teams/OKL/postseason", headers=headers).json()
        assert okl["postseasons"][0]["result"] == "Lost World Series"
