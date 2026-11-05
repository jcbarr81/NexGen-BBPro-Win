"""8.12.0: season awards per league, Gold Gloves and Silver Sluggers, and
award winners on their player pages.

The rollover chose one league-wide MVP and Cy Young, wrote them only to
``careers/<season>/awards.json`` and nothing on the player profile read that
file, so the 2026 winners' pages showed no award. Now a league split into
two named leagues (alpha-test's Mercado and Grandberg) gives each award per
league, Gold Gloves and Silver Sluggers join them, archived seasons get the
awards they were missing once, and the profile reads every season's file.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services import season_awards as A


def _hitter(pid, pos, fa=50, arm=50):
    return SimpleNamespace(
        player_id=pid, first_name=pid, last_name="", primary_position=pos,
        is_pitcher=False, fa=fa, arm=arm,
    )


def _pitcher(pid, fa=50):
    return SimpleNamespace(
        player_id=pid, first_name=pid, last_name="", primary_position="P",
        is_pitcher=True, fa=fa, arm=50,
    )


@pytest.fixture(autouse=True)
def _plain_ratings(monkeypatch):
    # The test players' ratings are engine points already.
    monkeypatch.setattr(A, "_rating", lambda player, key: float(getattr(player, key, 50)))


def _bat(ops, pa=600, g=150, **extra):
    return {"ops": ops, "pa": pa, "g": g, "hr": 20, **extra}


def _pit(era, ip=180.0, **extra):
    return {"era": era, "ip": ip, "g": 32, **extra}


TEAMS = [
    SimpleNamespace(team_id="BOS", division="East"),
    SimpleNamespace(team_id="NYY", division="East"),
    SimpleNamespace(team_id="SEA", division="West"),
]
SPLIT = {"East": "Mercado", "West": "Grandberg"}


def _choose(players, stats, team_of, leagues=SPLIT, games=162, kinds=A.AWARD_KINDS):
    return A.select_awards(
        players={p.player_id: p for p in players},
        stats=stats,
        team_of=team_of,
        team_league=A.team_leagues(TEAMS, leagues),
        max_games=games,
        kinds=kinds,
    )


# --- per league --------------------------------------------------------------------


def test_a_split_league_gives_an_mvp_and_cy_young_in_each_league():
    players = [_hitter("H1", "SS"), _hitter("H2", "SS"), _pitcher("P1"), _pitcher("P2")]
    stats = {"H1": _bat(0.950), "H2": _bat(0.800), "P1": _pit(2.50), "P2": _pit(3.10)}
    team_of = {"H1": "BOS", "P1": "NYY", "H2": "SEA", "P2": "SEA"}
    awards = _choose(players, stats, team_of, kinds=("MVP", "CY_YOUNG"))
    assert awards["MVP:Mercado"]["player_id"] == "H1"
    assert awards["MVP:Grandberg"]["player_id"] == "H2"
    assert awards["CY_YOUNG:Mercado"]["player_id"] == "P1"
    assert awards["CY_YOUNG:Grandberg"]["label"] == "Cy Young (Grandberg)"
    assert awards["MVP:Mercado"]["metric_label"] == ".950 OPS"


def test_a_league_that_isnt_split_keeps_one_set_under_the_old_keys():
    players = [_hitter("H1", "SS"), _pitcher("P1")]
    stats = {"H1": _bat(0.950), "P1": _pit(2.50)}
    awards = _choose(players, stats, {"H1": "BOS", "P1": "SEA"}, leagues={})
    assert set(awards) >= {"MVP", "CY_YOUNG"}
    assert awards["MVP"]["label"] == "MVP"


def test_a_traded_player_counts_in_his_last_clubs_league():
    players = [_hitter("H1", "SS")]
    awards = _choose(players, {"H1": _bat(0.9)}, {"H1": "SEA/BOS"}, kinds=("MVP",))
    assert "MVP:Mercado" in awards


# --- Gold Gloves ---------------------------------------------------------------------


def test_a_gold_glove_goes_mostly_by_fielding_ratings():
    players = [_hitter("S1", "SS", fa=70, arm=60), _hitter("S2", "SS", fa=50, arm=50)]
    stats = {
        "S1": _bat(0.7, fpct=0.970, rf9=4.0),
        "S2": _bat(0.7, fpct=0.990, rf9=4.6),  # better numbers, far worse glove
    }
    awards = _choose(players, stats, {"S1": "BOS", "S2": "NYY"}, kinds=("GOLD_GLOVE",))
    assert awards["GOLD_GLOVE:Mercado:SS"]["player_id"] == "S1"


def test_when_ratings_are_bunched_the_season_decides():
    # alpha-test 2026: fielding 50-52 for nearly everyone.
    players = [_hitter("S1", "SS", fa=52, arm=52), _hitter("S2", "SS", fa=51, arm=51)]
    stats = {
        "S1": _bat(0.7, fpct=0.960, rf9=3.9),
        "S2": _bat(0.7, fpct=0.992, rf9=4.6),
    }
    awards = _choose(players, stats, {"S1": "BOS", "S2": "NYY"}, kinds=("GOLD_GLOVE",))
    assert awards["GOLD_GLOVE:Mercado:SS"]["player_id"] == "S2"


def test_a_gold_glove_needs_half_the_clubs_games_at_the_position():
    players = [_hitter("S1", "SS", fa=80), _hitter("S2", "SS", fa=50)]
    stats = {"S1": _bat(0.7, g=60), "S2": _bat(0.7, g=150)}
    awards = _choose(players, stats, {"S1": "BOS", "S2": "NYY"}, kinds=("GOLD_GLOVE",))
    assert awards["GOLD_GLOVE:Mercado:SS"]["player_id"] == "S2"


def test_a_player_is_judged_where_he_started_most():
    # Listed at 3B, started 140 games at 1B.
    players = [_hitter("X", "3B", fa=70), _hitter("F", "1B", fa=50)]
    stats = {
        "X": _bat(0.7, gs_1B=140, gs_3B=5),
        "F": _bat(0.7, gs_1B=20, gs_DH=130),
    }
    awards = _choose(players, stats, {"X": "BOS", "F": "NYY"}, kinds=("GOLD_GLOVE",))
    assert awards["GOLD_GLOVE:Mercado:1B"]["player_id"] == "X"
    assert "GOLD_GLOVE:Mercado:3B" not in awards


def test_a_catchers_line_leaves_out_the_range_factor():
    players = [_hitter("C1", "C")]
    stats = {"C1": _bat(0.7, fpct=0.995, rf9=7.5, pb=3)}
    award = _choose(players, stats, {"C1": "BOS"}, kinds=("GOLD_GLOVE",))["GOLD_GLOVE:Mercado:C"]
    assert award["metric_label"] == ".995 fielding pct, 3 passed balls"


def test_a_pitchers_gold_glove_needs_an_inning_per_team_game():
    players = [_pitcher("P1", fa=80), _pitcher("P2", fa=50)]
    stats = {"P1": _pit(3.0, ip=60.0), "P2": _pit(3.0, ip=170.0)}
    awards = _choose(players, stats, {"P1": "BOS", "P2": "BOS"}, kinds=("GOLD_GLOVE",))
    assert awards["GOLD_GLOVE:Mercado:P"]["player_id"] == "P2"


# --- Silver Sluggers -------------------------------------------------------------------


def test_silver_sluggers_take_three_outfielders_and_a_dh():
    players = [_hitter(f"O{i}", pos) for i, pos in enumerate(["LF", "CF", "RF", "LF"])]
    players.append(_hitter("D", "1B"))
    stats = {
        "O0": _bat(0.900), "O1": _bat(0.850), "O2": _bat(0.800), "O3": _bat(0.950),
        "D": _bat(0.990, gs_DH=150),
    }
    team_of = {p.player_id: "BOS" for p in players}
    awards = _choose(players, stats, team_of, kinds=("SILVER_SLUGGER",))
    outfield = [awards[f"SILVER_SLUGGER:Mercado:OF:{i}"]["player_id"] for i in (1, 2, 3)]
    assert outfield == ["O3", "O0", "O1"]
    assert awards["SILVER_SLUGGER:Mercado:DH"]["player_id"] == "D"
    assert "SILVER_SLUGGER:Mercado:1B" not in awards


def test_a_silver_slugger_needs_two_plate_appearances_per_team_game():
    players = [_hitter("A", "2B"), _hitter("B", "2B")]
    stats = {"A": _bat(1.100, pa=200), "B": _bat(0.800, pa=500)}
    awards = _choose(players, stats, {"A": "BOS", "B": "BOS"}, kinds=("SILVER_SLUGGER",))
    assert awards["SILVER_SLUGGER:Mercado:2B"]["player_id"] == "B"


# --- reading old and new entries -----------------------------------------------------


def test_old_league_wide_entries_read_as_before():
    old = {"player_id": "P7", "player_name": "Ace", "metric": 3.5071}
    assert A.award_type("CY_YOUNG", old) == "CY_YOUNG"
    assert A.award_label("CY_YOUNG", old) == "Cy Young"
    assert A.metric_text("CY_YOUNG", old) == "3.51 ERA"
    assert A.metric_text("MVP", {"metric": 1.0644}) == "1.064 OPS"


def test_winners_text_names_each_league():
    awards = {
        "MVP:Grandberg": {"award": "MVP", "league": "Grandberg", "player_name": "B"},
        "MVP:Mercado": {"award": "MVP", "league": "Mercado", "player_name": "A"},
        "GOLD_GLOVE:Mercado:SS": {"award": "GOLD_GLOVE", "player_name": "C"},
    }
    assert A.winners_text(awards, "MVP") == "B (Grandberg), A (Mercado)"
    assert A.winners_text({"MVP": {"player_name": "Z"}}, "MVP") == "Z"
    assert A.winners_text({}, "MVP") == "-"


def test_the_news_names_each_leagues_mvp_and_cy_young():
    awards = {
        "MVP:Mercado": {"award": "MVP", "league": "Mercado", "player_name": "A", "team_id": "BOS"},
        "CY_YOUNG:Mercado": {"award": "CY_YOUNG", "league": "Mercado", "player_name": "B"},
        "SILVER_SLUGGER:Mercado:C": {"award": "SILVER_SLUGGER", "league": "Mercado"},
    }
    text = A.news_text(awards, 2027)
    assert text.startswith("2027 season awards: Mercado: MVP A (BOS), Cy Young B.")
    assert "Silver Sluggers" in text


# --- archived seasons ------------------------------------------------------------------


@pytest.fixture
def archive(tmp_path, monkeypatch):
    data = tmp_path / "data"
    season = data / "careers" / "lg-2026"
    season.mkdir(parents=True)
    (data / "career_index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "league": {"id": "lg"},
                "current": {"season_id": "lg-2027", "league_year": 2027},
                "seasons": [{"season_id": "lg-2026", "league_year": 2026}],
            }
        ),
        encoding="utf-8",
    )
    old = {"awards": {"MVP": {"player_id": "H1", "player_name": "H1", "metric": 0.95}}}
    (season / "awards.json").write_text(json.dumps(old), encoding="utf-8")
    (season / "stats.json").write_text(
        json.dumps(
            {
                "players": {
                    "H1": _bat(0.950, fpct=0.99, rf9=4.0),
                    "H2": _bat(0.800, fpct=0.98, rf9=4.1),
                },
                "teams": {"BOS": {"g": 162}, "SEA": {"g": 162}},
            }
        ),
        encoding="utf-8",
    )
    (season / "players.csv").write_text("player_id\n", encoding="utf-8")
    (data / "careers" / "career_players.json").write_text(
        json.dumps(
            {
                "players": {
                    "H1": {"seasons": {"lg-2026": {"team": "BOS"}}},
                    "H2": {"seasons": {"lg-2026": {"team": "SEA"}}},
                }
            }
        ),
        encoding="utf-8",
    )
    players = [_hitter("H1", "SS"), _hitter("H2", "SS")]
    monkeypatch.setattr("utils.player_loader.load_players_from_csv", lambda path: players)
    monkeypatch.setattr(A, "current_team_leagues", lambda d: A.team_leagues(TEAMS, SPLIT))
    return data


def test_an_archived_season_gets_its_missing_awards_once(archive):
    changed = A.backfill_archived_seasons(data_dir=archive)
    assert [c["season_id"] for c in changed] == ["lg-2026"]
    payload = json.loads((archive / "careers" / "lg-2026" / "awards.json").read_text())
    awards = payload["awards"]
    # The MVP stays exactly as awarded; the new awards join it, per league.
    assert awards["MVP"] == {"player_id": "H1", "player_name": "H1", "metric": 0.95}
    assert awards["GOLD_GLOVE:Mercado:SS"]["player_id"] == "H1"
    assert awards["SILVER_SLUGGER:Grandberg:SS"]["player_id"] == "H2"
    assert payload["kinds"] == ["GOLD_GLOVE", "MVP", "SILVER_SLUGGER"]
    assert A.backfill_archived_seasons(data_dir=archive) == []


def test_a_season_where_nobody_qualifies_is_still_marked_done(archive):
    stats = archive / "careers" / "lg-2026" / "stats.json"
    stats.write_text(json.dumps({"players": {}, "teams": {}}), encoding="utf-8")
    changed = A.backfill_archived_seasons(data_dir=archive)
    assert changed[0]["added"] == 0
    assert A.backfill_archived_seasons(data_dir=archive) == []


def test_the_profile_lists_the_awards_from_each_seasons_file(archive, monkeypatch):
    import playbalance.season_context as sc
    from services.player_profile_view_model import _collect_awards_history

    A.backfill_archived_seasons(data_dir=archive)
    monkeypatch.setattr(sc, "CAREER_DATA_DIR", archive / "careers")
    real_load = sc.SeasonContext.load
    monkeypatch.setattr(
        sc.SeasonContext, "load",
        classmethod(lambda cls, path=None: real_load(archive / "career_index.json")),
    )
    rows = _collect_awards_history(SimpleNamespace(player_id="H1"))
    assert {"year": "2026", "award": "MVP", "description": ".950 OPS"} in rows
    assert any(r["award"] == "Gold Glove, SS (Mercado)" for r in rows)


# --- games started by position -----------------------------------------------------------


def test_the_game_runner_counts_games_started_at_each_position(monkeypatch):
    from playbalance import game_runner

    monkeypatch.setattr("utils.stats_persistence.save_stats", lambda *a, **k: None)
    players = {
        "A": SimpleNamespace(player_id="A", season_stats={"gs_SS": 3}),
        "B": SimpleNamespace(player_id="B", season_stats={}),
    }
    game_runner._persist_physics_stats(
        metadata={"score": {"home": 1, "away": 0}},
        players_lookup=players,
        home_team=None,
        away_team=None,
        start_positions={"home": {"A": "SS"}, "away": {"B": "dh"}},
    )
    assert players["A"].season_stats["gs_SS"] == 4
    assert players["B"].season_stats["gs_DH"] == 1


def test_the_awards_page_rows_are_labelled_and_in_award_order():
    from api.routers.awards import _flatten_winners

    rows = _flatten_winners(
        {
            "awards": {
                "SILVER_SLUGGER:Mercado:C": {"award": "SILVER_SLUGGER", "league": "Mercado",
                                             "position": "C", "player_id": "S"},
                "GOLD_GLOVE:Mercado:SS": {"award": "GOLD_GLOVE", "league": "Mercado",
                                          "position": "SS", "player_id": "G"},
                "GOLD_GLOVE:Mercado:P": {"award": "GOLD_GLOVE", "league": "Mercado",
                                         "position": "P", "player_id": "Q"},
                "CY_YOUNG": {"player_id": "C", "metric": 3.5071},
                "MVP": {"player_id": "M", "metric": 1.0644},
            }
        }
    )
    assert [r["player_id"] for r in rows] == ["M", "C", "Q", "G", "S"]
    assert rows[1]["label"] == "Cy Young" and rows[1]["metric"] == "3.51 ERA"
    assert rows[2]["label"] == "Gold Glove, P (Mercado)"
    assert rows[4]["type"] == "SILVER_SLUGGER" and rows[4]["position"] == "C"
