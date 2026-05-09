"""Utility helpers for handling free agency.

This module provides simple functions to query which players are
currently unsigned and to sign players to teams.  The functions operate
purely on the in-memory player and team objects which makes them easy to
test and reuse in different contexts.
"""

from __future__ import annotations

import math
from pathlib import Path
import random
from typing import Dict, Iterable, List

from models.player import Player
from models.roster import Roster
from models.team import Team
from services.contract_negotiator import evaluate_free_agent_bids
from services.contracts_service import sign_free_agent_contract
from services.finance_ai import build_cpu_free_agent_bid_book
from services.finance_settings import LEVEL_OFF, load_financial_settings
from services.payroll_policy import (
    evaluate_free_agent_signing,
    record_payroll_policy_result,
)
from services.transaction_log import record_transaction
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_io import read_roster_csv
from utils.roster_loader import load_roster, save_roster
from utils.team_loader import load_teams


def list_unsigned_players(
    players: Dict[str, Player], teams: Iterable[Team]
) -> List[Player]:
    """Return a list of players not assigned to any team's roster.

    Parameters
    ----------
    players:
        Mapping of player ids to :class:`~models.player.Player` objects.
    teams:
        Iterable of :class:`~models.team.Team` instances representing the
        league's teams.
    """

    signed_ids = set()
    for team in teams:
        for roster in (team.act_roster, team.aaa_roster, team.low_roster):
            signed_ids.update(roster)

    return [player for pid, player in players.items() if pid not in signed_ids]


def sign_player_to_team(player_id: str, team: Team, level: str = "act") -> None:
    """Assign *player_id* to *team*'s roster at the specified level.

    Parameters
    ----------
    player_id:
        Identifier of the player to sign.
    team:
        The :class:`~models.team.Team` object representing the destination
        team.
    level:
        Roster level to assign the player to. One of ``"act"`` for the
        active roster, ``"aaa"`` for AAA or ``"low"`` for the low minors.
    """

    rosters = {
        "act": team.act_roster,
        "aaa": team.aaa_roster,
        "low": team.low_roster,
    }
    roster = rosters.get(level)
    if roster is None:
        raise ValueError(f"Unknown roster level: {level}")

    # Prevent duplicates across all rosters
    if any(player_id in r for r in rosters.values()):
        raise ValueError("Player already assigned to a roster")

    roster.append(player_id)


def list_unsigned_players_from_files(
    *,
    data_dir: Path | str | None = None,
) -> List[Player]:
    """Load league data from disk and return unsigned players.

    Excludes retired players so the free-agency UI never offers a
    signing for someone who's already left the league.
    """

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    players = load_players_from_csv(resolved_data_dir / "players.csv")
    teams = load_teams(resolved_data_dir / "teams.csv")
    for team in teams:
        roster = load_roster(
            team.team_id,
            roster_dir=resolved_data_dir / "rosters",
        )
        team.act_roster = list(roster.act)
        team.aaa_roster = list(roster.aaa)
        team.low_roster = list(roster.low)
    players_by_id = {player.player_id: player for player in players}

    # Filter out retirees. Their player rows still live in players.csv
    # so career history queries keep working, but they shouldn't show
    # up as signable free agents.
    try:
        from services.player_retirement import load_retirees

        retired_ids = set(load_retirees(resolved_data_dir).keys())
        if retired_ids:
            players_by_id = {
                pid: p for pid, p in players_by_id.items() if pid not in retired_ids
            }
    except Exception:
        pass

    return list_unsigned_players(players_by_id, teams)


def run_cpu_free_agency_round(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    max_signings: int | None = None,
    rng: random.Random | None = None,
) -> Dict[str, object]:
    """Run one automated CPU free-agency pass and persist signings."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    ai_level = settings.module_level("gm_finance_ai")
    fa_level = settings.module_level("gm_free_agency")
    if (not settings.enabled) or ai_level == LEVEL_OFF or fa_level == LEVEL_OFF:
        return {
            "applied": False,
            "reason": "financial_free_agency_disabled",
            "ai_level": ai_level,
            "signed_players": 0,
            "remaining_unsigned": len(list_unsigned_players_from_files(data_dir=resolved_data_dir)),
            "signings": [],
        }

    unsigned_players = list_unsigned_players_from_files(data_dir=resolved_data_dir)
    if not unsigned_players:
        return {
            "applied": False,
            "reason": "no_unsigned_players",
            "ai_level": ai_level,
            "signed_players": 0,
            "remaining_unsigned": 0,
            "signings": [],
        }

    teams = load_teams(resolved_data_dir / "teams.csv")
    cpu_teams = [team for team in teams if _is_cpu_team(team)]
    if not cpu_teams:
        return {
            "applied": False,
            "reason": "no_cpu_teams",
            "ai_level": ai_level,
            "signed_players": 0,
            "remaining_unsigned": len(unsigned_players),
            "signings": [],
        }

    randomizer = rng if rng is not None else random.Random()
    candidates = sorted(
        unsigned_players,
        key=lambda player: _quality_score(player),
        reverse=True,
    )
    if max_signings is not None:
        cap = max(0, int(max_signings))
        if cap == 0:
            candidates = []

    signed = 0
    signings: list[Dict[str, object]] = []
    for player in candidates:
        if max_signings is not None and signed >= max(0, int(max_signings)):
            break
        player_id = str(getattr(player, "player_id", "") or "").strip()
        if not player_id:
            continue
        bids = build_cpu_free_agent_bid_book(
            player,
            cpu_teams,
            ai_level=ai_level,
            data_dir=resolved_data_dir,
            rng=randomizer,
        )
        if not bids:
            continue
        selected_team_id = ""
        selected_offer = 0
        eligible_bids = dict(bids)
        while eligible_bids:
            winner = evaluate_free_agent_bids(player, eligible_bids)
            team_id = str(getattr(winner, "team_id", winner) or "").strip()
            if not team_id:
                break
            offer = int(eligible_bids.get(team_id, 0) or 0)
            policy = evaluate_free_agent_signing(
                team_id,
                annual_salary=offer,
                data_dir=resolved_data_dir,
                league_id=league_id,
            )
            if not policy.allowed:
                record_payroll_policy_result(
                    policy,
                    action="cpu_sign_free_agent",
                    data_dir=resolved_data_dir,
                )
                eligible_bids.pop(team_id, None)
                continue
            if policy.warning:
                record_payroll_policy_result(
                    policy,
                    action="cpu_sign_free_agent",
                    data_dir=resolved_data_dir,
                )
            selected_team_id = team_id
            selected_offer = offer
            break

        team_id = selected_team_id
        if not team_id:
            continue
        roster_level = _add_player_to_team_roster(
            team_id,
            player_id,
            data_dir=resolved_data_dir,
        )
        if roster_level is None:
            continue
        sign_free_agent_contract(
            player_id,
            team_id,
            player=player,
            data_dir=resolved_data_dir,
        )
        offer = int(selected_offer)
        try:
            record_transaction(
                action="fa_signing",
                team_id=team_id,
                player_id=player_id,
                from_level="FA",
                to_level=roster_level,
                details=f"CPU free-agent signing (${offer:,})",
                path=resolved_data_dir / "transactions.csv",
            )
        except Exception:
            pass
        signed += 1
        signings.append(
            {
                "player_id": player_id,
                "team_id": team_id,
                "offer": offer,
                "roster_level": roster_level,
                "player_name": f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')}".strip(),
            }
        )

    remaining = list_unsigned_players_from_files(data_dir=resolved_data_dir)
    return {
        "applied": signed > 0,
        "reason": "ok",
        "ai_level": ai_level,
        "signed_players": signed,
        "remaining_unsigned": len(remaining),
        "signings": signings,
    }


def estimate_cpu_free_agency_rounds(
    unsigned_count: int,
    *,
    cpu_team_count: int,
    free_agency_level: str,
) -> int:
    """Estimate how many CPU free-agency rounds to run this preseason."""

    unsigned = max(0, int(unsigned_count))
    teams = max(0, int(cpu_team_count))
    if unsigned <= 0 or teams <= 0:
        return 0
    base_rounds = int(math.ceil(float(unsigned) / float(max(1, teams * 2))))
    if str(free_agency_level or "").strip().lower() == "advanced":
        base_rounds += 1
    return max(1, min(8, base_rounds))


def run_cpu_free_agency_market(
    *,
    data_dir: Path | str | None = None,
    league_id: str | None = None,
    max_rounds: int | None = None,
    max_signings_per_round: int | None = None,
    rng: random.Random | None = None,
) -> Dict[str, object]:
    """Run multi-round CPU free agency; round count scales with market size."""

    resolved_data_dir = get_data_dir() if data_dir is None else Path(data_dir)
    settings = load_financial_settings(
        path=resolved_data_dir / "league_financial_settings.json",
        league_id=league_id,
    )
    ai_level = settings.module_level("gm_finance_ai")
    fa_level = settings.module_level("gm_free_agency")
    if (not settings.enabled) or ai_level == LEVEL_OFF or fa_level == LEVEL_OFF:
        return {
            "applied": False,
            "reason": "financial_free_agency_disabled",
            "ai_level": ai_level,
            "rounds_planned": 0,
            "rounds_run": 0,
            "signed_players": 0,
            "remaining_unsigned": len(list_unsigned_players_from_files(data_dir=resolved_data_dir)),
            "rounds": [],
        }

    teams = load_teams(resolved_data_dir / "teams.csv")
    cpu_teams = [team for team in teams if _is_cpu_team(team)]
    if not cpu_teams:
        return {
            "applied": False,
            "reason": "no_cpu_teams",
            "ai_level": ai_level,
            "rounds_planned": 0,
            "rounds_run": 0,
            "signed_players": 0,
            "remaining_unsigned": len(list_unsigned_players_from_files(data_dir=resolved_data_dir)),
            "rounds": [],
        }

    unsigned_before = list_unsigned_players_from_files(data_dir=resolved_data_dir)
    planned_rounds = estimate_cpu_free_agency_rounds(
        len(unsigned_before),
        cpu_team_count=len(cpu_teams),
        free_agency_level=fa_level,
    )
    if max_rounds is not None:
        planned_rounds = min(planned_rounds, max(0, int(max_rounds)))

    if planned_rounds <= 0:
        return {
            "applied": False,
            "reason": "no_unsigned_players",
            "ai_level": ai_level,
            "rounds_planned": 0,
            "rounds_run": 0,
            "signed_players": 0,
            "remaining_unsigned": len(unsigned_before),
            "rounds": [],
        }

    randomizer = rng if rng is not None else random.Random()
    rounds: list[Dict[str, object]] = []
    total_signed = 0
    remaining = len(unsigned_before)
    for round_index in range(1, planned_rounds + 1):
        if remaining <= 0:
            break
        rounds_left = max(1, planned_rounds - round_index + 1)
        computed_cap = int(math.ceil(float(remaining) / float(rounds_left)))
        if max_signings_per_round is not None:
            computed_cap = min(computed_cap, max(0, int(max_signings_per_round)))
        if computed_cap <= 0:
            break

        result = run_cpu_free_agency_round(
            data_dir=resolved_data_dir,
            league_id=league_id,
            max_signings=computed_cap,
            rng=randomizer,
        )
        signed_this_round = int(result.get("signed_players", 0) or 0)
        remaining = int(result.get("remaining_unsigned", remaining) or remaining)
        rounds.append(
            {
                "round": round_index,
                "max_signings": computed_cap,
                "signed_players": signed_this_round,
                "remaining_unsigned": remaining,
                "signings": list(result.get("signings", []) or []),
            }
        )
        total_signed += signed_this_round
        if signed_this_round <= 0:
            break

    return {
        "applied": total_signed > 0,
        "reason": "ok",
        "ai_level": ai_level,
        "rounds_planned": planned_rounds,
        "rounds_run": len(rounds),
        "signed_players": total_signed,
        "remaining_unsigned": remaining,
        "rounds": rounds,
    }


def _is_cpu_team(team: Team) -> bool:
    owner = str(getattr(team, "owner_id", "") or "").strip().lower()
    return owner in {"", "cpu", "ai", "none", "computer", "bot"}


def _quality_score(player: Player) -> int:
    is_pitcher = bool(getattr(player, "is_pitcher", False)) or str(
        getattr(player, "primary_position", "") or ""
    ).strip().upper() == "P"
    if is_pitcher:
        fields = ("arm", "control", "movement", "endurance")
    else:
        fields = ("ch", "ph", "sp", "eye", "fa", "arm")
    values = [int(round(float(getattr(player, field, 0) or 0))) for field in fields]
    values = [value for value in values if value > 0]
    if not values:
        return 55
    return max(20, min(95, int(round(sum(values) / len(values)))))


def _add_player_to_team_roster(
    team_id: str,
    player_id: str,
    *,
    data_dir: Path,
) -> str | None:
    roster_dir = data_dir / "rosters"
    roster_path = roster_dir / f"{team_id}.csv"
    roster_path.parent.mkdir(parents=True, exist_ok=True)
    if roster_path.exists():
        try:
            roster = read_roster_csv(roster_path, team_id)
        except Exception:
            return None
    else:
        roster = Roster(team_id=team_id)

    if player_id in roster.act or player_id in roster.aaa or player_id in roster.low:
        return None

    act = len(roster.act)
    aaa = len(roster.aaa)
    low = len(roster.low)

    if act < 25:
        target_level = "ACT"
        roster.act.append(player_id)
    elif aaa < 15:
        target_level = "AAA"
        roster.aaa.append(player_id)
    elif low < 10:
        target_level = "LOW"
        roster.low.append(player_id)
    else:
        return None

    try:
        save_roster(team_id, roster, roster_dir=roster_dir)
    except Exception:
        return None
    return target_level
