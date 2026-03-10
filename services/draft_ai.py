from __future__ import annotations

"""Draft AI helpers: team needs and strategy-aware prospect scoring."""

from datetime import date
from typing import Any, Dict, Iterable

from utils.path_utils import get_data_dir
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster

# Simple org target counts; tune as needed.
POSITION_TARGETS: Dict[str, int] = {
    "C": 4,
    "1B": 4,
    "2B": 5,
    "3B": 4,
    "SS": 5,
    "LF": 5,
    "CF": 5,
    "RF": 5,
}
SP_TARGET = 10
RP_TARGET = 15


def _as_pitcher(player: Any) -> bool:
    return bool(
        getattr(player, "is_pitcher", False)
        or str(getattr(player, "primary_position", "")).upper() == "P"
    )


def _is_sp(player: Any) -> bool:
    role = str(getattr(player, "role", "") or "").upper()
    if role == "SP":
        return True
    endurance = getattr(player, "endurance", 0) or 0
    return _as_pitcher(player) and endurance >= 70


def compute_team_needs(team_id: str) -> Dict[str, float]:
    """Return need scores per position plus SP/RP in [0, 1]."""

    players_path = get_data_dir() / "players.csv"
    players = {player.player_id: player for player in load_players_from_csv(str(players_path))}
    try:
        roster = load_roster(team_id)
        ids: list[str] = roster.act + roster.aaa + roster.low
    except FileNotFoundError:
        ids = []

    org: list[Any] = [players[player_id] for player_id in ids if player_id in players]
    counts: Dict[str, int] = {key: 0 for key in POSITION_TARGETS}
    sp = 0
    rp = 0
    for player in org:
        primary = str(getattr(player, "primary_position", "")).upper()
        if _as_pitcher(player):
            if _is_sp(player):
                sp += 1
            else:
                rp += 1
        elif primary in counts:
            counts[primary] += 1

    needs: Dict[str, float] = {}
    for position, target in POSITION_TARGETS.items():
        have = counts.get(position, 0)
        need = max(0.0, (target - have) / max(target, 1))
        needs[position] = min(1.0, need)
    needs["SP"] = min(1.0, max(0.0, (SP_TARGET - sp) / max(SP_TARGET, 1)))
    needs["RP"] = min(1.0, max(0.0, (RP_TARGET - rp) / max(RP_TARGET, 1)))
    return needs


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return default


def _norm(value: object) -> float:
    return max(0.0, min(99.0, float(_safe_int(value, 0)))) / 99.0


def _normalize_profile(value: object) -> str:
    token = str(value or "").strip().lower()
    if token in {
        "balanced",
        "win_now",
        "development_focus",
        "defense_first",
        "power_offense",
    }:
        return token
    return "balanced"


def _player_age(raw_birthdate: object) -> int | None:
    value = str(raw_birthdate or "").strip()
    if not value:
        return None
    token = value.split("T", 1)[0]
    try:
        born = date.fromisoformat(token)
    except ValueError:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _strategy_bonus(
    prospect: Dict[str, Any],
    *,
    strategy_profile: str,
    is_pitcher: bool,
) -> float:
    profile = _normalize_profile(strategy_profile)
    if profile == "balanced":
        return 0.0

    age = _player_age(prospect.get("birthdate"))
    youth_bonus = 0.0
    veteran_bonus = 0.0
    if age is not None:
        youth_bonus = max(0.0, float(24 - age)) / 10.0
        veteran_bonus = max(0.0, float(age - 23)) / 10.0

    if is_pitcher:
        endurance = _norm(prospect.get("endurance"))
        control = _norm(prospect.get("control"))
        movement = _norm(prospect.get("movement"))
        hold = _norm(prospect.get("hold_runner"))
        arm = _norm(prospect.get("arm", prospect.get("fb", 0)))
        pot_arm = _norm(prospect.get("pot_arm", prospect.get("arm", prospect.get("fb", 0))))
        pot_control = _norm(prospect.get("pot_control", prospect.get("control", 0)))
        pot_movement = _norm(prospect.get("pot_movement", prospect.get("movement", 0)))

        if profile == "win_now":
            return (20.0 * control) + (18.0 * movement) + (12.0 * endurance) + (5.0 * veteran_bonus)
        if profile == "development_focus":
            return (
                (18.0 * pot_arm)
                + (15.0 * pot_control)
                + (12.0 * pot_movement)
                + (7.0 * youth_bonus)
            )
        if profile == "defense_first":
            return (24.0 * control) + (21.0 * movement) + (14.0 * hold)
        if profile == "power_offense":
            return (20.0 * arm) + (12.0 * movement) + (7.0 * endurance) - (4.0 * hold)
        return 0.0

    ch = _norm(prospect.get("ch"))
    ph = _norm(prospect.get("ph"))
    sp = _norm(prospect.get("sp"))
    eye = _norm(prospect.get("eye"))
    fa = _norm(prospect.get("fa"))
    arm = _norm(prospect.get("arm"))
    gf = _norm(prospect.get("gf"))
    pot_ch = _norm(prospect.get("pot_ch", prospect.get("ch", 0)))
    pot_ph = _norm(prospect.get("pot_ph", prospect.get("ph", 0)))

    if profile == "win_now":
        return (19.0 * ch) + (18.0 * ph) + (10.0 * eye) + (7.0 * veteran_bonus)
    if profile == "development_focus":
        return (16.0 * pot_ch) + (16.0 * pot_ph) + (12.0 * sp) + (10.0 * fa) + (7.0 * youth_bonus)
    if profile == "defense_first":
        return (24.0 * fa) + (18.0 * arm) + (16.0 * gf) + (7.0 * sp) - (8.0 * ph)
    if profile == "power_offense":
        return (28.0 * ph) + (16.0 * ch) + (10.0 * eye) + (6.0 * sp) - (7.0 * fa)
    return 0.0


def score_prospect(
    prospect: Dict[str, Any],
    needs: Dict[str, float],
    *,
    strategy_profile: str | None = None,
) -> int:
    """Return a need-aware score for a prospect.

    Base score uses role-appropriate ratings and applies team need weighting.
    Strategy profile adds a secondary fit bonus for v2 draft behavior.
    """

    is_pitcher = bool(prospect.get("is_pitcher"))
    if is_pitcher:
        base = (
            _safe_int(prospect.get("endurance"), 0)
            + _safe_int(prospect.get("control"), 0)
            + _safe_int(prospect.get("movement"), 0)
        )
        endurance = _safe_int(prospect.get("endurance"), 0)
        bucket = "SP" if endurance >= 70 else "RP"
    else:
        base = (
            _safe_int(prospect.get("ch"), 0)
            + _safe_int(prospect.get("ph"), 0)
            + _safe_int(prospect.get("sp"), 0)
        )
        bucket = str(prospect.get("primary_position", "SS") or "SS").upper()
        if bucket not in POSITION_TARGETS:
            bucket = "SS"

    need = float(needs.get(bucket, 0.0))
    score = float(base) * (1.0 + 0.5 * need)
    score += _strategy_bonus(
        prospect,
        strategy_profile=strategy_profile or "balanced",
        is_pitcher=is_pitcher,
    )
    return int(round(score))


__all__ = ["compute_team_needs", "score_prospect"]
