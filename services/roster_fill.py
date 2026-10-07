"""Position-aware roster fills: who comes up when someone goes down.

Every automatic promotion used to pop whoever sat first in a team's AAA list
(``Roster.promote_replacements``). On 13 of 20 alpha-test clubs that was a
pitcher, so each injured hitter was replaced by an arm, the hitter went to AAA
when he came back (the active roster was full), and over a season the active
roster drifted to 8 position players and 17 pitchers. Below nine hitters the
lineup fill reached across the league for other teams' minor leaguers and the
sim day aborted ("Player X is not on the active roster"; audit H9).

The rules here, in the commissioner's order (audit decision 14):

* like for like -- a position player is replaced by a position player, a
  pitcher by a pitcher;
* the team's depth chart first, then players who can play the position, then
  (CPU clubs only) any position player;
* only the team's own organisation (AAA before Low-A), never another club's;
* better players first within each tier;
* every automatic move is recorded in the transaction log.

A CPU club's active roster converges to the 26-man shape of decision 8: at
most 13 pitchers (14 in September) and 13 position players.
"""

from __future__ import annotations

import ast
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from services.roster_validation import MIN_POSITION_PLAYERS_ACT
from utils.roster_rules import (
    ACT_HITTER_TARGET,
    MAX_ACTIVE_PITCHERS,
    MIN_ACTIVE_CATCHERS,
    SEPTEMBER_MAX_ACTIVE_PITCHERS,
    SEPTEMBER_ROSTER_SIZE,
    counts_as_pitcher,
    is_catcher,
)

__all__ = [
    "MIN_FIELDABLE_HITTERS",
    "HITTER_FLOOR",
    "is_pitcher",
    "positions_of",
    "can_play",
    "player_score",
    "callup_candidates",
    "ensure_fieldable_roster",
    "maintain_cpu_active_roster",
    "record_roster_moves",
    "record_emergency_callups",
    "choose_send_down",
    "pitcher_cap_for",
    "ForcedMove",
    "prepare_teams_for_game",
]

#: A game needs nine position players.
MIN_FIELDABLE_HITTERS = 9
#: Automatic moves never leave fewer active position players than this: one
#: above the season gate's minimum, so an injury can still be covered. Derived
#: so the 26-man change (decision 8) moves it with the gate.
HITTER_FLOOR = MIN_POSITION_PLAYERS_ACT + 1
#: When a CPU club must send a pitcher down to make room for a hitter, keep at
#: least this many active pitchers (two under the 13-pitcher limit).
PITCHER_KEEP = MAX_ACTIVE_PITCHERS - 2
#: CPU clubs aim for this many active position players (26 - 13).
HITTER_TARGET = ACT_HITTER_TARGET
#: Positions a lineup needs covered; mirrors
#: ``services.roster_auto_assign.REQUIRED_POSITIONS`` (a test pins the two).
_REQUIRED_POSITIONS: Tuple[str, ...] = ("C", "SS", "CF", "2B", "3B", "1B", "LF", "RF")
#: Release 3: a CPU club carries a spare for each group -- one more player who
#: can play the first position (SS, CF: nobody else covers them on a rest
#: day, the similar-position moves run the other way), else, without one in
#: the organisation, one more for the group. Mirrors full-mode auto-assign's
#: ``BACKUP_GROUPS``.
SPARE_GROUPS: Tuple[Tuple[str, ...], ...] = (("SS", "2B", "3B"), ("CF", "LF", "RF"))

Move = Tuple[str, str, str]  # (player_id, from_level, to_level)


class ForcedMove(tuple):
    """A CPU option made past the prospect option rules (decision 8, Q12).

    There are no waivers or DFA, so a surplus pitcher who is out of options
    could otherwise keep a CPU club over the pitcher limit for good. Compares
    and unpacks like a plain ``(player_id, from_level, to_level)`` move;
    :func:`record_roster_moves` labels it in the transaction log.
    """


def is_pitcher(player: object) -> bool:
    """True for anyone who counts toward the active-roster pitcher limit."""

    return counts_as_pitcher(player)


def pitcher_cap_for(cap: Optional[int]) -> int:
    """The pitcher limit that goes with an active-roster size cap.

    28 (September) allows 14 pitchers; anything else 13. Lets callers that
    only know the size cap (``active_roster_cap(date)``) get the matching
    pitcher limit without a second date lookup.
    """

    if cap is not None and int(cap) >= SEPTEMBER_ROSTER_SIZE:
        return SEPTEMBER_MAX_ACTIVE_PITCHERS
    return MAX_ACTIVE_PITCHERS


def positions_of(player: object) -> List[str]:
    """Primary position plus every secondary one, upper-cased.

    ``other_positions`` arrives as a list from the loader, but older rows hold
    a Python list literal (``"['RF']"``) or an empty ``"[]"``, which the
    ``|``-split loader turned into one bogus entry. Accept every form.
    """

    out: List[str] = []
    primary = str(getattr(player, "primary_position", "") or "").strip().upper()
    if primary:
        out.append(primary)
    raw = getattr(player, "other_positions", None) or []
    if isinstance(raw, str):
        raw = [raw]
    for item in raw:
        for pos in _split_positions(item):
            if pos and pos not in out:
                out.append(pos)
    return out


def _split_positions(value: object) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            parsed = text.strip("[]").replace("'", "").replace('"', "").split(",")
        if isinstance(parsed, (list, tuple)):
            return [str(p).strip().upper() for p in parsed if str(p).strip()]
    return [p.strip().upper() for p in text.replace("|", ",").split(",") if p.strip()]


def can_play(player: object, position: str) -> bool:
    """Whether a position player can take ``position`` (DH: any hitter)."""

    if player is None or is_pitcher(player):
        return False
    position = str(position or "").strip().upper()
    if position == "DH":
        return True
    return position in positions_of(player)


def player_score(player: object) -> float:
    """Overall quality used to pick the better of two players."""

    try:
        from utils.rating_display import overall_rating

        return float(overall_rating(player) or 0)
    except Exception:  # pragma: no cover - defensive
        return 0.0


def _available(player: object) -> bool:
    return player is not None and not bool(getattr(player, "injured", False))


def callup_candidates(
    roster: object,
    players_by_id: Mapping[str, object],
    *,
    want_pitcher: bool,
    position: Optional[str] = None,
    chart_order: Sequence[str] = (),
    exclude: Iterable[str] = (),
    allowed: Optional[Callable[[str, str], bool]] = None,
    position_only: bool = False,
    want_starter: bool = False,
) -> List[tuple]:
    """Ordered ``(player_id, from_level)`` candidates for one promotion.

    Tiers, each AAA before Low-A and best player first:
    1. players the depth chart lists for ``position``, in chart order;
    2. players who can play ``position``;
    3. any healthy player of the right type -- skipped when ``position_only``
       (an owner's club gets a player for the open position or nobody).

    ``want_starter`` (pitchers only): a starter goes down, so starter-capable
    arms come first -- a reliever called up for him would leave a hole in the
    rotation (Release 3, audit M15).

    ``allowed(player_id, from_level)`` lets the caller veto a move (prospect
    service-time rules); vetoed players are skipped, never forced.
    """

    skip = {str(p) for p in exclude or () if p}
    levels = (("aaa", list(getattr(roster, "aaa", []) or [])),
              ("low", list(getattr(roster, "low", []) or [])))
    pool: List[tuple] = []
    for level, ids in levels:
        for pid in ids:
            if pid in skip:
                continue
            player = players_by_id.get(pid)
            if not _available(player) or is_pitcher(player) != want_pitcher:
                continue
            pool.append((pid, level))
    level_rank = {"aaa": 0, "low": 1}

    def _best(entries: List[tuple]) -> List[tuple]:
        return sorted(
            entries,
            key=lambda e: (level_rank[e[1]], -player_score(players_by_id.get(e[0]))),
        )

    ordered: List[tuple] = []
    seen: set = set()
    by_id = {pid: (pid, lvl) for pid, lvl in pool}
    if position and not want_pitcher:
        for pid in chart_order:
            if pid in by_id and pid not in seen and can_play(players_by_id.get(pid), position):
                ordered.append(by_id[pid])
                seen.add(pid)
        fits = [e for e in pool if e[0] not in seen and can_play(players_by_id.get(e[0]), position)]
        for entry in _best(fits):
            ordered.append(entry)
            seen.add(entry[0])
        if position_only:
            pool = []
    for entry in _best([e for e in pool if e[0] not in seen]):
        ordered.append(entry)
        seen.add(entry[0])
    if want_pitcher and want_starter:
        from utils.pitcher_role import get_role

        # Stable: AAA before Low-A and best first within each group.
        ordered.sort(key=lambda e: get_role(players_by_id.get(e[0])) != "SP")
    if allowed is not None:
        ordered = [e for e in ordered if allowed(e[0], e[1])]
    return ordered


def _hitters(act: Sequence[str], players: Mapping[str, object]) -> List[str]:
    return [p for p in act if players.get(p) is not None and not is_pitcher(players.get(p))]


def _pitchers(act: Sequence[str], players: Mapping[str, object]) -> List[str]:
    return [p for p in act if is_pitcher(players.get(p))]


def _promote(roster: object, pid: str, level: str, moves: List[Move]) -> None:
    getattr(roster, level).remove(pid)
    roster.act.append(pid)
    moves.append((pid, level, "act"))


def _option(roster: object, pid: str, moves: List[Move], *, forced: bool = False) -> None:
    roster.act.remove(pid)
    roster.aaa.append(pid)
    moves.append(ForcedMove((pid, "act", "aaa")) if forced else (pid, "act", "aaa"))


def _weakest(ids: Sequence[str], players: Mapping[str, object]) -> Optional[str]:
    if not ids:
        return None
    return min(ids, key=lambda pid: player_score(players.get(pid)))


def _is_catcher(player: object) -> bool:
    # The shared predicate (Release 3): primary C or C listed among the
    # other positions, so a utility catcher protects the club too.
    return is_catcher(player)


def _healthy_catchers(ids: Sequence[str], players: Mapping[str, object]) -> List[str]:
    return [p for p in ids if _is_catcher(players.get(p)) and _available(players.get(p))]


def choose_send_down(
    roster: object,
    players: Mapping[str, object],
    *,
    exclude: Iterable[str] = (),
    allowed: Optional[Callable[[str], bool]] = None,
    pitcher_cap: Optional[int] = None,
    hitter_target: int = HITTER_TARGET,
    keep_catchers: int = 1,
) -> Optional[str]:
    """Who to option when the active roster is over the cap.

    By the composition of the WHOLE active roster, the arriving player
    included (counting without him hid a 14th pitcher): a pitcher while the
    staff is over ``pitcher_cap`` (default 13) or position players are at
    the floor; else a position player while there are more than
    ``hitter_target``; else one of the arriving player's type. Never the
    club's last healthy catcher (a pitcher-heavy CPU club once optioned its
    only catcher this way), and one of its last ``keep_catchers`` only when
    nobody else of the chosen type may go. CPU paths pass
    ``MIN_ACTIVE_CATCHERS`` (two, Release 3, owner decision 10); the default
    of one is for an owner's club, whose second catcher is his call. Players in
    ``exclude`` (the man just activated) are counted but never chosen; those
    ``allowed`` vetoes (option limits) are skipped.
    """

    skip = {str(p) for p in exclude or ()}
    act_all = list(roster.act)
    all_hitters = _hitters(act_all, players)
    all_arms = _pitchers(act_all, players)
    hitters = [p for p in all_hitters if p not in skip]
    arms = [p for p in all_arms if p not in skip]
    catchers = _healthy_catchers(act_all, players)
    limit = MAX_ACTIVE_PITCHERS if pitcher_cap is None else int(pitcher_cap)

    def _ok(pid: str, keep: int) -> bool:
        if pid in catchers and len(catchers) <= max(1, keep):
            return False
        return allowed is None or allowed(pid)

    if len(all_arms) > limit or len(all_hitters) <= HITTER_FLOOR:
        order = (arms, hitters)
    elif len(all_hitters) > hitter_target:
        order = (hitters, arms)
    else:
        arriving = [p for p in act_all if p in skip]
        if arriving and is_pitcher(players.get(arriving[0])):
            order = (arms, hitters)
        else:
            order = (hitters, arms)
    for pool in order:
        # The second catcher goes only when nobody else of this type may.
        for keep in (keep_catchers, 1):
            eligible = [p for p in pool if _ok(p, keep)]
            if eligible:
                return _weakest(eligible, players)
    return None


def _weakest_non_catcher_hitter(
    roster: object,
    players: Mapping[str, object],
    *,
    option_allowed: Optional[Callable[[str], bool]] = None,
    protect: Iterable[str] = (),
) -> Optional[str]:
    """The weakest active position player who is not a catcher, not in
    ``protect`` (see :func:`_protected_hitters`) and whom the option rules
    allow to go down, or ``None``."""

    keep = set(protect or ())
    pool = [
        p for p in _hitters(roster.act, players)
        if not _is_catcher(players.get(p)) and p not in keep
    ]
    if option_allowed is not None:
        pool = [p for p in pool if option_allowed(p)]
    return _weakest(pool, players)


def _injury_covers(team_id: str, roster: object) -> set:
    """Players called up to cover a teammate who is still on the injured
    list (``services.injury_replacements``): the upkeep never options them
    (one went LOW -> ACT -> AAA overnight)."""

    try:
        from services.injury_replacements import _load

        data = _load()
    except Exception:
        return set()
    hurt = {
        str(p)
        for level in ("dl", "ir")
        for p in list(getattr(roster, level, []) or [])
    }
    covers = set()
    for injured_id, entry in (data or {}).items():
        if not isinstance(entry, dict) or str(injured_id) not in hurt:
            continue
        if str(entry.get("team_id", "")) != str(team_id):
            continue
        if entry.get("replacement_id"):
            covers.add(str(entry["replacement_id"]))
    return covers


def _protected_hitters(roster: object, players: Mapping[str, object]) -> set:
    """Active position players the CPU upkeep never options to make room:

    * the last healthy one who can play a ``_REQUIRED_POSITIONS`` spot;
    * a club's only spare at a ``SPARE_GROUPS`` key position (SS, CF): while
      two or fewer can play it, both stay;
    * a group's only spare otherwise: while the group is covered by at most
      one more player than it has positions, all of them stay.
    """

    healthy = [p for p in _hitters(roster.act, players) if _available(players.get(p))]
    can = {pid: set(positions_of(players.get(pid))) for pid in healthy}
    protected = set()
    for pos in _REQUIRED_POSITIONS:
        able = [pid for pid in healthy if pos in can[pid]]
        if len(able) == 1:
            protected.add(able[0])
    for group in SPARE_GROUPS:
        key_able = [pid for pid in healthy if group[0] in can[pid]]
        if len(key_able) <= 2:
            protected.update(key_able)
        covering = [pid for pid in healthy if can[pid] & set(group)]
        if len(covering) <= len(group) + 1:
            protected.update(covering)
    return protected


def _spare_callup(
    roster: object,
    players: Mapping[str, object],
    group: Tuple[str, ...],
    *,
    allowed: Optional[Callable[[str, str], bool]],
    exclude: Iterable[str],
) -> Optional[tuple]:
    """The minor leaguer to call up as the club's spare for ``group``, or
    ``None`` when it has one (two who can play the key position, or -- with
    nobody in the minors who can -- one more than the group's positions)."""

    healthy = [p for p in _hitters(roster.act, players) if _available(players.get(p))]
    key = group[0]
    if sum(1 for p in healthy if can_play(players.get(p), key)) >= 2:
        return None
    cands = callup_candidates(
        roster, players, want_pitcher=False, position=key, allowed=allowed,
        position_only=True, exclude=exclude,
    )
    if cands:
        return cands[0]
    covering = sum(
        1 for p in healthy if set(positions_of(players.get(p))) & set(group)
    )
    if covering > len(group):
        return None
    for pos in group[1:]:
        cands = callup_candidates(
            roster, players, want_pitcher=False, position=pos, allowed=allowed,
            position_only=True, exclude=exclude,
        )
        if cands:
            return cands[0]
    return None


def _option_surplus_pitcher(
    roster: object,
    players: Mapping[str, object],
    moves: List[Move],
    *,
    exclude: Iterable[str] = (),
    option_allowed: Optional[Callable[[str], bool]] = None,
) -> bool:
    """Option the weakest active pitcher; False when there is none to send.

    Pitchers the option rules allow go first. When every one of them is out
    of options a CPU club options the weakest anyway, as a :class:`ForcedMove`
    (the September revert's precedent): with no waivers or DFA it would
    otherwise stay over the pitcher limit for good.
    """

    skip = {str(p) for p in exclude or ()}
    arms = [p for p in _pitchers(roster.act, players) if p not in skip]
    if not arms:
        return False
    free = arms if option_allowed is None else [p for p in arms if option_allowed(p)]
    if free:
        _option(roster, _weakest(free, players), moves)
    else:
        _option(roster, _weakest(arms, players), moves, forced=True)
    return True


def _best_callup(
    roster, players, *, want_pitcher, allowed, fallback_unrestricted=False, exclude=()
):
    cands = callup_candidates(
        roster, players, want_pitcher=want_pitcher, allowed=allowed, exclude=exclude
    )
    if not cands and fallback_unrestricted and allowed is not None:
        cands = callup_candidates(roster, players, want_pitcher=want_pitcher, exclude=exclude)
    return cands[0] if cands else None


def ensure_fieldable_roster(
    team_id: str,
    roster: object,
    players_by_id: Mapping[str, object],
    *,
    allowed: Optional[Callable[[str, str], bool]] = None,
    cpu_owned: bool = False,
    cap: Optional[int] = None,
    pitcher_cap: Optional[int] = None,
) -> List[Move]:
    """Emergency only: promote own minor-league hitters until nine are active.

    A game needs nine position players. When injuries leave fewer on the
    active roster, the team calls up its own best healthy AAA (then Low-A)
    position players -- never another club's, which is what the lineup fill
    used to reach for (audit H9). Owner teams included: the alternative is a
    game that cannot be played (decision 14, step 4). Prospect rules are
    honoured first and only overridden if the club would otherwise be short.
    A CPU club then options its weakest surplus pitchers to stay under
    ``cap`` and, after a call-up, the pitcher limit (``pitcher_cap``, by
    default the one that goes with ``cap``). Mutates ``roster``; returns the
    moves for the caller to save and record.
    """

    moves: List[Move] = []
    while len(_hitters(roster.act, players_by_id)) < MIN_FIELDABLE_HITTERS:
        pick = _best_callup(
            roster, players_by_id, want_pitcher=False, allowed=allowed,
            fallback_unrestricted=True,
        )
        if pick is None:
            break
        _promote(roster, pick[0], pick[1], moves)
    if cpu_owned and cap is not None:
        called_up = bool(moves)
        while len(roster.act) > cap:
            arms = _pitchers(roster.act, players_by_id)
            if len(arms) <= PITCHER_KEEP:
                break
            _option(roster, _weakest(arms, players_by_id), moves)
        # Logged as room for the emergency call-up, so only after one; the
        # daily upkeep trims a staff that is simply too big.
        limit = pitcher_cap_for(cap) if pitcher_cap is None else int(pitcher_cap)
        while called_up and len(_pitchers(roster.act, players_by_id)) > limit:
            arms = _pitchers(roster.act, players_by_id)
            _option(roster, _weakest(arms, players_by_id), moves)
    return moves


def maintain_cpu_active_roster(
    team_id: str,
    roster: object,
    players_by_id: Mapping[str, object],
    *,
    target_size: int,
    cap: int,
    allowed: Optional[Callable[[str, str], bool]] = None,
    pitcher_cap: Optional[int] = None,
    option_allowed: Optional[Callable[[str], bool]] = None,
    protect: Iterable[str] = (),
) -> List[Move]:
    """Keep a CPU club's active roster legal, full and balanced.

    Nothing refilled a CPU club's active roster once ``load_roster`` stopped
    topping it up silently: an uneven trade, a cut, or an injury with no
    like-for-like call-up left it short for good, and a roster that had
    already drifted pitcher-heavy (H9) stayed that way. Run before each sim
    and after each day:

    1. repair: while fewer than ``HITTER_FLOOR`` position players are active,
       swap the weakest surplus pitcher for the best minor-league hitter;
    2. pitcher limit: while more than ``pitcher_cap`` pitchers are active
       (default: 13, or 14 when ``cap`` is September's 28), option the
       weakest;
    3. fill: up to ``target_size``, a hitter while below ``HITTER_TARGET``
       position players, otherwise a pitcher -- never one past the pitcher
       limit (the roster stays short instead);
    4. rebalance: while there are more than ``HITTER_TARGET`` position
       players and fewer than 13 pitchers, swap the weakest surplus hitter
       (never the last healthy catcher) for the best arm in the organisation.
       A creator-built 11-pitcher/14-hitter club otherwise stopped at 12/14;
    5. trim: while over ``cap``, option by composition (``choose_send_down``).

    Only the club's own AAA/Low-A, never a free agent. ``option_allowed``
    vetoes send-downs the option rules forbid; a surplus pitcher nobody may
    option is optioned anyway (a :class:`ForcedMove`) -- nobody else ever is,
    so a club whose surplus is out of options stays over the size cap. CPU
    clubs only -- an owner's roster is the owner's. Mutates ``roster``.

    Step 0 keeps ``MIN_ACTIVE_CATCHERS`` (two) catchers active (Release 3,
    owner decision 10). A club with none healthy calls one up as before. A
    club with one -- a day-to-day catcher still on the active roster counts;
    only one on the injured list is missing -- calls up a catcher from its
    own minors and, when the roster is full, options its weakest non-catcher
    position player (one the option rules allow), so the 13 / 13 shape holds.
    That player is never the last who can play a required position, the
    club's only spare SS / CF, a player covering for a teammate still on the
    injured list, or one in ``protect``. No catcher in the organisation, or
    nobody who may go down, means no move. A third healthy catcher (primary
    C) is optioned.

    Step 6 carries a spare SS and CF (``SPARE_GROUPS``) from the club's own
    minors, by the same rules, so live CPU clubs match the full auto-assign
    shape.
    """

    moves: List[Move] = []
    players = players_by_id
    limit = pitcher_cap_for(cap) if pitcher_cap is None else int(pitcher_cap)
    keep_out = {str(p) for p in protect or ()} | _injury_covers(team_id, roster)
    sent_down: set = set()

    def _send(pid: str, *, forced: bool = False) -> None:
        _option(roster, pid, moves, forced=forced)
        sent_down.add(pid)

    def _hitter_victim() -> Optional[str]:
        return _weakest_non_catcher_hitter(
            roster, players, option_allowed=option_allowed,
            protect=keep_out | _protected_hitters(roster, players),
        )

    # 0. catchers: none healthy on the active roster is an emergency (any
    # send-down makes room); a lone catcher gets a partner from the minors.
    for _attempt in range(MIN_ACTIVE_CATCHERS):
        catchers = _healthy_catchers(list(roster.act), players)
        present = [p for p in roster.act if _is_catcher(players.get(p))]
        if catchers and len(present) >= MIN_ACTIVE_CATCHERS:
            break
        cands = callup_candidates(
            roster, players, want_pitcher=False, position="C",
            allowed=allowed, position_only=True,
        )
        if not cands:
            break
        if not catchers:
            if len(roster.act) >= cap:
                victim = choose_send_down(roster, players, pitcher_cap=limit)
                if victim is not None:
                    _send(victim)
        elif len(roster.act) >= min(cap, target_size):
            victim = _hitter_victim()
            if victim is None:
                break
            _send(victim)
        if len(roster.act) >= cap:
            break
        _promote(roster, cands[0][0], cands[0][1], moves)

    # 0b. a third healthy catcher (primary C) goes down; the fill below
    # replaces him with a hitter, never another catcher.
    while len(_healthy_catchers(list(roster.act), players)) > MIN_ACTIVE_CATCHERS:
        guarded = keep_out | _protected_hitters(roster, players)
        pool = [
            p for p in _healthy_catchers(list(roster.act), players)
            if str(getattr(players.get(p), "primary_position", "") or "").strip().upper() == "C"
            and p not in guarded
            and (option_allowed is None or option_allowed(p))
        ]
        if not pool:
            break
        _send(_weakest(pool, players))

    def _fill_exclude() -> set:
        # Nobody just sent down comes straight back, and no extra catcher.
        out = set(sent_down)
        if len(_healthy_catchers(list(roster.act), players)) >= MIN_ACTIVE_CATCHERS:
            for level in ("aaa", "low"):
                out.update(
                    p for p in getattr(roster, level, []) or [] if _is_catcher(players.get(p))
                )
        return out

    # 1. repair a pitcher-heavy drift
    while len(_hitters(roster.act, players)) < HITTER_FLOOR:
        pick = _best_callup(roster, players, want_pitcher=False, allowed=allowed)
        if pick is None:
            break
        if len(roster.act) >= target_size:
            arms = _pitchers(roster.act, players)
            if len(arms) <= PITCHER_KEEP:
                break
            _send(_weakest(arms, players))
        _promote(roster, pick[0], pick[1], moves)

    # 2. the pitcher limit
    while len(_pitchers(roster.act, players)) > limit:
        if not _option_surplus_pitcher(roster, players, moves, option_allowed=option_allowed):
            break

    # 3. fill to the target size, never past the pitcher limit
    while len(roster.act) < target_size:
        arms_full = len(_pitchers(roster.act, players)) >= limit
        want_pitcher = len(_hitters(roster.act, players)) >= HITTER_TARGET and not arms_full
        skip = _fill_exclude()
        pick = _best_callup(
            roster, players, want_pitcher=want_pitcher, allowed=allowed, exclude=skip
        )
        if pick is None and (want_pitcher or not arms_full):
            pick = _best_callup(
                roster, players, want_pitcher=not want_pitcher, allowed=allowed, exclude=skip
            )
        if pick is None:
            break
        _promote(roster, pick[0], pick[1], moves)

    # 4. rebalance a hitter-heavy roster toward 13 pitchers / 13 hitters
    staff_target = min(MAX_ACTIVE_PITCHERS, limit)
    while (
        len(_hitters(roster.act, players)) > HITTER_TARGET
        and len(_pitchers(roster.act, players)) < staff_target
    ):
        pick = _best_callup(roster, players, want_pitcher=True, allowed=allowed)
        if pick is None:
            break
        catchers = _healthy_catchers(list(roster.act), players)
        surplus = [
            p for p in _hitters(roster.act, players)
            if not (p in catchers and len(catchers) <= MIN_ACTIVE_CATCHERS)
        ]
        if option_allowed is not None:
            surplus = [p for p in surplus if option_allowed(p)]
        if not surplus:
            break
        _send(_weakest(surplus, players))
        _promote(roster, pick[0], pick[1], moves)

    # 5. trim to the cap. When the option rules veto everyone, only a surplus
    # pitcher (a staff over the limit) is forced down; anyone else stays and
    # the club stays over the size cap until a send-down is allowed.
    while len(roster.act) > cap:
        victim = choose_send_down(
            roster, players, allowed=option_allowed, pitcher_cap=limit,
            keep_catchers=MIN_ACTIVE_CATCHERS,
        )
        forced = False
        if victim is None and option_allowed is not None:
            arms = _pitchers(roster.act, players)
            if len(arms) > limit:
                victim = _weakest(arms, players)
                forced = True
        if victim is None:
            break
        _send(victim, forced=forced)

    # 6. a spare SS and CF from the club's own minors (Release 3): call one
    # up and, on a full roster, option the weakest position player nobody
    # needs (the step-0 rules). Nobody who may go down: no move.
    for group in SPARE_GROUPS:
        if len(roster.act) > cap:
            break
        pick = _spare_callup(roster, players, group, allowed=allowed, exclude=sent_down)
        if pick is None:
            continue
        full = len(roster.act) >= min(cap, target_size)
        origin = getattr(roster, pick[1])
        slot = origin.index(pick[0])
        _promote(roster, pick[0], pick[1], moves)
        if not full:
            continue
        victim = _weakest_non_catcher_hitter(
            roster, players, option_allowed=option_allowed,
            protect=keep_out | _protected_hitters(roster, players) | {pick[0]},
        )
        if victim is None:
            # Undo the call-up: the club keeps its shape.
            moves.pop()
            roster.act.remove(pick[0])
            origin.insert(slot, pick[0])
            continue
        _send(victim)
    return moves


def record_roster_moves(
    team_id: str,
    moves: Sequence[Move],
    players_by_id: Mapping[str, object],
    *,
    details: str,
    news: bool = False,
) -> None:
    """Transaction-log (and optionally news) lines for automatic moves.

    The sim's injury call-ups and send-downs used to reach only the prospect
    event log, so owners browsing transactions never saw them.
    """

    if not moves:
        return
    try:
        from services.transaction_log import record_transaction
        from utils.news_logger import log_news_event
    except Exception:  # pragma: no cover - defensive
        return
    for move in moves:
        pid, from_level, to_level = move
        player = players_by_id.get(pid)
        name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip() or pid
        line = details
        if isinstance(move, ForcedMove):
            line = f"{details}; optioned past his option limit (over the pitcher limit)"
        try:
            record_transaction(
                action="assign",
                team_id=team_id,
                player_id=pid,
                player_name=name,
                from_level=str(from_level).upper(),
                to_level=str(to_level).upper(),
                details=line,
            )
        except Exception:
            pass
        if news:
            try:
                log_news_event(
                    f"{team_id}: {name} {str(from_level).upper()} to {str(to_level).upper()} ({details})",
                    category="transaction",
                    team_id=team_id,
                )
            except Exception:
                pass


def record_emergency_callups(team_id: str, moves: Sequence[Move], players_by_id) -> None:
    """Back-compat wrapper: record emergency call-ups with a news line."""

    record_roster_moves(
        team_id,
        [(m[0], m[1], m[2] if len(m) > 2 else "act") for m in moves],
        players_by_id,
        details="Emergency call-up: fewer than nine healthy position players",
        news=True,
    )


def record_emergency_moves(team_id: str, moves: Sequence[Move], players_by_id) -> None:
    """Record :func:`ensure_fieldable_roster` moves with honest labels."""

    ups = [m for m in moves if m[2] == "act"]
    downs = [m for m in moves if m[2] != "act"]
    record_emergency_callups(team_id, ups, players_by_id)
    record_roster_moves(
        team_id, downs, players_by_id,
        details="Optioned to make room for an emergency call-up",
    )


def apply_prospect_bookkeeping(team_id: str, moves: Sequence[Move]) -> None:
    """Service-time / option / auto-protect bookkeeping for automatic moves,
    as the injury path and the monthly call-ups already do. Best effort: a
    no-op when prospect rules are off."""

    try:
        from services.prospect_rules import apply_roster_move, evaluate_roster_move
    except Exception:  # pragma: no cover - defensive
        return
    for pid, from_level, to_level in moves:
        try:
            decision = evaluate_roster_move(team_id, pid, from_level=from_level, to_level=to_level)
            if decision.allowed:
                apply_roster_move(
                    team_id, pid, from_level=from_level, to_level=to_level,
                    decision=decision, actor="system", trigger="roster_fill",
                )
        except Exception:
            continue


def prepare_teams_for_game(team_ids: Iterable[str]) -> None:
    """Emergency only, before a game outside the season loop (playoffs).

    The regular season readies rosters before each day; a playoff game had
    no such step, so a club left short by an injury could not field nine and
    the series could not advance. Every club, owner or CPU: decision 14 rule 4.
    A CPU club that calls someone up then options pitchers to stay within the
    size cap and the pitcher limit; when ownership can't be read every club
    is treated as an owner's.
    """

    try:
        from services.team_ownership import human_owned_team_ids_strict
        from utils.player_loader import load_players_from_csv
        from utils.roster_loader import active_roster_cap, load_roster, save_roster
    except Exception:  # pragma: no cover - defensive
        return
    try:
        players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
    except Exception:
        return
    try:
        human_ids = human_owned_team_ids_strict()
        cap = active_roster_cap()
    except Exception:  # pragma: no cover - defensive
        human_ids, cap = None, None
    for team_id in team_ids:
        try:
            roster = load_roster(team_id)
            cpu = human_ids is not None and str(team_id).upper() not in human_ids
            moves = ensure_fieldable_roster(
                team_id, roster, players, cpu_owned=cpu, cap=cap
            )
            if moves:
                save_roster(team_id, roster)
                record_emergency_moves(team_id, moves, players)
                apply_prospect_bookkeeping(team_id, moves)
        except Exception:
            continue
