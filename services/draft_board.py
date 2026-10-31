"""Owners' draft boards (8.7.0).

When an owner's pick clock ran out, the CPU took the best player left by
overall: no regard for the club's needs or for what it had already drafted,
so an owner who had taken three catchers could be handed a fourth. A draft
board is the owner's own instructions for that moment: a ranked list of
prospects plus a few plain rules.

* **The list.** Prospects in the owner's order, each with an optional note,
  an optional "not before round N" (don't reach for a sleeper), and an
  optional group letter: of a group, only one is ever taken. With tiers on,
  every player in a tier counts as equal; the board takes the one who fills
  an open need, then the best overall.
* **Position limits.** "At most 2 C": a full position is skipped.
* **Position needs.** "At least 1 SS by round 4": from that round on, until
  it is met, the pick must be a shortstop.
* **When the board runs dry.** What to take when nobody on the list can be
  taken: best available (as before), best pitcher, best hitter, the highest
  ceiling, or the best player at an open need.
* **Auto-draft.** ``off``: the board only picks when the clock runs out.
  ``board``: it picks the moment the club is on the clock, as long as a
  player on the list can be taken (otherwise the clock runs as usual).
  ``all``: it always picks at once, falling back as above.

Every pick counts toward the limits and needs, whoever made it. Boards are
private to the club's owner (the commissioner included), so the reason a
board gives for its pick is told to the owner only; the draft itself just
says the pick came from a draft board.

Stored per draft year and club at ``draft_boards/<year>/<TEAM>.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

__all__ = [
    "AUTODRAFT_MODES",
    "BoardChoice",
    "FALLBACKS",
    "GROUP_LABELS",
    "POSITION_GROUPS",
    "board_path",
    "choose",
    "default_board",
    "describe_pick",
    "has_board",
    "load_board",
    "normalize_board",
    "position_groups_of",
    "potential_score",
    "prospect_score",
    "record_pick",
    "save_board",
]

DIRNAME = "draft_boards"
MAX_ENTRIES = 400
MAX_NOTE = 200
MAX_NEEDS = 12

# What a limit or a need can name: one position, or a family of them.
POSITION_GROUPS: Dict[str, frozenset] = {
    "C": frozenset({"C"}),
    "1B": frozenset({"1B"}),
    "2B": frozenset({"2B"}),
    "3B": frozenset({"3B"}),
    "SS": frozenset({"SS"}),
    "LF": frozenset({"LF"}),
    "CF": frozenset({"CF"}),
    "RF": frozenset({"RF"}),
    "IF": frozenset({"1B", "2B", "3B", "SS"}),
    "OF": frozenset({"LF", "CF", "RF"}),
    "P": frozenset({"P", "SP", "RP"}),
}
GROUP_LABELS = ("A", "B", "C", "D", "E", "F", "G", "H")

FALLBACKS = {
    "best_available": "the best player available",
    "best_pitcher": "the best pitcher available",
    "best_hitter": "the best hitter available",
    "highest_potential": "the player with the highest ceiling",
    "best_need": "the best player at a position you still need",
}
DEFAULT_FALLBACK = "best_available"
AUTODRAFT_MODES = ("off", "board", "all")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_board(team_id: str, year: int) -> Dict[str, Any]:
    return {
        "team_id": str(team_id or "").strip().upper(),
        "year": int(year),
        "entries": [],
        "use_tiers": False,
        "position_limits": {},
        "needs": [],
        "fallback": DEFAULT_FALLBACK,
        "autodraft": "off",
        "made": [],
        "updated_at": None,
    }


def board_path(year: int, team_id: str, *, data_dir: Path | str | None = None) -> Path:
    if data_dir is None:
        from utils.path_utils import get_data_dir

        data_dir = get_data_dir()
    team = str(team_id or "").strip().upper()
    return Path(data_dir) / DIRNAME / str(int(year)) / f"{team}.json"


def has_board(year: int, team_id: str, *, data_dir: Path | str | None = None) -> bool:
    return board_path(year, team_id, data_dir=data_dir).exists()


def load_board(year: int, team_id: str, *, data_dir: Path | str | None = None) -> Dict[str, Any]:
    """The club's board for ``year`` (an empty one when it has none)."""

    path = board_path(year, team_id, data_dir=data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_board(team_id, year)
    if not isinstance(raw, Mapping):
        return default_board(team_id, year)
    try:
        board = normalize_board(raw, team_id=team_id, year=year)
    except ValueError:
        # A board saved under rules that have since changed: the owner keeps
        # his picks record, and his list is read without the bad setting.
        board = default_board(team_id, year)
        try:
            board["entries"] = normalize_board(
                {"entries": raw.get("entries") or []}, team_id=team_id, year=year
            )["entries"]
        except ValueError:
            pass
    board["made"] = [m for m in (raw.get("made") or []) if isinstance(m, Mapping)]
    board["updated_at"] = raw.get("updated_at")
    return board


def _int_or_none(value: Any, lo: int, hi: int) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{value!r} is not a whole number.")
    if number < lo or number > hi:
        raise ValueError(f"{number} must be between {lo} and {hi}.")
    return number


def _position_key(value: Any) -> str:
    key = str(value or "").strip().upper()
    if key not in POSITION_GROUPS:
        raise ValueError(
            f"Unknown position {value!r}; use one of {', '.join(POSITION_GROUPS)}."
        )
    return key


def normalize_board(
    raw: Mapping[str, Any],
    *,
    team_id: str,
    year: int,
    pool_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """A clean board from what a client sent (or what is on disk).

    Raises ``ValueError`` with a readable message for a bad position, need,
    limit, fallback or auto-draft setting. Players not in ``pool_ids`` (when
    given) and repeats are dropped rather than refused: the draft class is
    the board's universe, and a stale client is no reason to lose a save.
    """

    board = default_board(team_id, year)
    if not isinstance(raw, Mapping):
        raise ValueError("A draft board must be an object.")

    seen: Set[str] = set()
    entries: List[Dict[str, Any]] = []
    tier = 1
    for item in list(raw.get("entries") or [])[:MAX_ENTRIES]:
        if not isinstance(item, Mapping):
            continue
        pid = str(item.get("player_id") or "").strip()
        if not pid or pid in seen or (pool_ids is not None and pid not in pool_ids):
            continue
        seen.add(pid)
        group = str(item.get("group") or "").strip().upper() or None
        if group is not None and group not in GROUP_LABELS:
            raise ValueError(f"Group must be one of {', '.join(GROUP_LABELS)}.")
        # Tiers only ever go up the list: a tier lower than the one above it
        # is read as the same tier.
        tier = max(tier, _int_or_none(item.get("tier"), 1, MAX_ENTRIES) or tier)
        entries.append(
            {
                "player_id": pid,
                "note": str(item.get("note") or "").strip()[:MAX_NOTE],
                "not_before_round": _int_or_none(item.get("not_before_round"), 1, 99),
                "group": group,
                "tier": tier,
            }
        )
    board["entries"] = entries
    board["use_tiers"] = bool(raw.get("use_tiers"))

    limits: Dict[str, int] = {}
    for key, value in dict(raw.get("position_limits") or {}).items():
        number = _int_or_none(value, 0, 99)
        if number is not None:
            limits[_position_key(key)] = number
    board["position_limits"] = limits

    needs: List[Dict[str, Any]] = []
    for item in list(raw.get("needs") or [])[:MAX_NEEDS]:
        if not isinstance(item, Mapping):
            continue
        needs.append(
            {
                "position": _position_key(item.get("position")),
                "count": _int_or_none(item.get("count"), 1, 20) or 1,
                "by_round": _int_or_none(item.get("by_round"), 1, 99) or 1,
            }
        )
    board["needs"] = needs
    # A need the limits forbid would hold the pick at that position for the
    # rest of the draft.
    for need in needs:
        members = POSITION_GROUPS[need["position"]]
        for key, limit in limits.items():
            if members <= POSITION_GROUPS[key] and need["count"] > limit:
                raise ValueError(
                    f"You need at least {need['count']} {need['position']} but allow "
                    f"at most {limit} {key}."
                )

    fallback = str(raw.get("fallback") or DEFAULT_FALLBACK).strip().lower()
    if fallback not in FALLBACKS:
        raise ValueError(f"fallback must be one of {', '.join(FALLBACKS)}.")
    board["fallback"] = fallback
    autodraft = str(raw.get("autodraft") or "off").strip().lower()
    if autodraft not in AUTODRAFT_MODES:
        raise ValueError(f"autodraft must be one of {', '.join(AUTODRAFT_MODES)}.")
    board["autodraft"] = autodraft
    return board


def save_board(
    year: int,
    team_id: str,
    raw: Mapping[str, Any],
    *,
    pool_ids: Optional[Set[str]] = None,
    data_dir: Path | str | None = None,
) -> Dict[str, Any]:
    """Validate and write the owner's board. The record of picks the board
    has made is the server's, never the client's, and is kept."""

    board = normalize_board(raw, team_id=team_id, year=year, pool_ids=pool_ids)
    board["made"] = load_board(year, team_id, data_dir=data_dir).get("made") or []
    board["updated_at"] = _now()
    path = board_path(year, team_id, data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(board, indent=2), encoding="utf-8")
    return board


def record_pick(
    year: int,
    team_id: str,
    entry: Mapping[str, Any],
    *,
    data_dir: Path | str | None = None,
) -> None:
    """Add a pick made for the club (by its board, or by the CPU when it had
    none) to the club's board file, so the owner can read why."""

    path = board_path(year, team_id, data_dir=data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = default_board(team_id, year)
    made = [m for m in (raw.get("made") or []) if isinstance(m, Mapping)]
    made.append({**dict(entry), "at": _now()})
    raw["made"] = made
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Choosing the pick.


def position_groups_of(prospect: Mapping[str, Any]) -> Set[str]:
    """Every limit/need key ``prospect`` counts toward (SS -> SS and IF)."""

    position = str(prospect.get("primary_position") or "").strip().upper()
    flag = prospect.get("is_pitcher")
    if isinstance(flag, str):
        flag = flag.strip().lower() in {"1", "true", "yes", "y"}
    if flag:
        position = "P"
    return {key for key, members in POSITION_GROUPS.items() if position in members}


def prospect_score(prospect: Mapping[str, Any]) -> float:
    """The shared overall on the engine scale: the CPU's best-available."""

    from utils.player_overall import player_overall_score

    try:
        score = player_overall_score(prospect)
    except Exception:
        return 0.0
    return float(score) if score is not None else 0.0


def potential_score(prospect: Mapping[str, Any]) -> float:
    """The shared overall of the prospect's ceiling (his potentials, his
    current rating where one is unset)."""

    from utils.player_overall import player_overall_score
    from utils.rating_scale import engine_potential, engine_rating

    def _get(key: str) -> Any:
        value = engine_potential(prospect, key, None)
        try:
            if value is not None and float(value) > 0:
                return value
        except (TypeError, ValueError):
            pass
        return engine_rating(prospect, key)

    try:
        score = player_overall_score(prospect, get_raw=_get)
    except Exception:
        return prospect_score(prospect)
    return float(score) if score is not None else prospect_score(prospect)


@dataclass
class BoardChoice:
    player_id: str
    # "board": a player on the list; "fallback": the board ran dry.
    source: str
    reason: str
    rank: Optional[int] = None


def _name(prospect: Optional[Mapping[str, Any]], pid: str) -> str:
    if not prospect:
        return pid
    name = f"{prospect.get('first_name', '')} {prospect.get('last_name', '')}".strip()
    return name or pid


def _with_position(prospect: Optional[Mapping[str, Any]], pid: str) -> str:
    position = str((prospect or {}).get("primary_position") or "").strip()
    name = _name(prospect, pid)
    return f"{name} ({position})" if position else name


def _counts(drafted: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for prospect in drafted:
        for key in position_groups_of(prospect):
            counts[key] = counts.get(key, 0) + 1
    return counts


def _open_needs(board: Mapping[str, Any], counts: Mapping[str, int]) -> List[Dict[str, Any]]:
    """Needs not yet met, the most urgent first."""

    open_ = [
        n for n in board.get("needs") or ()
        if counts.get(n["position"], 0) < int(n.get("count", 1) or 1)
    ]
    return sorted(open_, key=lambda n: int(n.get("by_round", 1) or 1))


def _full_limit(
    prospect: Mapping[str, Any], board: Mapping[str, Any], counts: Mapping[str, int]
) -> Optional[str]:
    """The position limit ``prospect`` would break, if any ("2 C")."""

    for key in sorted(position_groups_of(prospect)):
        limit = (board.get("position_limits") or {}).get(key)
        if limit is not None and counts.get(key, 0) >= int(limit):
            return f"{int(limit)} {key}"
    return None


def choose(
    board: Mapping[str, Any],
    *,
    pool: Sequence[Mapping[str, Any]],
    taken: Set[str],
    drafted: Sequence[Mapping[str, Any]],
    round_no: int,
) -> Optional[BoardChoice]:
    """The pick the board makes in round ``round_no``.

    ``pool`` is the draft class, ``taken`` every id already drafted by
    anyone, ``drafted`` the prospects this club has drafted so far. ``None``
    only when nobody at all is left to take.
    """

    by_id = {str(p.get("player_id") or ""): p for p in pool}
    available = [p for pid, p in by_id.items() if pid and pid not in taken]
    if not available:
        return None
    counts = _counts(drafted)
    needs = _open_needs(board, counts)
    # The most urgent need that is due and can still be met: one with nobody
    # left at its position must not hold every pick for the rest of the draft.
    due = next(
        (
            n for n in needs
            if int(n["by_round"]) <= int(round_no)
            and any(n["position"] in position_groups_of(p) for p in available)
        ),
        None,
    )
    drafted_ids = {str(p.get("player_id") or "") for p in drafted}
    used_groups = {
        e["group"] for e in board.get("entries") or ()
        if e.get("group") and e["player_id"] in drafted_ids
    }

    # (rank, "#3 Joe Smith (taken)") for the players the board passed over.
    skipped: List[tuple] = []

    def _skip_reason(entry: Mapping[str, Any], prospect: Optional[Mapping[str, Any]]) -> Optional[str]:
        pid = entry["player_id"]
        if prospect is None:
            return "not in the class"
        if pid in taken:
            return "taken"
        nbr = entry.get("not_before_round")
        if nbr and int(round_no) < int(nbr):
            return f"not before round {int(nbr)}"
        if entry.get("group") and entry["group"] in used_groups:
            return f"you already took one of group {entry['group']}"
        limit = _full_limit(prospect, board, counts)
        if limit:
            return f"limit of {limit} reached"
        if due is not None and due["position"] not in position_groups_of(prospect):
            return f"your {due['position']} need is due"
        return None

    eligible: List[tuple] = []
    for rank, entry in enumerate(board.get("entries") or (), start=1):
        prospect = by_id.get(entry["player_id"])
        why = _skip_reason(entry, prospect)
        if why is None:
            eligible.append((rank, entry, prospect))
        elif len(skipped) < 6 and why != "not in the class":
            skipped.append((rank, f"#{rank} {_name(prospect, entry['player_id'])} ({why})"))

    if eligible:
        rank, entry, prospect = eligible[0]
        how = f"#{rank} on your board"
        if board.get("use_tiers"):
            tier = entry.get("tier", 1)
            same = [e for e in eligible if e[1].get("tier", 1) == tier]
            if len(same) > 1:
                need_keys = {n["position"] for n in needs}

                def _tier_key(item: tuple) -> tuple:
                    fills = bool(position_groups_of(item[2]) & need_keys)
                    return (not fills, -prospect_score(item[2]), item[0])

                rank, entry, prospect = min(same, key=_tier_key)
                fills = bool(position_groups_of(prospect) & need_keys)
                how = (
                    f"#{rank} on your board, from tier {tier}"
                    + (" (fills a need)" if fills else " (best of the tier)")
                )
        # Only what was passed over on the way to this pick explains it.
        passed = [text for at, text in skipped if at < rank]
        reason = f"From your board: {how}."
        if passed:
            reason += " Passed over: " + "; ".join(passed) + "."
        return BoardChoice(entry["player_id"], "board", reason, rank)

    # The board ran dry: the fallback, still inside the owner's rules. A
    # player he ruled out on his list (one of a group already used, not
    # before a later round) stays ruled out, unless nobody else is left.
    fallback = str(board.get("fallback") or DEFAULT_FALLBACK)
    ruled_out = {
        e["player_id"] for e in board.get("entries") or ()
        if (e.get("group") and e["group"] in used_groups)
        or (e.get("not_before_round") and int(round_no) < int(e["not_before_round"]))
    }
    candidates = [p for p in available if str(p.get("player_id") or "") not in ruled_out]
    candidates = candidates or available
    within = [p for p in candidates if not _full_limit(p, board, counts)]
    # Every player left is at a position the owner limited: somebody must
    # still be picked, so the limits give way.
    capped_out = not within
    pool_left = within or candidates
    at_due = False
    if due is not None:
        at_need = [p for p in pool_left if due["position"] in position_groups_of(p)]
        if at_need:
            pool_left, at_due = at_need, True
    kind = ""
    missing = ""
    if not at_due and fallback in ("best_pitcher", "best_hitter"):
        want_pitcher = fallback == "best_pitcher"
        narrowed = [p for p in pool_left if ("P" in position_groups_of(p)) == want_pitcher]
        if narrowed:
            pool_left, kind = narrowed, ("pitcher" if want_pitcher else "hitter")
        else:
            missing = "pitcher" if want_pitcher else "hitter"
    elif not at_due and fallback == "best_need" and needs:
        keys = {n["position"] for n in needs}
        narrowed = [p for p in pool_left if position_groups_of(p) & keys]
        if narrowed:
            pool_left, kind = narrowed, "need"
        else:
            missing = "player at a position you still need"
    ceiling = fallback == "highest_potential"
    score = potential_score if ceiling else prospect_score
    pick = max(pool_left, key=lambda p: (score(p), str(p.get("player_id") or "")))
    pid = str(pick.get("player_id") or "")

    # Say what it actually took, from the filters that applied.
    best = "highest-ceiling" if ceiling else "best"
    if at_due:
        what = (
            f"the {best} {due['position']} available "
            f"(your need by round {int(due['by_round'])})"
        )
    elif kind == "pitcher":
        what = "the best pitcher available"
    elif kind == "hitter":
        what = "the best hitter available"
    elif kind == "need":
        what = "the best player at a position you still need"
    elif ceiling:
        what = "the player with the highest ceiling"
    else:
        what = "the best player available"
    if missing:
        what += f" (no {missing} was left)"
    if board.get("entries"):
        reason = "Nobody on your board could be taken"
        if skipped:
            reason += " (" + "; ".join(text for _, text in skipped) + ")"
        reason += f", so it took {what}"
    else:
        reason = f"Your board has no players, so it took {what}"
    if capped_out:
        reason += "; every player left is at a position you limited"
    return BoardChoice(pid, "fallback", reason + ".")


def describe_pick(prospect: Optional[Mapping[str, Any]], pid: str) -> str:
    return _with_position(prospect, pid)
