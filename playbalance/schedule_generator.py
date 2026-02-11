from __future__ import annotations

"""Utilities for generating season schedules.

This module produces a basic full-season schedule for a league.  The
current implementation generates a double round-robin schedule where each
team plays every other team twice: once at home and once away.  Games are
scheduled on consecutive days starting from a provided start date.

The function returns a list of dictionaries with ``date`` (ISO formatted
string), ``home`` team and ``away`` team keys.  The simple data structure
is easy for callers or tests to consume and can be written to disk using
:func:`save_schedule` if desired.

The algorithm supports both even and odd numbers of teams.  For an odd
number of teams a bye is automatically inserted each round and games
involving the bye are skipped.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, List, Dict
import csv

__all__ = ["generate_schedule", "generate_mlb_schedule", "save_schedule"]


@dataclass
class Series:
    """Representation of a multi-game series."""

    home: str
    away: str
    length: int


def _round_robin_pairs(teams: List[str]) -> List[List[tuple[str, str]]]:
    """Return pairings for a single round-robin tournament.

    The returned value is a list of rounds, each round being a list of
    ``(home, away)`` tuples.  Home teams alternate in a simple pattern to
    avoid the same team always being home or away.  If the number of teams
    is odd, a ``None`` placeholder is added internally and any games
    involving ``None`` are skipped by callers.
    """

    teams = list(teams)
    if not teams:
        return []

    # For odd counts insert a bye placeholder.
    bye = None
    if len(teams) % 2 == 1:
        teams.append(bye)
    n = len(teams)
    rounds: List[List[tuple[str, str]]] = []

    for i in range(n - 1):
        round_games: List[tuple[str, str]] = []
        for j in range(n // 2):
            t1 = teams[j]
            t2 = teams[n - 1 - j]
            if t1 is bye or t2 is bye:
                continue
            # Alternate home/away to spread home games.
            if j % 2 == i % 2:
                round_games.append((t1, t2))
            else:
                round_games.append((t2, t1))
        rounds.append(round_games)
        # Rotate teams (fixed first team).
        teams = [teams[0]] + teams[-1:] + teams[1:-1]
    return rounds


def generate_schedule(teams: Iterable[str], start_date: date) -> List[Dict[str, str]]:
    """Generate a double round-robin schedule.

    Parameters
    ----------
    teams:
        Iterable of team identifiers/names.
    start_date:
        Date of the first day of the schedule.

    Returns
    -------
    list of dict
        Each dictionary contains ``date`` (ISO formatted string), ``home``
        team and ``away`` team keys.
    """

    teams_list = list(teams)
    rounds = _round_robin_pairs(teams_list)
    schedule: List[Dict[str, str]] = []
    current = start_date

    # First half of the season
    for round_games in rounds:
        for home, away in round_games:
            schedule.append({
                "date": current.isoformat(),
                "home": home,
                "away": away,
            })
        current += timedelta(days=1)

    # Mid-season break for the All-Star exhibition
    # ``current`` has already been advanced by one day after the last round
    # above so we add six additional days to produce roughly a one week pause
    # in the schedule.
    current += timedelta(days=6)

    # Second half with reversed home/away
    for round_games in rounds:
        for home, away in round_games:
            schedule.append({
                "date": current.isoformat(),
                "home": away,
                "away": home,
            })
        current += timedelta(days=1)

    return schedule


def generate_mlb_schedule(
    teams: Iterable[str],
    start_date: date,
    games_per_team: int = 162,
    *,
    include_all_star_break: bool = True,
    all_star_break_days: int = 6,
) -> List[Dict[str, str]]:
    """Generate a full 162-game schedule for each team.

    The algorithm builds upon :func:`generate_schedule` which creates a single
    double round-robin cycle with an All-Star break.  That base cycle is
    repeated as many times as necessary and truncated so that every club plays
    exactly *games_per_team* contests (81 home and 81 away when using the
    default).

    Parameters
    ----------
    teams:
        Iterable of team identifiers/names.
    start_date:
        Date of the first day of the schedule.
    games_per_team:
        Total number of games each team should play.  Defaults to ``162`` to
        mirror the length of a Major League Baseball season.
    include_all_star_break:
        When True, inserts a midseason break before the second half.
    all_star_break_days:
        Number of days to pause for the All-Star break.

    Returns
    -------
    list of dict
        Each dictionary contains ``date`` (ISO formatted string), ``home`` team
        and ``away`` team keys representing a single game.
    """

    teams_list = [team for team in teams if team]
    if not teams_list:
        return []

    series_plan = _build_series_plan(teams_list, games_per_team)
    return _build_series_schedule(
        teams_list,
        series_plan,
        start_date,
        include_all_star_break=include_all_star_break,
        all_star_break_days=all_star_break_days,
    )


def _series_order(teams: List[str]) -> List[tuple[str, str]]:
    """Return the deterministic ordering of series pairings."""

    order: List[tuple[str, str]] = []
    rounds = _round_robin_pairs(teams)
    for round_games in rounds:
        order.extend(round_games)
    for round_games in rounds:
        order.extend((away, home) for home, away in round_games)
    return order


def _required_cycles(team_count: int, games_per_team: int) -> int:
    """Return the number of home/away series cycles needed to hit the target."""

    if team_count < 2:
        return 0

    base_min = 4 * (team_count - 1)
    if games_per_team < base_min:
        raise ValueError(
            f"games_per_team={games_per_team} is smaller than the "
            f"minimum achievable total of {base_min} for {team_count} teams"
        )

    cycles = 1
    while True:
        min_possible = cycles * base_min
        max_possible = cycles * 8 * (team_count - 1)
        if min_possible <= games_per_team <= max_possible:
            return cycles
        if games_per_team < min_possible:
            raise ValueError(
                f"games_per_team={games_per_team} is too small for any "
                f"configuration with {team_count} teams"
            )
        cycles += 1


def _build_series_plan(teams: List[str], games_per_team: int) -> List[Series]:
    """Construct the series list required to satisfy *games_per_team*."""

    team_count = len(teams)
    if team_count < 2:
        return []

    cycles = _required_cycles(team_count, games_per_team)
    order = _series_order(teams)

    plan: List[Series] = []
    for _ in range(cycles):
        for home, away in order:
            plan.append(Series(home=home, away=away, length=3))

    totals: Dict[str, int] = defaultdict(int)
    for series in plan:
        totals[series.home] += series.length
        totals[series.away] += series.length

    expected = next(iter(totals.values()))
    if any(total != expected for total in totals.values()):
        raise ValueError("Internal series generation imbalance detected.")

    delta = expected - games_per_team
    if delta > 0:
        reductions = {team: delta for team in teams}
        for series in plan:
            while (
                series.length > 2
                and reductions[series.home] > 0
                and reductions[series.away] > 0
            ):
                series.length -= 1
                reductions[series.home] -= 1
                reductions[series.away] -= 1
        if any(value > 0 for value in reductions.values()):
            raise ValueError(
                "Unable to reach the requested games_per_team by "
                "shortening series lengths."
            )
    elif delta < 0:
        additions = {team: -delta for team in teams}
        for series in plan:
            while (
                series.length < 4
                and additions[series.home] > 0
                and additions[series.away] > 0
            ):
                series.length += 1
                additions[series.home] -= 1
                additions[series.away] -= 1
        if any(value > 0 for value in additions.values()):
            raise ValueError(
                "Unable to reach the requested games_per_team by "
                "extending series lengths."
            )

    _validate_plan(plan, teams, games_per_team)
    return plan


def _validate_plan(plan: List[Series], teams: List[str], games_per_team: int) -> None:
    """Ensure the plan yields the expected number of games for each team."""

    totals: Dict[str, int] = defaultdict(int)
    for series in plan:
        totals[series.home] += series.length
        totals[series.away] += series.length
    for team in teams:
        if totals[team] != games_per_team:
            raise ValueError(
                f"Series plan imbalance detected for {team!r}: "
                f"{totals[team]} games vs expected {games_per_team}"
            )


def _series_remaining(
    queues: Dict[tuple[str, str], deque[Series]]
) -> bool:
    """Return True if any series still exists."""

    return any(queue for queue in queues.values())


def _build_series_schedule(
    teams: List[str],
    plan: List[Series],
    start_date: date,
    *,
    include_all_star_break: bool = True,
    all_star_break_days: int = 6,
) -> List[Dict[str, str]]:
    """Expand a series plan into a day-by-day schedule."""

    if not plan:
        return []

    rounds = _round_robin_pairs(teams)
    if not rounds:
        return []

    reverse_rounds = [
        [(away, home) for home, away in round_games] for round_games in rounds
    ]

    if len(rounds) <= 1:
        patterns = rounds + reverse_rounds
    else:
        patterns = []
        total_rounds = len(rounds)
        for idx in range(total_rounds):
            patterns.append(rounds[idx])
            patterns.append(reverse_rounds[(idx + 1) % total_rounds])

    queues: Dict[tuple[str, str], deque[Series]] = defaultdict(deque)
    for series in plan:
        queues[(series.home, series.away)].append(series)

    total_games = sum(series.length for series in plan)
    schedule: List[Dict[str, str]] = []
    current = start_date
    games_scheduled = 0
    pattern_index = 0
    all_star_inserted = False

    while _series_remaining(queues):
        round_games = patterns[pattern_index % len(patterns)]
        pattern_index += 1

        assignments: List[Series] = []
        for home, away in round_games:
            queue = queues[(home, away)]
            if queue:
                assignments.append(queue.popleft())

        if not assignments:
            continue

        for series in assignments:
            for offset in range(series.length):
                date_value = (current + timedelta(days=offset)).isoformat()
                schedule.append(
                    {"date": date_value, "home": series.home, "away": series.away}
                )
                games_scheduled += 1

        round_length = max(series.length for series in assignments)
        current += timedelta(days=round_length)

        if (
            include_all_star_break
            and not all_star_inserted
            and games_scheduled >= total_games / 2
            and _series_remaining(queues)
        ):
            current += timedelta(days=all_star_break_days)
            all_star_inserted = True

        if _series_remaining(queues):
            current += timedelta(days=1)

    schedule.sort(key=lambda g: (g["date"], g["home"], g["away"]))
    return schedule


def save_schedule(schedule: Iterable[Dict[str, str]], path: str | Path) -> None:
    """Save a generated schedule to a CSV file.

    Parameters
    ----------
    schedule:
        Iterable of dictionaries as produced by :func:`generate_schedule`.
    path:
        Destination path for the CSV file.  Parent directories are created
        automatically.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Include optional result/played columns so that schedule files can track
    # outcomes as the season progresses.  Unknown fields default to blank
    # strings to keep the CSV consistent.
    fieldnames = ["date", "home", "away", "result", "played", "boxscore"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for game in schedule:
            writer.writerow(
                {
                    "date": game.get("date", ""),
                    "home": game.get("home", ""),
                    "away": game.get("away", ""),
                    "result": game.get("result", ""),
                    "played": game.get("played", ""),
                    "boxscore": game.get("boxscore", ""),
                }
            )
