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
