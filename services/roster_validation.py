"""Shared roster / lineup / pitching / depth-chart / trade validators.

Centralises the validation rules that were scattered across PyQt dialog
code (ui/lineup_editor.py, ui/pitching_editor.py, ui/depth_chart_dialog.py,
ui/reassign_players_dialog.py, ui/trade_dialog.py). Both the Electron
sidecar and the PyQt app should call these so behaviour stays consistent.

Every public validator returns a ``ValidationResult`` with ``ok``, plus
two lists of human-readable messages:

- ``errors``   — blocking problems; callers should refuse to save.
- ``warnings`` — cosmetic or advisory; callers can save anyway but
                 should surface to the operator.

The module is intentionally dependency-free at import time (no PyQt, no
pydantic, no FastAPI) so any caller can pull it in cheaply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Mapping, Sequence, Set

from utils.roster_rules import (
    BASE_LEVEL_CAPS,
    MAX_ACTIVE_PITCHERS,
    counts_as_pitcher,
)
from utils.staff_roles import (
    OPTIONAL_PITCHING_ROLES,
    REQUIRED_PITCHING_ROLES,
    STAFF_ROLES,
)

# ---------------------------------------------------------------------------
# Constants

ALL_POSITIONS: Sequence[str] = (
    "C",
    "1B",
    "2B",
    "3B",
    "SS",
    "LF",
    "CF",
    "RF",
    "DH",
)

REQUIRED_DEF_POSITIONS: Sequence[str] = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")

# The 11 required staff slots, plus MR4/MR5 as optional homes for the 12th
# and 13th active arms (Release 3, owner decision Q7). One source of truth in
# utils.staff_roles; existing staff files are never migrated to the new slots.
PITCHING_ROLES: Sequence[str] = REQUIRED_PITCHING_ROLES
OPTIONAL_STAFF_ROLES: Sequence[str] = OPTIONAL_PITCHING_ROLES
ALL_STAFF_ROLES: Sequence[str] = STAFF_ROLES

STARTER_ROLES: Set[str] = {"SP1", "SP2", "SP3", "SP4", "SP5"}
CLOSER_ROLES: Set[str] = {"CL", "SU"}

# 26 / 15 / 10 (utils.roster_rules; owner decision 8). September and the
# pitcher limit come from utils.roster_loader.effective_level_caps /
# active_pitcher_cap at the call site.
DEFAULT_LEVEL_CAPS = dict(BASE_LEVEL_CAPS)
DEFAULT_PITCHER_CAP = MAX_ACTIVE_PITCHERS

MIN_POSITION_PLAYERS_ACT = 11
MIN_DEPTH_PRIMARY = 1  # at least one entry per defensive position
MAX_DEPTH_PER_POSITION = 3
LOW_LEVEL_MAX_AGE = 27

# ---------------------------------------------------------------------------
# Result type


@dataclass
class ValidationResult:
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)
        self.ok = False

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        if not other.ok:
            self.ok = False
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": list(self.errors), "warnings": list(self.warnings)}


# ---------------------------------------------------------------------------
# Helpers


def _player_positions(player: Mapping[str, Any]) -> Set[str]:
    """Return the set of positions a player can play, excluding 'P'."""

    primary = str(player.get("primary_position", "") or "").upper()
    raw_others = player.get("other_positions", "")
    if isinstance(raw_others, str):
        others = [tok.strip().upper() for tok in raw_others.replace(",", "/").split("/") if tok.strip()]
    elif isinstance(raw_others, Iterable):
        others = [str(tok).strip().upper() for tok in raw_others if str(tok).strip()]
    else:
        others = []
    positions: Set[str] = set()
    if primary:
        positions.add(primary)
    positions.update(others)
    positions.discard("P")
    return positions


def _is_pitcher(player: Mapping[str, Any]) -> bool:
    flag = player.get("is_pitcher")
    if isinstance(flag, bool):
        return flag
    if flag is None:
        return False
    return str(flag).strip().lower() in {"1", "true", "yes", "t", "y"}


def _resolve_caps(
    level_caps: Mapping[str, int] | None,
    pitcher_cap: int | None,
) -> tuple[dict[str, int], int]:
    """Merge ``level_caps`` over the defaults and settle the pitcher cap.

    Returns ``(level caps, pitcher cap)``. The level caps hold roster levels
    only. A caller may pass the pitcher cap either as ``pitcher_cap`` or as
    an ``"act_pitchers"`` key inside ``level_caps`` (the compliance payload's
    shape); the explicit argument wins.
    """

    caps = {**DEFAULT_LEVEL_CAPS, **(level_caps or {})}
    embedded = caps.pop("act_pitchers", None)
    if pitcher_cap is None:
        pitcher_cap = embedded if embedded is not None else DEFAULT_PITCHER_CAP
    return caps, int(pitcher_cap)


def _active_pitcher_count(
    act_ids: Iterable[str], players: Mapping[str, Mapping[str, Any]]
) -> int:
    """Count the active pitchers (``counts_as_pitcher``; ids not in
    ``players`` cannot be classified and are skipped). Injured-but-active
    pitchers count, as in MLB."""

    return sum(1 for pid in act_ids if pid in players and counts_as_pitcher(players[pid]))


def _player_label(player: Mapping[str, Any], fallback_id: str) -> str:
    first = str(player.get("first_name", "") or "").strip()
    last = str(player.get("last_name", "") or "").strip()
    name = f"{first} {last}".strip()
    return name or fallback_id


# ---------------------------------------------------------------------------
# 1. Lineup validation


def validate_lineup(
    *,
    lineup_rows: Sequence[Mapping[str, Any]],
    players: Mapping[str, Mapping[str, Any]],
    vs: str | None = None,
) -> ValidationResult:
    """Validate a 9-slot batting lineup.

    Rules (ported from ui/lineup_editor.py):
    - Exactly 9 filled slots, each with a player_id + position.
    - No duplicate players across slots.
    - Every defensive position (C/1B/2B/3B/SS/LF/CF/RF/DH) covered once.
    - Each player eligible for their assigned position (primary or
      other_positions). DH is universal.
    - Pitchers cannot occupy the DH slot (nor any batting slot).
    """

    result = ValidationResult()
    filled = [row for row in lineup_rows if row.get("player_id") and row.get("position")]

    if len(lineup_rows) != 9:
        result.error(f"Lineup must have 9 slots, got {len(lineup_rows)}.")

    if len(filled) != 9:
        result.error(f"All 9 batting slots must be filled (found {len(filled)} with a player + position).")

    # Duplicate-player check.
    seen_players: Set[str] = set()
    for idx, row in enumerate(filled, start=1):
        pid = str(row.get("player_id", ""))
        if pid in seen_players:
            player = players.get(pid, {})
            result.error(
                f"Slot {idx}: {_player_label(player, pid)} is listed more than once."
            )
        seen_players.add(pid)

    # Position-coverage check: every required slot filled exactly once.
    pos_counts: dict[str, int] = {}
    for idx, row in enumerate(filled, start=1):
        pos = str(row.get("position", "")).upper()
        pos_counts[pos] = pos_counts.get(pos, 0) + 1
    for required in ALL_POSITIONS:
        count = pos_counts.get(required, 0)
        if count == 0:
            result.error(f"Position {required} is not covered by any batter.")
        elif count > 1:
            result.error(f"Position {required} appears {count} times; each position must be used once.")

    # Eligibility + pitcher-as-batter checks.
    for idx, row in enumerate(filled, start=1):
        pid = str(row.get("player_id", ""))
        pos = str(row.get("position", "")).upper()
        player = players.get(pid)
        if not player:
            result.error(f"Slot {idx}: player {pid} not found on this team.")
            continue
        if _is_pitcher(player):
            result.error(
                f"Slot {idx}: {_player_label(player, pid)} is a pitcher and cannot bat (DH included)."
            )
            continue
        if pos == "DH":
            # DH is universal for hitters.
            continue
        eligible = _player_positions(player)
        if pos not in eligible:
            result.warn(
                f"Slot {idx}: {_player_label(player, pid)} is not listed at {pos} "
                f"(eligible: {', '.join(sorted(eligible)) or 'none'})."
            )

    if vs and vs.lower() not in {"lhp", "rhp"}:
        result.error(f"Unknown matchup orientation '{vs}' (expected 'lhp' or 'rhp').")

    return result


# ---------------------------------------------------------------------------
# 2. Pitching staff validation


def validate_pitching_staff(
    *,
    staff: Sequence[Mapping[str, Any]],
    players: Mapping[str, Mapping[str, Any]],
    active_ids: Sequence[str] | None = None,
) -> ValidationResult:
    """Validate the pitching-staff role map.

    Rules (ported from ui/pitching_editor.py):
    - Every one of the 11 required roles (SP1..SP5, LR, MR1..MR3, SU, CL) is
      filled. MR4 and MR5 are optional slots for the 12th and 13th arms.
    - No pitcher occupies more than one role.
    - Every assigned pitcher is on the active roster (if active_ids given).
    - Non-pitchers cannot hold pitching roles.
    - Warn when an SP-role has a non-starter (no SP rating) or CL has no
      closer rating.
    - Warn, without blocking the save, on a label that is not a staff slot
      (a legacy "MR" row) or a slot listed twice (an older file's two SU
      rows): the sim pitches those arms as relievers either way.
    """

    result = ValidationResult()
    active_set: Set[str] | None = set(active_ids) if active_ids is not None else None
    known_roles = set(ALL_STAFF_ROLES)

    entries: list[tuple[str, str]] = []
    for entry in staff:
        role = str(entry.get("role", "") or "").strip().upper()
        pid = str(entry.get("player_id", "") or "").strip()
        if not role:
            continue
        entries.append((role, pid))

    filled_roles = {role for role, pid in entries if pid}
    # Staff files written before 7.46.0 carry plain "MR" rows and a second
    # "SU" instead of MR1-MR3. Those arms pitch as middle relievers either
    # way, so let such spare relief rows stand in for empty MR slots (they
    # still get the warning below) rather than flag every older league.
    filled_counts: dict[str, int] = {}
    for role, pid in entries:
        if pid:
            filled_counts[role] = filled_counts.get(role, 0) + 1
    spare_relief = sum(
        count if role not in known_roles else count - 1
        for role, count in filled_counts.items()
        if role not in STARTER_ROLES and (role not in known_roles or count > 1)
    )
    for role in PITCHING_ROLES:
        if role not in filled_roles:
            if role.startswith("MR") and spare_relief > 0:
                spare_relief -= 1
                continue
            result.error(f"Role {role} is not assigned.")

    role_counts: dict[str, int] = {}
    for role, pid in entries:
        if pid:
            role_counts[role] = role_counts.get(role, 0) + 1
    for role, count in role_counts.items():
        if role not in known_roles:
            result.warn(
                f"{role} is not a staff slot; that pitcher works as a middle "
                "reliever. Pick a slot (MR1-MR5) to keep the staff tidy."
            )
        elif count > 1:
            result.warn(f"Role {role} is listed {count} times.")

    # Duplicate pitcher check.
    seen: dict[str, str] = {}
    for role, pid in entries:
        if not pid:
            continue
        if pid in seen:
            player = players.get(pid, {})
            result.error(
                f"{_player_label(player, pid)} is assigned to both {seen[pid]} and {role}."
            )
        else:
            seen[pid] = role

    # Per-pitcher checks, once per pitcher.
    for pid, role in seen.items():
        player = players.get(pid)
        if not player:
            result.error(f"{role}: player {pid} not found.")
            continue
        if not _is_pitcher(player):
            result.error(
                f"{role}: {_player_label(player, pid)} is not a pitcher."
            )
            continue
        if active_set is not None and pid not in active_set:
            result.error(
                f"{role}: {_player_label(player, pid)} is not on the active roster."
            )

        role_rating = _role_rating(player, role)
        if role in STARTER_ROLES and role_rating is not None and role_rating < 40:
            result.warn(
                f"{role}: {_player_label(player, pid)} has a low starter rating ({role_rating})."
            )
        if role == "CL" and role_rating is not None and role_rating < 40:
            result.warn(
                f"CL: {_player_label(player, pid)} has a low closer rating ({role_rating})."
            )

    return result


def _role_rating(player: Mapping[str, Any], role: str) -> int | None:
    """Best-effort role rating lookup. Returns None when not present."""

    ratings = player.get("ratings")
    if isinstance(ratings, Mapping):
        for key in (role.lower(), role):
            if key in ratings:
                try:
                    return int(ratings[key])
                except (TypeError, ValueError):
                    return None
    return None


# ---------------------------------------------------------------------------
# 3. Depth-chart validation


def validate_depth_chart(
    *,
    chart: Mapping[str, Sequence[str]],
    players: Mapping[str, Mapping[str, Any]],
    roster_ids: Iterable[str] | None = None,
) -> ValidationResult:
    """Validate an ordered depth chart.

    Rules (ported from ui/depth_chart_dialog.py):
    - At most 3 entries per position slot.
    - No duplicate player within the same position list.
    - Every player listed can actually play that position (primary or
      other_positions). DH accepts any non-pitcher.
    - Pitchers cannot appear in position-player slots.
    - If ``roster_ids`` provided, every listed player must exist in that
      set.
    - Warn when a defensive position has zero depth.
    """

    result = ValidationResult()
    roster_set: Set[str] | None = set(roster_ids) if roster_ids is not None else None

    for pos in REQUIRED_DEF_POSITIONS:
        entries = list(chart.get(pos, []) or [])
        if len(entries) == 0:
            result.warn(f"No depth listed for {pos}.")
        if len(entries) > MAX_DEPTH_PER_POSITION:
            result.error(
                f"{pos} has {len(entries)} entries; maximum {MAX_DEPTH_PER_POSITION} allowed."
            )

    for pos, entries in chart.items():
        pos_u = str(pos).upper()
        seen: Set[str] = set()
        for rank, pid in enumerate(entries or [], start=1):
            if not pid:
                continue
            if pid in seen:
                player = players.get(pid, {})
                result.error(
                    f"{pos_u}: {_player_label(player, pid)} listed more than once."
                )
            seen.add(pid)

            player = players.get(pid)
            if not player:
                result.error(f"{pos_u} #{rank}: player {pid} not found.")
                continue
            if roster_set is not None and pid not in roster_set:
                result.error(
                    f"{pos_u} #{rank}: {_player_label(player, pid)} is not on this team's roster."
                )
            if _is_pitcher(player):
                result.error(
                    f"{pos_u} #{rank}: {_player_label(player, pid)} is a pitcher."
                )
                continue
            if pos_u == "DH":
                continue
            eligible = _player_positions(player)
            if pos_u not in eligible:
                result.warn(
                    f"{pos_u} #{rank}: {_player_label(player, pid)} is not listed at {pos_u} "
                    f"(eligible: {', '.join(sorted(eligible)) or 'none'})."
                )

    return result


# ---------------------------------------------------------------------------
# 4. Roster-move validation


def validate_roster_move(
    *,
    current_levels: Mapping[str, Sequence[str]],
    player_id: str,
    target_level: str,
    players: Mapping[str, Mapping[str, Any]],
    level_caps: Mapping[str, int] | None = None,
    pitcher_cap: int | None = None,
) -> ValidationResult:
    """Validate a single player move between roster levels.

    Rules (ported from ui/reassign_players_dialog.py):
    - target_level must be one of act / aaa / low / dl / ir.
    - Level caps on act/aaa/low (defaults 26/15/10) — a warning.
    - LOW level: players 27+ cannot be demoted there (an error).
    - Active pitchers above ``pitcher_cap`` (default 13) — a warning.
    - Active roster should carry at least ``MIN_POSITION_PLAYERS_ACT``
      non-pitchers and cover all 8 defensive positions — warnings.

    Everything about the active roster's shape is a warning here so an owner
    can promote first and demote next; the sim gate
    (:func:`validate_roster_state`) is where those become errors.
    """

    result = ValidationResult()
    caps, max_pitchers = _resolve_caps(level_caps, pitcher_cap)

    target = target_level.lower()
    if target not in {"act", "aaa", "low", "dl", "ir"}:
        result.error(f"Unknown target level '{target_level}'.")
        return result

    # Simulate the move against a fresh copy of the level map.
    post = {k.lower(): [pid for pid in v if pid != player_id] for k, v in current_levels.items()}
    post.setdefault(target, [])
    if player_id not in post[target]:
        post[target].append(player_id)

    # Level caps: a WARNING, not a hard block. An owner must be able to promote
    # into a full level intending to demote someone next (or bench-manage over a
    # move or two). The season/sim gate (validate_roster_state) still HARD-errors
    # on an over-cap roster, so games can never start while it's illegal.
    if target in caps and len(post[target]) > caps[target]:
        result.warn(
            f"{target.upper()} is over the {caps[target]}-man cap "
            f"({len(post[target])}/{caps[target]}) — send a player down before the next game."
        )

    player = players.get(player_id)
    if not player:
        result.error(f"Player {player_id} not found.")
        return result

    # LOW age gate.
    if target == "low":
        age = player.get("age")
        try:
            age_int = int(age) if age is not None else None
        except (TypeError, ValueError):
            age_int = None
        if age_int is not None and age_int >= LOW_LEVEL_MAX_AGE:
            result.error(
                f"{_player_label(player, player_id)} (age {age_int}) cannot be assigned to LOW "
                f"(age limit: {LOW_LEVEL_MAX_AGE - 1})."
            )

    # Active-roster composition after the move — a WARNING, not a hard block.
    # Like the cap, this must not stop an owner mid-edit: a move that doesn't
    # even touch ACT (e.g. AAA<->LOW) shouldn't be rejected just because ACT is
    # temporarily short a position or a defensive slot. The season/sim gate
    # (validate_roster_state) still HARD-errors on this, so a game can never
    # start while the active roster is illegal.
    act_ids = post.get("act", [])
    act_players = [players[pid] for pid in act_ids if pid in players]
    non_pitchers = [p for p in act_players if not counts_as_pitcher(p)]
    if len(non_pitchers) < MIN_POSITION_PLAYERS_ACT:
        result.warn(
            f"Active roster would have {len(non_pitchers)} position players "
            f"(minimum {MIN_POSITION_PLAYERS_ACT}) — fix before the next game."
        )

    # Pitcher limit (owner decision 8): a warning on a single move, so the
    # owner can call a pitcher up and option another next.
    n_pitchers = _active_pitcher_count(act_ids, players)
    if n_pitchers > max_pitchers:
        result.warn(
            f"ACT would carry {n_pitchers} pitchers (max {max_pitchers}) — "
            "send a pitcher down before the next game."
        )

    covered: Set[str] = set()
    for p in non_pitchers:
        covered |= _player_positions(p)
    missing = [pos for pos in REQUIRED_DEF_POSITIONS if pos not in covered]
    if missing:
        result.warn(
            f"Active roster would not cover these positions after the move: "
            f"{', '.join(missing)} — fix before the next game."
        )

    return result


def validate_roster_swap(
    *,
    current_levels: Mapping[str, Sequence[str]],
    player_a_id: str,
    player_b_id: str,
    players: Mapping[str, Mapping[str, Any]],
    level_caps: Mapping[str, int] | None = None,
    pitcher_cap: int | None = None,
) -> ValidationResult:
    """Validate swapping the roster LEVELS of two players (A<->B) atomically.

    A swap exchanges the levels of two players in one operation, so each
    affected level's headcount is unchanged — which is exactly what lets a
    promote into a *full* level succeed (the exchange partner goes the other
    way). Same rules as :func:`validate_roster_move`, evaluated on the FINAL
    post-swap state as errors: level caps, LOW age gate for whoever lands in
    LOW, ACT composition (min position players + defensive coverage) and the
    active pitcher limit.

    Callers pass the caps in force on the sim date (``effective_level_caps``
    / ``active_pitcher_cap``); the defaults are the base 26 / 13.
    """
    result = ValidationResult()
    caps, max_pitchers = _resolve_caps(level_caps, pitcher_cap)

    if player_a_id == player_b_id:
        result.error("Pick two different players to swap.")
        return result
    pa = players.get(player_a_id)
    pb = players.get(player_b_id)
    if not pa:
        result.error(f"Player {player_a_id} not found.")
        return result
    if not pb:
        result.error(f"Player {player_b_id} not found.")
        return result

    norm = {k.lower(): list(v) for k, v in current_levels.items()}

    def _level_of(pid: str) -> str | None:
        for lvl, ids in norm.items():
            if pid in ids:
                return lvl
        return None

    la = _level_of(player_a_id)
    lb = _level_of(player_b_id)
    if la is None:
        result.error(f"{_player_label(pa, player_a_id)} is not on the roster.")
        return result
    if lb is None:
        result.error(f"{_player_label(pb, player_b_id)} is not on the roster.")
        return result
    if la == lb:
        result.error("Both players are already at the same level — nothing to swap.")
        return result

    # Final state: remove both, then place A at B's old level and B at A's.
    post = {
        lvl: [pid for pid in ids if pid not in (player_a_id, player_b_id)]
        for lvl, ids in norm.items()
    }
    post.setdefault(la, [])
    post.setdefault(lb, [])
    post[lb].append(player_a_id)
    post[la].append(player_b_id)

    for lvl, cap in caps.items():
        if lvl in post and len(post[lvl]) > cap:
            result.error(f"{lvl.upper()} would exceed cap ({len(post[lvl])}/{cap}).")

    # LOW age gate for whichever player ends up at LOW.
    for pid, pl, dest in ((player_a_id, pa, lb), (player_b_id, pb, la)):
        if dest == "low":
            age = pl.get("age")
            try:
                age_int = int(age) if age is not None else None
            except (TypeError, ValueError):
                age_int = None
            if age_int is not None and age_int >= LOW_LEVEL_MAX_AGE:
                result.error(
                    f"{_player_label(pl, pid)} (age {age_int}) cannot be assigned to LOW "
                    f"(age limit: {LOW_LEVEL_MAX_AGE - 1})."
                )

    # Pitcher limit (owner decision 8: an error at the swap). Like the level
    # caps above, judged on the final state; only a swap that lowers an
    # over-limit pitcher count is let through, so an owner can always swap
    # toward a legal roster.
    pitchers_before = _active_pitcher_count(norm.get("act", []), players)
    pitchers_after = _active_pitcher_count(post.get("act", []), players)
    if pitchers_after > max_pitchers:
        if pitchers_after >= pitchers_before:
            result.error(
                f"Active roster would carry {pitchers_after} pitchers "
                f"(maximum {max_pitchers})."
            )
        else:
            result.warn(
                f"Active roster still carries {pitchers_after} pitchers "
                f"(maximum {max_pitchers}) — send a pitcher down before the next game."
            )

    # ACT composition after the swap.
    act_players = [players[pid] for pid in post.get("act", []) if pid in players]
    non_pitchers = [p for p in act_players if not counts_as_pitcher(p)]
    if len(non_pitchers) < MIN_POSITION_PLAYERS_ACT:
        result.error(
            f"Active roster would have {len(non_pitchers)} position players "
            f"(minimum {MIN_POSITION_PLAYERS_ACT})."
        )
    covered: Set[str] = set()
    for p in non_pitchers:
        covered |= _player_positions(p)
    missing = [pos for pos in REQUIRED_DEF_POSITIONS if pos not in covered]
    if missing:
        result.error(
            f"Active roster would not cover these positions after the swap: {', '.join(missing)}."
        )

    return result


# ---------------------------------------------------------------------------
# 4b. Roster-state validation (no proposed move)


def validate_roster_state(
    *,
    current_levels: Mapping[str, Sequence[str]],
    players: Mapping[str, Mapping[str, Any]],
    level_caps: Mapping[str, int] | None = None,
    pitcher_cap: int | None = None,
) -> ValidationResult:
    """Audit an existing roster for rule compliance.

    Sister function to :func:`validate_roster_move` — same rules but
    evaluated against the *current* state instead of a hypothetical
    post-move state. Called from the roster page (to display banners)
    and from the season-sim gate (to refuse advancing while the team
    is over a cap or missing positional coverage).

    Rules (all errors):
    - ACT / AAA / LOW level caps (defaults 26 / 15 / 10; callers pass
      ``effective_level_caps(date)`` so September allows 28 active).
    - At most ``pitcher_cap`` active pitchers (default 13; 14 in September).
      Injured-but-active pitchers count. There is no active-roster minimum.
    - LOW age gate: players 27+ should not be carried at LOW.
    - ACT must carry at least ``MIN_POSITION_PLAYERS_ACT`` non-pitchers.
    - ACT must cover every required defensive position.
    """

    result = ValidationResult()
    caps, max_pitchers = _resolve_caps(level_caps, pitcher_cap)

    levels = {k.lower(): list(v or []) for k, v in (current_levels or {}).items()}

    # Level caps.
    for level, cap in caps.items():
        roster = levels.get(level, [])
        if len(roster) > cap:
            result.error(
                f"{level.upper()} roster is over cap ({len(roster)}/{cap})."
            )

    # LOW age gate.
    for pid in levels.get("low", []):
        player = players.get(pid)
        if not player:
            continue
        age = player.get("age")
        try:
            age_int = int(age) if age is not None else None
        except (TypeError, ValueError):
            age_int = None
        if age_int is not None and age_int >= LOW_LEVEL_MAX_AGE:
            result.error(
                f"{_player_label(player, pid)} (age {age_int}) is over the "
                f"LOW age limit ({LOW_LEVEL_MAX_AGE - 1})."
            )

    # ACT composition.
    act_ids = levels.get("act", [])
    n_pitchers = _active_pitcher_count(act_ids, players)
    if n_pitchers > max_pitchers:
        result.error(
            f"Active roster carries {n_pitchers} pitchers (maximum {max_pitchers})."
        )

    act_players = [players[pid] for pid in act_ids if pid in players]
    non_pitchers = [p for p in act_players if not counts_as_pitcher(p)]
    if len(non_pitchers) < MIN_POSITION_PLAYERS_ACT:
        result.error(
            f"Active roster carries {len(non_pitchers)} position players "
            f"(minimum {MIN_POSITION_PLAYERS_ACT})."
        )

    covered: Set[str] = set()
    for p in non_pitchers:
        covered |= _player_positions(p)
    missing = [pos for pos in REQUIRED_DEF_POSITIONS if pos not in covered]
    if missing:
        result.error(
            f"Active roster is missing defensive coverage at: {', '.join(missing)}."
        )

    return result


# ---------------------------------------------------------------------------
# 5. Trade validation


def validate_trade(
    *,
    give_player_ids: Sequence[str],
    receive_player_ids: Sequence[str],
    give_pick_ids: Sequence[str] = (),
    receive_pick_ids: Sequence[str] = (),
    from_team_levels: Mapping[str, Sequence[str]] | None = None,
    to_team_levels: Mapping[str, Sequence[str]] | None = None,
    players: Mapping[str, Mapping[str, Any]] | None = None,
    settings: Mapping[str, Any] | None = None,
    payroll_result: Mapping[str, Any] | None = None,
    tradable_pick_ids_from: Iterable[str] | None = None,
    tradable_pick_ids_to: Iterable[str] | None = None,
    level_caps: Mapping[str, int] | None = None,
    pitcher_cap: int | None = None,
) -> ValidationResult:
    """Validate a proposed trade.

    Rules (ported from ui/trade_dialog.py):
    - Each side must include at least one asset (player OR pick).
    - If a side has no players AND no picks, reject.
    - Players on each side must not already belong to the other team.
    - Draft-pick trading respects commissioner enable flag + max year.
    - Picks must be in the team's tradable pool.
    - Payroll policy result (if provided) adds errors for disallowed
      impacts and warnings for soft violations.
    - Post-trade level caps and the active pitcher limit are WARNINGS
      (``level_caps`` / ``pitcher_cap`` default to the base 26/15/10 and 13;
      callers pass the caps in force on the sim date).
    """

    result = ValidationResult()
    players = players or {}
    settings = settings or {}

    # Minimum asset checks.
    if not give_player_ids and not give_pick_ids:
        result.error("Your side of the trade must include at least one player or pick.")
    if not receive_player_ids and not receive_pick_ids:
        result.error("The other side of the trade must include at least one player or pick.")

    # Draft-pick trading enable flag.
    if (give_pick_ids or receive_pick_ids):
        if not bool(settings.get("draft_pick_trading_enabled", True)):
            result.error("Draft-pick trading is disabled by the commissioner.")

    # Max pick trade years (year difference from current).
    max_years = settings.get("max_pick_trade_years")
    try:
        max_years_int = int(max_years) if max_years is not None else None
    except (TypeError, ValueError):
        max_years_int = None
    current_year = settings.get("current_year")
    if max_years_int and current_year:
        for pid in list(give_pick_ids) + list(receive_pick_ids):
            year = _pick_year(pid)
            if year is None or current_year is None:
                continue
            if year - int(current_year) > max_years_int:
                result.error(
                    f"Draft pick {pid} is {year - int(current_year)} years out — "
                    f"commissioner limit is {max_years_int}."
                )

    # Pick ownership.
    if tradable_pick_ids_from is not None:
        legal_from = set(tradable_pick_ids_from)
        for pid in give_pick_ids:
            if pid not in legal_from:
                result.error(f"Draft pick {pid} is not in your tradable pool.")
    if tradable_pick_ids_to is not None:
        legal_to = set(tradable_pick_ids_to)
        for pid in receive_pick_ids:
            if pid not in legal_to:
                result.error(f"Draft pick {pid} is not in the other team's tradable pool.")

    # Non-empty-player sanity: players must exist.
    for pid in list(give_player_ids) + list(receive_player_ids):
        if players and pid not in players:
            result.warn(f"Player {pid} not found in the supplied players map.")

    # Payroll policy fold-in.
    if payroll_result is not None:
        allowed = bool(payroll_result.get("allowed", True))
        violations = payroll_result.get("violations") or []
        if not allowed:
            for v in violations:
                result.error(f"Payroll violation: {v}")
        else:
            for v in violations:
                result.warn(f"Payroll concern: {v}")

    # Post-trade roster sanity (caps and the pitcher limit — defensive
    # coverage is expensive to compute without full player detail; leave as a
    # hook). A trade may leave a team temporarily over a roster cap or the
    # pitcher limit: that's a WARNING, not a blocker. Owners get their rosters
    # compliant afterward, and the season/sim gate (validate_roster_state)
    # still HARD-errors on both, so an over-limit roster can never actually
    # start a game.
    if from_team_levels and to_team_levels:
        caps, max_pitchers = _resolve_caps(level_caps, pitcher_cap)
        post_from = _apply_trade(from_team_levels, drop=give_player_ids, add=receive_player_ids)
        post_to = _apply_trade(to_team_levels, drop=receive_player_ids, add=give_player_ids)
        for side, post in (("your team", post_from), ("other team", post_to)):
            for level, cap in caps.items():
                if len(post.get(level, [])) > cap:
                    result.warn(
                        f"{side.title()} {level.upper()} would be over the limit "
                        f"({len(post[level])}/{cap}) after the trade — get the "
                        "roster compliant before the next sim."
                    )
            n_pitchers = _active_pitcher_count(post.get("act", []), players)
            if n_pitchers > max_pitchers:
                result.warn(
                    f"{side.title()} would carry {n_pitchers} active pitchers "
                    f"(max {max_pitchers}) after the trade — send a pitcher "
                    "down before the next sim."
                )

    return result


def _pick_year(pick_id: str) -> int | None:
    """Extract a year from a pick id like ``2028-R1-POR``. Returns None if not parseable."""

    if not pick_id:
        return None
    token = pick_id.split("-", 1)[0]
    try:
        return int(token)
    except (TypeError, ValueError):
        return None


def _apply_trade(
    levels: Mapping[str, Sequence[str]],
    *,
    drop: Sequence[str],
    add: Sequence[str],
) -> dict[str, List[str]]:
    drop_set = set(drop)
    result: dict[str, List[str]] = {
        key.lower(): [pid for pid in value if pid not in drop_set]
        for key, value in levels.items()
    }
    # New arrivals land on ACT by default. Callers can re-shuffle later.
    result.setdefault("act", [])
    for pid in add:
        if pid not in result["act"]:
            result["act"].append(pid)
    return result


__all__ = [
    "ValidationResult",
    "validate_lineup",
    "validate_pitching_staff",
    "validate_depth_chart",
    "validate_roster_move",
    "validate_roster_swap",
    "validate_roster_state",
    "validate_trade",
    "ALL_POSITIONS",
    "REQUIRED_DEF_POSITIONS",
    "PITCHING_ROLES",
    "OPTIONAL_STAFF_ROLES",
    "ALL_STAFF_ROLES",
    "DEFAULT_LEVEL_CAPS",
    "DEFAULT_PITCHER_CAP",
]


# ---------------------------------------------------------------------------
# 6. Catcher depth (Release 3, owner decision 10) -- advisory only


def validate_catcher_depth(
    act_ids: Iterable[str],
    players: Mapping[str, Mapping[str, Any]],
    *,
    min_catchers: int | None = None,
) -> ValidationResult:
    """Warn when the active roster carries fewer than two catchers.

    Never an error: CPU clubs carry two (their roster upkeep calls one up),
    while an owner's roster is the owner's -- a one-catcher club still plays,
    it just can't rest its catcher, who starts every game, tires and plays a
    little worse (Release 3 batter fatigue). A catcher is
    a position player at C or listing C (:func:`utils.roster_rules.is_catcher`);
    an injured one doesn't count. Ids missing from ``players`` are skipped.
    """

    from utils.roster_rules import MIN_ACTIVE_CATCHERS, is_catcher

    want = MIN_ACTIVE_CATCHERS if min_catchers is None else int(min_catchers)
    result = ValidationResult()
    count = 0
    for pid in act_ids or ():
        player = players.get(pid)
        if not player or not is_catcher(player):
            continue
        if str(player.get("injured", "") or "").strip().lower() in {"1", "true", "yes"}:
            continue
        count += 1
    if count < want:
        noun = "catcher" if count == 1 else "catchers"
        cost = (
            " A rest day needs a backup catcher: without one he catches every "
            "game, tires and plays a little worse."
            if count == 1
            else ""
        )
        result.warn(
            f"Active roster carries {count} healthy {noun}; clubs carry {want} "
            f"so the starter can rest.{cost}"
        )
    return result


__all__.append("validate_catcher_depth")
