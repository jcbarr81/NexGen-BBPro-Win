from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

import pytest

from playbalance.schedule_generator import generate_mlb_schedule


def _collect_series_lengths(schedule: list[dict[str, str]]) -> list[int]:
    """Return the lengths of consecutive series for each home/away pairing."""

    active: dict[tuple[str, str], tuple[date, int]] = {}
    lengths: list[int] = []

    for game in sorted(schedule, key=lambda g: (g["home"], g["away"], g["date"])):
        key = (game["home"], game["away"])
        current = date.fromisoformat(game["date"])
        last = active.get(key)
        if last is None or (current - last[0]).days > 1:
            if last is not None:
                lengths.append(last[1])
            active[key] = (current, 1)
        else:
            active[key] = (current, last[1] + 1)

    lengths.extend(length for _, length in active.values())
    return lengths


def _max_location_blocks(schedule: list[dict[str, str]]) -> tuple[int, int]:
    """Return the maximum consecutive home and away series for any team."""

    games_by_team: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for game in schedule:
        date_str = game["date"]
        home = game["home"]
        away = game["away"]
        games_by_team[home].append((date_str, "home", away))
        games_by_team[away].append((date_str, "away", home))

    max_home_block = 0
    max_away_block = 0

    for team, entries in games_by_team.items():
        entries.sort(key=lambda item: item[0])
        series: list[tuple[str, str, int]] = []
        current_loc: str | None = None
        current_opp: str | None = None
        current_len = 0

        for _, loc, opp in entries:
            if loc == current_loc and opp == current_opp:
                current_len += 1
            else:
                if current_loc is not None:
                    series.append((current_loc, current_opp or "", current_len))
                current_loc = loc
                current_opp = opp
                current_len = 1
        if current_loc is not None:
            series.append((current_loc, current_opp or "", current_len))

        block = 0
        for loc, *_ in series:
            if loc == "home":
                block += 1
                max_home_block = max(max_home_block, block)
            else:
                block = 0
        block = 0
        for loc, *_ in series:
            if loc == "away":
                block += 1
                max_away_block = max(max_away_block, block)
            else:
                block = 0

    return max_home_block, max_away_block


def test_mlb_schedule_totals_and_series_distribution() -> None:
    teams = [f"T{i:02d}" for i in range(30)]
    schedule = generate_mlb_schedule(teams, date(2025, 3, 27))

    assert len(schedule) == len(teams) * 162 // 2

    game_counts = Counter()
    for game in schedule:
        game_counts[game["home"]] += 1
        game_counts[game["away"]] += 1

    assert all(count == 162 for count in game_counts.values())

    series_lengths = _collect_series_lengths(schedule)
    assert series_lengths
    assert all(2 <= length <= 4 for length in series_lengths)

    distribution = Counter(series_lengths)
    assert distribution[3] >= distribution[2]
    assert distribution[3] >= distribution[4]

    max_home_block, max_away_block = _max_location_blocks(schedule)
    assert max_home_block <= 3
    assert max_away_block <= 3


def test_mlb_schedule_includes_travel_days_and_break() -> None:
    teams = [f"T{i:02d}" for i in range(30)]
    schedule = generate_mlb_schedule(teams, date(2025, 3, 27))

    unique_dates = sorted({game["date"] for game in schedule})
    assert unique_dates

    intervals = set()
    previous = date.fromisoformat(unique_dates[0])
    for value in unique_dates[1:]:
        current = date.fromisoformat(value)
        intervals.add((current - previous).days)
        previous = current

    assert 2 in intervals  # one-day travel buffer between series
    assert max(intervals) >= 6  # midseason All-Star break


def test_mlb_schedule_small_league_supports_longer_seasons() -> None:
    teams = ["A", "B", "C", "D"]
    schedule = generate_mlb_schedule(teams, date(2025, 3, 31), games_per_team=30)

    counts = Counter()
    for game in schedule:
        counts[game["home"]] += 1
        counts[game["away"]] += 1

    assert all(count == 30 for count in counts.values())

    series_lengths = _collect_series_lengths(schedule)
    assert all(2 <= length <= 4 for length in series_lengths)


def test_mlb_schedule_rejects_too_few_games() -> None:
    teams = ["A", "B", "C", "D"]
    with pytest.raises(ValueError):
        generate_mlb_schedule(teams, date(2025, 3, 31), games_per_team=10)


def _span_and_longest_run(schedule: list[dict[str, str]]) -> tuple[int, int]:
    days = sorted({date.fromisoformat(g["date"]) for g in schedule})
    span = (days[-1] - days[0]).days + 1
    longest = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)
    return span, longest


@pytest.mark.parametrize("team_count", [30, 20, 12, 8, 4])
def test_mlb_schedule_is_dense_by_default(team_count: int) -> None:
    """Owner decision Q4 (Release 3): series run back to back, keeping the
    weekly off day and the All-Star break -- about 190 days, like MLB."""
    teams = [f"T{i:02d}" for i in range(team_count)]
    schedule = generate_mlb_schedule(teams, date(2025, 4, 1))
    counts = Counter()
    for game in schedule:
        counts[game["home"]] += 1
        counts[game["away"]] += 1
    assert set(counts.values()) == {162}
    span, longest = _span_and_longest_run(schedule)
    assert 180 <= span <= 196, span
    assert longest <= 10
    # The weekly off day survives: no series starts on a Monday, so Mondays
    # are off unless a 4-game series runs through one.
    mondays = {g["date"] for g in schedule if date.fromisoformat(g["date"]).weekday() == 0}
    assert len(mondays) < 27


def test_series_off_day_restores_the_old_layout() -> None:
    teams = [f"T{i:02d}" for i in range(30)]
    schedule = generate_mlb_schedule(teams, date(2025, 4, 1), series_off_day=True)
    span, _ = _span_and_longest_run(schedule)
    assert span == 231


def test_mlb_162_template_is_dense() -> None:
    from services.league_presets import (
        generate_schedule_from_template,
        get_schedule_template,
    )

    template = get_schedule_template("mlb_162")
    assert template is not None and template.series_off_day is False
    teams = [f"T{i:02d}" for i in range(30)]
    schedule = generate_schedule_from_template("mlb_162", teams, year=2027)
    span, _ = _span_and_longest_run(schedule)
    assert 180 <= span <= 196, span


# --- Release 5: every club hosts the same number of games --------------------


def _template_cases() -> list[tuple[str, int]]:
    """Every schedule template at every league size it can be played at.

    A league has 2 to ``MAX_LEAGUE_TEAMS`` clubs and the count can be odd
    (the wizard takes any number of divisions and teams per division). A
    template too short for the league raises ``ValueError``; league creation
    then falls back to ``mlb_162``, which fits every size.
    """
    from playbalance.league_creator import MAX_LEAGUE_TEAMS
    from services.league_presets import load_schedule_templates

    cases: list[tuple[str, int]] = []
    for template in load_schedule_templates():
        for team_count in range(2, MAX_LEAGUE_TEAMS + 1):
            if template.games_per_team >= 4 * (team_count - 1):
                cases.append((template.template_id, team_count))
    return cases


def _unbalanced_template_schedule(
    template_id: str, teams: list[str], year: int
) -> list[dict[str, str]]:
    """The template's schedule as it was before Release 5."""
    from services.league_presets import get_schedule_template

    template = get_schedule_template(template_id)
    assert template is not None
    return generate_mlb_schedule(
        teams,
        date(year, template.start_month, template.start_day),
        games_per_team=template.games_per_team,
        include_all_star_break=template.include_all_star_break,
        weekly_off_weekday=template.weekly_off_weekday,
        extra_off_every_n_rounds=template.extra_off_every_n_rounds,
        series_off_day=template.series_off_day,
        balance_home_games=False,
    )


def _home_counts(schedule: list[dict[str, str]]) -> Counter:
    return Counter(game["home"] for game in schedule)


def _dates_and_opponents(schedule: list[dict[str, str]]) -> list[tuple]:
    """The schedule without who is at home."""
    return sorted(
        (game["date"], *sorted((game["home"], game["away"])))
        for game in schedule
    )


def _longest_home_and_road_runs(
    schedule: list[dict[str, str]]
) -> tuple[int, int]:
    """The longest homestand and road trip of any club, in games."""
    places: dict[str, list[str]] = defaultdict(list)
    for game in sorted(schedule, key=lambda g: g["date"]):
        places[game["home"]].append("home")
        places[game["away"]].append("away")
    longest = {"home": 0, "away": 0}
    for sequence in places.values():
        run = 0
        previous = None
        for place in sequence:
            run = run + 1 if place == previous else 1
            previous = place
            longest[place] = max(longest[place], run)
    return longest["home"], longest["away"]


def test_every_league_size_and_template_is_covered() -> None:
    from playbalance.league_creator import MAX_LEAGUE_TEAMS

    sizes: dict[str, set[int]] = defaultdict(set)
    for template_id, team_count in _template_cases():
        sizes[template_id].add(team_count)
    assert set(sizes) == {"mlb_162", "balanced_120", "compact_84", "short_48"}
    # The fallback fits every league the product allows, odd sizes included.
    assert sizes["mlb_162"] == set(range(2, MAX_LEAGUE_TEAMS + 1))
    assert {20, 24, 30} <= sizes["balanced_120"]
    assert {19, 20} <= sizes["compact_84"]


@pytest.mark.parametrize("template_id, team_count", _template_cases())
def test_template_schedule_gives_every_club_the_same_home_games(
    template_id: str, team_count: int
) -> None:
    """Release 5 adds a home-field advantage, so every club must host the
    same number of games; before, a club's place in the team list decided it
    (75 to 87 of 162 with 30 teams, 70 to 92 with 24)."""
    from services.league_presets import (
        generate_schedule_from_template,
        get_schedule_template,
    )

    template = get_schedule_template(template_id)
    assert template is not None
    games = template.games_per_team
    teams = [f"T{i:02d}" for i in range(team_count)]
    schedule = generate_schedule_from_template(template_id, teams, year=2027)

    home = _home_counts(schedule)
    away = Counter(game["away"] for game in schedule)
    assert games % 2 == 0
    assert {home[team] for team in teams} == {games // 2}
    assert {away[team] for team in teams} == {games // 2}

    # No club plays twice in a day.
    playing = Counter()
    for game in schedule:
        playing[(game["date"], game["home"])] += 1
        playing[(game["date"], game["away"])] += 1
    assert set(playing.values()) == {1}

    # Series stay two to four games: balancing never puts two series
    # between the same clubs in the same park back to back.
    assert all(2 <= n <= 4 for n in _collect_series_lengths(schedule))

    # Opponents are spread evenly, at home and away.
    hosted = Counter((game["home"], game["away"]) for game in schedule)
    meetings = [
        hosted[(club, other)] + hosted[(other, club)]
        for club in teams
        for other in teams
        if club != other
    ]
    assert max(meetings) - min(meetings) <= 1
    assert all(
        abs(hosted[(club, other)] - hosted[(other, club)]) <= 1
        for club in teams
        for other in teams
    )

    # Only who hosts changed: the dates and opponents are the ones the
    # unbalanced layout gives, so the weekly off day, the All-Star break and
    # the season's length are untouched.
    before = _unbalanced_template_schedule(template_id, teams, 2027)
    assert _dates_and_opponents(schedule) == _dates_and_opponents(before)

    # Homestands and road trips are no longer than they were (at most two
    # four-game series; MLB rarely goes past 10 to 13 games).
    stand, trip = _longest_home_and_road_runs(schedule)
    stand_before, trip_before = _longest_home_and_road_runs(before)
    assert stand <= stand_before <= 8
    assert trip <= trip_before <= 8


def test_unbalanced_layout_is_still_available() -> None:
    """``balance_home_games=False`` is the layout from before Release 5; the
    KPI harness keeps it so its baselines keep their schedule."""
    teams = [f"T{i:02d}" for i in range(30)]
    before = _home_counts(
        generate_mlb_schedule(
            teams, date(2025, 4, 1), balance_home_games=False
        )
    )
    after = _home_counts(generate_mlb_schedule(teams, date(2025, 4, 1)))
    assert (min(before.values()), max(before.values())) == (75, 87)
    assert (min(after.values()), max(after.values())) == (81, 81)


@pytest.mark.parametrize("team_count", [4, 12, 20])
def test_odd_season_length_splits_home_games_within_one(
    team_count: int,
) -> None:
    teams = [f"T{i:02d}" for i in range(team_count)]
    schedule = generate_mlb_schedule(
        teams, date(2025, 4, 1), games_per_team=81
    )
    home = _home_counts(schedule)
    assert sorted(set(home.values())) == [40, 41]
    assert sum(home.values()) == team_count * 81 // 2


def test_two_team_schedule_is_left_alone() -> None:
    """Two clubs already alternate parks; there is nothing to exchange."""
    for games in (48, 81, 162):
        balanced = generate_mlb_schedule(["A", "B"], date(2025, 4, 1), games)
        before = generate_mlb_schedule(
            ["A", "B"], date(2025, 4, 1), games, balance_home_games=False
        )
        assert balanced == before


@pytest.mark.parametrize("team_count", [9, 20, 24, 30])
def test_schedule_is_deterministic(team_count: int) -> None:
    teams = [f"T{i:02d}" for i in range(team_count)]
    first = generate_mlb_schedule(teams, date(2025, 4, 1))
    assert generate_mlb_schedule(teams, date(2025, 4, 1)) == first
    assert generate_mlb_schedule(tuple(teams), date(2025, 4, 1)) == first
    assert generate_mlb_schedule(iter(teams), date(2025, 4, 1)) == first


def test_schedule_does_not_depend_on_the_hash_seed() -> None:
    """A league's schedule must not change with the process that builds it
    (string hashing differs between processes unless PYTHONHASHSEED is set)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import hashlib, json\n"
        "from datetime import date\n"
        "from playbalance.schedule_generator import generate_mlb_schedule\n"
        "teams = ['Austin Aces', 'Boise Bears', 'Cary Cubs', 'Dover Ducks',"
        " 'Erie Elks', 'Fargo Foxes', 'Gary Gulls', 'Hilo Hawks',"
        " 'Iowa Ibis']\n"
        "rows = generate_mlb_schedule(teams, date(2027, 4, 1))\n"
        "print(hashlib.sha256(json.dumps(rows).encode()).hexdigest())\n"
    )
    digests = set()
    for seed in ("1", "2", "random"):
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True,
            text=True,
            check=True,
        )
        digests.add(result.stdout.strip())
    assert len(digests) == 1


def test_rollover_keeps_an_existing_schedule_and_balances_a_new_one(
    tmp_path, monkeypatch
) -> None:
    """A season already under way keeps the schedule in its schedule.csv,
    byte for byte; only a league with no schedule gets a new, balanced one."""
    import shutil

    import api.routers.season as season
    from playbalance.schedule_generator import save_schedule
    from playbalance.season_context import SeasonContext
    from utils.team_loader import load_teams

    def no_context(*args, **kwargs):
        raise RuntimeError("no season context in this test")

    shutil.copy("data/calibration/teams.csv", tmp_path / "teams.csv")
    monkeypatch.setattr(season, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(SeasonContext, "load", no_context)
    teams = [team.team_id for team in load_teams(tmp_path / "teams.csv")]
    assert len(teams) == 30

    existing = generate_mlb_schedule(
        teams, date(2026, 4, 1), balance_home_games=False
    )
    existing[0]["result"] = "5-3"
    existing[0]["played"] = "1"
    path = tmp_path / "schedule.csv"
    save_schedule(existing, path)
    written = path.read_bytes()

    assert season._ensure_new_season_schedule() == {
        "generated": False,
        "reason": "schedule_exists",
    }
    assert path.read_bytes() == written

    path.unlink()
    outcome = season._ensure_new_season_schedule()
    assert outcome["generated"] is True and outcome["games"] == 2430
    home = Counter(row["home"] for row in season._load_schedule())
    assert {home[team] for team in teams} == {81}
