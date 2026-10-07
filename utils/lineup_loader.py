import csv
import random
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Tuple

from playbalance.simulation import TeamState
from models.player import Player
from models.pitcher import Pitcher
from models.roster import Roster
from utils.path_utils import resolve_app_path
from .player_loader import load_players_from_csv
from .roster_loader import load_roster
from .pitcher_role import get_role
from utils.team_loader import load_teams


def load_lineup(team_id: str, vs: str = "lhp", lineup_dir: str | Path = "data/lineups") -> List[Tuple[str, str]]:
    """Load a lineup from ``lineup_dir`` for the given team.

    Files are expected to follow the naming pattern
    ``{team_id}_vs_{vs}.csv`` and contain columns
    ``order,player_id,position`` where ``player_id`` uses IDs like
    ``P1000``.
    """
    suffix = f"vs_{vs.lower()}"
    lineup_dir = resolve_app_path(lineup_dir)
    file_path = lineup_dir / f"{team_id}_{suffix}.csv"
    if not file_path.exists():
        raise FileNotFoundError(f"Lineup file not found: {file_path}")

    lineup: List[Tuple[str, str]] = []
    with file_path.open(newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            player_id = row.get("player_id", "").strip()
            position = row.get("position", "").strip()
            lineup.append((player_id, position))
    return lineup


def _separate_players(players: Iterable[Player]) -> Tuple[List[Player], List[Pitcher]]:
    """Return hitters and pitchers from ``players``.

    Pitchers are identified using :func:`utils.pitcher_role.get_role`.  Players
    for which ``get_role`` returns ``"SP"`` or ``"RP"`` are treated as
    pitchers, everything else is considered a position player.
    """

    hitters: List[Player] = []
    pitchers: List[Pitcher] = []
    for p in players:
        role = get_role(p)
        if role in {"SP", "RP"}:
            pitchers.append(p)  # type: ignore[arg-type]
        else:
            hitters.append(p)
    return hitters, pitchers


def _load_pitching_staff(
    team_id: str,
    roster_dir: str,
    valid_pitchers: set[str],
) -> List[tuple[str, str]]:
    """Return ordered pitching staff entries from ``*_pitching.csv``."""

    roster_path = resolve_app_path(roster_dir)
    file_path = roster_path / f"{team_id}_pitching.csv"
    entries: List[tuple[str, str]] = []
    if not file_path.exists():
        return entries
    seen: set[str] = set()
    try:
        with file_path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            for row in reader:
                if len(row) < 2:
                    continue
                pid = row[0].strip()
                role = row[1].strip()
                if not pid or pid in seen or pid not in valid_pitchers:
                    continue
                entries.append((pid, role))
                seen.add(pid)
    except OSError:
        return []
    return entries


def _resolve_players(
    ids: Iterable[str], all_players: dict[str, Player], seen: set[str]
) -> List[Player]:
    """Resolve ``ids`` against ``all_players``, skipping ids already in ``seen``."""

    found: List[Player] = []
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        player = all_players.get(pid)
        if player is not None:
            found.append(player)
    return found


def _default_hitters(
    team_id: str, roster: Roster, all_players: dict[str, Player]
) -> Tuple[List[Player], List[Player]]:
    """Return ``(lineup, bench)`` for ``team_id``'s default game state.

    Nine position players are chosen by the lineup auto-fill's coverage-first
    :func:`utils.lineup_autofill.build_lineup` (Release 3: it used to be the
    top nine by ``ph``, which could leave C or SS empty), in memory -- no
    lineup file is written -- and batted in the auto-fill's slot order. Each
    lineup player's ``position`` is set as :func:`apply_lineup` does; a saved
    lineup applied afterwards overrides it. The remaining hitters form the
    bench. Only the club's own players: the old fallback to other clubs'
    hitters is gone (the game rejected them anyway, audit H9).
    """

    # A big-league game uses the ACTIVE roster. 3.2.12 widened this pool to
    # every level, and for the whole 2026 alpha-test season AAA and Low-A
    # players -- and players on the DL -- started in MLB lineups and pitched
    # out of MLB bullpens: the best nine hitters in the organisation made the
    # default lineup, and half the CPU clubs fielded 3-5 minor leaguers every
    # game. Injured players are never eligible; healthy minor leaguers only
    # fill in when the active roster cannot field a team.
    seen_ids: set[str] = set()
    hitters, _ = _separate_players(_resolve_players(roster.act, all_players, seen_ids))
    if len(hitters) < 9:
        minor_hitters, _ = _separate_players(
            _resolve_players(list(roster.aaa) + list(roster.low), all_players, seen_ids)
        )
        minor_hitters.sort(key=lambda p: getattr(p, "ph", 0), reverse=True)
        hitters.extend(minor_hitters[: max(0, 9 - len(hitters))])

    from utils.lineup_autofill import (
        _assign_batting_order,
        build_lineup,
        lineup_hitter_score,
    )

    by_id = {p.player_id: p for p in hitters}

    def score(pid: str) -> float:
        return lineup_hitter_score(by_id[pid], vs_hand="R")

    picked, _counters = build_lineup(list(by_id), by_id, score=score)
    if len(picked) >= 9:
        picked = _assign_batting_order(picked, by_id, vs_hand="R", overall_score=score)
    lineup: List[Player] = []
    for pid, pos in picked:
        player = by_id[pid]
        setattr(player, "position", pos)
        lineup.append(player)
    chosen = {p.player_id for p in lineup}
    bench = [p for p in hitters if p.player_id not in chosen]
    return lineup, bench


def _default_pitchers(
    team_id: str, roster_dir: str, roster: Roster, all_players: dict[str, Player]
) -> List[Pitcher]:
    """Return ``team_id``'s pitchers, the five-man rotation first.

    Staff-file arms keep their listed roles; the rotation is labelled SP1-SP5
    and followed by the remaining bullpen arms.
    """

    # Active roster first; healthy minor leaguers only when it has no arms
    # (see _default_hitters).
    seen_ids: set[str] = set()
    _, pitchers = _separate_players(_resolve_players(roster.act, all_players, seen_ids))
    if not pitchers:
        _, minor_pitchers = _separate_players(
            _resolve_players(list(roster.aaa) + list(roster.low), all_players, seen_ids)
        )
        minor_pitchers.sort(key=lambda p: getattr(p, "endurance", 0), reverse=True)
        pitchers.extend(minor_pitchers[:10])
    if not pitchers:
        _, all_pitchers = _separate_players(all_players.values())
        fallback_pitchers = list(all_pitchers)
        rng = random.Random(f"{team_id}-fallback-pitchers")
        rng.shuffle(fallback_pitchers)
        pitchers.extend(fallback_pitchers[:10])

    pitcher_lookup = {p.player_id: p for p in pitchers}
    staff_entries = _load_pitching_staff(team_id, roster_dir, set(pitcher_lookup))
    ordered_pitchers: List[Pitcher] = []

    for pid, role in staff_entries:
        pitcher = pitcher_lookup.pop(pid, None)
        if pitcher is None:
            continue
        setattr(pitcher, "assigned_pitching_role", role)
        ordered_pitchers.append(pitcher)

    remaining = list(pitcher_lookup.values())
    for pitcher in remaining:
        # Always derive the non-staff role fresh from the pitcher's static
        # ratings. ``assigned_pitching_role`` is a mutable attribute on cached
        # player objects, and later steps here relabel extra rotation arms to
        # "MR" in place. Honoring a persisted value (the old ``if not assigned``
        # guard) made staff ordering depend on whether the player had already
        # appeared in this process — non-deterministic across parallel workers
        # and inconsistent between a season's first day and the rest (S1-10).
        derived = get_role(pitcher)
        setattr(pitcher, "assigned_pitching_role", derived or "")
    remaining.sort(key=lambda p: getattr(p, "endurance", 0), reverse=True)
    ordered_pitchers.extend(remaining)

    if not ordered_pitchers:
        pitchers.sort(key=lambda p: getattr(p, "endurance", 0), reverse=True)
        ordered_pitchers = pitchers
        for pitcher in ordered_pitchers:
            assigned = getattr(pitcher, "assigned_pitching_role", None)
            if not assigned:
                derived = get_role(pitcher)
                setattr(pitcher, "assigned_pitching_role", derived or "")

    # Ensure a five-man rotation exists and starters do not clutter the bullpen.
    rotation: List[Pitcher] = []
    bullpen: List[Pitcher] = []
    for pitcher in ordered_pitchers:
        role = str(getattr(pitcher, "assigned_pitching_role", "") or "").upper()
        if role.startswith("SP"):
            rotation.append(pitcher)
        else:
            bullpen.append(pitcher)

    if len(rotation) < 5:
        bullpen_sorted = sorted(
            bullpen, key=lambda p: getattr(p, "endurance", 0), reverse=True
        )
        while len(rotation) < 5 and bullpen_sorted:
            promote = bullpen_sorted.pop(0)
            if promote in bullpen:
                bullpen.remove(promote)
            rotation.append(promote)

    # Keep exactly five rotation slots, push any extras to the bullpen group.
    extra_rotation = rotation[5:]
    if extra_rotation:
        for pitcher in extra_rotation:
            setattr(pitcher, "assigned_pitching_role", "MR")
        bullpen = extra_rotation + bullpen
        rotation = rotation[:5]

    # Label rotation spots consistently (SP1..SP5) for downstream consumers.
    for idx, pitcher in enumerate(rotation, start=1):
        setattr(pitcher, "assigned_pitching_role", f"SP{idx}")

    for pitcher in bullpen:
        role = str(getattr(pitcher, "assigned_pitching_role", "") or "").upper()
        if role == "SP":
            setattr(pitcher, "assigned_pitching_role", "MR")

    ordered_pitchers = rotation + bullpen

    return ordered_pitchers


def _build_default_lists(
    team_id: str, players_file: str, roster_dir: str
) -> Tuple[List[Player], List[Player], List[Pitcher]]:
    """Return ``(lineup, bench, pitchers)`` for ``team_id``.

    The active roster is loaded from ``roster_dir`` and players are resolved via
    ``players_file``. The hitters come from :func:`_default_hitters` and the
    pitchers, a single starter first followed by the remaining bullpen arms,
    from :func:`_default_pitchers`.
    """

    all_players = {p.player_id: p for p in load_players_from_csv(players_file)}
    roster = load_roster(team_id, roster_dir)
    # Hitters first: their pool is chosen before any pitcher's
    # ``assigned_pitching_role`` is (re)labelled, as it always was.
    lineup, bench = _default_hitters(team_id, roster, all_players)
    pitchers = _default_pitchers(team_id, roster_dir, roster, all_players)
    return lineup, bench, pitchers


@lru_cache(maxsize=None)
def _teams_lookup(path: str) -> dict[str, object]:
    try:
        teams = load_teams(path)
    except Exception:
        return {}
    return {t.team_id: t for t in teams}


def build_default_game_state(
    team_id: str,
    players_file: str = "data/players.csv",
    roster_dir: str = "data/rosters",
    teams_file: str | Path = "data/teams.csv",
) -> TeamState:
    """Return a :class:`~playbalance.simulation.TeamState` for ``team_id``.

    The state uses nine best hitters for the lineup, remaining hitters as the
    bench and pitchers ordered with a starter first followed by the bullpen.
    """

    lineup, bench, pitchers = _build_default_lists(team_id, players_file, roster_dir)

    if len(lineup) < 9:
        raise ValueError(f"Team {team_id} does not have enough position players")
    if not pitchers:
        raise ValueError(f"Team {team_id} does not have any pitchers")

    team_obj = None
    if teams_file:
        lookup_path = resolve_app_path(teams_file)
        team_obj = _teams_lookup(str(lookup_path)).get(team_id)

    state = TeamState(lineup=lineup, bench=bench, pitchers=pitchers, team=team_obj)
    if team_obj is not None:
        season = getattr(team_obj, "season_stats", None)
        if season:
            state.team_stats = dict(season)
    return state
