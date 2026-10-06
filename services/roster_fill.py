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
"""

from __future__ import annotations

import ast
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from services.roster_validation import MIN_POSITION_PLAYERS_ACT
from utils.pitcher_role import get_role

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
    "prepare_teams_for_game",
]

#: A game needs nine position players.
MIN_FIELDABLE_HITTERS = 9
#: Automatic moves never leave fewer active position players than this: one
#: above the season gate's minimum, so an injury can still be covered. Derived
#: so the 26-man change (decision 8) moves it with the gate.
HITTER_FLOOR = MIN_POSITION_PLAYERS_ACT + 1
#: When a CPU club must send a pitcher down to make room for a hitter, keep at
#: least this many active pitchers (the call-up module's comfort line).
PITCHER_KEEP = 11
#: CPU clubs aim for this many active position players when filling.
HITTER_TARGET = 13

Move = Tuple[str, str, str]  # (player_id, from_level, to_level)


def is_pitcher(player: object) -> bool:
    """True for anyone the game treats as a pitcher."""

    if player is None:
        return False
    if str(getattr(player, "primary_position", "") or "").strip().upper() == "P":
        return True
    return get_role(player) in {"SP", "RP"}


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
) -> List[tuple]:
    """Ordered ``(player_id, from_level)`` candidates for one promotion.

    Tiers, each AAA before Low-A and best player first:
    1. players the depth chart lists for ``position``, in chart order;
    2. players who can play ``position``;
    3. any healthy player of the right type -- skipped when ``position_only``
       (an owner's club gets a player for the open position or nobody).

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


def _option(roster: object, pid: str, moves: List[Move]) -> None:
    roster.act.remove(pid)
    roster.aaa.append(pid)
    moves.append((pid, "act", "aaa"))


def _weakest(ids: Sequence[str], players: Mapping[str, object]) -> Optional[str]:
    if not ids:
        return None
    return min(ids, key=lambda pid: player_score(players.get(pid)))


def _is_catcher(player: object) -> bool:
    return (
        player is not None
        and not is_pitcher(player)
        and str(getattr(player, "primary_position", "") or "").strip().upper() == "C"
    )


def _healthy_catchers(ids: Sequence[str], players: Mapping[str, object]) -> List[str]:
    return [p for p in ids if _is_catcher(players.get(p)) and _available(players.get(p))]


def choose_send_down(
    roster: object,
    players: Mapping[str, object],
    *,
    exclude: Iterable[str] = (),
    allowed: Optional[Callable[[str], bool]] = None,
) -> Optional[str]:
    """Who to option when the active roster is over the cap.

    By composition, not by type of whoever just arrived: a pitcher when the
    staff is oversized or position players are at the floor, otherwise the
    weakest position player. Never the club's last healthy catcher (a
    pitcher-heavy CPU club once optioned its only catcher this way). Players
    in ``exclude`` (the man just activated) and those ``allowed`` vetoes
    (option limits) are skipped.
    """

    skip = {str(p) for p in exclude or ()}
    act = [p for p in roster.act if p not in skip]
    hitters = _hitters(act, players)
    arms = _pitchers(act, players)
    catchers = _healthy_catchers(list(roster.act), players)

    def _ok(pid: str) -> bool:
        if pid in catchers and len(catchers) <= 1:
            return False
        return allowed is None or allowed(pid)

    if len(arms) > PITCHER_KEEP + 2 or len(hitters) <= HITTER_FLOOR:
        order = (arms, hitters)
    else:
        order = (hitters, arms)
    for pool in order:
        pool = [p for p in pool if _ok(p)]
        if pool:
            return _weakest(pool, players)
    return None


def _best_callup(roster, players, *, want_pitcher, allowed, fallback_unrestricted=False):
    cands = callup_candidates(roster, players, want_pitcher=want_pitcher, allowed=allowed)
    if not cands and fallback_unrestricted and allowed is not None:
        cands = callup_candidates(roster, players, want_pitcher=want_pitcher)
    return cands[0] if cands else None


def ensure_fieldable_roster(
    team_id: str,
    roster: object,
    players_by_id: Mapping[str, object],
    *,
    allowed: Optional[Callable[[str, str], bool]] = None,
    cpu_owned: bool = False,
    cap: Optional[int] = None,
) -> List[Move]:
    """Emergency only: promote own minor-league hitters until nine are active.

    A game needs nine position players. When injuries leave fewer on the
    active roster, the team calls up its own best healthy AAA (then Low-A)
    position players -- never another club's, which is what the lineup fill
    used to reach for (audit H9). Owner teams included: the alternative is a
    game that cannot be played (decision 14, step 4). Prospect rules are
    honoured first and only overridden if the club would otherwise be short.
    A CPU club then options its weakest surplus pitchers to stay under
    ``cap``. Mutates ``roster``; returns the moves for the caller to save and
    record.
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
        while len(roster.act) > cap:
            arms = _pitchers(roster.act, players_by_id)
            if len(arms) <= PITCHER_KEEP:
                break
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
) -> List[Move]:
    """Keep a CPU club's active roster legal, full and balanced.

    Nothing refilled a CPU club's active roster once ``load_roster`` stopped
    topping it up silently: an uneven trade, a cut, or an injury with no
    like-for-like call-up left it short for good, and a roster that had
    already drifted pitcher-heavy (H9) stayed that way. Run before each sim
    and after each day:

    1. repair: while fewer than ``HITTER_FLOOR`` position players are active,
       swap the weakest surplus pitcher for the best minor-league hitter;
    2. fill: up to ``target_size``, a hitter while below ``HITTER_TARGET``
       position players, otherwise a pitcher;
    3. trim: while over ``cap``, option the weakest player of the type the
       roster has too many of.

    CPU clubs only -- an owner's roster is the owner's. Mutates ``roster``.
    """

    moves: List[Move] = []
    players = players_by_id

    # 0. a catcher: a club with none healthy on the active roster calls one up
    if not _healthy_catchers(list(roster.act), players):
        cands = callup_candidates(
            roster, players, want_pitcher=False, position="C",
            allowed=allowed, position_only=True,
        )
        if cands:
            if len(roster.act) >= cap:
                victim = choose_send_down(roster, players)
                if victim is not None:
                    _option(roster, victim, moves)
            if len(roster.act) < cap:
                _promote(roster, cands[0][0], cands[0][1], moves)

    # 1. repair a pitcher-heavy drift
    while len(_hitters(roster.act, players)) < HITTER_FLOOR:
        pick = _best_callup(roster, players, want_pitcher=False, allowed=allowed)
        if pick is None:
            break
        if len(roster.act) >= target_size:
            arms = _pitchers(roster.act, players)
            if len(arms) <= PITCHER_KEEP:
                break
            _option(roster, _weakest(arms, players), moves)
        _promote(roster, pick[0], pick[1], moves)

    # 2. fill to the target size
    while len(roster.act) < target_size:
        want_pitcher = len(_hitters(roster.act, players)) >= HITTER_TARGET
        pick = _best_callup(roster, players, want_pitcher=want_pitcher, allowed=allowed)
        if pick is None:
            pick = _best_callup(roster, players, want_pitcher=not want_pitcher, allowed=allowed)
        if pick is None:
            break
        _promote(roster, pick[0], pick[1], moves)

    # 3. trim to the cap
    while len(roster.act) > cap:
        victim = choose_send_down(roster, players)
        if victim is None:
            break
        _option(roster, victim, moves)
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
    for pid, from_level, to_level in moves:
        player = players_by_id.get(pid)
        name = f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip() or pid
        try:
            record_transaction(
                action="assign",
                team_id=team_id,
                player_id=pid,
                player_name=name,
                from_level=str(from_level).upper(),
                to_level=str(to_level).upper(),
                details=details,
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
    """

    try:
        from utils.player_loader import load_players_from_csv
        from utils.roster_loader import load_roster, save_roster
    except Exception:  # pragma: no cover - defensive
        return
    try:
        players = {p.player_id: p for p in load_players_from_csv("data/players.csv")}
    except Exception:
        return
    for team_id in team_ids:
        try:
            roster = load_roster(team_id)
            moves = ensure_fieldable_roster(team_id, roster, players)
            if moves:
                save_roster(team_id, roster)
                record_emergency_moves(team_id, moves, players)
                apply_prospect_bookkeeping(team_id, moves)
        except Exception:
            continue
