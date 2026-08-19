"""CPU proactive trade proposal generation with cadence controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import random
from typing import Mapping, Sequence
import uuid

from models.trade import Trade
from services.cpu_trade_evaluator import evaluate_cpu_trade_offer
from services.trade_settings import load_trade_settings
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster
from utils.sim_date import get_current_sim_date
from utils.team_loader import load_teams
from utils.trade_utils import load_trades, save_trade, trade_deadline_for_year
from utils.user_manager import load_users
from services.team_outlook import load_outlooks, OUTLOOK_CONTEND, OUTLOOK_REBUILD

__all__ = ["run_cpu_trade_proposal_cycle"]

CPU_OWNER_IDS = {"", "cpu", "ai", "none", "computer", "bot"}
PROPOSAL_STATE_FILENAME = "cpu_trade_proposal_state.json"
VERSION = 1

_CADENCE_CONFIG = {
    "off": {
        "min_days_between": 999_999,
        "min_days_between_target": 999_999,
        "daily_chance": 0.0,
        "max_offers_per_run": 0,
        "max_pending_per_target": 0,
        "min_score_margin": 9_999.0,
    },
    "low": {
        "min_days_between": 21,
        "min_days_between_target": 14,
        "daily_chance": 0.25,
        "max_offers_per_run": 1,
        "max_pending_per_target": 1,
        "min_score_margin": 0.20,
    },
    "normal": {
        "min_days_between": 10,
        "min_days_between_target": 8,
        "daily_chance": 0.45,
        "max_offers_per_run": 2,
        "max_pending_per_target": 1,
        "min_score_margin": 0.14,
    },
    "high": {
        "min_days_between": 4,
        "min_days_between_target": 4,
        "daily_chance": 0.75,
        "max_offers_per_run": 3,
        "max_pending_per_target": 1,
        "min_score_margin": 0.10,
    },
}

_MAX_PENDING_CPU_OFFERS_TOTAL = 8
_REPEAT_PACKAGE_BLOCK_DAYS = 45
_PACKAGE_HISTORY_RETENTION_DAYS = 180

# S2-09 deadline-aware shaping.
_DEADLINE_REWEIGHT_DAYS = 30       # timeline reweight + pool-shaping window
_DEADLINE_VOLUME_DAYS = 14         # cadence-boost window
_DEADLINE_CADENCE_MULT = 2.0       # daily_chance multiplier in the last 14 days
_DEADLINE_TIMELINE_FACTOR = 1.5    # 0.12 -> 0.18 effective timeline weight
_VETERAN_AGE = 28                  # "veteran" for pool shaping
_YOUTH_AGE = 25                    # "youth" for pool shaping

# S2-10 CPU-to-CPU auto-resolved lane.
_CPU_CPU_MAX_PER_WEEK = 2          # executed deals per rolling 7 sim days
_CPU_CPU_TEAM_COOLDOWN_DAYS = 21   # either party
_CPU_CPU_DAILY_CHANCE = 0.30       # per-cycle gate before any pairing work
_CPU_CPU_OFFER_SHORTLIST = 8       # ranked offers the proposer shops per attempt


@dataclass(frozen=True)
class _CandidateOffer:
    trade: Trade
    score_margin: float
    cpu_team_id: str
    target_team_id: str


def run_cpu_trade_proposal_cycle(
    *,
    simulated_dates: Sequence[str] | None = None,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    rng: random.Random | None = None,
) -> dict[str, object]:
    """Generate proactive CPU trade offers for a simulation update window."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    settings = load_trade_settings(
        path=resolved_data_dir / "trade_settings.json",
        league_id=league_id,
    )
    cadence = str(getattr(settings, "cpu_proposal_cadence", "normal") or "normal").strip().lower()
    cadence_cfg = dict(_CADENCE_CONFIG.get(cadence, _CADENCE_CONFIG["normal"]))
    result: dict[str, object] = {
        "applied": False,
        "reason": "ok",
        "cadence": cadence,
        "offers_created": 0,
        "offers": [],
        "dates_evaluated": list(_unique_dates(simulated_dates)),
        "teams_considered": 0,
        "teams_eligible": 0,
    }

    if not settings.trades_enabled:
        result["reason"] = "trading_disabled"
        return result
    if not settings.cpu_initiated_trades_enabled:
        result["reason"] = "cpu_initiated_disabled"
        return result
    if cadence == "off":
        result["reason"] = "cadence_off"
        return result

    dates = list(_unique_dates(simulated_dates))
    if not dates:
        current = str(get_current_sim_date() or "").strip()
        if current:
            dates = [current]
    if not dates:
        result["reason"] = "no_dates"
        return result

    current_date = _parse_iso_date(dates[-1])
    if current_date is None:
        result["reason"] = "invalid_date"
        return result

    # S2-09: hard-stop the cycle after the July 31 deadline instead of burning
    # save attempts that save_trade would reject anyway. The cycle only runs
    # during REGULAR_SEASON (api/routers/season.py:557), so a plain date check
    # is sufficient — no phase lookup needed.
    deadline = trade_deadline_for_year(current_date.year)
    if current_date > deadline:
        result["reason"] = "past_deadline"
        result["deadline"] = deadline.isoformat()
        return result
    days_to_deadline = (deadline - current_date).days

    teams = load_teams(resolved_data_dir / "teams.csv")
    teams_by_id = {
        str(getattr(team, "team_id", "") or "").strip().upper(): team
        for team in teams
    }
    # Ownership lives in ``users.txt`` (``role == "owner"`` rows pin a
    # user to a team_id). ``teams.csv`` carries an ``owner_id`` column
    # but the league creator currently writes it empty, so reading from
    # there alone classifies every team as CPU and the proposal cycle
    # bails with ``insufficient_teams``. Mirror the same lookup the
    # roster auto-assign service uses, falling back to the teams.csv
    # ``owner_id`` flag when users.txt is empty (legacy/test fixtures).
    human_team_ids = _load_human_team_ids(data_dir=resolved_data_dir)
    if human_team_ids:
        cpu_teams = [
            team_id
            for team_id in teams_by_id.keys()
            if team_id not in human_team_ids
        ]
        human_teams = [
            team_id
            for team_id in teams_by_id.keys()
            if team_id in human_team_ids
        ]
    else:
        cpu_teams = [
            team_id for team_id, team in teams_by_id.items() if _is_cpu_team(team)
        ]
        human_teams = [
            team_id
            for team_id, team in teams_by_id.items()
            if not _is_cpu_team(team)
        ]
    result["teams_considered"] = len(cpu_teams)
    # S2-10: the human-target pass needs at least one CPU + one human team; the
    # CPU-CPU pass needs >= 2 CPU teams. Bail only when BOTH are impossible
    # (e.g. an all-human league, or a single lone CPU team).
    human_pass_possible = bool(cpu_teams and human_teams)
    cpu_cpu_possible = len(cpu_teams) >= 2
    if not human_pass_possible and not cpu_cpu_possible:
        result["reason"] = "insufficient_teams"
        return result

    players = {
        str(getattr(player, "player_id", "") or ""): player
        for player in load_players_from_csv(resolved_data_dir / "players.csv")
    }
    rosters_by_team = _load_rosters(cpu_teams + human_teams, data_dir=resolved_data_dir)
    pending_trades = load_trades(resolved_data_dir / "trades_pending.csv")

    proposal_state = _load_state(data_dir=resolved_data_dir)
    clean_league_id = str(settings.league_id or league_id or "league").strip() or "league"
    leagues = proposal_state.setdefault("leagues", {})
    league_state = leagues.setdefault(clean_league_id, {})
    team_last_offer_dates = _coerce_state_map(
        league_state.get("team_last_offer_dates"),
    )
    target_last_offer_dates = _coerce_state_map(
        league_state.get("target_last_offer_dates"),
    )
    recent_packages = _coerce_recent_packages(
        league_state.get("recent_packages"),
    )
    league_state["team_last_offer_dates"] = team_last_offer_dates
    league_state["target_last_offer_dates"] = target_last_offer_dates
    league_state["recent_packages"] = recent_packages

    randomizer = rng if rng is not None else random.Random()
    cadence_chance = float(cadence_cfg.get("daily_chance", 0.0) or 0.0)
    if 0 <= days_to_deadline <= _DEADLINE_VOLUME_DAYS:
        # Ramp proposal volume into the deadline (e.g. normal 0.45 -> 0.90/day).
        cadence_chance = min(0.95, cadence_chance * _DEADLINE_CADENCE_MULT)
    run_chance = _window_probability(cadence_chance, len(dates))
    min_days_between = int(cadence_cfg.get("min_days_between", 7) or 7)
    min_target_days_between = int(cadence_cfg.get("min_days_between_target", 7) or 7)
    max_offers = int(cadence_cfg.get("max_offers_per_run", 1) or 1)
    max_pending_per_target = int(cadence_cfg.get("max_pending_per_target", 1) or 1)
    min_score_margin = float(cadence_cfg.get("min_score_margin", 0.14) or 0.14)
    pending_cpu_total = _count_pending_cpu_offers(
        pending_trades,
        cpu_team_ids=cpu_teams,
    )
    if pending_cpu_total >= _MAX_PENDING_CPU_OFFERS_TOTAL:
        result["reason"] = "pending_cpu_offer_limit"
        result["pending_cpu_offers"] = pending_cpu_total
        return result
    recent_packages = _prune_recent_packages(
        recent_packages,
        current_date=current_date,
        retention_days=_PACKAGE_HISTORY_RETENTION_DAYS,
    )
    blocked_package_signatures = _blocked_package_signatures(
        recent_packages,
        current_date=current_date,
        block_days=_REPEAT_PACKAGE_BLOCK_DAYS,
    )
    filtered_counts: dict[str, int] = {
        "team_cooldown": 0,
        "target_cooldown": 0,
        "cadence_skip": 0,
        "cpu_pending": 0,
        "target_pending": 0,
        "no_valid_offer": 0,
        "save_failed": 0,
    }

    # S2-09: standings-based outlook per CPU team ({} => everyone "bubble",
    # i.e. behavior identical to the pre-S2-09 standings-blind path).
    outlooks = load_outlooks(data_dir=resolved_data_dir)

    offers: list[dict[str, object]] = []
    eligible_count = 0
    target_offer_counts: dict[str, int] = {}
    for cpu_team_id in randomizer.sample(cpu_teams, len(cpu_teams)):
        if len(offers) >= max_offers:
            break
        last_token = str(team_last_offer_dates.get(cpu_team_id, "") or "").strip()
        last_offer_date = _parse_iso_date(last_token)
        if last_offer_date is not None:
            days_since = (current_date - last_offer_date).days
            if days_since < min_days_between:
                filtered_counts["team_cooldown"] += 1
                continue
        if randomizer.random() > run_chance:
            filtered_counts["cadence_skip"] += 1
            continue
        if _team_has_pending_offer(cpu_team_id, pending_trades):
            filtered_counts["cpu_pending"] += 1
            continue
        eligible_count += 1
        offer = _build_best_offer(
            cpu_team_id=cpu_team_id,
            target_team_ids=human_teams,
            players_by_id=players,
            rosters_by_team=rosters_by_team,
            teams_by_id=teams_by_id,
            pending_trades=pending_trades,
            data_dir=resolved_data_dir,
            rng=randomizer,
            min_score_margin=min_score_margin,
            blocked_packages=blocked_package_signatures,
            target_offer_counts=target_offer_counts,
            pending_target_limit=max_pending_per_target,
            outlook=str(outlooks.get(cpu_team_id, "bubble") or "bubble"),
            days_to_deadline=days_to_deadline,
        )
        if offer is None:
            filtered_counts["no_valid_offer"] += 1
            continue
        target_last_token = str(
            target_last_offer_dates.get(offer.target_team_id, "") or ""
        ).strip()
        target_last_date = _parse_iso_date(target_last_token)
        if target_last_date is not None:
            target_days_since = (current_date - target_last_date).days
            if target_days_since < min_target_days_between:
                filtered_counts["target_cooldown"] += 1
                continue
        pending_target_count = _count_pending_cpu_offers_for_target(
            pending_trades,
            cpu_team_ids=cpu_teams,
            target_team_id=offer.target_team_id,
        )
        pending_target_count += int(target_offer_counts.get(offer.target_team_id, 0) or 0)
        if pending_target_count >= max_pending_per_target:
            filtered_counts["target_pending"] += 1
            continue
        try:
            save_trade(offer.trade, resolved_data_dir / "trades_pending.csv")
        except RuntimeError:
            filtered_counts["save_failed"] += 1
            continue
        pending_trades.append(offer.trade)
        team_last_offer_dates[cpu_team_id] = current_date.isoformat()
        target_last_offer_dates[offer.target_team_id] = current_date.isoformat()
        target_offer_counts[offer.target_team_id] = (
            int(target_offer_counts.get(offer.target_team_id, 0) or 0) + 1
        )
        signature = _offer_package_signature(offer.trade)
        if signature:
            blocked_package_signatures.add(signature)
        recent_packages.append(
            {
                "date": current_date.isoformat(),
                "from_team": offer.trade.from_team,
                "to_team": offer.trade.to_team,
                "give_player_ids": list(offer.trade.give_player_ids),
                "receive_player_ids": list(offer.trade.receive_player_ids),
                "give_pick_ids": list(getattr(offer.trade, "give_pick_ids", []) or []),
                "receive_pick_ids": list(
                    getattr(offer.trade, "receive_pick_ids", []) or []
                ),
            }
        )
        offers.append(
            {
                "trade_id": offer.trade.trade_id,
                "from_team": offer.trade.from_team,
                "to_team": offer.trade.to_team,
                "give_players": len(offer.trade.give_player_ids),
                "receive_players": len(offer.trade.receive_player_ids),
                "score_margin": round(float(offer.score_margin), 3),
                "proposer_outlook": str(
                    outlooks.get(offer.cpu_team_id, "bubble") or "bubble"
                ),
            }
        )

    # S2-10: CPU-to-CPU auto-resolved lane runs after the human-target pass so
    # it shares every loaded artifact + the single state write below.
    if cpu_cpu_possible:
        cpu_cpu_result = _run_cpu_cpu_pass(
            cpu_teams=cpu_teams,
            players_by_id=players,
            rosters_by_team=rosters_by_team,
            teams_by_id=teams_by_id,
            pending_trades=pending_trades,
            league_state=league_state,
            current_date=current_date,
            days_to_deadline=days_to_deadline,
            outlooks=outlooks,
            data_dir=resolved_data_dir,
            rng=randomizer,
            min_score_margin=min_score_margin,
            blocked_packages=blocked_package_signatures,
            recent_packages=recent_packages,
            settings=settings,
            dates=dates,
        )
        result["cpu_cpu_trades"] = cpu_cpu_result

    _write_state(proposal_state, data_dir=resolved_data_dir)
    result["days_to_deadline"] = days_to_deadline
    result["offers_created"] = len(offers)
    result["offers"] = offers
    result["teams_eligible"] = eligible_count
    result["applied"] = len(offers) > 0
    result["reason"] = "ok"
    result["filtered_counts"] = filtered_counts
    return result


def _build_best_offer(
    *,
    cpu_team_id: str,
    target_team_ids: Sequence[str],
    players_by_id: Mapping[str, object],
    rosters_by_team: Mapping[str, object],
    teams_by_id: Mapping[str, object],
    pending_trades: Sequence[Trade],
    data_dir: Path,
    rng: random.Random,
    min_score_margin: float,
    blocked_packages: set[str],
    target_offer_counts: Mapping[str, int],
    pending_target_limit: int,
    outlook: str = "bubble",
    days_to_deadline: int = 999,
    return_ranked: int = 0,
):
    """Build the best proactive 1-for-1 offer for ``cpu_team_id``.

    Default: return the single highest proposer-margin ``_CandidateOffer`` (or
    None). When ``return_ranked > 0``, instead return a list of up to
    ``return_ranked`` proposer-accepted candidates sorted by margin desc — used
    by the CPU-CPU lane so the proposer can *shop* offers against the receiver
    (the single margin-max offer is systematically the one the receiver likes
    least, so the greedy pick almost never closes; S2-10 acceptance-gate finding)."""

    cpu_roster = list(getattr(rosters_by_team.get(cpu_team_id), "act", []) or [])
    cpu_roster = [pid for pid in cpu_roster if pid in players_by_id]
    if len(cpu_roster) < 5:
        return None

    # S2-09: within 30 days of the deadline a contender/rebuilder shapes its
    # pools + value band toward buying vets / selling vets for youth. Bubble
    # teams and out-of-window days keep the original standings-blind behavior.
    reweight_active = (
        0 <= days_to_deadline <= _DEADLINE_REWEIGHT_DAYS
        and outlook in {OUTLOOK_CONTEND, OUTLOOK_REBUILD}
    )
    timeline_factor = _DEADLINE_TIMELINE_FACTOR if reweight_active else 1.0

    def _value_of(pid: str) -> float:
        return _player_trade_value(players_by_id.get(pid))

    def _age_filter(pids, *, min_age=None, max_age=None):
        kept = []
        for pid in pids:
            age = _player_age(players_by_id.get(pid))
            if age is None:  # missing age passes no filter
                continue
            if min_age is not None and age < min_age:
                continue
            if max_age is not None and age > max_age:
                continue
            kept.append(pid)
        return kept if len(kept) >= 3 else list(pids)  # fall back when < 3 names

    if reweight_active and outlook == OUTLOOK_CONTEND:
        # Buyer: shop own youth first, chase the target's veterans; overpay band.
        send_candidates = sorted(
            cpu_roster,
            key=lambda pid: (
                0 if (_player_age(players_by_id.get(pid)) or 99) <= _YOUTH_AGE else 1,
                _value_of(pid),
            ),
        )[:10]
        band_low, band_high = 0.82, 1.35
    elif reweight_active and outlook == OUTLOOK_REBUILD:
        # Seller: shop own best veterans, ask for youth; discount band.
        send_candidates = sorted(
            _age_filter(cpu_roster, min_age=_VETERAN_AGE),
            key=_value_of,
            reverse=True,
        )[:10]
        band_low, band_high = 0.70, 1.22
    else:
        send_candidates = sorted(cpu_roster, key=_value_of)[:10]
        band_low, band_high = 0.82, 1.22
    if not send_candidates:
        return [] if return_ranked else None

    best: _CandidateOffer | None = None
    ranked: list[_CandidateOffer] = []
    target_ids = list(target_team_ids)
    if target_ids:
        target_ids = rng.sample(target_ids, len(target_ids))
    for human_team_id in target_ids:
        if _pair_has_pending_offer(cpu_team_id, human_team_id, pending_trades):
            continue
        if int(target_offer_counts.get(human_team_id, 0) or 0) >= pending_target_limit:
            continue
        human_roster = list(getattr(rosters_by_team.get(human_team_id), "act", []) or [])
        human_roster = [pid for pid in human_roster if pid in players_by_id]
        if len(human_roster) < 5:
            continue
        if reweight_active and outlook == OUTLOOK_CONTEND:
            request_pool = _age_filter(human_roster, min_age=_VETERAN_AGE)
        elif reweight_active and outlook == OUTLOOK_REBUILD:
            request_pool = _age_filter(human_roster, max_age=_YOUTH_AGE)
        else:
            request_pool = human_roster
        request_candidates = sorted(request_pool, key=_value_of, reverse=True)[:14]
        if not request_candidates:
            continue

        sampled_send = send_candidates[:]
        if len(sampled_send) > 6:
            sampled_send = rng.sample(sampled_send, 6)
        sampled_receive = request_candidates[:]
        if len(sampled_receive) > 8:
            sampled_receive = rng.sample(sampled_receive, 8)

        for cpu_player_id in sampled_send:
            cpu_value = _player_trade_value(players_by_id.get(cpu_player_id))
            for human_player_id in sampled_receive:
                owner_value = _player_trade_value(players_by_id.get(human_player_id))
                if owner_value <= 0.0 or cpu_value <= 0.0:
                    continue
                if owner_value < cpu_value * band_low:
                    continue
                if owner_value > cpu_value * band_high:
                    continue
                proactive_trade = Trade(
                    trade_id=uuid.uuid4().hex[:8],
                    from_team=cpu_team_id,
                    to_team=human_team_id,
                    give_player_ids=[cpu_player_id],
                    receive_player_ids=[human_player_id],
                    initiated_by="cpu",
                )
                signature = _offer_package_signature(proactive_trade)
                if signature in blocked_packages:
                    continue
                eval_trade = Trade(
                    trade_id=proactive_trade.trade_id,
                    from_team=human_team_id,
                    to_team=cpu_team_id,
                    give_player_ids=[human_player_id],
                    receive_player_ids=[cpu_player_id],
                )
                evaluation = evaluate_cpu_trade_offer(
                    eval_trade,
                    players_by_id=players_by_id,
                    data_dir=data_dir,
                    teams_by_id=teams_by_id,
                    rosters_by_team=rosters_by_team,
                    allow_counter_offers=False,
                    timeline_weight_factor=timeline_factor,
                )
                if evaluation is None:
                    continue
                if str(getattr(evaluation, "action", "")).strip().lower() != "accept":
                    continue
                margin = float(getattr(evaluation, "total_score", 0.0)) - float(
                    getattr(evaluation, "threshold", 0.0)
                )
                if margin < float(min_score_margin):
                    continue
                candidate = _CandidateOffer(
                    trade=proactive_trade,
                    score_margin=margin,
                    cpu_team_id=cpu_team_id,
                    target_team_id=human_team_id,
                )
                if best is None or candidate.score_margin > best.score_margin:
                    best = candidate
                if return_ranked:
                    ranked.append(candidate)

    if return_ranked:
        # Shop the most BALANCED offers first (lowest proposer margin above the
        # min-margin floor). Proposer margin and receiver acceptance are
        # anti-correlated for 1-for-1 swaps, so the proposer's greediest offer is
        # the one the receiver likes least; fair deals close and are realistic
        # (CPU teams should trade fairly, not extract lopsided steals).
        ranked.sort(key=lambda c: c.score_margin)
        return ranked[:return_ranked]
    return best


def _factor_for(outlook: str | None, days_to_deadline: int) -> float:
    """S2-09/S2-10 deadline timeline reweight for an evaluating team."""

    token = str(outlook or "bubble")
    if 0 <= days_to_deadline <= _DEADLINE_REWEIGHT_DAYS and token in {
        OUTLOOK_CONTEND,
        OUTLOOK_REBUILD,
    }:
        return _DEADLINE_TIMELINE_FACTOR
    return 1.0


def _run_cpu_cpu_pass(
    *,
    cpu_teams: Sequence[str],
    players_by_id: Mapping[str, object],
    rosters_by_team: Mapping[str, object],
    teams_by_id: Mapping[str, object],
    pending_trades: list[Trade],
    league_state: dict[str, object],
    current_date: date,
    days_to_deadline: int,
    outlooks: Mapping[str, str],
    data_dir: Path,
    rng: random.Random,
    min_score_margin: float,
    blocked_packages: set[str],
    recent_packages: list[dict[str, object]],
    settings: object,
    dates: Sequence[str],
) -> dict[str, object]:
    """Propose + auto-resolve at most one CPU-to-CPU trade this cycle (S2-10)."""

    from services.roster_validation import validate_trade
    from services.payroll_policy import evaluate_trade_payroll_impact
    from services.trade_execution import commit_trade, announce_trade
    from services.trade_settings import current_league_year

    filtered: dict[str, int] = {
        "weekly_cap": 0,
        "cadence_skip": 0,
        "no_offer": 0,
        "counter_dropped": 0,
        "validation_failed": 0,
        "payroll_blocked": 0,
        "commit_failed": 0,
    }
    executed: list[dict[str, object]] = []

    # State: last-trade dates (cooldown) + rolling execution log (pruned to 30d).
    cpu_cpu_last = _coerce_state_map(league_state.get("cpu_cpu_last_trade_dates"))
    executions = [
        d
        for d in (league_state.get("cpu_cpu_executions") or [])
        if _parse_iso_date(str(d)) is not None
        and 0 <= (current_date - _parse_iso_date(str(d))).days <= 30
    ]
    league_state["cpu_cpu_last_trade_dates"] = cpu_cpu_last
    league_state["cpu_cpu_executions"] = executions

    def _result() -> dict[str, object]:
        return {"executed": executed, "filtered": filtered}

    # Cap 1: rolling weekly execution ceiling.
    recent_execs = [
        d
        for d in executions
        if 0 <= (current_date - _parse_iso_date(str(d))).days < 7
    ]
    if len(recent_execs) >= _CPU_CPU_MAX_PER_WEEK:
        filtered["weekly_cap"] = 1
        return _result()

    # Cap 2: per-cycle cadence gate.
    if rng.random() > _window_probability(_CPU_CPU_DAILY_CHANCE, len(dates)):
        filtered["cadence_skip"] = 1
        return _result()

    def _on_cooldown(team_id: str) -> bool:
        token = str(team_id or "").strip().upper()
        last = _parse_iso_date(str(cpu_cpu_last.get(token, "") or ""))
        if last is None:
            return False
        return (current_date - last).days < _CPU_CPU_TEAM_COOLDOWN_DAYS

    # Players mapping (once) for validate_trade.
    players_map = {
        pid: {
            "is_pitcher": bool(getattr(p, "is_pitcher", False)),
            "primary_position": getattr(p, "primary_position", "") or "",
            "other_positions": list(getattr(p, "other_positions", []) or []),
            "first_name": getattr(p, "first_name", "") or "",
            "last_name": getattr(p, "last_name", "") or "",
        }
        for pid, p in players_by_id.items()
    }

    def _levels(team_id: str) -> dict[str, list[str]]:
        roster = rosters_by_team.get(str(team_id).strip().upper())
        return {
            "act": list(getattr(roster, "act", []) or []),
            "aaa": list(getattr(roster, "aaa", []) or []),
            "low": list(getattr(roster, "low", []) or []),
        }

    trade_settings = {
        "draft_pick_trading_enabled": bool(
            getattr(settings, "draft_pick_trading_enabled", True)
        ),
        "max_pick_trade_years": getattr(settings, "max_pick_trade_years", None),
        "current_year": current_league_year(),
    }

    for proposer in rng.sample(list(cpu_teams), len(cpu_teams)):
        proposer_outlook = str(outlooks.get(proposer, "bubble") or "bubble")
        # Only contenders/rebuilders initiate; skip proposers on cooldown.
        if proposer_outlook == "bubble" or _on_cooldown(proposer):
            continue
        eligible_targets = [
            t for t in cpu_teams if t != proposer and not _on_cooldown(t)
        ]
        if not eligible_targets:
            continue

        # Ranked shortlist: the proposer shops candidates against the receiver
        # rather than betting everything on its single margin-max offer, which
        # is systematically the one the receiver values least (S2-10
        # acceptance-gate finding — the greedy pick almost never closes).
        candidates = _build_best_offer(
            cpu_team_id=proposer,
            target_team_ids=eligible_targets,
            players_by_id=players_by_id,
            rosters_by_team=rosters_by_team,
            teams_by_id=teams_by_id,
            pending_trades=pending_trades,
            data_dir=data_dir,
            rng=rng,
            min_score_margin=min_score_margin,
            blocked_packages=blocked_packages,
            target_offer_counts={},
            pending_target_limit=99,
            outlook=proposer_outlook,
            days_to_deadline=days_to_deadline,
            return_ranked=_CPU_CPU_OFFER_SHORTLIST,
        )
        if not candidates:
            filtered["no_offer"] += 1
            continue

        final: Trade | None = None
        receiver: str | None = None
        counter_seen = False
        for offer in candidates:
            receiver = offer.target_team_id
            # Receiver evaluates the offer (already oriented to_team=receiver).
            evaluation = evaluate_cpu_trade_offer(
                offer.trade,
                players_by_id=players_by_id,
                data_dir=data_dir,
                teams_by_id=teams_by_id,
                rosters_by_team=rosters_by_team,
                allow_counter_offers=True,
                timeline_weight_factor=_factor_for(
                    outlooks.get(receiver), days_to_deadline
                ),
            )
            if evaluation is None:
                continue
            action = str(getattr(evaluation, "action", "")).strip().lower()
            if action == "accept":
                final = offer.trade
                break
            if action == "counter" and getattr(evaluation, "counter_offer", None):
                counter_seen = True
                co = evaluation.counter_offer
                # Perspective flip: evaluator "incoming_*" flow TO the receiver =
                # FROM the proposer; on the flipped trade (from_team=receiver)
                # those are the receiver's `receive_*`.
                counter = Trade(
                    trade_id=uuid.uuid4().hex[:8],
                    from_team=receiver,
                    to_team=proposer,
                    give_player_ids=list(co.get("outgoing_player_ids", []) or []),
                    receive_player_ids=list(co.get("incoming_player_ids", []) or []),
                    give_pick_ids=list(co.get("outgoing_pick_ids", []) or []),
                    receive_pick_ids=list(co.get("incoming_pick_ids", []) or []),
                    initiated_by="cpu",
                )
                proposer_eval = evaluate_cpu_trade_offer(
                    counter,
                    players_by_id=players_by_id,
                    data_dir=data_dir,
                    teams_by_id=teams_by_id,
                    rosters_by_team=rosters_by_team,
                    allow_counter_offers=False,
                    timeline_weight_factor=_factor_for(
                        outlooks.get(proposer), days_to_deadline
                    ),
                )
                if (
                    proposer_eval is not None
                    and str(getattr(proposer_eval, "action", "")).strip().lower() == "accept"
                ):
                    final = counter
                    break
            # otherwise try the next (more receiver-favorable) candidate

        if final is None:
            filtered["counter_dropped" if counter_seen else "no_offer"] += 1
            continue

        # Guards: level caps + payroll policy for both sides.
        validation = validate_trade(
            give_player_ids=list(final.give_player_ids),
            receive_player_ids=list(final.receive_player_ids),
            give_pick_ids=list(getattr(final, "give_pick_ids", []) or []),
            receive_pick_ids=list(getattr(final, "receive_pick_ids", []) or []),
            from_team_levels=_levels(final.from_team),
            to_team_levels=_levels(final.to_team),
            players=players_map,
            settings=trade_settings,
        )
        if not getattr(validation, "ok", False):
            filtered["validation_failed"] += 1
            continue
        payroll = evaluate_trade_payroll_impact(
            final, players_by_id=players_by_id, data_dir=data_dir
        )
        if not bool(getattr(payroll, "allowed", True)):
            filtered["payroll_blocked"] += 1
            continue

        # Commit + persist + announce.
        final.status = "accepted"
        try:
            commit_trade(final, data_dir=data_dir)
        except ValueError:
            filtered["commit_failed"] += 1
            continue
        save_trade(final, data_dir / "trades_pending.csv")
        announce_trade(final, players_by_id=players_by_id, data_dir=data_dir)

        # State + in-memory roster mutation (blocks double-trades this run).
        iso = current_date.isoformat()
        cpu_cpu_last[str(final.from_team).strip().upper()] = iso
        cpu_cpu_last[str(final.to_team).strip().upper()] = iso
        executions.append(iso)
        _apply_roster_swap(rosters_by_team, final)
        signature = _offer_package_signature(final)
        if signature:
            blocked_packages.add(signature)
        recent_packages.append(
            {
                "date": iso,
                "from_team": final.from_team,
                "to_team": final.to_team,
                "give_player_ids": list(final.give_player_ids),
                "receive_player_ids": list(final.receive_player_ids),
                "give_pick_ids": list(getattr(final, "give_pick_ids", []) or []),
                "receive_pick_ids": list(getattr(final, "receive_pick_ids", []) or []),
            }
        )
        pending_trades.append(final)
        _withdraw_conflicting_pending(final, pending_trades, data_dir)

        executed.append(
            {
                "trade_id": final.trade_id,
                "from_team": final.from_team,
                "to_team": final.to_team,
                "give_players": len(final.give_player_ids),
                "receive_players": len(final.receive_player_ids),
                "proposer_outlook": proposer_outlook,
            }
        )
        break  # one execution per cycle run (D4)

    return _result()


def _apply_roster_swap(rosters_by_team: Mapping[str, object], trade: Trade) -> None:
    """Mirror commit_trade's ACT<->ACT move on the in-memory roster objects."""

    from_roster = rosters_by_team.get(str(trade.from_team).strip().upper())
    to_roster = rosters_by_team.get(str(trade.to_team).strip().upper())
    if from_roster is None or to_roster is None:
        return
    from_act = getattr(from_roster, "act", None)
    to_act = getattr(to_roster, "act", None)
    if from_act is None or to_act is None:
        return
    for pid in trade.give_player_ids:
        if pid in from_act:
            from_act.remove(pid)
        if pid in to_act:
            to_act.remove(pid)
        to_act.append(pid)
    for pid in trade.receive_player_ids:
        if pid in to_act:
            to_act.remove(pid)
        if pid in from_act:
            from_act.remove(pid)
        from_act.append(pid)


def _withdraw_conflicting_pending(
    executed: Trade, pending_trades: Sequence[Trade], data_dir: Path
) -> None:
    """Withdraw any still-pending offer whose assets the executed deal moved."""

    moved = {
        str(pid).strip()
        for pid in list(executed.give_player_ids) + list(executed.receive_player_ids)
        if str(pid).strip()
    }
    if not moved:
        return
    for trade in list(pending_trades):
        if trade is executed:
            continue
        if str(getattr(trade, "status", "") or "").strip().lower() != "pending":
            continue
        assets = {
            str(pid).strip()
            for pid in list(getattr(trade, "give_player_ids", []) or [])
            + list(getattr(trade, "receive_player_ids", []) or [])
        }
        if assets & moved:
            trade.status = "withdrawn"
            try:
                save_trade(trade, data_dir / "trades_pending.csv")
            except Exception:
                pass


def _team_has_pending_offer(team_id: str, pending_trades: Sequence[Trade]) -> bool:
    token = str(team_id or "").strip().upper()
    if not token:
        return False
    for trade in pending_trades:
        status = str(getattr(trade, "status", "") or "").strip().lower()
        if status != "pending":
            continue
        if str(getattr(trade, "from_team", "") or "").strip().upper() == token:
            return True
    return False


def _pair_has_pending_offer(
    cpu_team_id: str,
    human_team_id: str,
    pending_trades: Sequence[Trade],
) -> bool:
    cpu_token = str(cpu_team_id or "").strip().upper()
    human_token = str(human_team_id or "").strip().upper()
    if not cpu_token or not human_token:
        return False
    for trade in pending_trades:
        status = str(getattr(trade, "status", "") or "").strip().lower()
        if status != "pending":
            continue
        from_team = str(getattr(trade, "from_team", "") or "").strip().upper()
        to_team = str(getattr(trade, "to_team", "") or "").strip().upper()
        if {from_team, to_team} == {cpu_token, human_token}:
            return True
    return False


def _count_pending_cpu_offers(
    pending_trades: Sequence[Trade],
    *,
    cpu_team_ids: Sequence[str],
) -> int:
    cpu_tokens = {str(team_id or "").strip().upper() for team_id in cpu_team_ids}
    if not cpu_tokens:
        return 0
    total = 0
    for trade in pending_trades:
        status = str(getattr(trade, "status", "") or "").strip().lower()
        if status != "pending":
            continue
        from_team = str(getattr(trade, "from_team", "") or "").strip().upper()
        if from_team in cpu_tokens:
            total += 1
    return total


def _count_pending_cpu_offers_for_target(
    pending_trades: Sequence[Trade],
    *,
    cpu_team_ids: Sequence[str],
    target_team_id: str,
) -> int:
    cpu_tokens = {str(team_id or "").strip().upper() for team_id in cpu_team_ids}
    target_token = str(target_team_id or "").strip().upper()
    if not cpu_tokens or not target_token:
        return 0
    total = 0
    for trade in pending_trades:
        status = str(getattr(trade, "status", "") or "").strip().lower()
        if status != "pending":
            continue
        from_team = str(getattr(trade, "from_team", "") or "").strip().upper()
        to_team = str(getattr(trade, "to_team", "") or "").strip().upper()
        if from_team in cpu_tokens and to_team == target_token:
            total += 1
    return total


def _coerce_state_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    coerced: dict[str, str] = {}
    for key, value in raw.items():
        token = str(key or "").strip().upper()
        if not token:
            continue
        date_token = str(value or "").strip()
        if not date_token:
            continue
        coerced[token] = date_token
    return coerced


def _coerce_recent_packages(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, object]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        date_token = str(entry.get("date", "") or "").strip()
        if _parse_iso_date(date_token) is None:
            continue
        normalized.append(
            {
                "date": date_token,
                "from_team": str(entry.get("from_team", "") or "").strip().upper(),
                "to_team": str(entry.get("to_team", "") or "").strip().upper(),
                "give_player_ids": list(entry.get("give_player_ids", []) or []),
                "receive_player_ids": list(entry.get("receive_player_ids", []) or []),
                "give_pick_ids": list(entry.get("give_pick_ids", []) or []),
                "receive_pick_ids": list(entry.get("receive_pick_ids", []) or []),
            }
        )
    return normalized


def _prune_recent_packages(
    packages: Sequence[Mapping[str, object]],
    *,
    current_date: date,
    retention_days: int,
) -> list[dict[str, object]]:
    kept: list[dict[str, object]] = []
    for entry in packages:
        date_token = str(entry.get("date", "") or "").strip()
        token_date = _parse_iso_date(date_token)
        if token_date is None:
            continue
        age = (current_date - token_date).days
        if age < 0:
            continue
        if age > max(1, int(retention_days)):
            continue
        kept.append(dict(entry))
    return kept


def _blocked_package_signatures(
    packages: Sequence[Mapping[str, object]],
    *,
    current_date: date,
    block_days: int,
) -> set[str]:
    blocked: set[str] = set()
    for entry in packages:
        date_token = str(entry.get("date", "") or "").strip()
        token_date = _parse_iso_date(date_token)
        if token_date is None:
            continue
        age = (current_date - token_date).days
        if age < 0 or age > max(1, int(block_days)):
            continue
        trade = Trade(
            trade_id="history",
            from_team=str(entry.get("from_team", "") or "").strip(),
            to_team=str(entry.get("to_team", "") or "").strip(),
            give_player_ids=[str(pid or "").strip() for pid in entry.get("give_player_ids", []) or []],
            receive_player_ids=[
                str(pid or "").strip() for pid in entry.get("receive_player_ids", []) or []
            ],
            give_pick_ids=[str(pid or "").strip() for pid in entry.get("give_pick_ids", []) or []],
            receive_pick_ids=[
                str(pid or "").strip() for pid in entry.get("receive_pick_ids", []) or []
            ],
        )
        signature = _offer_package_signature(trade)
        if signature:
            blocked.add(signature)
    return blocked


def _offer_package_signature(trade: Trade) -> str:
    from_team = str(getattr(trade, "from_team", "") or "").strip().upper()
    to_team = str(getattr(trade, "to_team", "") or "").strip().upper()
    if not from_team or not to_team:
        return ""
    give_players = sorted(
        str(pid or "").strip()
        for pid in getattr(trade, "give_player_ids", []) or []
        if str(pid or "").strip()
    )
    receive_players = sorted(
        str(pid or "").strip()
        for pid in getattr(trade, "receive_player_ids", []) or []
        if str(pid or "").strip()
    )
    give_picks = sorted(
        str(pid or "").strip()
        for pid in getattr(trade, "give_pick_ids", []) or []
        if str(pid or "").strip()
    )
    receive_picks = sorted(
        str(pid or "").strip()
        for pid in getattr(trade, "receive_pick_ids", []) or []
        if str(pid or "").strip()
    )
    if (not give_players and not give_picks) or (not receive_players and not receive_picks):
        return ""
    return (
        f"{from_team}>{to_team}|"
        f"GP:{'|'.join(give_players)}|RP:{'|'.join(receive_players)}|"
        f"GK:{'|'.join(give_picks)}|RK:{'|'.join(receive_picks)}"
    )


def _player_age(player: object) -> int | None:
    """Best-effort player age (copy of cpu_trade_evaluator._player_age).

    Duplicated rather than importing a private symbol from the evaluator."""

    age_val = getattr(player, "age", None)
    if isinstance(age_val, (int, float)):
        return max(14, min(50, int(age_val)))
    birthdate = str(getattr(player, "birthdate", "") or "").strip()
    if len(birthdate) >= 4 and birthdate[:4].isdigit():
        birth_year = int(birthdate[:4])
        from services.trade_settings import current_league_year

        season_year = current_league_year()
        return max(14, min(50, season_year - birth_year))
    return None


def _player_trade_value(player: object) -> float:
    if player is None:
        return 0.0
    is_pitcher = bool(getattr(player, "is_pitcher", False)) or str(
        getattr(player, "primary_position", "") or ""
    ).strip().upper() == "P"
    if is_pitcher:
        keys = ("arm", "control", "movement", "endurance", "fb", "cb", "sl")
    else:
        keys = ("ch", "ph", "sp", "fa", "arm", "sc")
    samples = []
    for key in keys:
        raw = getattr(player, key, 0)
        try:
            value = float(raw)
        except Exception:
            value = 0.0
        if value > 0:
            samples.append(value)
    if not samples:
        return 45.0
    return float(sum(samples)) / float(len(samples))


def _is_cpu_team(team: object) -> bool:
    owner = str(getattr(team, "owner_id", "") or "").strip().lower()
    return owner in CPU_OWNER_IDS


def _load_human_team_ids(*, data_dir: Path) -> set[str]:
    """Return the set of team_ids that have a real (human) owner.

    Reads ``users.txt`` because that's the source of truth for who
    owns which team. Falls back to an empty set on any I/O failure —
    that just means every team gets treated as CPU, matching the prior
    behavior.
    """

    users_path = data_dir / "users.txt"
    try:
        users = load_users(str(users_path))
    except Exception:
        return set()
    owned: set[str] = set()
    for user in users:
        role = str(user.get("role", "") or "").strip().lower()
        if role != "owner":
            continue
        team_id = str(user.get("team_id", "") or "").strip().upper()
        if team_id:
            owned.add(team_id)
    return owned


def _load_rosters(team_ids: Sequence[str], *, data_dir: Path) -> dict[str, object]:
    rosters: dict[str, object] = {}
    roster_dir = data_dir / "rosters"
    for team_id in team_ids:
        token = str(team_id or "").strip().upper()
        if not token:
            continue
        try:
            rosters[token] = load_roster(token, roster_dir=roster_dir)
        except Exception:
            rosters[token] = type(
                "_RosterFallback",
                (),
                {"act": [], "aaa": [], "low": []},
            )()
    return rosters


def _window_probability(daily_probability: float, day_count: int) -> float:
    chance = max(0.0, min(1.0, float(daily_probability)))
    days = max(1, int(day_count))
    return 1.0 - pow((1.0 - chance), days)


def _unique_dates(values: Sequence[str] | None) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        token = str(raw or "").strip()
        if not token or token in seen:
            continue
        if _parse_iso_date(token) is None:
            continue
        seen.add(token)
        unique.append(token)
    return sorted(unique)


def _parse_iso_date(value: str | None) -> date | None:
    token = str(value or "").strip()
    if not token:
        return None
    try:
        return date.fromisoformat(token)
    except Exception:
        return None


def _state_path(*, data_dir: Path) -> Path:
    return data_dir / PROPOSAL_STATE_FILENAME


def _load_state(*, data_dir: Path) -> dict[str, object]:
    path = _state_path(data_dir=data_dir)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {"version": VERSION, "leagues": {}}


def _write_state(payload: Mapping[str, object], *, data_dir: Path) -> None:
    path = _state_path(data_dir=data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2), encoding="utf-8")
