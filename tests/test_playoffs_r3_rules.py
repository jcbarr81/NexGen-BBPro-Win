"""Release 3 playoff rules: no ties, the postseason flag, MLB-style dates.

- A tied result is never stored: the game is re-simulated with a salted seed
  and otherwise the slot stays unplayed (no hang).
- A tied game stored by an older version does not use up a series slot.
- Every game gets a date: an off day after the season and between rounds,
  travel days at changes of home field in a 5- or 7-game series, none in a
  3-game Wild Card; games run in calendar order across both leagues.
- The real simulator is called with ``postseason=True``.
"""

from __future__ import annotations

from datetime import date

import pytest

import playbalance.playoffs as pf
from models.team import Team
from playbalance.playoffs import (
    GameResult,
    Matchup,
    PlayoffBracket,
    PlayoffTeam,
    Round,
    SeriesConfig,
    generate_bracket,
    simulate_next_game,
    simulate_next_round,
    simulate_playoffs,
    simulate_series,
)
from playbalance.playoffs_config import PlayoffsConfig


def _team(team_id: str, division: str) -> Team:
    return Team(
        team_id=team_id, name=team_id, city=team_id, abbreviation=team_id,
        division=division, stadium="Test Park", primary_color="#112233",
        secondary_color="#445566", owner_id="owner",
    )


def _two_league_bracket() -> PlayoffBracket:
    """Six playoff clubs per league: Wild Card, Division Series, LCS, WS."""
    divisions = ("East", "East", "Central", "Central", "West", "West")
    al = [_team(f"A{i}", f"AL {d}") for i, d in enumerate(divisions, start=1)]
    nl = [_team(f"N{i}", f"NL {d}") for i, d in enumerate(divisions, start=1)]
    standings = {
        t.team_id: {"wins": 100 - idx, "runs_for": 700, "runs_against": 650}
        for idx, t in enumerate(al + nl)
    }
    cfg = PlayoffsConfig(num_playoff_teams_per_league=6)
    cfg.playoff_slots_by_league_size = {6: 6}
    bracket = generate_bracket(standings, al + nl, cfg)
    assert [r.name for r in bracket.rounds] == [
        "AL WC", "AL DS", "AL CS", "NL WC", "NL DS", "NL CS", "WS",
    ]
    return bracket


def _matchup(length=3, pattern=(1, 1, 1)) -> Matchup:
    return Matchup(
        high=PlayoffTeam(team_id="H", seed=1, league="L", wins=90),
        low=PlayoffTeam(team_id="W", seed=2, league="L", wins=80),
        config=SeriesConfig(length=length, pattern=list(pattern)),
    )


@pytest.fixture
def no_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "get_data_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "get_data_dir", lambda: tmp_path)
    (tmp_path / "schedule.csv").write_text(
        "date,home,away\n2025-04-01,A1,N1\n2025-09-28,A2,N2\n2025-09-27,A3,N3\n",
        encoding="utf-8",
    )
    return date(2025, 9, 28)


# --- ties ---------------------------------------------------------------------


def test_a_tied_result_is_re_simulated_not_stored(no_schedule):
    seeds = []

    def tie_first(home, away, seed=None):
        seeds.append(seed)
        return (2, 2, "<html/>", {}) if len(seeds) == 1 else (3, 1, "<html/>", {})

    m = simulate_series(_matchup(), year=2025, round_name="Final", series_index=0, simulate_game=tie_first)
    assert m.winner == "H"
    assert all(g.result != "2-2" for g in m.games)
    # The retry used a salted seed; the next slot's seed is the usual one.
    assert seeds[0] != seeds[1]
    assert seeds[2] == pf._deterministic_seed("2025", "Final", "0", "1", "W", "H")


def test_a_game_that_keeps_tying_leaves_the_slot_unplayed_without_hanging(no_schedule):
    calls = []

    def always_tie(home, away, seed=None):
        calls.append(seed)
        return (1, 1, "<html/>", {})

    bracket = PlayoffBracket(year=2025, rounds=[Round(name="Final", matchups=[_matchup()])])
    simulate_playoffs(bracket, simulate_game=always_tie, persist_cb=lambda b: None)
    assert bracket.rounds[0].matchups[0].games == []
    assert bracket.champion is None
    assert len(calls) == pf._TIE_TRIES


def test_a_stored_tie_does_not_use_up_a_series_slot(no_schedule):
    """Self-heal: brackets saved before Release 3 may hold a tied game."""
    m = _matchup()
    m.games = [
        GameResult(home="H", away="W", result="1-0"),
        GameResult(home="W", away="H", result="4-4"),
        GameResult(home="H", away="W", result="0-2"),
    ]
    # Before the fix all three slots were used and 1-1 never resolved.
    played = []

    def home_wins(home, away, seed=None):
        played.append(home)
        return (5, 0, "<html/>", {})

    bracket = PlayoffBracket(year=2025, rounds=[Round(name="Final", matchups=[m])])
    simulate_playoffs(bracket, simulate_game=home_wins, persist_cb=lambda b: None)
    # Two slots count (the tie does not), so game 3 is slot 2 of [H, W, H]:
    # at H, who wins it and the series 2-1.
    assert played == ["H"]
    assert m.winner == "H"
    assert bracket.champion == "H"


# --- the postseason flag --------------------------------------------------------


def test_real_games_are_simulated_as_postseason_games(schedule, monkeypatch):
    import playbalance.game_runner as gr
    import services.roster_fill as roster_fill

    seen = []

    def fake_scores(home_id, away_id, **kwargs):
        seen.append(kwargs)
        return (2, 1, "<html/>", {})

    monkeypatch.setattr(gr, "simulate_game_scores", fake_scores)
    monkeypatch.setattr(roster_fill, "prepare_teams_for_game", lambda teams: None)
    bracket = PlayoffBracket(year=2025, rounds=[Round(name="WS", matchups=[_matchup(7, (2, 3, 2))])])
    simulate_next_game(bracket, persist_cb=lambda b: None)
    assert seen and seen[0]["postseason"] is True
    assert seen[0]["game_date"] == "2025-09-30"
    assert isinstance(seen[0]["seed"], int)


# --- dates ----------------------------------------------------------------------


def test_series_day_offsets_follow_mlb_travel_days():
    assert pf._series_day_offsets([1, 1, 1]) == [0, 1, 2]
    assert pf._series_day_offsets([2, 2, 1]) == [0, 1, 3, 4, 6]
    assert pf._series_day_offsets([2, 3, 2]) == [0, 1, 3, 4, 5, 7, 8]


def test_every_game_is_dated_mlb_style_and_played_in_calendar_order(schedule):
    calls = []

    def home_wins(home, away, seed=None, game_date=None):
        calls.append((game_date, home, away))
        return (1, 0, "<html/>", {})

    bracket = _two_league_bracket()
    simulate_playoffs(bracket, simulate_game=home_wins, persist_cb=lambda b: None)
    assert bracket.champion

    dates = [d for d, _, _ in calls]
    assert None not in dates
    assert dates == sorted(dates), "games must run in calendar order"

    def round_dates(name):
        rnd = next(r for r in bracket.rounds if r.name == name)
        return sorted({g.date for m in rnd.matchups for g in m.games})

    # Season ends Sun 09-28; off day; Wild Card on three straight days.
    assert round_dates("AL WC") == round_dates("NL WC") == [
        "2025-09-30", "2025-10-01", "2025-10-02",
    ]
    # Off day, then a 2-2-1 Division Series with travel days (home always
    # wins, so every DS goes five).
    assert round_dates("AL DS") == ["2025-10-04", "2025-10-05", "2025-10-07", "2025-10-08", "2025-10-10"]
    # LCS: starts after an off day; 2-3-2 with travel after games 2 and 5.
    assert round_dates("AL CS") == [
        "2025-10-12", "2025-10-13", "2025-10-15", "2025-10-16", "2025-10-17",
        "2025-10-19", "2025-10-20",
    ]
    assert round_dates("WS")[0] == "2025-10-22"

    # No team ever plays twice on one date.
    by_team = {}
    for game_date, home, away in calls:
        for team in (home, away):
            assert game_date not in by_team.setdefault(team, set())
            by_team[team].add(game_date)


def test_a_sweep_does_not_move_the_next_round_up(schedule):
    calls = []

    def high_seed_wins(home, away, seed=None, game_date=None):
        calls.append((game_date, home, away))
        high = home if home in {"A1", "A2", "A3", "N1", "N2", "N3"} else away
        return (1, 0, "<html/>", {}) if home == high else (0, 1, "<html/>", {})

    bracket = _two_league_bracket()
    simulate_playoffs(bracket, simulate_game=high_seed_wins, persist_cb=lambda b: None)
    ds = next(r for r in bracket.rounds if r.name == "AL DS")
    assert sorted({g.date for m in ds.matchups for g in m.games})[0] == "2025-10-04"


def test_next_game_plays_one_calendar_day_across_both_leagues(schedule):
    def home_wins(home, away, seed=None, game_date=None):
        return (1, 0, "<html/>", {})

    bracket = _two_league_bracket()
    simulate_next_game(bracket, simulate_game=home_wins, persist_cb=lambda b: None)
    wc = [r for r in bracket.rounds if r.name in ("AL WC", "NL WC")]
    assert [len(m.games) for r in wc for m in r.matchups] == [1, 1, 1, 1]
    assert {g.date for r in wc for m in r.matchups for g in m.games} == {"2025-09-30"}


def test_games_stay_undated_without_a_matching_schedule(no_schedule):
    seen = []

    def home_wins(home, away, **kwargs):
        seen.append(kwargs)
        return (1, 0, "<html/>", {})

    bracket = PlayoffBracket(year=2025, rounds=[Round(name="Final", matchups=[_matchup()])])
    simulate_playoffs(bracket, simulate_game=home_wins, persist_cb=lambda b: None)
    assert bracket.champion == "H"
    assert all("game_date" not in kw for kw in seen)
    assert all(g.date is None for g in bracket.rounds[0].matchups[0].games)


def test_a_schedule_from_another_season_is_not_used(schedule):
    assert pf._regular_season_end(2025) == schedule
    assert pf._regular_season_end(2026) is None


def test_round_mode_still_finishes_the_round_it_starts(schedule):
    def home_wins(home, away, **kwargs):
        return (1, 0, "<html/>")

    bracket = _two_league_bracket()
    simulate_next_round(bracket, simulate_game=home_wins)
    assert all(m.winner for r in bracket.rounds if r.name == "AL WC" for m in r.matchups)
    al_ds = next(r for r in bracket.rounds if r.name == "AL DS")
    assert len(al_ds.matchups) == 2 and not any(m.games for m in al_ds.matchups)


def test_single_league_final_copy_mirrors_the_series_after_a_reload(no_schedule):
    teams = [_team(f"A{i}", "AL East") for i in range(1, 5)]
    standings = {t.team_id: {"wins": 100 - i, "runs_for": 700, "runs_against": 650} for i, t in enumerate(teams)}
    bracket = generate_bracket(standings, teams, PlayoffsConfig(num_playoff_teams_per_league=4))
    assert [r.name for r in bracket.rounds][-1] == "Final"
    calls = []

    def home_wins(home, away, **kwargs):
        calls.append((home, away))
        return (1, 0, "<html/>")

    simulate_next_round(bracket, simulate_game=home_wins)  # the DS
    reloaded = PlayoffBracket.from_dict(bracket.to_dict())
    final_copy = next(r for r in reloaded.rounds if r.name == "Final").matchups[0]
    league_cs = next(r for r in reloaded.rounds if r.name.endswith("CS")).matchups[0]
    assert final_copy is not league_cs
    before = len(calls)
    simulate_playoffs(reloaded, simulate_game=home_wins, persist_cb=lambda b: None)
    # The championship series is played once, not again as "Final".
    assert len(calls) - before == len(league_cs.games) <= 7
    assert final_copy.games == league_cs.games
    assert reloaded.champion == league_cs.winner


def test_a_series_seeded_early_waits_for_its_round(schedule):
    """Five clubs: the 2-3 Division Series exists from the start, but it is
    not played before the Wild Card round is over."""
    divisions = ("AL East", "AL East", "AL Central", "AL Central", "AL West")
    teams = [_team(f"A{i}", d) for i, d in enumerate(divisions, start=1)]
    standings = {
        t.team_id: {"wins": 100 - i, "runs_for": 700, "runs_against": 650}
        for i, t in enumerate(teams)
    }
    cfg = PlayoffsConfig(num_playoff_teams_per_league=5)
    cfg.playoff_slots_by_league_size = {5: 5}
    bracket = generate_bracket(standings, teams, cfg)
    ds = next(r for r in bracket.rounds if r.name.endswith("DS"))
    assert len(ds.matchups) == 1  # 2 v 3, seeded at generation

    def home_wins(home, away, **kwargs):
        return (1, 0, "<html/>")

    simulate_next_game(bracket, simulate_game=home_wins, persist_cb=lambda b: None)
    assert ds.matchups[0].games == []
    simulate_playoffs(bracket, simulate_game=home_wins, persist_cb=lambda b: None)
    wc = next(r for r in bracket.rounds if r.name.endswith("WC"))
    last_wc = max(g.date for m in wc.matchups for g in m.games)
    first_ds = min(g.date for m in ds.matchups for g in m.games)
    assert first_ds > last_wc
    assert first_ds == "2025-10-04"


def test_later_rounds_use_the_configured_series_lengths(schedule, monkeypatch):
    """A league that configures a five-game LCS gets one: the series is built
    with that length and its calendar window is a five-game window, so the
    World Series starts after an off day following game 5, not game 7."""
    import playbalance.playoffs_config as pcfg

    cfg = PlayoffsConfig(num_playoff_teams_per_league=6)
    cfg.playoff_slots_by_league_size = {6: 6}
    cfg.series_lengths = dict(cfg.series_lengths, cs=5)
    monkeypatch.setattr(pcfg, "load_playoffs_config", lambda path=None: cfg)

    divisions = ("East", "East", "Central", "Central", "West", "West")
    al = [_team(f"A{i}", f"AL {d}") for i, d in enumerate(divisions, start=1)]
    nl = [_team(f"N{i}", f"NL {d}") for i, d in enumerate(divisions, start=1)]
    standings = {
        t.team_id: {"wins": 100 - idx, "runs_for": 700, "runs_against": 650}
        for idx, t in enumerate(al + nl)
    }
    bracket = generate_bracket(standings, al + nl, cfg)

    # Before the LCS exists, its planned window is already five games long.
    calendar = pf._PlayoffCalendar(bracket, schedule)
    cs_start = calendar._start[pf._stage_key_from_round_name("AL CS")]
    ws_start = calendar._start[pf._stage_key_from_round_name("WS")]
    assert ws_start - cs_start == pf._series_span([2, 2, 1]) + 1

    def home_wins(home, away, seed=None, game_date=None):
        return (1, 0, "<html/>", {})

    simulate_playoffs(bracket, simulate_game=home_wins, persist_cb=lambda b: None)

    def round_dates(name):
        rnd = next(r for r in bracket.rounds if r.name == name)
        return sorted({g.date for m in rnd.matchups for g in m.games})

    cs = next(r for r in bracket.rounds if r.name == "AL CS")
    assert [m.config.length for m in cs.matchups] == [5]
    assert round_dates("AL CS") == [
        "2025-10-12", "2025-10-13", "2025-10-15", "2025-10-16", "2025-10-18",
    ]
    assert round_dates("WS")[0] == "2025-10-20"
