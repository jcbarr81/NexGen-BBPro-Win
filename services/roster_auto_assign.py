from __future__ import annotations

"""Automatic roster assignment utilities.

Selects Active/AAA/Low rosters based on player ratings while respecting
current roster policies:

- Active roster: max 25 players and at least 11 position players
- AAA roster: max 15 players
- Low roster: max 10 players

Players marked as injured are moved to the disabled list (DL) and are not
considered for the Active roster. Existing DL/IR assignments are preserved.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Set

from playbalance.aging import calculate_age
from utils.path_utils import get_base_dir
from utils.player_loader import load_players_from_csv
from utils.team_loader import load_teams
from utils.user_manager import load_users
from utils.lineup_autofill import auto_fill_lineup_for_team
from utils.roster_loader import load_roster, save_roster
from utils.pitcher_role import get_role


ACTIVE_MAX = 25
AAA_MAX = 15
LOW_MAX = 10
AAA_MIN_PITCHERS = 4
AAA_MIN_HITTERS = 4
PROSPECT_AGE_CUTOFF = 21
PROSPECT_BONUS_PER_YEAR = 1.5

# Defensive positions that must be represented by at least one
# eligible player on the Active (ACT) roster to allow a legal lineup.
REQUIRED_POSITIONS: Tuple[str, ...] = ("C", "SS", "CF", "2B", "3B", "1B", "LF", "RF")


@dataclass
class _Buckets:
    hitters: List[object]
    pitchers: List[object]
    injured: List[object]


def _split_players(players: Iterable[object]) -> _Buckets:
    hitters: List[object] = []
    pitchers: List[object] = []
    injured: List[object] = []
    for p in players:
        if getattr(p, "injured", False):
            injured.append(p)
            continue
        if getattr(p, "is_pitcher", False) or getattr(p, "primary_position", "").upper() == "P":
            pitchers.append(p)
        else:
            hitters.append(p)
    return _Buckets(hitters, pitchers, injured)


def _overall_score(p) -> float:
    """Estimate an overall rating in line with the UI.

    Mirrors the logic used by ``ui.player_profile_dialog._estimate_overall_rating``
    so that auto-assignment aligns with what users see as a player's overall.
    """
    is_pitcher = bool(getattr(p, "is_pitcher", False) or str(getattr(p, "primary_position", "")).upper() == "P")
    if is_pitcher:
        keys = [
            "endurance",
            "control",
            "movement",
            "hold_runner",
            "arm",
            "fa",
            "fb",
            "cu",
            "cb",
            "sl",
            "si",
            "scb",
            "kn",
        ]
    else:
        keys = [
            "ch",
            "ph",
            "sp",
            "pl",
            "vl",
            "sc",
            "fa",
            "arm",
            "gf",
        ]
    vals = []
    for k in keys:
        v = getattr(p, k, 0)
        try:
            vals.append(float(v))
        except (TypeError, ValueError):
            vals.append(0.0)
    if not vals:
        return 0.0
    avg = sum(vals) / len(vals)
    # Clamp to 0-99 range for consistency with ratings
    return max(0.0, min(99.0, float(avg)))


def _player_age(player: object) -> int | None:
    birthdate = getattr(player, "birthdate", None)
    if not birthdate:
        return None
    try:
        return calculate_age(str(birthdate))
    except Exception:
        return None


def _age_bonus(age: int | None) -> float:
    if age is None or age >= PROSPECT_AGE_CUTOFF:
        return 0.0
    return float(PROSPECT_AGE_CUTOFF - age) * PROSPECT_BONUS_PER_YEAR


def _active_sort_key(player: object) -> tuple[float, int]:
    age = _player_age(player)
    age_value = age if age is not None else 99
    return (_overall_score(player), -age_value)


def _prospect_sort_key(player: object) -> tuple[float, int]:
    age = _player_age(player)
    age_value = age if age is not None else 99
    return (_overall_score(player) + _age_bonus(age), -age_value)


def _pitcher_score(p) -> float:
    # Preserve a role-aware score for tie-breaks and staff shaping
    endurance = float(getattr(p, "endurance", 0))
    control = float(getattr(p, "control", 0))
    movement = float(getattr(p, "movement", 0))
    hold = float(getattr(p, "hold_runner", 0))
    arm = float(getattr(p, "arm", getattr(p, "fb", 0)))
    role = get_role(p)
    if role == "SP":
        return 0.5 * endurance + 0.25 * control + 0.2 * movement + 0.05 * hold
    return 0.35 * control + 0.35 * movement + 0.2 * endurance + 0.1 * arm


def _eligible_positions(player: object) -> Set[str]:
    """Return defensive positions the hitter can play.

    A player is considered eligible for their ``primary_position`` and any
    entries in ``other_positions``. Values are normalized to uppercase.
    Pitchers are excluded by the caller.
    """

    primary = str(getattr(player, "primary_position", "")).upper()
    others = getattr(player, "other_positions", []) or []
    elig = {primary} if primary else set()
    for pos in others:
        if not pos:
            continue
        elig.add(str(pos).upper())
    return elig


def _pick_active_roster(
    hitters: List[object],
    pitchers: List[object],
) -> Tuple[List[str], List[object], List[object]]:
    """Select a 25-man active roster with legal defensive coverage.

    - Target 12 hitters and 13 pitchers (min 11 hitters)
    - Ensure at least one eligible player for each defensive position in
      ``REQUIRED_POSITIONS`` among the 12 hitters.
    - Prefer best-graded players by role when multiple candidates exist.
    """

    # Sort by overall to align with UI/user expectations; use role-aware
    # pitcher score only for shaping the staff (e.g., guaranteeing SPs)
    hitters_sorted = sorted(hitters, key=_active_sort_key, reverse=True)
    pitchers_sorted = sorted(pitchers, key=_active_sort_key, reverse=True)

    # Build the pitching staff: at least 5 SPs if available, then best remaining
    sps = [p for p in pitchers_sorted if get_role(p) == "SP"]
    active_pitchers: List[object] = []
    active_pitchers.extend(sps[:5])
    remaining_slots = 13 - len(active_pitchers)
    if remaining_slots > 0:
        pool = [p for p in pitchers_sorted if p not in active_pitchers]
        active_pitchers.extend(pool[:remaining_slots])

    # First, guarantee required defensive coverage among the hitters
    active_hitters: List[object] = []
    selected_ids: Set[str] = set()

    # Scarcity-aware order: C/SS/CF are typically the rarest
    for pos in REQUIRED_POSITIONS:
        candidate = None
        for h in hitters_sorted:
            pid = getattr(h, "player_id")
            if pid in selected_ids:
                continue
            elig = _eligible_positions(h)
            if pos in elig:
                candidate = h
                break
        if candidate is not None:
            active_hitters.append(candidate)
            selected_ids.add(getattr(candidate, "player_id"))

    # Fill remaining hitter slots up to 12 with best available
    for h in hitters_sorted:
        if len(active_hitters) >= 12:
            break
        pid = getattr(h, "player_id")
        if pid in selected_ids:
            continue
        active_hitters.append(h)
        selected_ids.add(pid)

    # Ensure at least 11 hitters overall; if short on hitters in org,
    # reduce pitchers to keep ACT at 25 while maximizing hitters.
    while len(active_hitters) < 11 and hitters_sorted:
        # Add next best hitter not already selected; bail if none remain.
        added = False
        for h in hitters_sorted:
            pid = getattr(h, "player_id")
            if pid not in selected_ids:
                active_hitters.append(h)
                selected_ids.add(pid)
                added = True
                break
        if not added:
            break
        # Trim one pitcher if we somehow exceeded 13 earlier (safety)
        if len(active_pitchers) + len(active_hitters) > ACTIVE_MAX and active_pitchers:
            active_pitchers.pop()

    # Top off the 25-man roster if underfilled (shouldn't generally happen)
    total = len(active_hitters) + len(active_pitchers)
    if total < ACTIVE_MAX:
        # Prefer pitchers next to reach 25, but keep at least 11 hitters
        extra_pitchers = [p for p in pitchers_sorted if p not in active_pitchers]
        extra_hitters = [h for h in hitters_sorted if getattr(h, "player_id") not in selected_ids]
        while total < ACTIVE_MAX:
            if len(active_pitchers) < 13 and extra_pitchers:
                active_pitchers.append(extra_pitchers.pop(0))
            elif extra_hitters:
                active_hitters.append(extra_hitters.pop(0))
            elif extra_pitchers:
                active_pitchers.append(extra_pitchers.pop(0))
            else:
                break
            total = len(active_hitters) + len(active_pitchers)

    act_ids = [getattr(p, "player_id") for p in (active_pitchers + active_hitters)]
    rest_hitters = [p for p in hitters_sorted if getattr(p, "player_id") not in act_ids]
    rest_pitchers = [p for p in pitchers_sorted if getattr(p, "player_id") not in act_ids]
    return act_ids, rest_hitters, rest_pitchers


def _pick_minor_rosters(
    hitters: List[object],
    pitchers: List[object],
) -> Tuple[List[str], List[str]]:
    hitters_sorted = sorted(hitters, key=_prospect_sort_key, reverse=True)
    pitchers_sorted = sorted(pitchers, key=_prospect_sort_key, reverse=True)

    total = len(hitters_sorted) + len(pitchers_sorted)
    if total == 0:
        return [], []

    if hitters_sorted and pitchers_sorted:
        ratio = len(pitchers_sorted) / total
        min_pitchers = min(AAA_MIN_PITCHERS, len(pitchers_sorted))
        min_hitters = min(AAA_MIN_HITTERS, len(hitters_sorted))
        target_pitchers = int(round(AAA_MAX * ratio))
        target_pitchers = max(min_pitchers, min(target_pitchers, AAA_MAX - min_hitters))
    elif pitchers_sorted:
        target_pitchers = min(AAA_MAX, len(pitchers_sorted))
    else:
        target_pitchers = 0

    target_pitchers = min(target_pitchers, len(pitchers_sorted))
    target_hitters = min(AAA_MAX - target_pitchers, len(hitters_sorted))

    while target_hitters + target_pitchers < AAA_MAX:
        if len(hitters_sorted) > target_hitters:
            target_hitters += 1
            continue
        if len(pitchers_sorted) > target_pitchers:
            target_pitchers += 1
            continue
        break

    aaa_players = hitters_sorted[:target_hitters] + pitchers_sorted[:target_pitchers]
    aaa_players = sorted(aaa_players, key=_overall_score, reverse=True)
    aaa_ids = [getattr(p, "player_id") for p in aaa_players][:AAA_MAX]

    aaa_set = set(aaa_ids)
    remainder = [p for p in hitters_sorted + pitchers_sorted if getattr(p, "player_id") not in aaa_set]
    remainder = sorted(remainder, key=_overall_score, reverse=True)
    low_ids = [getattr(p, "player_id") for p in remainder][:LOW_MAX]
    return aaa_ids, low_ids


def auto_assign_team(team_id: str, *, players_file: str = "data/players.csv", roster_dir: str = "data/rosters") -> None:
    base = get_base_dir()
    players = {p.player_id: p for p in load_players_from_csv(players_file)}
    roster = load_roster(team_id, roster_dir)

    # Build the pool from current org players (ACT/AAA/LOW); keep DL/IR intact
    pool_ids = roster.act + roster.aaa + roster.low
    pool = [players[pid] for pid in pool_ids if pid in players]
    buckets = _split_players(pool)

    # Choose Active roster
    act_ids, rest_hitters, rest_pitchers = _pick_active_roster(buckets.hitters, buckets.pitchers)

    # Balance minors so AAA isn't stacked with only hitters or pitchers.
    aaa_ids, low_ids = _pick_minor_rosters(rest_hitters, rest_pitchers)

    # Preserve injured players on DL/IR: keep existing DL/IR and move any newly
    # identified injured players from the org pool to DL if they aren't already there.
    injured_ids = {getattr(p, "player_id") for p in buckets.injured}
    # Maintain original ordering but append any new injured
    roster.act = act_ids
    roster.aaa = aaa_ids
    roster.low = low_ids
    merged_dl = list(dict.fromkeys(list(roster.dl) + [pid for pid in pool_ids if pid in injured_ids]))
    roster.dl = merged_dl
    # Default any new assignments to the 15-day DL; UI/workflows can upgrade them later.
    roster.dl_tiers = {pid: roster.dl_tiers.get(pid, "dl15") for pid in merged_dl}
    # Save
    save_roster(team_id, roster)


def auto_assign_all_teams(*, players_file: str = "data/players.csv", roster_dir: str = "data/rosters", teams_file: str = "data/teams.csv") -> None:
    load_roster.cache_clear()
    teams = load_teams(teams_file)
    users = load_users("data/users.txt")
    owned: set[str] = {u.get("team_id", "") for u in users if u.get("role") == "owner" and u.get("team_id")}
    for team in teams:
        try:
            auto_assign_team(team.team_id, players_file=players_file, roster_dir=roster_dir)
            load_roster.cache_clear()
            # For unmanaged teams, auto-generate lineups to keep sims valid
            if team.team_id not in owned:
                auto_fill_lineup_for_team(
                    team.team_id,
                    players_file=players_file,
                    roster_dir=roster_dir,
                    lineup_dir="data/lineups",
                )
        except Exception:
            # Continue with other teams; admin can fix any outliers manually
            continue


__all__ = ["auto_assign_team", "auto_assign_all_teams"]
