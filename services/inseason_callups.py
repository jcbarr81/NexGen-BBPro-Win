"""In-season AAA->ACT callups + September roster expansion (S2-11).

The offseason promoter (``services.prospect_promotion``) runs once per year;
this module adds the *in-season* lane: a monthly, outlook-weighted,
protection/option-aware callup check wired into the sim's post-day
automations, plus September 1 expansion (26 -> 28, at most 14 pitchers) with
a revert at the REGULAR_SEASON -> PLAYOFFS edge. Automated moves apply to CPU
teams only -- ownership read strictly, so an unreadable ``users.txt`` means
no moves at all; human owners manage their own rosters. The one exception is
the revert, which options every club (owners included) back to 26 active and
13 pitchers, each move logged.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from playbalance.aging import calculate_age
from services.prospect_promotion import (
    AAA_TO_ACT_BLUECHIP_OVR,
    _player_overall,
    evaluate_promotion,
)
from services.prospect_rules import (
    apply_roster_move,
    evaluate_roster_move,
    is_player_protected,
)
from services.team_outlook import (
    OUTLOOK_CONTEND,
    OUTLOOK_REBUILD,
    load_outlooks,
)
from services.team_ownership import human_owned_team_ids_strict
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import (
    ACTIVE_ROSTER_SIZE,
    MIN_ACTIVE_PITCHERS,
    active_pitcher_cap,
    active_roster_cap,
    load_roster,
    save_roster,
)
from utils.roster_rules import MAX_ACTIVE_PITCHERS, counts_as_pitcher
from utils.team_loader import load_teams
from utils.trade_utils import trade_deadline_for_year

__all__ = [
    "run_monthly_callups",
    "run_september_expansion",
    "revert_september_expansion",
]

CALLUP_STATE_FILENAME = "callup_state.json"
VERSION = 1
_HITTER_POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
# Fewer active arms than this is a pitching hole: one under the 13-pitcher
# limit, matching the trade evaluator's need line.
_PITCHER_COMFORT = MAX_ACTIVE_PITCHERS - 1
# Never leave fewer active position players than this after a swap: one above
# the season gate's minimum (roster_validation.MIN_POSITION_PLAYERS_ACT) so an
# injury can still be covered. Pitcher call-ups with no floor here were one of
# the paths that drifted CPU active rosters to 8 hitters (audit H9).
from services.roster_fill import HITTER_FLOOR as _POSITION_PLAYER_FLOOR  # noqa: E402
_HOLE_PERCENTILE = 0.25


# ---------------------------------------------------------------------------
# Scoring + player helpers


def _is_pitcher(player: object) -> bool:
    return counts_as_pitcher(player)


def _act_pitcher_count(roster: object, players_by_id: Mapping[str, object]) -> int:
    act = list(getattr(roster, "act", []) or [])
    return sum(1 for pid in act if _is_pitcher(players_by_id.get(pid)))


def _primary_pos(player: object) -> str:
    return str(getattr(player, "primary_position", "") or "").strip().upper()


def _num(player: object, key: str) -> float:
    try:
        return float(getattr(player, key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _hitter_score(player: object) -> float:
    # Duplicated from utils.lineup_autofill.hitter_score (a closure; do not
    # refactor that module here).
    ch, ph = _num(player, "ch"), _num(player, "ph")
    return (
        0.6 * (0.5 * ch + 0.5 * ph)
        + 0.2 * _num(player, "sp")
        + 0.2 * (0.5 * _num(player, "fa") + 0.5 * _num(player, "arm"))
    )


def _pitcher_score(player: object) -> float:
    vals = [_num(player, k) for k in ("arm", "control", "movement", "endurance")]
    vals = [v for v in vals if v > 0]
    return sum(vals) / len(vals) if vals else 0.0


def _score(player: object) -> float:
    return _pitcher_score(player) if _is_pitcher(player) else _hitter_score(player)


def _player_age(player: object) -> int | None:
    bd = getattr(player, "birthdate", None)
    if not bd:
        return None
    try:
        return calculate_age(str(bd))
    except Exception:
        return None


def _name(player: object, pid: str) -> str:
    first = str(getattr(player, "first_name", "") or "")
    last = str(getattr(player, "last_name", "") or "")
    return f"{first} {last}".strip() or pid


# ---------------------------------------------------------------------------
# State + team classification


def _rules_path(data_dir: Path) -> Path:
    return data_dir / "prospect_rules.json"


def _state_path(data_dir: Path) -> Path:
    return data_dir / CALLUP_STATE_FILENAME


def _load_state(data_dir: Path) -> dict:
    path = _state_path(data_dir)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {"version": VERSION, "leagues": {}}


def _write_state(payload: Mapping, data_dir: Path) -> None:
    path = _state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")


def _human_team_ids(data_dir: Path) -> set[str] | None:
    """Team ids with a real (human) owner, or None when that can't be read.

    The strict reader: the old private copy returned an empty set when
    ``users.txt`` could not be read, which made every owner's club look CPU
    and let the call-ups move its players.
    """

    try:
        return human_owned_team_ids_strict(data_dir)
    except Exception:
        return None


def _current_phase_is_regular_season() -> bool:
    try:
        from playbalance.season_manager import SeasonManager, SeasonPhase

        return SeasonManager().phase == SeasonPhase.REGULAR_SEASON
    except Exception:
        return True  # fail toward running (the sim caller already gates)


def _record(action, **kwargs) -> None:
    try:
        from services.transaction_log import record_transaction

        record_transaction(action=action, **kwargs)
    except Exception:
        pass


def _news(message: str, *, category: str, team_id: str, data_dir: Path) -> None:
    try:
        from utils.news_logger import log_news_event

        log_news_event(
            message,
            category=category,
            team_id=team_id,
            file_path=data_dir / "news_feed.txt",
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Hole detection + demotion selection


def _percentile(values: Sequence[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[max(0, int(pct * (len(ordered) - 1)))]


def _build_hole_table(
    cpu_team_ids: Sequence[str],
    rosters: Mapping[str, object],
    players_by_id: Mapping[str, object],
) -> dict[str, dict[str, bool]]:
    """{team_id: {position: is_hole}} for hitter positions, keyed off the
    league's 25th-percentile per-team-best ACT score at each position."""

    team_best: dict[str, dict[str, float | None]] = {}
    for team_id in cpu_team_ids:
        roster = rosters.get(team_id)
        act = list(getattr(roster, "act", []) or [])
        best: dict[str, float | None] = {pos: None for pos in _HITTER_POSITIONS}
        for pid in act:
            player = players_by_id.get(pid)
            if player is None or _is_pitcher(player):
                continue
            pos = _primary_pos(player)
            if pos not in best:
                continue
            score = _hitter_score(player)
            if best[pos] is None or score > best[pos]:
                best[pos] = score
        team_best[team_id] = best

    thresholds: dict[str, float] = {}
    for pos in _HITTER_POSITIONS:
        vals = [team_best[t][pos] for t in cpu_team_ids if team_best[t][pos] is not None]
        thresholds[pos] = _percentile(vals, _HOLE_PERCENTILE) if vals else 0.0

    holes: dict[str, dict[str, bool]] = {}
    for team_id in cpu_team_ids:
        holes[team_id] = {
            pos: (team_best[team_id][pos] is None)
            or (team_best[team_id][pos] < thresholds[pos])
            for pos in _HITTER_POSITIONS
        }
    return holes


def _has_pitching_hole(roster: object, players_by_id: Mapping[str, object]) -> bool:
    act = list(getattr(roster, "act", []) or [])
    count = sum(1 for pid in act if _is_pitcher(players_by_id.get(pid)))
    return count < _PITCHER_COMFORT


def _select_demotion_candidate(
    team_id: str,
    roster: object,
    players_by_id: Mapping[str, object],
    *,
    data_dir: Path,
    incoming_is_catcher: bool = False,
    incoming_is_hitter: bool = False,
    force: bool = False,
    pitchers_only: bool = False,
) -> str | None:
    """Pick the worst-score demotable ACT player (D7). ``force`` skips the
    protection + option gates (used by the September revert as a last resort).

    ``pitchers_only`` limits the choice to pitchers (an incoming arm at the
    pitcher limit, or a staff over it).
    """

    act = list(getattr(roster, "act", []) or [])
    pitcher_count = sum(1 for pid in act if _is_pitcher(players_by_id.get(pid)))
    hitter_count = sum(
        1 for pid in act if players_by_id.get(pid) is not None
        and not _is_pitcher(players_by_id.get(pid))
    )
    catcher_count = sum(
        1
        for pid in act
        if not _is_pitcher(players_by_id.get(pid))
        and _primary_pos(players_by_id.get(pid)) == "C"
    )
    rules_path = _rules_path(data_dir)

    candidates: list[tuple[float, str]] = []
    for pid in act:
        player = players_by_id.get(pid)
        if player is None:
            continue
        if getattr(player, "injured", False):
            continue
        if pitchers_only and not _is_pitcher(player):
            continue
        if _is_pitcher(player) and pitcher_count <= MIN_ACTIVE_PITCHERS:
            continue
        if (
            not _is_pitcher(player)
            and hitter_count - 1 + (1 if incoming_is_hitter else 0) < _POSITION_PLAYER_FLOOR
        ):
            continue
        if _primary_pos(player) == "C" and not _is_pitcher(player):
            # Keep at least one catcher post-move (the incoming callup counts).
            if catcher_count - 1 + (1 if incoming_is_catcher else 0) < 1:
                continue
        if not force:
            if is_player_protected(team_id, pid, path=rules_path):
                continue
            decision = evaluate_roster_move(
                team_id, pid, from_level="act", to_level="aaa", path=rules_path
            )
            if not decision.allowed:
                continue
        candidates.append((_score(player), pid))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1]


# ---------------------------------------------------------------------------
# Public API


def _demote(
    team_id: str,
    roster: object,
    victim: str,
    players_by_id: Mapping[str, object],
    *,
    data_dir: Path,
    current: str | None,
    trigger: str,
    force: bool = False,
    details: str = "Sent down to open a roster spot",
) -> dict:
    player = players_by_id.get(victim)
    name = _name(player, victim)
    roster.move_player(victim, "act", "aaa")
    try:
        apply_roster_move(
            team_id,
            victim,
            from_level="act",
            to_level="aaa",
            actor="system",
            trigger=trigger,
            path=_rules_path(data_dir),
        )
    except Exception:
        pass
    _record(
        "demote",
        team_id=team_id,
        player_id=victim,
        player_name=name,
        from_level="ACT",
        to_level="AAA",
        details=details,
        season_date=current,
    )
    _news(f"{team_id} option {name} to AAA.", category="demotion", team_id=team_id, data_dir=data_dir)
    return {"team_id": team_id, "player_id": victim, "forced": force}


def _promote(
    team_id: str,
    roster: object,
    pid: str,
    player: object,
    *,
    data_dir: Path,
    current: str | None,
    detail_suffix: str,
    outlook: str,
) -> dict:
    age = _player_age(player)
    overall = _player_overall(player)
    pos = _primary_pos(player) or "?"
    name = _name(player, pid)
    decision = evaluate_roster_move(
        team_id, pid, from_level="aaa", to_level="act", path=_rules_path(data_dir)
    )
    roster.move_player(pid, "aaa", "act")
    try:
        apply_roster_move(
            team_id,
            pid,
            from_level="aaa",
            to_level="act",
            decision=decision,
            actor="system",
            trigger="inseason_callup",
            path=_rules_path(data_dir),
        )
    except Exception:
        pass
    _record(
        "promote",
        team_id=team_id,
        player_id=pid,
        player_name=name,
        from_level="AAA",
        to_level="ACT",
        details=f"Called up ({outlook}{detail_suffix}, OVR {overall})",
        season_date=current,
    )
    _news(
        f"{team_id} called up to the majors: {pos} {name} (age {age}, OVR {overall}).",
        category="promotion",
        team_id=team_id,
        data_dir=data_dir,
    )
    return {
        "team_id": team_id,
        "player_id": pid,
        "position": pos,
        "age": age,
        "overall": overall,
        "outlook": outlook,
    }


def _eligible_aaa(roster: object, players_by_id: Mapping[str, object]) -> list[tuple[str, object, int]]:
    out: list[tuple[str, object, int]] = []
    for pid in list(getattr(roster, "aaa", []) or []):
        player = players_by_id.get(pid)
        if player is None or getattr(player, "injured", False):
            continue
        overall = _player_overall(player)
        age = _player_age(player)
        if evaluate_promotion(current_level="AAA", age=age, overall=overall) == "ACT":
            out.append((pid, player, overall))
    out.sort(key=lambda item: item[2], reverse=True)
    return out


def run_monthly_callups(
    *,
    played_dates: Sequence[str],
    data_dir: Path | None = None,
    league_id: str | None = None,
) -> dict:
    """Idempotent monthly AAA->ACT callup check for CPU teams."""

    resolved = Path(data_dir) if data_dir is not None else get_data_dir()
    dates = [str(d).strip() for d in (played_dates or []) if str(d).strip()]
    if not dates:
        return {"applied": False, "reason": "no_dates"}
    current = dates[-1]
    month_key = current[:7]
    clean_league_id = str(league_id or "league").strip() or "league"

    state = _load_state(resolved)
    leagues = state.setdefault("leagues", {})
    league_state = leagues.setdefault(clean_league_id, {})
    if str(league_state.get("last_check_month") or "") == month_key:
        return {"applied": False, "reason": "already_ran", "month": month_key}

    if not _current_phase_is_regular_season():
        return {"applied": False, "reason": "phase_blocked", "month": month_key}

    try:
        players_by_id = {
            str(getattr(p, "player_id", "") or ""): p
            for p in load_players_from_csv(resolved / "players.csv")
        }
        teams = load_teams(resolved / "teams.csv")
    except Exception as exc:
        return {"applied": False, "reason": f"load_failed:{exc}", "month": month_key}

    human = _human_team_ids(resolved)
    if human is None:
        # Ownership unreadable: never guess which clubs are CPU. Not marked
        # as run, so the next day's check tries again.
        return {"applied": False, "reason": "ownership_unknown", "month": month_key}
    cpu_team_ids = [
        str(getattr(t, "team_id", "") or "").strip().upper()
        for t in teams
        if str(getattr(t, "team_id", "") or "").strip().upper() not in human
    ]
    cpu_team_ids = [t for t in cpu_team_ids if t]

    outlooks = load_outlooks(data_dir=resolved)
    rosters = {t: load_roster(t, resolved / "rosters") for t in cpu_team_ids}
    holes = _build_hole_table(cpu_team_ids, rosters, players_by_id)

    try:
        past_deadline = date.fromisoformat(current) > trade_deadline_for_year(
            int(current[:4])
        )
    except Exception:
        past_deadline = False

    promotions: list[dict] = []
    demotions: list[dict] = []
    filtered = {
        "no_candidates": 0,
        "blocked_by_rules": 0,
        "no_roster_space": 0,
        "not_a_hole": 0,
    }

    for team_id in cpu_team_ids:
        roster = rosters[team_id]
        outlook = str(outlooks.get(team_id, "bubble") or "bubble")
        candidates = _eligible_aaa(roster, players_by_id)
        if not candidates:
            filtered["no_candidates"] += 1
            continue

        if outlook == OUTLOOK_REBUILD:
            quota = 2 if past_deadline else 1
            require_hole = not past_deadline
            bluechip_only = False
        elif outlook == OUTLOOK_CONTEND:
            quota, require_hole, bluechip_only = 1, True, False
        else:  # bubble
            quota, require_hole, bluechip_only = 1, True, True

        promoted_here = 0
        changed = False
        for pid, player, overall in candidates:
            if promoted_here >= quota:
                break
            if bluechip_only and overall < AAA_TO_ACT_BLUECHIP_OVR:
                continue
            if require_hole:
                if _is_pitcher(player):
                    if not _has_pitching_hole(roster, players_by_id):
                        filtered["not_a_hole"] += 1
                        continue
                else:
                    if not holes.get(team_id, {}).get(_primary_pos(player), False):
                        filtered["not_a_hole"] += 1
                        continue

            decision = evaluate_roster_move(
                team_id, pid, from_level="aaa", to_level="act", path=_rules_path(resolved)
            )
            if not decision.allowed:
                filtered["blocked_by_rules"] += 1
                continue

            # A pitcher coming up to a staff at the limit swaps for a
            # pitcher, even with an open roster spot; a staff already over
            # the limit gives up a pitcher whoever comes up.
            arms = _act_pitcher_count(roster, players_by_id)
            arm_cap = active_pitcher_cap(current)
            arms_full = _is_pitcher(player) and arms >= arm_cap
            if arms_full or len(getattr(roster, "act", []) or []) >= active_roster_cap(current):
                victim = _select_demotion_candidate(
                    team_id,
                    roster,
                    players_by_id,
                    data_dir=resolved,
                    incoming_is_catcher=(_primary_pos(player) == "C"),
                    incoming_is_hitter=not _is_pitcher(player),
                    pitchers_only=arms_full or arms > arm_cap,
                )
                if victim is None:
                    filtered["no_roster_space"] += 1
                    continue
                demotions.append(
                    _demote(
                        team_id,
                        roster,
                        victim,
                        players_by_id,
                        data_dir=resolved,
                        current=current,
                        trigger="inseason_callup_demotion",
                    )
                )
                changed = True

            suffix = ", post-deadline" if (outlook == OUTLOOK_REBUILD and past_deadline) else ""
            promotions.append(
                _promote(
                    team_id,
                    roster,
                    pid,
                    player,
                    data_dir=resolved,
                    current=current,
                    detail_suffix=suffix,
                    outlook=outlook,
                )
            )
            promoted_here += 1
            changed = True

        if changed:
            try:
                save_roster(team_id, roster, roster_dir=resolved / "rosters")
            except Exception:
                pass

    # September expansion within the same run.
    if current[5:7] in {"09", "10"}:
        run_september_expansion(sim_date=current, data_dir=resolved)

    league_state["last_check_month"] = month_key
    _write_state(state, resolved)
    return {
        "applied": bool(promotions or demotions),
        "reason": "ok",
        "month": month_key,
        "promotions": promotions,
        "demotions": demotions,
        "teams_checked": len(cpu_team_ids),
        "filtered": filtered,
    }


def run_september_expansion(*, sim_date: str, data_dir: Path | None = None) -> dict:
    """Fill every CPU team toward the (expanded) active cap with its best
    remaining eligible AAA players — no hole requirement, no demotions.

    26 -> 28; pitchers stop at the September limit (14), so the extra spots
    go to position players once the staff is full.
    """

    resolved = Path(data_dir) if data_dir is not None else get_data_dir()
    cap = active_roster_cap(sim_date)
    if cap <= ACTIVE_ROSTER_SIZE:
        return {"applied": False, "reason": "not_expanded", "promotions": []}
    pitcher_cap = active_pitcher_cap(sim_date)

    try:
        players_by_id = {
            str(getattr(p, "player_id", "") or ""): p
            for p in load_players_from_csv(resolved / "players.csv")
        }
        teams = load_teams(resolved / "teams.csv")
    except Exception as exc:
        return {"applied": False, "reason": f"load_failed:{exc}", "promotions": []}

    human = _human_team_ids(resolved)
    if human is None:
        return {"applied": False, "reason": "ownership_unknown", "promotions": []}
    cpu_team_ids = [
        t
        for t in (
            str(getattr(x, "team_id", "") or "").strip().upper() for x in teams
        )
        if t and t not in human
    ]

    promotions: list[dict] = []
    for team_id in cpu_team_ids:
        roster = load_roster(team_id, resolved / "rosters")
        changed = False
        for pid, player, overall in _eligible_aaa(roster, players_by_id):
            if len(getattr(roster, "act", []) or []) >= cap:
                break
            if _is_pitcher(player) and _act_pitcher_count(roster, players_by_id) >= pitcher_cap:
                continue
            decision = evaluate_roster_move(
                team_id, pid, from_level="aaa", to_level="act", path=_rules_path(resolved)
            )
            if not decision.allowed:
                continue
            promotions.append(
                _promote(
                    team_id,
                    roster,
                    pid,
                    player,
                    data_dir=resolved,
                    current=sim_date,
                    detail_suffix=", September",
                    outlook="expansion",
                )
            )
            changed = True
        if changed:
            try:
                save_roster(team_id, roster, roster_dir=resolved / "rosters")
            except Exception:
                pass

    return {"applied": bool(promotions), "reason": "ok", "promotions": promotions}


def revert_september_expansion(*, data_dir: Path | None = None) -> dict:
    """Trim every team (CPU and human) back to 26 active and 13 pitchers.

    Runs at the REGULAR_SEASON -> PLAYOFFS edge. Owners' clubs included: a
    documented exception to "CPU never touches an owner's roster" (decision
    8), and only ever by optioning to AAA, never a release. First the size
    (worst-scoring demotable player), then -- while more than 13 pitchers
    are active -- the worst pitcher. Option and protection rules are honoured
    until nobody else is left, then overridden; every move is a logged
    transaction.
    """

    resolved = Path(data_dir) if data_dir is not None else get_data_dir()
    try:
        players_by_id = {
            str(getattr(p, "player_id", "") or ""): p
            for p in load_players_from_csv(resolved / "players.csv")
        }
        teams = load_teams(resolved / "teams.csv")
    except Exception as exc:
        return {"applied": False, "reason": f"load_failed:{exc}", "demotions": []}

    demotions: list[dict] = []
    for team in teams:
        team_id = str(getattr(team, "team_id", "") or "").strip().upper()
        if not team_id:
            continue
        try:
            roster = load_roster(team_id, resolved / "rosters")
        except Exception:
            continue
        changed = False
        guard = 0
        while guard < 40:
            over_size = len(getattr(roster, "act", []) or []) > ACTIVE_ROSTER_SIZE
            over_arms = _act_pitcher_count(roster, players_by_id) > MAX_ACTIVE_PITCHERS
            if not (over_size or over_arms):
                break
            guard += 1
            victim = _select_demotion_candidate(
                team_id, roster, players_by_id, data_dir=resolved,
                pitchers_only=over_arms,
            )
            forced = False
            if victim is None:
                victim = _select_demotion_candidate(
                    team_id, roster, players_by_id, data_dir=resolved, force=True,
                    pitchers_only=over_arms,
                )
                forced = True
            if victim is None:
                break
            detail = (
                f"Optioned for the postseason: over the {MAX_ACTIVE_PITCHERS}-pitcher limit"
                if over_arms and not over_size
                else f"Optioned for the postseason: back to the {ACTIVE_ROSTER_SIZE}-man roster"
            )
            demotions.append(
                _demote(
                    team_id,
                    roster,
                    victim,
                    players_by_id,
                    data_dir=resolved,
                    current=None,
                    trigger="september_revert_forced" if forced else "september_revert",
                    force=forced,
                    details=detail,
                )
            )
            changed = True
        if changed:
            try:
                save_roster(team_id, roster, roster_dir=resolved / "rosters")
            except Exception:
                pass

    return {"applied": bool(demotions), "reason": "ok", "demotions": demotions}
