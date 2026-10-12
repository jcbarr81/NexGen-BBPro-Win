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
    weekly_off_weekday: int | None = 0,
    extra_off_every_n_rounds: int = 0,
    series_off_day: bool = False,
    max_consecutive_days: int | None = 10,
    balance_home_games: bool = True,
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
    weekly_off_weekday:
        ISO weekday number (0=Monday, 6=Sunday) on which no series should
        start. Models the MLB convention of light Monday game days. Pass
        ``None`` to disable. Default ``0`` (Monday).
    extra_off_every_n_rounds:
        When > 0, insert an extra day off after every Nth round in
        addition to any inter-round buffer.
        Default ``0`` (no extra off days).
    series_off_day:
        When True, every round of series is followed by a league-wide day
        off (the pre-Release-3 layout: about 246 days for 30 teams). The
        default ``False`` is MLB-dense (owner decision Q4, Release 3): series
        run back to back, so with the weekly off day a club plays six days in
        seven and 162 games span about 190 days plus the All-Star break.
        Rest is counted in calendar days, so the density decides how often a
        bullpen gets a day off.
    max_consecutive_days:
        Dense layout only: the longest stretch of straight game days before a
        league-wide day off is forced. Rounds of 4-game series can run
        through the weekly off day; this keeps an off day at least every
        ``max_consecutive_days`` days. ``None`` or ``0`` disables it.
    balance_home_games:
        When True (the default) every club hosts exactly half of its games,
        or within one of half when *games_per_team* is odd. Dates, opponents
        and series lengths are the same either way: balancing only decides
        which club hosts which leg of a home-and-home pair of series (see
        :func:`_balance_home_games`). ``False`` keeps the layout from before
        Release 5, where the club's place in *teams* decided how many of its
        shortened or lengthened series were at home (75 to 87 home games in
        a 30-team, 162-game season); the KPI harness uses it so its
        calibration baselines keep their schedule.

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
        weekly_off_weekday=weekly_off_weekday,
        extra_off_every_n_rounds=extra_off_every_n_rounds,
        series_off_day=series_off_day,
        max_consecutive_days=max_consecutive_days,
        balance_home_games=balance_home_games,
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


def _chain_to_poorer(
    favoured: Dict[str, List[str]], surplus: Dict[str, int], start: str
) -> List[str] | None:
    """Return the shortest chain of clubs from *start*, each hosting the next
    for one game more than it visits, that ends at a club at least three
    home games worse off than *start* -- or ``None`` when there is none."""

    target = surplus[start] - 3
    previous: Dict[str, str | None] = {start: None}
    frontier = deque([start])
    while frontier:
        club = frontier.popleft()
        if surplus[club] <= target:
            chain = [club]
            while previous[chain[-1]] is not None:
                chain.append(previous[chain[-1]])
            return chain[::-1]
        for opponent in favoured[club]:
            if opponent not in previous:
                previous[opponent] = club
                frontier.append(opponent)
    return None


def _balance_home_games(
    teams: List[str], queues: Dict[tuple[str, str], deque[Series]]
) -> None:
    """Exchange hosts between pairs of clubs until home games come out even.

    Every club hosts each opponent for as many series as it visits them, so
    home games are uneven only because series were shortened or lengthened
    to reach the season total: a club that hosts the longer series against
    many opponents and the shorter against few plays more at home. Exchanging
    the hosts of every series between two such clubs moves one home game from
    one to the other and changes nothing else: the dates, the opponents, the
    series lengths and the count of series each hosts against the other all
    stay as they were, and the two clubs still alternate parks.

    A club with a surplus passes a home game down a chain of such pairs to a
    club with a deficit; the clubs in between give one and take one, and
    pairs off the chain keep their hosts. This repeats until no chain helps,
    which leaves every club within one game of an even split (exactly even
    when it plays an even number of games) provided no two clubs' home games
    against each other differ by more than one -- true of every plan
    :func:`_build_series_plan` makes.

    *queues* is keyed by each series' place in the calendar, which is why
    the place does not move when ``home`` and ``away`` do. The result depends
    only on the order of *teams* and the series lengths.
    """

    hosted: Dict[tuple[str, str], int] = {}
    surplus = {team: 0 for team in teams}
    for (home, away), queue in queues.items():
        games = sum(series.length for series in queue)
        hosted[(home, away)] = games
        surplus[home] += games
        surplus[away] -= games

    # favoured[club]: the opponents it hosts for exactly one game more than
    # it visits. Exchanging hosts with one of them hands that game over.
    favoured: Dict[str, List[str]] = {team: [] for team in teams}
    for index, club in enumerate(teams):
        for opponent in teams[index + 1:]:
            edge = hosted.get((club, opponent), 0) - hosted.get(
                (opponent, club), 0
            )
            if edge == 1:
                favoured[club].append(opponent)
            elif edge == -1:
                favoured[opponent].append(club)

    while True:
        chain = None
        for club in sorted(teams, key=lambda team: -surplus[team]):
            chain = _chain_to_poorer(favoured, surplus, club)
            if chain:
                break
        if not chain:
            return
        for giver, taker in zip(chain, chain[1:]):
            for key in ((giver, taker), (taker, giver)):
                for series in queues.get(key, ()):
                    series.home, series.away = series.away, series.home
            favoured[giver].remove(taker)
            favoured[taker].append(giver)
        surplus[chain[0]] -= 2
        surplus[chain[-1]] += 2


def _build_series_schedule(
    teams: List[str],
    plan: List[Series],
    start_date: date,
    *,
    include_all_star_break: bool = True,
    all_star_break_days: int = 6,
    weekly_off_weekday: int | None = 0,
    extra_off_every_n_rounds: int = 0,
    series_off_day: bool = False,
    max_consecutive_days: int | None = 10,
    balance_home_games: bool = True,
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
    if balance_home_games:
        _balance_home_games(teams, queues)

    total_games = sum(series.length for series in plan)
    schedule: List[Dict[str, str]] = []
    current = start_date
    games_scheduled = 0
    pattern_index = 0
    rounds_played = 0
    all_star_inserted = False
    # Dense layout bookkeeping: first day of the current stretch of straight
    # game days, and the day after the last round ended.
    run_start: date | None = None
    run_end: date | None = None

    while _series_remaining(queues):
        round_games = patterns[pattern_index % len(patterns)]
        pattern_index += 1

        # Skip weekly off day before starting a new series so MLB-style
        # Monday rest stays intact between series rather than mid-series.
        if weekly_off_weekday is not None:
            while current.weekday() == weekly_off_weekday:
                current += timedelta(days=1)

        assignments: List[Series] = []
        for home, away in round_games:
            queue = queues[(home, away)]
            if queue:
                assignments.append(queue.popleft())

        if not assignments:
            continue

        round_length = max(series.length for series in assignments)
        if (
            not series_off_day
            and max_consecutive_days
            and run_start is not None
            and current == run_end
            and (current - run_start).days + round_length > max_consecutive_days
        ):
            # Dense layout: with 4-game series a round can run through the
            # weekly off day, so cap the stretch of straight game days.
            current += timedelta(days=1)
        if current != run_end:
            run_start = current

        for series in assignments:
            for offset in range(series.length):
                date_value = (current + timedelta(days=offset)).isoformat()
                schedule.append(
                    {"date": date_value, "home": series.home, "away": series.away}
                )
                games_scheduled += 1

        current += timedelta(days=round_length)
        run_end = current
        rounds_played += 1

        if (
            include_all_star_break
            and not all_star_inserted
            and games_scheduled >= total_games / 2
            and _series_remaining(queues)
        ):
            current += timedelta(days=all_star_break_days)
            all_star_inserted = True

        if _series_remaining(queues):
            if series_off_day:
                current += timedelta(days=1)
            # Periodic extra off day on top of any travel buffer.
            if (
                extra_off_every_n_rounds > 0
                and rounds_played % extra_off_every_n_rounds == 0
            ):
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
