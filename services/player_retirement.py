"""Yearly player retirement.

Runs once per offseason (called from ``LeagueRolloverService``). For each
player on any team's roster, decides whether to retire them based on age
and current overall rating. Retirees are:

  - Removed from their team's roster
  - Released from any active contract
  - Recorded to ``retired_players.json`` so the FA list filters them out
    going forward and the UI can render a Retirements section
  - Surfaced as a ``retirement`` news event so the league feed reflects
    the move

Pure rule-based; no random rolls. Tunable via the constants below.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from playbalance.aging import calculate_age
from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv

# Retirement is graded by age AND roster level. Bars are higher in the
# minors because a player stuck at AAA into their 30s isn't going to
# get called up — the writing's on the wall. Career LOW guys are
# essentially out at 27+ unless they're elite prospects.
#
# Each list is (min_age, min_OVR_to_continue), sorted oldest-first.
# Walk the tiers and pick the first one that applies.

# Major-league tier — there's no hard cap, true outliers can play
# into their late 40s if they're still elite (Ichiro/Bartolo/Julio
# Franco profiles).
_THRESHOLDS_ACT: tuple[tuple[int, int], ...] = (
    (46, 90),  # 46+: only the top 1% of all players keeps going
    (44, 85),  # 44-45: still elite-only
    (42, 80),  # 42-43: clearly above-average vets
    (38, 60),  # 38-41: "declining" — washed bench guys retire
    (36, 45),  # 36-37: replacement-level fringe guys retire
)

# AAA tier — career minor-leaguers need to be exceptional to keep
# pushing for a callup. After 30, the bar climbs fast.
_THRESHOLDS_AAA: tuple[tuple[int, int], ...] = (
    (44, 95),  # late 40s in AAA: essentially impossible
    (40, 85),
    (35, 70),
    (32, 60),  # 32+ in AAA: need to still profile as a callup
    (30, 50),  # 30+ in AAA: average-ish guys hang it up
)

# LOW tier — short ladder. Past 27 in LOW you've washed out as a
# prospect; only true late bloomers (rare) get to keep going.
_THRESHOLDS_LOW: tuple[tuple[int, int], ...] = (
    (32, 99),  # 32 in LOW: gone unless God-tier (functionally never)
    (29, 80),
    (27, 65),
    (25, 50),
)

# DL/IR mirror ACT — being injured doesn't reset retirement math.
RETIREMENT_THRESHOLDS_BY_LEVEL: dict[str, tuple[tuple[int, int], ...]] = {
    "ACT": _THRESHOLDS_ACT,
    "AAA": _THRESHOLDS_AAA,
    "LOW": _THRESHOLDS_LOW,
    "DL": _THRESHOLDS_ACT,
    "IR": _THRESHOLDS_ACT,
}


def _retirement_threshold(age: int, level: Optional[str] = None) -> Optional[int]:
    """Return the minimum OVR required to keep playing at *age* on *level*.

    Returns ``None`` when the player is too young for any tier to
    apply (no retirement pressure at all).
    """

    tiers = RETIREMENT_THRESHOLDS_BY_LEVEL.get(
        (level or "ACT").strip().upper(),
        _THRESHOLDS_ACT,
    )
    for tier_age, tier_overall in tiers:
        if age >= tier_age:
            return tier_overall
    return None

_RETIREES_FILENAME = "retired_players.json"


def _retirees_path(data_dir: Optional[Path] = None) -> Path:
    return (data_dir or get_data_dir()) / _RETIREES_FILENAME


def load_retirees(data_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Return the retirees registry, keyed by player_id."""

    path = _retirees_path(data_dir)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(k): dict(v) for k, v in payload.items() if isinstance(v, dict)}


def save_retirees(
    registry: Dict[str, Dict[str, Any]],
    *,
    data_dir: Optional[Path] = None,
) -> None:
    path = _retirees_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def is_retired(player_id: str, *, data_dir: Optional[Path] = None) -> bool:
    return str(player_id) in load_retirees(data_dir)


def _player_overall(player: object) -> int:
    """Crude OVR approximation; mirrors what _talent_score does in the
    contract negotiator. Avoids importing UI-side rating tables."""

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


def should_retire(
    player: object,
    *,
    age: Optional[int] = None,
    overall: Optional[int] = None,
    level: Optional[str] = None,
) -> Optional[str]:
    """Return a short reason string when the player should retire.

    Reasons describe why they're done:
      - ``"can't keep up"`` — failed the age-graded OVR threshold (ACT)
      - ``"career minor leaguer"`` — stuck at AAA past their development window
      - ``"prospect washout"`` — stuck at LOW past their development window
      - ``"declining"`` — older + below-average rating (ACT)
      - ``"washed"`` — fringe major-leaguer past their prime

    Returns ``None`` when the player still belongs in the league.
    """

    if age is None:
        bd = getattr(player, "birthdate", None)
        if bd:
            age = calculate_age(str(bd))
    if age is None:
        return None
    norm_level = (level or "ACT").strip().upper()
    threshold = _retirement_threshold(age, norm_level)
    if threshold is None:
        return None
    if overall is None:
        overall = _player_overall(player)
    if overall >= threshold:
        return None
    # Reason maps to the level + age tier that triggered.
    if norm_level == "AAA":
        return "career minor leaguer"
    if norm_level == "LOW":
        return "prospect washout"
    if age >= 42:
        return "can't keep up"
    if age >= 38:
        return "declining"
    return "washed"


def _load_team_rosters(
    rosters_dir: Path,
) -> Dict[str, Dict[str, str]]:
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
                    # DL15/DL45 collapse to DL/IR for retirement purposes.
                    if level in {"DL", "DL15"}:
                        level = "DL"
                    elif level in {"DL45", "IR"}:
                        level = "IR"
                    levels[pid] = level
        except OSError:
            continue
        if levels:
            out[team_id] = levels
    return out


def run_yearly_retirements(
    *,
    season_year: Optional[int] = None,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Apply retirement rules to every rostered player. Returns a summary."""

    resolved = data_dir or get_data_dir()
    rosters_dir = resolved / "rosters"
    team_rosters = _load_team_rosters(rosters_dir)
    if not team_rosters:
        return {"retirees": [], "count": 0}

    rostered_ids: set[str] = set()
    team_for: Dict[str, str] = {}
    level_for: Dict[str, str] = {}
    for team_id, ids_with_levels in team_rosters.items():
        for pid, level in ids_with_levels.items():
            rostered_ids.add(pid)
            team_for.setdefault(pid, team_id)
            level_for.setdefault(pid, level)

    try:
        players = list(load_players_from_csv(resolved / "players.csv"))
    except Exception:
        return {"retirees": [], "count": 0, "error": "failed to load players.csv"}

    retirees: List[Dict[str, Any]] = []
    for player in players:
        pid = str(getattr(player, "player_id", "") or "").strip()
        if not pid or pid not in rostered_ids:
            continue
        bd = getattr(player, "birthdate", None)
        age = calculate_age(str(bd)) if bd else None
        overall = _player_overall(player)
        level = level_for.get(pid, "ACT")
        reason = should_retire(player, age=age, overall=overall, level=level)
        if not reason:
            continue
        retirees.append(
            {
                "player_id": pid,
                "first_name": getattr(player, "first_name", "") or "",
                "last_name": getattr(player, "last_name", "") or "",
                "primary_position": getattr(player, "primary_position", "") or "",
                "is_pitcher": bool(getattr(player, "is_pitcher", False)),
                "team_id": team_for.get(pid, ""),
                "level": level,
                "age": age,
                "overall": overall,
                "reason": reason,
            }
        )

    if not retirees:
        return {"retirees": [], "count": 0}

    # Persist to the registry keyed by player_id so other services can
    # check is_retired() and the UI can render a Retirements section.
    registry = load_retirees(resolved)
    year = int(season_year or datetime.utcnow().year)
    timestamp = datetime.utcnow().isoformat() + "Z"
    for entry in retirees:
        registry[entry["player_id"]] = {
            **entry,
            "retired_year": year,
            "retired_at": timestamp,
        }
    save_retirees(registry, data_dir=resolved)

    # Remove from rosters + release contracts. Roster cleanup is the
    # safety net for downstream code that filters by roster membership;
    # contract release stops the team from paying a retiree.
    try:
        from services.contracts_service import release_contracts_to_free_agency

        release_contracts_to_free_agency(
            [entry["player_id"] for entry in retirees],
            data_dir=resolved,
        )
    except Exception:
        pass

    # The contract release helper already strips retirees from rosters
    # via its internal sweep, but we double-check by rewriting any
    # roster file that still references a retiree.
    _scrub_rosters(rosters_dir, {entry["player_id"] for entry in retirees})

    # Log a news event per retiree so the league feed reflects the move.
    try:
        from utils.news_logger import log_news_event

        news_path = resolved / "news_feed.txt"
        for entry in retirees:
            name = (
                f"{entry['first_name']} {entry['last_name']}".strip()
                or entry["player_id"]
            )
            label = (
                f"{entry['primary_position']} {name}".strip()
                if entry["primary_position"]
                else name
            )
            log_news_event(
                f"{label} retires at age {entry['age']} ({entry['reason']}).",
                category="retirement",
                team_id=entry["team_id"] or None,
                file_path=news_path,
            )
    except Exception:
        pass

    return {"retirees": retirees, "count": len(retirees)}


def _scrub_rosters(rosters_dir: Path, retired_ids: Iterable[str]) -> None:
    """Defensive: strip any retired player_ids from roster CSVs."""

    targets = set(retired_ids)
    if not targets or not rosters_dir.exists():
        return
    for roster_file in rosters_dir.glob("*.csv"):
        try:
            with roster_file.open("r", encoding="utf-8", newline="") as fh:
                rows = [row for row in csv.reader(fh) if row]
        except OSError:
            continue
        kept = [row for row in rows if not row or (row[0] or "").strip() not in targets]
        if len(kept) == len(rows):
            continue
        try:
            with roster_file.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                for row in kept:
                    writer.writerow(row)
        except OSError:
            continue


__all__ = [
    "RETIREMENT_THRESHOLDS_BY_LEVEL",
    "is_retired",
    "load_retirees",
    "run_yearly_retirements",
    "save_retirees",
    "should_retire",
]
