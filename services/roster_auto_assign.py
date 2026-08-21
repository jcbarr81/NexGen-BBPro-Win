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
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Set, Tuple

from playbalance.aging import calculate_age, get_sim_date
from services.roster_validation import LOW_LEVEL_MAX_AGE
from services.team_strategy_profiles import resolve_team_strategy_profile
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


def _age_on_date(birthdate: str, as_of_date: date) -> int | None:
    value = str(birthdate or "").strip()
    if not value:
        return None
    candidate = value.split("T", 1)[0]
    try:
        born = date.fromisoformat(candidate)
    except ValueError:
        return None
    return as_of_date.year - born.year - (
        (as_of_date.month, as_of_date.day) < (born.month, born.day)
    )


def _player_age(
    player: object,
    *,
    as_of_date: date | None = None,
    age_cache: Dict[str, int | None] | None = None,
) -> int | None:
    birthdate = getattr(player, "birthdate", None)
    if not birthdate:
        return None
    birthdate_key = str(birthdate)
    if age_cache is not None and birthdate_key in age_cache:
        return age_cache[birthdate_key]
    age_value: int | None = None
    try:
        if as_of_date is not None:
            age_value = _age_on_date(birthdate_key, as_of_date)
        if age_value is None:
            age_value = calculate_age(birthdate_key, as_of=as_of_date)
    except Exception:
        age_value = None
    if age_cache is not None:
        age_cache[birthdate_key] = age_value
    return age_value


def _age_bonus(age: int | None) -> float:
    if age is None or age >= PROSPECT_AGE_CUTOFF:
        return 0.0
    return float(PROSPECT_AGE_CUTOFF - age) * PROSPECT_BONUS_PER_YEAR


def _active_sort_key(
    player: object,
    *,
    as_of_date: date | None = None,
    age_cache: Dict[str, int | None] | None = None,
    strategy_profile: str = "balanced",
) -> tuple[float, int]:
    age = _player_age(player, as_of_date=as_of_date, age_cache=age_cache)
    age_value = age if age is not None else 99
    score = _overall_score(player) + _strategy_assignment_bonus(
        player,
        strategy_profile=strategy_profile,
        age=age,
        prospect_mode=False,
    )
    return (score, -age_value)


def _prospect_sort_key(
    player: object,
    *,
    as_of_date: date | None = None,
    age_cache: Dict[str, int | None] | None = None,
    strategy_profile: str = "balanced",
) -> tuple[float, int]:
    age = _player_age(player, as_of_date=as_of_date, age_cache=age_cache)
    age_value = age if age is not None else 99
    prospect_bonus = _age_bonus(age)
    if strategy_profile == "development_focus":
        prospect_bonus *= 1.70
    elif strategy_profile == "win_now":
        prospect_bonus *= 0.65
    score = (
        _overall_score(player)
        + prospect_bonus
        + _strategy_assignment_bonus(
            player,
            strategy_profile=strategy_profile,
            age=age,
            prospect_mode=True,
        )
    )
    return (score, -age_value)


def _norm_rating(value: object) -> float:
    try:
        numeric = float(value)
    except Exception:
        return 0.0
    return max(0.0, min(99.0, numeric)) / 99.0


def _strategy_assignment_bonus(
    player: object,
    *,
    strategy_profile: str,
    age: int | None,
    prospect_mode: bool,
) -> float:
    profile = str(strategy_profile or "balanced").strip().lower()
    if profile == "balanced":
        return 0.0

    is_pitcher = bool(
        getattr(player, "is_pitcher", False)
        or str(getattr(player, "primary_position", "")).upper() == "P"
    )
    if is_pitcher:
        control = _norm_rating(getattr(player, "control", 0))
        movement = _norm_rating(getattr(player, "movement", 0))
        endurance = _norm_rating(getattr(player, "endurance", 0))
        hold = _norm_rating(getattr(player, "hold_runner", 0))
        arm = _norm_rating(getattr(player, "arm", getattr(player, "fb", 0)))
        if profile == "win_now":
            bonus = (2.2 * control) + (2.0 * movement) + (1.7 * endurance)
            if isinstance(age, int) and age <= 23:
                bonus -= 0.4
            return bonus
        if profile == "development_focus":
            bonus = (1.2 * arm) + (1.1 * control) + (0.8 * endurance)
            if isinstance(age, int) and age < 28:
                bonus += max(0, 28 - age) * 0.28
            if prospect_mode:
                bonus += 0.6
            return bonus
        if profile == "defense_first":
            return (2.8 * control) + (2.4 * movement) + (1.5 * hold)
        if profile == "power_offense":
            return (1.8 * arm) + (1.4 * endurance) - (0.5 * hold)
        return 0.0

    ch = _norm_rating(getattr(player, "ch", 0))
    ph = _norm_rating(getattr(player, "ph", 0))
    sp = _norm_rating(getattr(player, "sp", 0))
    fa = _norm_rating(getattr(player, "fa", 0))
    arm = _norm_rating(getattr(player, "arm", 0))
    gf = _norm_rating(getattr(player, "gf", 0))
    if profile == "win_now":
        bonus = (2.3 * ch) + (2.7 * ph) + (0.8 * sp) - (0.6 * fa)
        if isinstance(age, int) and age <= 23:
            bonus -= 0.5
        return bonus
    if profile == "development_focus":
        bonus = (1.1 * sp) + (0.9 * fa) + (0.9 * ch)
        if isinstance(age, int) and age < 28:
            bonus += max(0, 28 - age) * 0.32
        if prospect_mode:
            bonus += 0.6
        return bonus
    if profile == "defense_first":
        return (2.8 * fa) + (1.8 * arm) + (1.8 * gf) - (0.5 * ph)
    if profile == "power_offense":
        return (3.1 * ph) + (1.1 * ch) + (0.6 * sp) - (0.6 * fa)
    return 0.0


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
    *,
    as_of_date: date | None = None,
    age_cache: Dict[str, int | None] | None = None,
    strategy_profile: str = "balanced",
) -> Tuple[List[str], List[object], List[object]]:
    """Select a 25-man active roster with legal defensive coverage.

    - Target 12 hitters and 13 pitchers (min 11 hitters)
    - Ensure at least one eligible player for each defensive position in
      ``REQUIRED_POSITIONS`` among the 12 hitters.
    - Prefer best-graded players by role when multiple candidates exist.
    """

    # Sort by overall to align with UI/user expectations; use role-aware
    # pitcher score only for shaping the staff (e.g., guaranteeing SPs)
    hitters_sorted = sorted(
        hitters,
        key=lambda player: _active_sort_key(
            player,
            as_of_date=as_of_date,
            age_cache=age_cache,
            strategy_profile=strategy_profile,
        ),
        reverse=True,
    )
    pitchers_sorted = sorted(
        pitchers,
        key=lambda player: _active_sort_key(
            player,
            as_of_date=as_of_date,
            age_cache=age_cache,
            strategy_profile=strategy_profile,
        ),
        reverse=True,
    )

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
    *,
    as_of_date: date | None = None,
    age_cache: Dict[str, int | None] | None = None,
    strategy_profile: str = "balanced",
) -> Tuple[List[str], List[str]]:
    hitters_sorted = sorted(
        hitters,
        key=lambda player: _prospect_sort_key(
            player,
            as_of_date=as_of_date,
            age_cache=age_cache,
            strategy_profile=strategy_profile,
        ),
        reverse=True,
    )
    pitchers_sorted = sorted(
        pitchers,
        key=lambda player: _prospect_sort_key(
            player,
            as_of_date=as_of_date,
            age_cache=age_cache,
            strategy_profile=strategy_profile,
        ),
        reverse=True,
    )

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
    aaa_set = {getattr(p, "player_id") for p in aaa_players}
    remainder = [
        p
        for p in hitters_sorted + pitchers_sorted
        if getattr(p, "player_id") not in aaa_set
    ]

    # League rule: the LOW roster is reserved for young players (under the
    # LOW age limit). Without this, auto-assign happily parks aging veterans
    # at LOW, producing a roster that fails validation and blocks the season
    # sim. Unknown ages are treated as eligible so missing birthdates never
    # trigger a release.
    #
    # Critically, age here is computed against the *real* calendar date — the
    # same basis services.roster_validation / the season-sim gate use (via
    # validation.load_players_map). Don't use the sim-date-aware _player_age:
    # if the two bases disagree at the boundary, auto-assign could seat a
    # player at LOW that the validator then rejects, re-blocking the sim.
    today = date.today()

    def _low_eligible(player: object) -> bool:
        birthdate = getattr(player, "birthdate", None)
        age = _age_on_date(str(birthdate), today) if birthdate else None
        return age is None or age < LOW_LEVEL_MAX_AGE

    # Any over-age player that landed in the LOW remainder has no legal minor
    # slot left. Rather than release them, promote them into AAA (where there
    # is no age limit) by bumping AAA's weakest LOW-eligible player down to
    # LOW. This keeps everyone on the roster and legal in the common case;
    # over-age players are only released when AAA genuinely can't seat them.
    over_age_remainder = [p for p in remainder if not _low_eligible(p)]
    if over_age_remainder:
        swappable = sorted(
            (p for p in aaa_players if _low_eligible(p)),
            key=_overall_score,
        )  # weakest first
        bumped_ids: Set[str] = set()
        bumped_players: List[object] = []
        promoted_ids: Set[str] = set()
        for vet in sorted(over_age_remainder, key=_overall_score, reverse=True):
            if not swappable:
                break  # no AAA slot can be freed — this vet will be released
            bumped = swappable.pop(0)
            bumped_ids.add(getattr(bumped, "player_id"))
            bumped_players.append(bumped)
            promoted_ids.add(getattr(vet, "player_id"))
        if promoted_ids:
            promoted = [
                p for p in over_age_remainder if getattr(p, "player_id") in promoted_ids
            ]
            aaa_players = [
                p for p in aaa_players if getattr(p, "player_id") not in bumped_ids
            ] + promoted
            remainder = [
                p for p in remainder if getattr(p, "player_id") not in promoted_ids
            ] + bumped_players

    aaa_players = sorted(aaa_players, key=_overall_score, reverse=True)
    aaa_ids = [getattr(p, "player_id") for p in aaa_players][:AAA_MAX]

    aaa_set = set(aaa_ids)
    low_candidates = [
        p
        for p in remainder
        if getattr(p, "player_id") not in aaa_set and _low_eligible(p)
    ]
    low_candidates = sorted(low_candidates, key=_overall_score, reverse=True)
    low_ids = [getattr(p, "player_id") for p in low_candidates][:LOW_MAX]
    return aaa_ids, low_ids


def auto_assign_team(
    team_id: str,
    *,
    players_file: str = "data/players.csv",
    roster_dir: str = "data/rosters",
    players_by_id: Dict[str, object] | None = None,
    as_of_date: date | None = None,
    age_cache: Dict[str, int | None] | None = None,
    strategy_profile: str | None = None,
) -> Dict[str, List[str]]:
    """Re-balance ACT / AAA / LOW for *team_id*.

    Returns a dict describing the result. ``released`` lists every player
    that didn't fit any roster level after the rebalance and was released
    to free agency. The release path goes through
    :func:`services.transaction_log.record_transaction` so the cut shows
    up on the Transactions page, and through
    :func:`services.contracts_service.release_contracts_to_free_agency`
    so payroll stays consistent. Without this the post-draft case
    (14-in-LOW after a 4-round draft) silently dropped the overflow off
    the roster and out of the transaction log.
    """

    players = players_by_id
    if players is None:
        players = {p.player_id: p for p in load_players_from_csv(players_file)}
    roster = load_roster(team_id, roster_dir)

    # Build the pool from current org players (ACT/AAA/LOW); keep DL/IR intact
    pool_ids = roster.act + roster.aaa + roster.low
    # Remember each pool player's pre-assign level for the transaction log
    # entries we generate below.
    pre_levels: Dict[str, str] = {}
    for level in ("act", "aaa", "low"):
        for pid in getattr(roster, level, []) or []:
            pre_levels.setdefault(pid, level.upper())
    pool = [players[pid] for pid in pool_ids if pid in players]
    buckets = _split_players(pool)
    profile = _resolve_strategy_profile_token(
        team_id,
        explicit=strategy_profile,
        players_file=players_file,
    )

    # Choose Active roster
    act_ids, rest_hitters, rest_pitchers = _pick_active_roster(
        buckets.hitters,
        buckets.pitchers,
        as_of_date=as_of_date,
        age_cache=age_cache,
        strategy_profile=profile,
    )

    # Balance minors so AAA isn't stacked with only hitters or pitchers.
    aaa_ids, low_ids = _pick_minor_rosters(
        rest_hitters,
        rest_pitchers,
        as_of_date=as_of_date,
        age_cache=age_cache,
        strategy_profile=profile,
    )

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

    # Identify any player who was in the org pool (ACT/AAA/LOW pre-assign)
    # but didn't land on ACT / AAA / LOW / DL / IR after the rebalance.
    # _pick_minor_rosters truncates LOW at LOW_MAX, so after a 4-round
    # draft a 14-player LOW gets clipped to 10 and the bottom four
    # otherwise vanish without a trace.
    assigned: Set[str] = set()
    assigned.update(act_ids)
    assigned.update(aaa_ids)
    assigned.update(low_ids)
    assigned.update(merged_dl)
    assigned.update(roster.ir)
    released = [pid for pid in pool_ids if pid not in assigned]

    # Coverage guard: never release the LAST eligible player for a required
    # defensive position. The active-roster picker guarantees coverage among the
    # hitters it sees, but a position player mis-flagged as a pitcher (or an
    # over-cap release) could still leave the org unable to field a spot (e.g.
    # no 2B). If a required position has nobody assigned but an eligible player
    # is about to be released, rescue the best such player into LOW.
    if released:
        pool_by_id = {
            getattr(p, "player_id"): p
            for p in list(buckets.hitters) + list(buckets.pitchers)
        }

        def _has_assigned_eligible(pos: str) -> bool:
            return any(
                pid in pool_by_id and pos in _eligible_positions(pool_by_id[pid])
                for pid in assigned
            )

        for pos in REQUIRED_POSITIONS:
            if _has_assigned_eligible(pos):
                continue
            candidates = [
                pool_by_id[pid]
                for pid in released
                if pid in pool_by_id and pos in _eligible_positions(pool_by_id[pid])
            ]
            if not candidates:
                continue  # genuinely nobody in the org can play here
            rescue_id = getattr(max(candidates, key=_overall_score), "player_id")
            released.remove(rescue_id)
            roster.low.append(rescue_id)
            assigned.add(rescue_id)

    save_roster(team_id, roster)

    if released:
        try:
            from services.transaction_log import record_transaction

            for pid in released:
                try:
                    record_transaction(
                        action="cut",
                        team_id=team_id,
                        player_id=pid,
                        from_level=pre_levels.get(pid, "?"),
                        to_level="FA",
                        details="Released by Auto-assign (over roster cap)",
                    )
                except Exception:
                    continue
        except Exception:
            pass
        try:
            from services.contracts_service import release_contracts_to_free_agency

            release_contracts_to_free_agency(released)
        except Exception:
            pass

    return {"released": released}


def auto_assign_all_teams(
    *,
    players_file: str = "data/players.csv",
    roster_dir: str = "data/rosters",
    teams_file: str = "data/teams.csv",
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> None:
    def _report_progress(phase: str, done: int, total: int) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(str(phase), int(done), int(total))
        except Exception:
            pass

    load_roster.cache_clear()
    teams = load_teams(teams_file)
    total_teams = len(teams)
    _report_progress("Loading", 0, total_teams)
    players_by_id = {p.player_id: p for p in load_players_from_csv(players_file)}
    as_of_date = get_sim_date() or date.today()
    age_cache: Dict[str, int | None] = {}
    users = load_users("data/users.txt")
    owned: set[str] = {u.get("team_id", "") for u in users if u.get("role") == "owner" and u.get("team_id")}
    for index, team in enumerate(teams, start=1):
        _report_progress("Processing", index - 1, total_teams)
        try:
            team_profile = _resolve_strategy_profile_token(
                team.team_id,
                explicit=None,
                players_file=players_file,
            )
            auto_assign_team(
                team.team_id,
                players_file=players_file,
                roster_dir=roster_dir,
                players_by_id=players_by_id,
                as_of_date=as_of_date,
                age_cache=age_cache,
                strategy_profile=team_profile,
            )
            load_roster.cache_clear()
            # For unmanaged teams, auto-generate lineups to keep sims valid
            if team.team_id not in owned:
                auto_fill_lineup_for_team(
                    team.team_id,
                    players_file=players_file,
                    roster_dir=roster_dir,
                    lineup_dir="data/lineups",
                    strategy_profile=team_profile,
                )
        except Exception:
            # Continue with other teams; admin can fix any outliers manually
            continue
        _report_progress("Saving", index, total_teams)
    _report_progress("Complete", total_teams, total_teams)


def _resolve_strategy_profile_token(
    team_id: str,
    *,
    explicit: str | None,
    players_file: str | None = None,
) -> str:
    token = str(explicit or "").strip().lower()
    if token:
        return token
    data_dir = None
    if players_file:
        try:
            path = Path(players_file)
            if path.name.lower() == "players.csv":
                data_dir = path.parent
        except Exception:
            data_dir = None
    try:
        resolved = resolve_team_strategy_profile(team_id, data_dir=data_dir)
        return str(resolved.profile or "balanced")
    except Exception:
        return "balanced"


__all__ = ["auto_assign_team", "auto_assign_all_teams"]
