"""Release 3 (audit M15, owner Q9/Q14): post-game arm and fatigue injuries.

The hazards are rolled after the final out on their own random streams, so
they must never change a game: the box score and pitch log are byte-identical
with them on or off, and only ``injury_events`` differs.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from physics_sim import arm_injury
from physics_sim.config import DEFAULT_TUNING, TuningConfig, load_tuning
from physics_sim.engine import simulate_matchup_from_files
from physics_sim.usage import PitcherWorkload, UsageState

ROOT = Path(__file__).resolve().parents[1]
CAL = ROOT / "data" / "calibration"

NEW_KNOBS = (
    "batter_fatigue_injury_enabled",
    "batter_fatigue_injury_base",
    "batter_fatigue_injury_moderate_share",
    "batter_fatigue_injury_major_share",
)


def _tuning(**overrides) -> TuningConfig:
    return load_tuning(overrides=overrides or None)


def _game(seed: int, **overrides):
    return simulate_matchup_from_files(
        away_team="CAL01",
        home_team="CAL02",
        players_path=CAL / "players.csv",
        base_dir=CAL,
        seed=seed,
        tuning_overrides=overrides or None,
        usage_state=UsageState(),
        game_day=0,
    )


def _without_injuries(result) -> str:
    meta = dict(result.metadata or {})
    meta.pop("injury_events", None)
    return json.dumps(
        {"totals": result.totals, "pitch_log": result.pitch_log, "meta": meta},
        sort_keys=True,
        default=str,
    )


# --- the strict gate: never changes a game ---------------------------------


@pytest.mark.parametrize("seed", [11, 12, 13])
def test_hazards_never_change_the_game(seed):
    off = _game(seed, pitcher_arm_enabled=0.0, batter_fatigue_injury_enabled=0.0)
    # Everyone who pitches is hurt; the game must still be identical.
    forced = _game(seed, pitcher_arm_base=50.0)

    assert _without_injuries(forced) == _without_injuries(off)
    arm = [e for e in forced.metadata["injury_events"] if e["trigger"] == "pitcher_arm"]
    pitched = {
        u["player_id"]
        for side in forced.metadata["pitcher_usage"].values()
        for u in side
        if u["pitches"] > 0
    }
    overuse = {
        e["player_id"]
        for e in forced.metadata["injury_events"]
        if e["trigger"] == "pitcher_overuse"
    }
    assert {e["player_id"] for e in arm} == pitched - overuse
    assert not any(e["trigger"] == "pitcher_arm" for e in off.metadata["injury_events"])


def test_same_seed_same_injuries():
    a = _game(21, pitcher_arm_base=0.2)
    b = _game(21, pitcher_arm_base=0.2)
    assert a.metadata["injury_events"] == b.metadata["injury_events"]
    assert any(e["trigger"] == "pitcher_arm" for e in a.metadata["injury_events"])


def test_arm_event_schema():
    result = _game(5, pitcher_arm_base=50.0)
    event = next(e for e in result.metadata["injury_events"] if e["trigger"] == "pitcher_arm")
    assert event["team"] in {"away", "home"}
    assert event["dl_tier"] in {"dl15", "il60"}
    assert event["severity"] in {"moderate", "major"}
    assert event["pitch_count"] > 0
    assert isinstance(event["starter"], bool)
    assert "rest_days" in event and event["post_game"] is True


# --- the hazard ----------------------------------------------------------


def test_hazard_falls_with_durability_and_rises_with_pitches():
    t = _tuning()

    def h(**kw):
        args = dict(pitches=20, durability=50, started=False, rest_days=2, tuning=t)
        args.update(kw)
        return arm_injury.arm_hazard(**args)

    assert h(durability=30) > h(durability=50) > h(durability=70)
    ratio = h(durability=40) / h(durability=60)
    assert ratio == pytest.approx(math.exp(DEFAULT_TUNING["pitcher_arm_durability_k"] * 2))
    assert h(pitches=90, started=True, rest_days=4) > h(pitches=20)
    # The ramp only starts past ramp_start pitches.
    base = h(pitches=100, started=True, rest_days=4)
    ramped = h(pitches=110, started=True, rest_days=4)
    linear = base * (
        t.get("pitcher_arm_base") + t.get("pitcher_arm_per_pitch") * 110
    ) / (t.get("pitcher_arm_base") + t.get("pitcher_arm_per_pitch") * 100)
    assert ramped == pytest.approx(linear * (1 + t.get("pitcher_arm_pitch_ramp")))


def test_short_rest_raises_the_hazard():
    t = _tuning()
    rested = arm_injury.arm_hazard(pitches=20, durability=50, started=False, rest_days=1, tuning=t)
    b2b = arm_injury.arm_hazard(pitches=20, durability=50, started=False, rest_days=0, tuning=t)
    assert b2b == pytest.approx(rested * 1.5)
    normal = arm_injury.arm_hazard(pitches=90, durability=50, started=True, rest_days=4, tuning=t)
    short = arm_injury.arm_hazard(pitches=90, durability=50, started=True, rest_days=3, tuning=t)
    assert short == pytest.approx(normal * 1.5)
    unknown = arm_injury.arm_hazard(pitches=20, durability=50, started=False, rest_days=None, tuning=t)
    assert unknown == pytest.approx(rested)


def test_injury_level_scales_the_hazard():
    assert arm_injury.hazard_level(_tuning()) == pytest.approx(1.0)
    assert arm_injury.hazard_level(_tuning(injury_rate_scale=0.05)) == pytest.approx(0.5)
    assert arm_injury.hazard_level(_tuning(injuries_enabled=0.0)) == 0.0
    assert arm_injury.hazard_level(_tuning(injury_rate_scale=0.0)) == 0.0


def test_injuries_off_rolls_nothing():
    result = _game(5, pitcher_arm_base=50.0, injuries_enabled=0.0)
    assert result.metadata["injury_events"] == []


def test_rest_days_read_before_today_is_recorded():
    usage = UsageState()
    assert arm_injury.rest_days_before(usage, "P1", 10) is None
    usage.workloads["P1"] = PitcherWorkload(last_used_day=9)
    assert arm_injury.rest_days_before(usage, "P1", 10) == 0
    usage.workloads["P1"] = PitcherWorkload(last_used_day=6)
    assert arm_injury.rest_days_before(usage, "P1", 10) == 3
    assert arm_injury.rest_days_before(None, "P1", 10) is None
    assert arm_injury.rest_days_before(usage, "P1", None) is None
    # Reading never creates a workload entry.
    arm_injury.rest_days_before(usage, "NEW", 10)
    assert "NEW" not in usage.workloads


def test_works_with_the_legacy_fallback_catalog(monkeypatch):
    from services import injury_simulator

    monkeypatch.setattr(
        injury_simulator, "load_injury_catalog", lambda *a, **k: injury_simulator._fallback_catalog()
    )
    result = _game(5, pitcher_arm_base=50.0)
    arm = [e for e in result.metadata["injury_events"] if e["trigger"] == "pitcher_arm"]
    assert arm and all(e["description"] for e in arm)


# --- tired hitters (owner Q14) --------------------------------------------


def _batter(pid="B1", **attrs):
    return SimpleNamespace(player_id=pid, durability=50.0, primary_position="CF", **attrs)


def test_fatigue_level_reads_the_penalty_or_an_explicit_level():
    t = _tuning()
    cap = t.get("batter_fatigue_penalty_cap")
    assert arm_injury.batter_fatigue_level(_batter(), t) == 0.0
    assert arm_injury.batter_fatigue_level(_batter(fatigue_penalty=cap / 2), t) == pytest.approx(0.5)
    assert arm_injury.batter_fatigue_level(_batter(fatigue_penalty=cap * 3), t) == 1.0
    assert arm_injury.batter_fatigue_level(_batter(fatigue_level=0.25, fatigue_penalty=cap), t) == 0.25


def test_fatigue_chance_is_small_and_scales():
    t = _tuning()
    assert arm_injury.fatigue_injury_chance(0.0, tuning=t) == 0.0
    full = arm_injury.fatigue_injury_chance(1.0, tuning=t)
    assert 0.0 < full <= 0.02  # small on purpose (owner: no injury-riddled seasons)
    assert arm_injury.fatigue_injury_chance(0.5, tuning=t) == pytest.approx(full / 2)
    off = _tuning(batter_fatigue_injury_enabled=0.0)
    assert arm_injury.fatigue_injury_chance(1.0, tuning=off) == 0.0


def _roll_batters(batters, **overrides):
    t = _tuning(pitcher_arm_enabled=0.0, **overrides)
    lineup = SimpleNamespace(
        batting_lines={b.player_id: None for b in batters}, fielding_lines={}
    )
    injured: set = set()
    events = arm_injury.roll_post_game_injuries(
        seed=7,
        tuning=t,
        usage_state=None,
        game_day=0,  # a season game; an undated one rolls nothing
        staffs={},
        lineups={"home": lineup},
        batters={"home": batters},
        injured_players=injured,
    )
    return events, injured


def test_only_tired_hitters_can_be_hurt():
    cap = DEFAULT_TUNING["batter_fatigue_penalty_cap"]
    tired = _batter("TIRED", fatigue_penalty=cap)
    fresh = _batter("FRESH")
    events, injured = _roll_batters([tired, fresh], batter_fatigue_injury_base=1.0)
    assert [e["player_id"] for e in events] == ["TIRED"]
    assert events[0]["trigger"] == "batter_fatigue"
    assert events[0]["fatigue_level"] == 1.0
    assert injured == {"TIRED"}


def test_a_player_already_hurt_in_the_game_is_skipped():
    cap = DEFAULT_TUNING["batter_fatigue_penalty_cap"]
    t = _tuning(pitcher_arm_enabled=0.0, batter_fatigue_injury_base=1.0)
    lineup = SimpleNamespace(batting_lines={"TIRED": None}, fielding_lines={})
    events = arm_injury.roll_post_game_injuries(
        seed=7, tuning=t, usage_state=None, game_day=0, staffs={},
        lineups={"home": lineup},
        batters={"home": [_batter("TIRED", fatigue_penalty=cap)]},
        injured_players={"TIRED"},
    )
    assert events == []


def test_fatigue_severity_mix_is_mostly_short():
    cap = DEFAULT_TUNING["batter_fatigue_penalty_cap"]
    batters = [_batter(f"B{i}", fatigue_penalty=cap) for i in range(400)]
    events, _ = _roll_batters(batters, batter_fatigue_injury_base=1.0)
    assert len(events) == 400
    il = [e for e in events if e["dl_tier"] != "none"]
    # minor (day-to-day) 50%, moderate 45%, major 5% by default
    assert 0.35 < len(il) / len(events) < 0.65


# --- knobs ----------------------------------------------------------------


@pytest.mark.parametrize("key", NEW_KNOBS)
def test_new_knobs_are_registered(key):
    assert key in DEFAULT_TUNING
    value = DEFAULT_TUNING[key] + 0.5
    tuning = TuningConfig.from_overrides(overrides={key: str(value)})
    assert tuning.get(key) == pytest.approx(value)


def test_arm_hazard_is_on_by_default():
    assert DEFAULT_TUNING["pitcher_arm_enabled"] == 1.0
    assert DEFAULT_TUNING["batter_fatigue_injury_enabled"] == 1.0


def test_fatigue_penalised_batter_copy_keeps_its_level():
    # The engine stamps fatigue_penalty on a dataclasses.replace() copy; the
    # accessor must see it on that copy.
    from physics_sim.models import BatterRatings

    b = BatterRatings(
        player_id="X", bats="R", primary_position="CF", other_positions=[],
        contact=50, power=50, gb_tendency=50, pull_tendency=50, vs_left=50,
        fielding=50, arm=50, speed=50, eye=50, height=72, durability=50,
    )
    tired = replace(b, contact=40)
    setattr(tired, "fatigue_penalty", DEFAULT_TUNING["batter_fatigue_penalty_cap"])
    assert arm_injury.batter_fatigue_level(tired, _tuning()) == 1.0
