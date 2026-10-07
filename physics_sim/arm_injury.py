"""Post-game workload injury hazards (Release 3; audit M15, owner Q9/Q14).

Two hazards are rolled once per game, after the final out:

* **Pitcher arm injuries.** Every pitcher who threw a pitch carries a
  per-appearance chance of an arm injury that grows with his pitch count,
  falls with his durability (read against the league's own average, decision
  2) and rises when he pitched on short rest. This is the engine's main source
  of pitcher injured-list stints; the in-game ``pitcher_overuse`` roll stays as
  it was. Owner decision (2026-10-07): about 3/4 of MLB's rate, i.e. 9-10
  pitcher IL stints per team-season, in every league from deploy.
* **Fatigued position players** (owner Q14). Playing a tired regular carries
  a real but small extra injury chance, for every team. The chance scales with
  the batter's fatigue level, so a club that rests its regulars barely sees it
  and an owner who switches rest days off pays for it.

Both rolls use their own random stream -- ``random.Random`` keyed by
``crc32(f"{seed}:{player_id}:{salt}")`` -- and happen after the last pitch, so
they can never change a game's outcome: the box score, pitch log and the
engine's shared RNG are identical with the hazards on or off; only
``injury_events`` differs. The same seed replays the same injuries, so serial
and parallel day simulation agree.

Both reuse the league's injury catalog (``pitcher_overuse`` templates for the
arm, ``swing`` soft-tissue templates for tired hitters), so no catalog change
is needed and older catalogs keep working.

Inputs this module needs from elsewhere:

* rest days -- ``UsageState.workloads[pid].last_used_day`` against
  ``game_day``, read before the post-game usage record loop. Under the
  Release 3 calendar clock (item A) that is calendar days; before it, distinct
  game dates.
* batter fatigue -- :func:`batter_fatigue_level`: a ``fatigue_level`` attribute
  in [0, 1] if the fatigue model sets one, else the in-game fatigue penalty the
  engine stamps on the batter (``fatigue_penalty``) over its cap.
"""

from __future__ import annotations

import math
import random
import zlib
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .config import TuningConfig

__all__ = [
    "ARM_TRIGGER",
    "FATIGUE_TRIGGER",
    "arm_hazard",
    "batter_fatigue_level",
    "fatigue_injury_chance",
    "hazard_level",
    "hazard_rng",
    "pitcher_durability",
    "rest_days_before",
    "roll_post_game_injuries",
]

ARM_TRIGGER = "pitcher_arm"
FATIGUE_TRIGGER = "batter_fatigue"

# Catalog triggers whose templates the hazards borrow, in order of preference.
_ARM_TEMPLATE_TRIGGERS = ("pitcher_overuse",)
_FATIGUE_TEMPLATE_TRIGGERS = ("swing", "collision")


def hazard_level(tuning: TuningConfig) -> float:
    """The league injury level as a multiplier: 1.0 at "normal", 0.5 "low".

    ``injury_rate_scale`` over ``pitcher_arm_rate_reference`` (0.1, the
    "normal" level), and 0 when injuries are switched off.
    """

    if tuning.get("injuries_enabled", 1.0) <= 0.5:
        return 0.0
    reference = tuning.get("pitcher_arm_rate_reference", 0.1)
    if reference <= 0.0:
        return 0.0
    return max(0.0, tuning.get("injury_rate_scale", 0.1) / reference)


def hazard_rng(seed: Optional[int], player_id: str, salt: str) -> random.Random:
    """A private random stream for one player's post-game roll.

    Keyed on the game seed, so a replayed game replays its injuries. An
    unseeded game has nothing to replay, so it draws fresh entropy rather than
    giving every unseeded game the same roll for the same player.
    """

    if seed is None:
        return random.Random()
    key = f"{seed}:{player_id}:{salt}".encode("utf-8")
    return random.Random(zlib.crc32(key))


def rest_days_before(
    usage_state: Any, pitcher_id: str, game_day: Optional[int]
) -> Optional[int]:
    """Days off the pitcher had before today, or None when unknown.

    Read before the post-game usage loop records today's outing. 0 means he
    also pitched the previous day.
    """

    if usage_state is None or game_day is None:
        return None
    workloads = getattr(usage_state, "workloads", None) or {}
    workload = workloads.get(pitcher_id)
    last = getattr(workload, "last_used_day", None)
    if last is None:
        return None
    return max(0, int(game_day) - int(last) - 1)


def arm_hazard(
    *,
    pitches: int,
    durability: float,
    started: bool,
    rest_days: Optional[int],
    tuning: TuningConfig,
    level: float = 1.0,
) -> float:
    """Chance that one appearance ends in an arm injury.

    ``level * (base + per_pitch * pitches)
    * exp(-durability_k * (durability - durability_center) / 10)
    * rest multiplier * (1 + pitch_ramp * max(0, pitches - ramp_start) / 10)``.
    The rest multiplier applies to a reliever who also pitched the previous
    day, or a starter on fewer than ``pitcher_arm_starter_short_rest_days``.
    """

    if level <= 0.0 or pitches <= 0:
        return 0.0
    hazard = tuning.get("pitcher_arm_base", 0.0) + tuning.get(
        "pitcher_arm_per_pitch", 0.0
    ) * pitches
    center = tuning.get("pitcher_arm_durability_center", 50.0)
    k_dur = tuning.get("pitcher_arm_durability_k", 0.0)
    hazard *= math.exp(-k_dur * (float(durability) - center) / 10.0)
    if rest_days is not None:
        if started:
            short = tuning.get("pitcher_arm_starter_short_rest_days", 4.0)
            if rest_days < short:
                hazard *= 1.0 + tuning.get(
                    "pitcher_arm_starter_short_rest_penalty", 0.0
                )
        elif rest_days <= 0:
            hazard *= 1.0 + tuning.get("pitcher_arm_reliever_rest_penalty", 0.0)
    ramp_start = tuning.get("pitcher_arm_pitch_ramp_start", 100.0)
    ramp = tuning.get("pitcher_arm_pitch_ramp", 0.0)
    hazard *= 1.0 + ramp * max(0.0, pitches - ramp_start) / 10.0
    return min(1.0, max(0.0, level * hazard))


def pitcher_durability(pitcher: Any, default: float = 50.0) -> float:
    """The pitcher's durability rating; ``default`` only when it is missing.

    A rating of 0 is real -- the least durable arm there is -- so only None,
    an empty value or an unreadable one falls back to the league average.
    """

    value = getattr(pitcher, "durability", None)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def batter_fatigue_level(batter: Any, tuning: TuningConfig) -> float:
    """How tired a batter played today, from 0 (fresh) to 1 (exhausted).

    The fatigue model (item F) may set ``fatigue_level`` directly; otherwise
    this reads the in-game penalty the engine stamps on a tired batter
    (``fatigue_penalty``, 0 up to ``batter_fatigue_penalty_cap``).
    """

    level = getattr(batter, "fatigue_level", None)
    if level is None:
        penalty = float(getattr(batter, "fatigue_penalty", 0.0) or 0.0)
        cap = tuning.get("batter_fatigue_penalty_cap", 0.35)
        level = penalty / cap if cap > 0.0 else 0.0
    try:
        level = float(level)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, level))


def fatigue_injury_chance(
    fatigue: float, *, tuning: TuningConfig, level: float = 1.0
) -> float:
    """Chance that a tired position player is hurt in a game he played."""

    if level <= 0.0 or fatigue <= 0.0:
        return 0.0
    if tuning.get("batter_fatigue_injury_enabled", 1.0) <= 0.5:
        return 0.0
    chance = tuning.get("batter_fatigue_injury_base", 0.0) * fatigue
    return min(1.0, max(0.0, level * chance))


def roll_post_game_injuries(
    *,
    seed: Optional[int],
    tuning: TuningConfig,
    usage_state: Any,
    game_day: Optional[int],
    staffs: Mapping[str, Any],
    lineups: Mapping[str, Any],
    batters: Mapping[str, Iterable[Any]],
    injured_players: set,
) -> List[Dict[str, Any]]:
    """Roll both post-game hazards and return the new injury events.

    ``staffs`` maps "away"/"home" to the engine's team pitching state (with
    ``starter`` and ``all_pitchers()``); ``lineups`` to its lineup state (with
    ``batting_lines``/``fielding_lines``); ``batters`` to every batter object
    the side could have used (lineup and bench). Players already hurt in this
    game are skipped and every new casualty is added to ``injured_players``.

    An undated game (``game_day`` None: the admin exhibition, one-off tools)
    rolls nothing. It is not part of a season, so there is no rest clock to
    read and no injured list it should put a real player on.
    """

    if game_day is None:
        return []
    level = hazard_level(tuning)
    if level <= 0.0:
        return []
    events: List[Dict[str, Any]] = []
    simulator = None

    def _simulator(rng: random.Random):
        nonlocal simulator
        if simulator is None:
            from services.injury_simulator import InjurySimulator

            simulator = InjurySimulator(rng=rng)
        simulator.rng = rng
        return simulator

    arm_on = tuning.get("pitcher_arm_enabled", 0.0) > 0.5
    for side in ("away", "home"):
        staff = staffs.get(side)
        if staff is None or not arm_on:
            continue
        starter = getattr(staff, "starter", None)
        for state in staff.all_pitchers():
            pitches = int(getattr(state, "pitches", 0) or 0)
            pitcher = state.pitcher
            pid = str(pitcher.player_id)
            if pitches <= 0 or pid in injured_players:
                continue
            started = state is starter
            rest = rest_days_before(usage_state, pid, game_day)
            durability = pitcher_durability(pitcher)
            chance = arm_hazard(
                pitches=pitches,
                durability=durability,
                started=started,
                rest_days=rest,
                tuning=tuning,
                level=level,
            )
            rng = hazard_rng(seed, pid, "arm")
            if chance <= 0.0 or rng.random() >= chance:
                continue
            major = rng.random() < tuning.get("pitcher_arm_major_share", 0.3)
            outcome = _create_outcome(
                _simulator(rng),
                pitcher,
                severities=("major", "moderate") if major else ("moderate",),
                triggers=_ARM_TEMPLATE_TRIGGERS,
                is_pitcher=True,
            )
            if outcome is None:
                continue
            injured_players.add(pid)
            events.append(
                {
                    "team": side,
                    "player_id": pid,
                    "trigger": ARM_TRIGGER,
                    "severity": outcome.severity,
                    "days": outcome.days,
                    "dl_tier": outcome.dl_tier,
                    "description": outcome.description,
                    "pitcher_id": pid,
                    "pitch_count": pitches,
                    "rest_days": rest,
                    "starter": started,
                    "durability": durability,
                    "post_game": True,
                }
            )

    for side in ("away", "home"):
        lineup_state = lineups.get(side)
        if lineup_state is None:
            continue
        lookup = {str(b.player_id): b for b in batters.get(side, ()) or ()}
        played = set(getattr(lineup_state, "batting_lines", {}) or {})
        played.update(getattr(lineup_state, "fielding_lines", {}) or {})
        for pid in sorted(str(p) for p in played):
            batter = lookup.get(pid)
            if batter is None or pid in injured_players:
                continue
            fatigue = batter_fatigue_level(batter, tuning)
            chance = fatigue_injury_chance(fatigue, tuning=tuning, level=level)
            if chance <= 0.0:
                continue
            rng = hazard_rng(seed, pid, "fatigue")
            if rng.random() >= chance:
                continue
            roll = rng.random()
            major_share = tuning.get("batter_fatigue_injury_major_share", 0.0)
            moderate_share = tuning.get("batter_fatigue_injury_moderate_share", 0.0)
            if roll < major_share:
                severities = ("major", "moderate", "minor")
            elif roll < major_share + moderate_share:
                severities = ("moderate", "minor")
            else:
                severities = ("minor",)
            outcome = _create_outcome(
                _simulator(rng),
                batter,
                severities=severities,
                triggers=_FATIGUE_TEMPLATE_TRIGGERS,
                is_pitcher=False,
            )
            if outcome is None:
                continue
            injured_players.add(pid)
            events.append(
                {
                    "team": side,
                    "player_id": pid,
                    "trigger": FATIGUE_TRIGGER,
                    "severity": outcome.severity,
                    "days": outcome.days,
                    "dl_tier": outcome.dl_tier,
                    "description": outcome.description,
                    "pitcher_id": "",
                    "fatigue_level": round(fatigue, 4),
                    "post_game": True,
                }
            )
    return events


def _create_outcome(
    simulator: Any,
    player: Any,
    *,
    severities: Iterable[str],
    triggers: Iterable[str],
    is_pitcher: bool,
):
    """First catalog injury that fits, trying severities then triggers in order."""

    for severity in severities:
        for trigger in triggers:
            outcome = simulator.maybe_create_injury(
                trigger,
                player,
                force=True,
                severity_override=severity,
                is_pitcher=is_pitcher,
            )
            if outcome is not None:
                return outcome
    return None
