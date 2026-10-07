"""Yearly prospect promotion.

Runs once per offseason (called from ``LeagueRolloverService``, AFTER
retirements so promotions can fill any newly-vacated roster spots).

Rules per level:

  **LOW → AAA**
    - Age >= 22 regardless of overall (LOW is the developmental floor;
      anyone who hasn't progressed past it by 22 needs to face AAA
      pitching or get washed out)
    - OR overall >= 55 (talented enough to challenge AAA)

  **AAA → ACT**
    - Overall >= 65 AND age >= 23 (clear callup; the kid is ready)
    - OR overall >= 72 (no-doubt callup regardless of age — true blue-chip prospect)

We don't auto-demote in v1. Promotions never push players past their
level: a LOW prospect who deserves AAA *and* ACT in the same pass goes to
AAA this year and ACT the next (one rung at a time keeps the pipeline
visible to the owner).

Room (decision 8): AAA -> ACT is automatic for CPU clubs only, into an open
spot on the 26-man roster and -- for a pitcher -- a staff under 13.
LOW -> AAA is automatic for CPU clubs too, only into an open AAA spot (15).
Best players first. An owner's ready prospect -- at either rung -- is a
suggestion (a news line and the returned ``suggestions``), never a move:
the CPU does not change an owner's roster. When ownership can't be read
nothing moves at all (``reason: "ownership_unknown"``).
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from playbalance.aging import calculate_age
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster, save_roster
from utils.roster_rules import (
    AAA_CAP,
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    counts_as_pitcher,
)

# LOW → AAA thresholds
LOW_TO_AAA_AGE_FORCE = 22
LOW_TO_AAA_OVR = 55

# AAA → ACT thresholds
AAA_TO_ACT_AGE = 23
AAA_TO_ACT_OVR = 65
AAA_TO_ACT_BLUECHIP_OVR = 72


def _player_overall(player: object) -> int:
    """The promotion score the 55 / 65 / 72 bars were tuned for.

    Deliberately NOT the shared display overall (utils.player_overall): that
    score spreads players about 1.3x wider, so these fixed bars would promote
    several times as many players (alpha-test LOW->AAA: 2.4% -> 12.9%),
    filling the open roster spots with marginal promotions. This flat
    average never had the pitch-count bias of audit M14. Retune the bars
    before switching (docs/future_work.md).
    """

    is_pitcher = bool(getattr(player, "is_pitcher", False))
    keys = (
        ("arm", "control", "movement", "endurance")
        if is_pitcher
        else ("ch", "ph", "sp", "eye", "fa", "arm")
    )
    values: list[float] = []
    for key in keys:
        raw = getattr(player, key, None)
        if raw is None:
            continue
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not values:
        return 50
    return int(round(sum(values) / len(values)))


def evaluate_promotion(
    *,
    current_level: str,
    age: Optional[int],
    overall: int,
) -> Optional[str]:
    """Return the target level if *player* should be promoted, else None.

    Only single-step promotions: a LOW player who deserves AAA returns
    "AAA" even if they'd also clear the AAA→ACT bar. They get the second
    promotion next offseason.
    """

    level = (current_level or "").strip().upper()
    if level == "LOW":
        if (age is not None and age >= LOW_TO_AAA_AGE_FORCE) or overall >= LOW_TO_AAA_OVR:
            return "AAA"
        return None
    if level == "AAA":
        if overall >= AAA_TO_ACT_BLUECHIP_OVR:
            return "ACT"
        if overall >= AAA_TO_ACT_OVR and age is not None and age >= AAA_TO_ACT_AGE:
            return "ACT"
        return None
    return None


def _load_team_rosters_with_levels(rosters_dir: Path) -> Dict[str, Dict[str, str]]:
    """Return ``{team_id: {player_id: level}}`` for every roster file."""

    out: Dict[str, Dict[str, str]] = {}
    if not rosters_dir.exists():
        return out
    for roster_file in rosters_dir.glob("*.csv"):
        team_id = roster_file.stem
        if team_id.endswith("_pitching") or team_id.endswith("_lineup"):
            continue
        levels: Dict[str, str] = {}
        try:
            with roster_file.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.reader(fh):
                    if not row or len(row) < 2:
                        continue
                    pid = (row[0] or "").strip()
                    level = (row[1] or "").strip().upper()
                    if not pid:
                        continue
                    if level in {"DL", "DL15", "DL45", "IR"}:
                        # Injured players don't get promoted while on
                        # the shelf — wait until they're activated.
                        continue
                    levels[pid] = level
        except OSError:
            continue
        if levels:
            out[team_id] = levels
    return out


def run_yearly_promotions(
    *,
    season_year: Optional[int] = None,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Promote eligible AAA / LOW prospects across every team.

    See the module docstring for who moves where. When ownership can't be
    read nothing moves: an owner's club must never be mistaken for a CPU one.
    """

    resolved = data_dir or get_data_dir()
    rosters_dir = resolved / "rosters"
    team_rosters = _load_team_rosters_with_levels(rosters_dir)
    if not team_rosters:
        return {"promotions": [], "count": 0}

    try:
        players = list(load_players_from_csv(resolved / "players.csv"))
    except Exception:
        return {"promotions": [], "count": 0, "error": "failed to load players.csv"}
    players_by_id = {getattr(p, "player_id", ""): p for p in players}
    try:
        from services.team_ownership import human_owned_team_ids_strict

        human_ids = human_owned_team_ids_strict(resolved)
    except Exception:  # pragma: no cover - defensive
        human_ids = None
    if human_ids is None:
        return {
            "promotions": [],
            "count": 0,
            "suggestions": [],
            "reason": "ownership_unknown",
        }

    promotions: List[Dict[str, Any]] = []
    suggestions: List[Dict[str, Any]] = []
    skipped = {"act_full": 0, "staff_full": 0, "aaa_full": 0}
    for team_id, ids_with_levels in team_rosters.items():
        # Mutate the roster in-memory then save once at the end so we
        # don't re-read it for each promotion.
        try:
            roster = load_roster(team_id)
        except Exception:
            continue
        cpu = str(team_id).upper() not in human_ids
        candidates: List[Dict[str, Any]] = []
        for pid, current_level in list(ids_with_levels.items()):
            player = players_by_id.get(pid)
            if player is None:
                continue
            bd = getattr(player, "birthdate", None)
            age = calculate_age(str(bd)) if bd else None
            overall = _player_overall(player)
            target = evaluate_promotion(
                current_level=current_level,
                age=age,
                overall=overall,
            )
            if not target:
                continue
            candidates.append(
                {
                    "player_id": pid,
                    "first_name": getattr(player, "first_name", "") or "",
                    "last_name": getattr(player, "last_name", "") or "",
                    "primary_position": getattr(player, "primary_position", "") or "",
                    "is_pitcher": counts_as_pitcher(player),
                    "team_id": team_id,
                    "from_level": current_level,
                    "to_level": target,
                    "age": age,
                    "overall": overall,
                }
            )
        # AAA -> ACT first (each one opens an AAA spot), best players first.
        candidates.sort(key=lambda e: (e["to_level"] != "ACT", -e["overall"], e["player_id"]))
        roster_changed = False
        for entry in candidates:
            pid = entry["player_id"]
            if not cpu:
                # An owner's club: every promotion is the owner's call.
                suggestions.append(entry)
                continue
            if entry["to_level"] == "ACT":
                if len(roster.act) >= ACTIVE_ROSTER_SIZE:
                    skipped["act_full"] += 1
                    continue
                if entry["is_pitcher"] and sum(
                    1 for a in roster.act if counts_as_pitcher(players_by_id.get(a))
                ) >= MAX_ACTIVE_PITCHERS:
                    skipped["staff_full"] += 1
                    continue
            elif len(roster.aaa) >= AAA_CAP:
                skipped["aaa_full"] += 1
                continue
            try:
                roster.move_player(pid, entry["from_level"].lower(), entry["to_level"].lower())
            except Exception:
                continue
            roster_changed = True
            promotions.append(entry)
        if roster_changed:
            try:
                save_roster(team_id, roster)
            except Exception:
                pass

    _announce_suggestions(suggestions, resolved)
    if not promotions:
        return {"promotions": [], "count": 0, "suggestions": suggestions, "skipped": skipped}

    # Surface to the news feed so owners see the moves.
    try:
        from utils.news_logger import log_news_event

        news_path = resolved / "news_feed.txt"
        for entry in promotions:
            name = (
                f"{entry['first_name']} {entry['last_name']}".strip()
                or entry["player_id"]
            )
            label = (
                f"{entry['primary_position']} {name}".strip()
                if entry["primary_position"]
                else name
            )
            verb = (
                "called up to the majors"
                if entry["to_level"] == "ACT"
                else f"promoted to {entry['to_level']}"
            )
            log_news_event(
                f"{entry['team_id']} {verb}: {label} (age {entry['age']}, OVR {entry['overall']}).",
                category="promotion",
                team_id=entry["team_id"],
                file_path=news_path,
            )
    except Exception:
        pass

    # Log transactions too so the team finance + activity ledgers reflect
    # the move.
    try:
        from services.transaction_log import record_transaction

        sim_date = None
        try:
            from utils.sim_date import get_current_sim_date

            sim_date = get_current_sim_date()
        except Exception:
            sim_date = None
        for entry in promotions:
            try:
                record_transaction(
                    action="promote",
                    team_id=entry["team_id"],
                    player_id=entry["player_id"],
                    player_name=f"{entry['first_name']} {entry['last_name']}".strip()
                    or entry["player_id"],
                    from_level=entry["from_level"],
                    to_level=entry["to_level"],
                    details=f"Promoted ({entry['from_level']} → {entry['to_level']})",
                    season_date=sim_date,
                )
            except Exception:
                continue
    except Exception:
        pass

    return {
        "promotions": promotions,
        "count": len(promotions),
        "suggestions": suggestions,
        "skipped": skipped,
        "season_year": int(season_year) if season_year is not None else None,
    }


def _announce_suggestions(suggestions: List[Dict[str, Any]], data_dir: Path) -> None:
    """A news line per owner prospect who is ready for the next level."""

    if not suggestions:
        return
    try:
        from utils.news_logger import log_news_event
    except Exception:  # pragma: no cover - defensive
        return
    for entry in suggestions:
        name = f"{entry['first_name']} {entry['last_name']}".strip() or entry["player_id"]
        label = f"{entry['primary_position']} {name}".strip()
        if entry["to_level"] == "ACT":
            advice = "is ready for the majors -- promote him from AAA when you have a spot."
        else:
            advice = (
                f"is ready for {entry['to_level']} -- promote him from "
                f"{entry['from_level']} when you have a spot."
            )
        try:
            log_news_event(
                f"{entry['team_id']}: {label} (age {entry['age']}, OVR "
                f"{entry['overall']}) {advice}",
                category="promotion",
                team_id=entry["team_id"],
                file_path=data_dir / "news_feed.txt",
            )
        except Exception:
            continue


__all__ = [
    "AAA_TO_ACT_AGE",
    "AAA_TO_ACT_BLUECHIP_OVR",
    "AAA_TO_ACT_OVR",
    "LOW_TO_AAA_AGE_FORCE",
    "LOW_TO_AAA_OVR",
    "evaluate_promotion",
    "run_yearly_promotions",
]
