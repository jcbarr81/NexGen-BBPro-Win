"""Yearly prospect promotion.

Runs once per offseason (called from ``LeagueRolloverService``, AFTER
retirements so promotions can fill any newly-vacated roster spots).

Rules per level. "Overall" is the shared overall
(``utils.player_overall``), and every bar is relative to the league's own
players at the same role (hitters against hitters, pitchers against
pitchers), measured on the roster files when the promoter runs
(:func:`promotion_bars`, backlog #51):

  **LOW → AAA**
    - Age >= 22 regardless of overall (LOW is the developmental floor;
      anyone who hasn't progressed past it by 22 needs to face AAA
      pitching or get washed out)
    - OR in the top quarter of the league's AAA players (talented enough
      to challenge AAA)

  **AAA → ACT**
    - At least the league's median big leaguer AND age >= 23 (clear
      callup; the kid is ready)
    - OR in the top quarter of the league's big leaguers, any age (a
      blue-chip prospect)

Fixed bars (55 / 65 / 72 on a flat rating average) used to stand here. In
engine points, where big leaguers average about 52, nobody reached 65: the
2027 rollover in alpha-test called up no one and in-season call-ups had no
candidates.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from playbalance.aging import calculate_age
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.player_overall import player_overall_score
from utils.rating_display import league_display_scale, overall_for_text
from utils.roster_loader import load_roster, save_roster
from utils.roster_rules import (
    AAA_CAP,
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    counts_as_pitcher,
)

# Ages
LOW_TO_AAA_AGE_FORCE = 22
AAA_TO_ACT_AGE = 23

# Where each bar sits in the league's own population at the player's role.
LOW_TO_AAA_SHARE = 0.75  # of the league's AAA players
AAA_TO_ACT_READY_SHARE = 0.50  # of the league's big leaguers
AAA_TO_ACT_BLUECHIP_SHARE = 0.75  # of the league's big leaguers

# Fewer players than this at a level and role and the fixed bars below stand
# in. They are alpha-test's 2027 values (shared overall, engine points).
MIN_POPULATION = 20
FALLBACK_BARS = {
    False: {"low_to_aaa": 52.4, "ready": 52.4, "bluechip": 54.7},
    True: {"low_to_aaa": 52.6, "ready": 52.8, "bluechip": 54.5},
}


@dataclass(frozen=True)
class RoleBars:
    """The promotion bars for one role (hitters or pitchers) in one league."""

    low_to_aaa: float
    ready: float
    bluechip: float


PromotionBars = Dict[bool, RoleBars]  # keyed by "is a pitcher"


def _player_overall(player: object) -> float:
    """The promotion score: the shared overall (``utils.player_overall``),
    the score the rest of the game shows and ranks by, to one decimal."""

    score = player_overall_score(player)
    return round(float(score), 1) if score is not None else 50.0


def _share_point(values: List[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def promotion_bars(
    players_by_id: Mapping[str, object],
    levels: Iterable[Tuple[str, str]],
) -> PromotionBars:
    """The league's promotion bars from ``(player_id, level)`` pairs.

    Each bar is a point in the league's own population at the player's role,
    so it means the same on either rating scale and in any generation.
    """

    scores: Dict[Tuple[bool, str], List[float]] = {}
    for pid, level in levels:
        player = players_by_id.get(pid)
        level = (level or "").strip().upper()
        if player is None or level not in ("ACT", "AAA"):
            continue
        scores.setdefault((counts_as_pitcher(player), level), []).append(
            _player_overall(player)
        )
    bars: PromotionBars = {}
    for pitcher in (False, True):
        fallback = FALLBACK_BARS[pitcher]
        act = scores.get((pitcher, "ACT"), [])
        aaa = scores.get((pitcher, "AAA"), [])
        enough_act = len(act) >= MIN_POPULATION
        bars[pitcher] = RoleBars(
            low_to_aaa=(
                _share_point(aaa, LOW_TO_AAA_SHARE)
                if len(aaa) >= MIN_POPULATION
                else fallback["low_to_aaa"]
            ),
            ready=(
                _share_point(act, AAA_TO_ACT_READY_SHARE)
                if enough_act
                else fallback["ready"]
            ),
            bluechip=(
                _share_point(act, AAA_TO_ACT_BLUECHIP_SHARE)
                if enough_act
                else fallback["bluechip"]
            ),
        )
    return bars


def league_promotion_bars(
    data_dir: Path, players_by_id: Mapping[str, object]
) -> PromotionBars:
    """:func:`promotion_bars` over every roster file in ``data_dir``."""

    rosters = _load_team_rosters_with_levels(Path(data_dir) / "rosters")
    return promotion_bars(
        players_by_id,
        ((pid, level) for levels in rosters.values() for pid, level in levels.items()),
    )


def evaluate_promotion(
    *,
    current_level: str,
    age: Optional[int],
    overall: float,
    bars: RoleBars,
) -> Optional[str]:
    """Return the target level if *player* should be promoted, else None.

    ``bars`` are the league's bars for the player's role
    (:func:`promotion_bars`). Only single-step promotions: a LOW player who
    deserves AAA returns "AAA" even if they'd also clear the AAA→ACT bar.
    They get the second promotion next offseason.
    """

    level = (current_level or "").strip().upper()
    if level == "LOW":
        if (age is not None and age >= LOW_TO_AAA_AGE_FORCE) or overall >= bars.low_to_aaa:
            return "AAA"
        return None
    if level == "AAA":
        if overall >= bars.bluechip:
            return "ACT"
        if overall >= bars.ready and age is not None and age >= AAA_TO_ACT_AGE:
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

    bars = promotion_bars(
        players_by_id,
        ((pid, level) for levels in team_rosters.values() for pid, level in levels.items()),
    )
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
                bars=bars[counts_as_pitcher(player)],
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

    # News quotes the overall the league's pages show (rating scale 2) or,
    # on scale 1, the promotion score it always quoted.
    league_scale = league_display_scale(resolved / "players.csv")

    def _ovr(entry: Dict[str, Any]) -> Any:
        quoted = int(round(entry["overall"]))
        player = players_by_id.get(entry["player_id"])
        if player is None:
            return quoted
        return overall_for_text(player, quoted, league_scale)

    _announce_suggestions(suggestions, resolved, _ovr)
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
                f"{entry['team_id']} {verb}: {label} (age {entry['age']}, OVR {_ovr(entry)}).",
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


def _announce_suggestions(
    suggestions: List[Dict[str, Any]], data_dir: Path, ovr=None
) -> None:
    """News for an owner's prospects who are ready for the next level: one
    line per club and level, best first, so a deep farm doesn't post a
    line per player.

    ``ovr(entry)`` is the overall the line quotes (default: the entry's
    promotion score)."""

    if not suggestions:
        return
    try:
        from utils.news_logger import log_news_event
    except Exception:  # pragma: no cover - defensive
        return
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for entry in suggestions:
        key = (entry["team_id"], entry["from_level"], entry["to_level"])
        groups.setdefault(key, []).append(entry)
    for (team_id, from_level, to_level), entries in groups.items():
        entries = sorted(entries, key=lambda e: -float(e["overall"]))
        labels = []
        for entry in entries:
            name = f"{entry['first_name']} {entry['last_name']}".strip() or entry["player_id"]
            label = f"{entry['primary_position']} {name}".strip()
            quoted = ovr(entry) if ovr else int(round(float(entry["overall"])))
            labels.append(f"{label} (age {entry['age']}, OVR {quoted})")
        where = "the majors" if to_level == "ACT" else to_level
        if len(entries) == 1:
            message = (
                f"{team_id}: {labels[0]} is ready for {where} -- promote him "
                f"from {from_level} when you have a spot."
            )
        else:
            message = (
                f"{team_id}: {len(entries)} prospects are ready for {where}: "
                f"{'; '.join(labels)}. Promote them from {from_level} when you "
                "have a spot."
            )
        try:
            log_news_event(
                message,
                category="promotion",
                team_id=team_id,
                file_path=data_dir / "news_feed.txt",
            )
        except Exception:
            continue


__all__ = [
    "AAA_TO_ACT_AGE",
    "AAA_TO_ACT_BLUECHIP_SHARE",
    "AAA_TO_ACT_READY_SHARE",
    "LOW_TO_AAA_AGE_FORCE",
    "LOW_TO_AAA_SHARE",
    "PromotionBars",
    "RoleBars",
    "evaluate_promotion",
    "league_promotion_bars",
    "promotion_bars",
    "run_yearly_promotions",
]
