"""Release 6a, pitching (plan 2.1): the switch group, whole games, the
manager and the Velocity slider.

Stuff (A), velocity (B), the single pitch-quality path into exit velocity
(C) and fatigue (D) are ONE switch group: generation 6 turns all four on or
none (the design measured what each half does without the other). The
generation 6 values live in ``scripts/kpi_profiles/r6_pitching.json``, laid
over the generation 6 profile with ``--tuning-overrides`` until the lead
folds them in.

* the profile: registered keys only, this area's keys only, all four parts
  on;
* whole games: at the defaults, and with every new key spelled out, the
  legacy and generation 5 games are the games they were (pinned digests),
  and each part reaches the engine;
* the manager: the reliever score is the old formula on the legacy engine
  and generation 5 and reads the generation's weights from generation 6;
* the commissioner's Velocity Scale slider says what it does on each engine.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import physics_sim.engine as engine
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine import PitcherState
from physics_sim.engine_generation import engine_defaults, engine_profile
from physics_sim.models import PitcherRatings
from physics_sim.usage import UsageState
from scripts import physics_sim_season_kpis as kpis
from services.physics_tuning_spec import (
    _TUNING_SECTIONS,
    _VELOCITY_MODEL_SLIDERS,
    tuning_sections,
    tuning_sections_for_generation,
)
from tests import test_r5_situational as legacy_games

REPO = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO / "scripts" / "kpi_profiles" / "r6_pitching.json"

# Every key this work registered, with the value that leaves the engine as
# it was ...
OFF_VALUES = {
    "pq_weight_control": 0.4,
    "pq_weight_movement": 0.4,
    "pq_weight_grade": 0.2,
    "swing_pq_chase_logit": 0.0,
    "ev_velocity_model": 0.0,
    "difficulty_velocity_scale": 1.0,
    "ev_pq_contact_base_weight": 0.4,
    "ev_pq_slope": 0.004,
    "difficulty_pq_scale": 1.0,
    "fatigue_model": 0.0,
    "pitcher_score_model": 0.0,
}
# ... and the ones read only under a switch, with a value that would show.
SWITCHED_ONLY_WILD = {
    "ev_velo_dev_weight": 3.0,
    "ev_base_offset_mph": -40.0,
    "fatigue_control_points": 40.0,
    "fatigue_movement_points": 40.0,
    "fatigue_stuff_points": 40.0,
    "fatigue_velocity_mph": 40.0,
    "pitcher_score_weight_control": 0.0,
    "pitcher_score_weight_movement": 0.0,
    "pitcher_score_weight_grade": 9.0,
    "pitcher_score_weight_arm": 0.0,
}
NEW_KEYS = set(OFF_VALUES) | set(SWITCHED_ONLY_WILD)
# Existing keys the group retunes with it (plan 2.1 and its follow-ons).
RETUNED_KEYS = {
    "contact_logit_velo", "ev_pitch_weight", "tto_pass2_weight",
    "tto_pass3_weight", "reliever_fresh_bonus", "contact_logit_zone",
    "contact_logit_chase", "hr_scale", "command_error_control_log_slope",
    "zone_target_base",
}


def _profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


# What "on" means for each part of the group, as a check of the profile.
PARTS = {
    "A stuff": lambda p: (
        p.get("pq_weight_grade", 0.2) > 0.2
        and p.get("pq_weight_control", 0.4) < 0.4
        and p.get("swing_pq_chase_logit") is not None
    ),
    "B velocity": lambda p: (
        p.get("ev_velocity_model", 0) >= 1
        and p.get("contact_logit_velo", 0.0) > 0.0
        and p.get("ev_pitch_weight", 0.48) < 0.48
        and p.get("difficulty_velocity_scale", 1.0) < 1.0
    ),
    "C one path": lambda p: (
        p.get("ev_pq_contact_base_weight", 0.4) == 0.0
        and p.get("difficulty_pq_scale", 1.0) == 0.0
        and 0.0 < p.get("ev_pq_slope", 0.004) < 0.004
    ),
    "D fatigue": lambda p: (
        p.get("fatigue_model", 0) >= 1
        and all(
            p.get(key, 0.0) > 0.0
            for key in (
                "fatigue_control_points", "fatigue_movement_points",
                "fatigue_stuff_points", "fatigue_velocity_mph",
            )
        )
    ),
}


# --- the profile ------------------------------------------------------------------


def test_new_keys_are_registered_off():
    for key, value in OFF_VALUES.items():
        assert DEFAULT_TUNING[key] == value, key
    for key in SWITCHED_ONLY_WILD:
        assert key in DEFAULT_TUNING, key
    # Neither generation a league can play switches any of it on.
    for generation in (4, 5):
        defaults = engine_defaults(generation)
        for key, value in OFF_VALUES.items():
            assert defaults[key] == value, (generation, key)
        assert defaults["contact_logit_velo"] == 0.0


def test_profile_holds_registered_keys_of_this_area_only():
    profile = _profile()
    assert not [key for key in profile if key not in DEFAULT_TUNING]
    assert set(profile) <= NEW_KEYS | RETUNED_KEYS, sorted(
        set(profile) - NEW_KEYS - RETUNED_KEYS
    )
    # It is a harness overrides file as it stands.
    loaded = kpis.load_tuning_overrides_file(PROFILE_PATH)
    assert set(loaded) == set(profile)
    merged = kpis.resolve_run_overrides(engine=6, overrides_path=PROFILE_PATH)
    assert merged["swing_model"] == 1.0 and merged["fatigue_model"] == 1.0


def test_the_profile_switches_all_four_parts_on():
    """A, B, C and D are one switch group: never ship a profile with only
    some of them (the new kernel on the old fatigue costs a tired starter
    four times the intended wOBA; the new fatigue on the old kernel leaves
    Arm wrong-signed)."""
    profile = _profile()
    state = {name: bool(check(profile)) for name, check in PARTS.items()}
    assert all(state.values()), state
    # The pitch-quality weights still sum to one.
    assert (
        profile["pq_weight_control"] + profile["pq_weight_movement"]
        + profile["pq_weight_grade"]
    ) == pytest.approx(1.0)
    # Owner decisions 2 and 3: Arm at slope 0.06, the moderate fatigue set.
    assert profile["contact_logit_velo"] == 0.06
    assert (
        profile["fatigue_control_points"], profile["fatigue_movement_points"],
        profile["fatigue_stuff_points"], profile["fatigue_velocity_mph"],
    ) == (3.0, 1.5, 1.0, 1.5)
    # The manager chooses by the same generation's weights.
    assert profile["pitcher_score_model"] >= 1


@pytest.mark.parametrize("dropped", sorted(PARTS))
def test_the_group_check_notices_a_missing_part(dropped):
    """The check above is not vacuous: take one part's keys back to their
    off values and it fails for that part alone."""
    off = {
        "A stuff": {"pq_weight_control": 0.4, "pq_weight_movement": 0.4,
                    "pq_weight_grade": 0.2},
        "B velocity": {"ev_velocity_model": 0.0},
        "C one path": {"ev_pq_slope": 0.004},
        "D fatigue": {"fatigue_model": 0.0},
    }[dropped]
    profile = {**_profile(), **off}
    state = {name: bool(check(profile)) for name, check in PARTS.items()}
    assert state == {name: name != dropped for name in PARTS}


def test_a_league_cannot_switch_part_of_the_group_on_through_its_overrides():
    """The keys that DEFINE the group are the generation's, like the
    Release 5 model switches: a copy posted to the tuning API (or left in a
    league's overrides file) is dropped, so no league plays half the group.
    The group's sizes stay ordinary knobs."""
    from services import physics_tuning_settings as settings

    defining = {
        "ev_velocity_model", "fatigue_model", "pitcher_score_model",
        "pq_weight_control", "pq_weight_movement", "pq_weight_grade",
        "ev_pq_contact_base_weight", "ev_pq_slope", "difficulty_pq_scale",
        "difficulty_velocity_scale",
    }
    assert defining | {"contact_logit_velo"} <= set(settings.GENERATION_OWNED_KEYS)
    assert defining <= set(OFF_VALUES)
    # The contact roll's velocity term is wrong-signed on the old fatigue.
    assert settings._sanitize_overrides({"contact_logit_velo": 0.06}) == {}
    posted = {key: _profile().get(key, 1.0) for key in defining}
    assert settings._sanitize_overrides(posted) == {}
    assert settings._sanitize_overrides(posted, strict=True) == {}
    # Every key that is on/off by itself in OFF_VALUES is owned, except the
    # chase slope, which is a size (0 = no term) like the fatigue points.
    assert set(OFF_VALUES) - defining == {"swing_pq_chase_logit"}
    sizes = {"fatigue_control_points": 2.0, "swing_pq_chase_logit": 0.01,
             "ev_velo_dev_weight": 0.12, "hr_scale": 0.95}
    assert settings._sanitize_overrides(sizes) == sizes


# --- whole games ------------------------------------------------------------------


def _g5_overrides(fixture: str, **extra) -> dict:
    base = REPO / "data" / fixture
    return kpis.with_rating_centers(
        {**engine_profile(5), **extra}, base / "players.csv", base
    )


def _play_g5(fixture, away, home, seed, extra=None, **kwargs):
    base = REPO / "data" / fixture
    return engine.simulate_matchup_from_files(
        away_team=away, home_team=home, base_dir=base,
        players_path=base / "players.csv", seed=seed,
        tuning_overrides=_g5_overrides(fixture, **(extra or {})), **kwargs,
    )


def _g5_digests(extra=None) -> dict[str, str]:
    usage_state = UsageState()
    series = [
        _play_g5(
            "calibration", "CAL03", "CAL04", 100 + day, extra,
            usage_state=usage_state, game_day=day,
        )
        for day in range(3)
    ]
    return {
        "cal1": legacy_games._digest(_play_g5("calibration", "CAL01", "CAL02", 1, extra)),
        "cal2": legacy_games._digest(_play_g5("calibration", "CAL01", "CAL02", 2, extra)),
        "cal_series": legacy_games._digest(*series),
        "league1": legacy_games._digest(
            _play_g5("calibration_league", "ALB", "DET", 1, extra)
        ),
    }


# sha256 of the canonical JSON (every float as its repr) of the pitch log,
# totals and metadata of seeded GENERATION 5 games -- the profile
# physics_sim/profiles/engine_5.json over the fixture's rating centres, as
# the KPI harness plays them -- computed on the tree before this work
# (3abbbc251, 7.51.3; exported with git archive). The legacy engine's pins
# are tests/test_r5_situational.PINNED_DIGESTS. RE-BASELINE only when
# generation 5 changes on purpose.
G5_PINNED_DIGESTS = {
    "cal1": "78d311a752598970ae0b4491f93b1e489d3c94b39762be9a5dfa8057289a8cb2",
    "cal2": "2712df1b33b678349642a72117a335d0b0376412ce44a2add10db1513ce15191",
    "cal_series": "333b241db74db6632f0066887fb03c32df38d67440b8f60f68fe0b6d2168f162",
    "league1": "2efcf0ed6ffa52c270c9558f780e3868052c625183a2903b2b01f630efb8767e",
}
# One part of the group switched on by itself, for "it reaches the engine"
# only: never a profile.
PART_SWITCHES = {
    "A weights": {"pq_weight_control": 0.15, "pq_weight_movement": 0.30,
                  "pq_weight_grade": 0.55},
    "A chase": {"swing_pq_chase_logit": 0.02},
    "B ev model": {"ev_velocity_model": 1.0, "ev_pitch_weight": 0.25},
    "B difficulty": {"difficulty_velocity_scale": 0.0},
    "C contact base": {"ev_pq_contact_base_weight": 0.0},
    "C slope": {"ev_pq_slope": 0.0015},
    "C difficulty": {"difficulty_pq_scale": 0.0},
    "D fatigue": {"fatigue_model": 1.0},
}

needs_hashseed = pytest.mark.skipif(
    os.environ.get("PYTHONHASHSEED") != "0",
    reason="game digests are pinned under PYTHONHASHSEED=0",
)


@needs_hashseed
def test_legacy_games_with_every_new_key_spelled_out_are_the_pinned_games():
    got = legacy_games._all_digests({**OFF_VALUES, **SWITCHED_ONLY_WILD})
    assert got == legacy_games.PINNED_DIGESTS, f"got {got}"


@needs_hashseed
def test_generation_5_games_match_the_pinned_digests():
    got = _g5_digests()
    assert got == G5_PINNED_DIGESTS, f"got {got}"


@needs_hashseed
def test_generation_5_games_with_every_new_key_spelled_out_are_the_same():
    got = _g5_digests({**OFF_VALUES, **SWITCHED_ONLY_WILD})
    assert got == G5_PINNED_DIGESTS, f"got {got}"


@needs_hashseed
@pytest.mark.parametrize("name", sorted(PART_SWITCHES))
def test_each_switch_reaches_the_engine(name):
    got = _g5_digests(PART_SWITCHES[name])
    changed = {key for key, value in got.items() if value != G5_PINNED_DIGESTS[key]}
    assert {"cal1", "cal2"} & changed, name
    assert "league1" in changed or "cal_series" in changed, name


@needs_hashseed
def test_the_legacy_engine_reads_what_it_can_of_the_group():
    """Legacy has no swing or contact model 1, so the chase term and the
    contact velocity term are not read there; the rest reaches it."""
    pinned = legacy_games.PINNED_DIGESTS
    for name in ("A chase",):
        assert legacy_games._all_digests(PART_SWITCHES[name]) == pinned, name
    assert legacy_games._all_digests({"contact_logit_velo": 0.06}) == pinned
    for name in ("A weights", "B ev model", "C slope", "D fatigue"):
        got = legacy_games._all_digests(PART_SWITCHES[name])
        assert {"cal1", "cal2", "cal3"} & {
            key for key, value in got.items() if value != pinned[key]
        }, name


def test_the_generation_6_profile_plays_a_different_game():
    profile = kpis.load_tuning_overrides_file(PROFILE_PATH)
    result = _play_g5("calibration", "CAL01", "CAL02", 1, profile)
    assert result.totals["pa"] > 50
    assert legacy_games._digest(result) != legacy_games._digest(
        _play_g5("calibration", "CAL01", "CAL02", 1)
    )
    # Nobody's fastball falls off a cliff.
    fastballs: dict[str, list[float]] = {}
    for entry in result.pitch_log:
        if entry.get("pitch_type") == "fb" and "pitcher_id" in entry:
            fastballs.setdefault(entry["pitcher_id"], []).append(entry["velocity"])
    assert fastballs
    assert max(max(v) - min(v) for v in fastballs.values()) <= 2.25 + 1e-9


# --- the manager: the reliever score ----------------------------------------------


def _arm(pid, *, control, movement, arm, grades, endurance=50.0) -> PitcherState:
    ratings = PitcherRatings(
        player_id=pid, bats="R", throws="R", role="RP", preferred_role="RP",
        velocity=50.0, control=control, movement=movement, gb_tendency=50.0,
        vs_left=50.0, hold_runner=50.0, endurance=endurance, durability=50.0,
        fielding=50.0, arm=arm,
        repertoire=dict(zip(("fb", "sl", "cu"), grades)),
    )
    return PitcherState(
        pitcher=ratings, pitches=0, fatigue_start=40.0, fatigue_limit=60.0,
        staff_role="MR",
    )


# Good ratings the old formula reads, poor pitches; and the reverse.
COMMAND_ARM = dict(control=64.0, movement=60.0, arm=62.0, grades=(42.0, 40.0, 41.0))
STUFF_ARM = dict(control=48.0, movement=52.0, arm=50.0, grades=(72.0, 70.0, 68.0))
CENTRED = {
    "pitcher_control_usage_center": 53.0, "pitcher_movement_usage_center": 51.0,
    "pitcher_arm_usage_center": 56.0, "pitcher_grade_usage_center": 55.0,
}


def _tunings():
    yield "legacy", load_tuning()
    yield "generation 5", load_tuning(_g5_overrides("calibration"))
    yield "legacy, weights set", load_tuning(SWITCHED_ONLY_WILD)
    yield "generation 5, weights set", load_tuning(
        _g5_overrides("calibration", **SWITCHED_ONLY_WILD)
    )


def test_stuff_score_is_the_old_mean_on_the_legacy_engine_and_generation_5():
    for name, tuning in _tunings():
        for spec in (COMMAND_ARM, STUFF_ARM):
            state = _arm("p", **spec)
            pitcher = state.pitcher
            old = (
                engine._league_relative(
                    pitcher.control, "pitcher_control_usage_center", tuning
                )
                + engine._league_relative(
                    pitcher.movement, "pitcher_movement_usage_center", tuning
                )
                + engine._league_relative(
                    pitcher.arm, "pitcher_arm_usage_center", tuning
                )
            ) / 3.0
            # Exactly: the same additions in the same order.
            assert engine._pitcher_stuff_score(pitcher, tuning) == old, name
    assert engine._pitcher_stuff_score(_arm("p", **COMMAND_ARM).pitcher, None) == (
        (64.0 + 60.0 + 62.0) / 3.0
    )


def test_reliever_choice_is_todays_on_the_legacy_engine_and_generation_5():
    for name, tuning in _tunings():
        command, stuff = _arm("a", **COMMAND_ARM), _arm("b", **STUFF_ARM)
        for leverage in ("high", "long", "mid"):
            scores = {
                arm.pitcher.player_id: engine._reliever_score(
                    arm, leverage, score_diff=1, tuning=tuning
                )
                for arm in (command, stuff)
            }
            # The pitch grades are not read: the command arm is preferred.
            assert scores["a"] > scores["b"], (name, leverage)


def test_stuff_score_reads_the_generation_s_weights_under_model_1():
    weights = {
        "pitcher_score_model": 1.0, "pitcher_score_weight_control": 0.24,
        "pitcher_score_weight_movement": 0.25,
        "pitcher_score_weight_grade": 0.39, "pitcher_score_weight_arm": 0.12,
    }
    tuning = load_tuning(weights)
    command, stuff = _arm("a", **COMMAND_ARM), _arm("b", **STUFF_ARM)
    assert engine._pitcher_stuff_score(command.pitcher, tuning) == pytest.approx(
        0.24 * 64 + 0.25 * 60 + 0.39 * 41 + 0.12 * 62
    )
    assert engine._pitcher_stuff_score(stuff.pitcher, tuning) == pytest.approx(
        0.24 * 48 + 0.25 * 52 + 0.39 * 70 + 0.12 * 50
    )
    # Now the manager brings in the arm with the pitches.
    for leverage in ("high", "mid"):
        assert engine._reliever_score(
            stuff, leverage, score_diff=1, tuning=tuning
        ) > engine._reliever_score(command, leverage, score_diff=1, tuning=tuning)
    # The weights are relative: doubling all four changes nothing.
    doubled = load_tuning({k: v * (2.0 if "weight" in k else 1.0)
                           for k, v in weights.items()})
    assert engine._pitcher_stuff_score(stuff.pitcher, doubled) == pytest.approx(
        engine._pitcher_stuff_score(stuff.pitcher, tuning)
    )
    # All-zero weights fall back to the old mean instead of dividing by zero.
    zero = load_tuning({**{k: 0.0 for k in weights}, "pitcher_score_model": 1.0})
    assert engine._pitcher_stuff_score(stuff.pitcher, zero) == (48 + 52 + 50) / 3.0


def test_stuff_score_is_league_relative_and_fills_in_a_missing_repertoire():
    tuning = load_tuning(
        {**_g5_overrides("calibration"), **CENTRED, "pitcher_score_model": 1.0}
    )
    w_control, w_movement, w_grade, w_arm = (
        DEFAULT_TUNING[f"pitcher_score_weight_{name}"]
        for name in ("control", "movement", "grade", "arm")
    )
    total = w_control + w_movement + w_grade + w_arm
    stuff = _arm("b", **STUFF_ARM).pitcher
    expected = (
        w_control * (48 - 53 + 50) + w_movement * (52 - 51 + 50)
        + w_grade * (70 - 55 + 50) + w_arm * (50 - 56 + 50)
    ) / total
    assert engine._pitcher_stuff_score(stuff, tuning) == pytest.approx(expected)
    # No repertoire: the league's average pitch, as the pitch itself has it.
    bare = _arm("c", control=48.0, movement=52.0, arm=50.0, grades=()).pitcher
    assert engine._pitcher_stuff_score(bare, tuning) == pytest.approx(
        expected - w_grade * 15.0 / total
    )
    # The registered weights are the profile's.
    profile = _profile()
    for name, weight in zip(
        ("control", "movement", "grade", "arm"),
        (w_control, w_movement, w_grade, w_arm),
    ):
        assert profile[f"pitcher_score_weight_{name}"] == weight


def test_the_profile_s_manager_weights_are_a_share_each():
    profile = _profile()
    weights = [
        profile.get(f"pitcher_score_weight_{name}", DEFAULT_TUNING[
            f"pitcher_score_weight_{name}"
        ])
        for name in ("control", "movement", "grade", "arm")
    ]
    assert all(weight > 0.0 for weight in weights)
    assert sum(weights) == pytest.approx(1.0, abs=0.011)
    # Pitch grade is the largest share, as it is of pitch quality.
    assert weights[2] == max(weights)


# --- the Velocity Scale slider ------------------------------------------------------


def _velocity_spec(sections):
    (spec,) = [
        s for _label, specs in sections for s in specs if s.key == "velocity_scale"
    ]
    return spec


def test_velocity_slider_is_untouched_before_generation_6():
    assert tuning_sections() is _TUNING_SECTIONS
    assert tuning_sections(0.0, 0.0, 0.0) is _TUNING_SECTIONS
    legacy = _velocity_spec(_TUNING_SECTIONS)
    assert legacy.description == "Pitch velocity scaling."
    for generation in (4, 5):
        assert _velocity_spec(tuning_sections_for_generation(generation)) is legacy
    # Generation 5's own swaps are as they were.
    assert tuning_sections(1.0, 1.0) == tuning_sections(1.0, 1.0, 0.0)


def test_velocity_slider_says_it_helps_pitchers_from_generation_6():
    profile = _profile()
    sections = tuning_sections(1.0, 1.0, float(profile["ev_velocity_model"]))
    spec = _velocity_spec(sections)
    assert spec is _VELOCITY_MODEL_SLIDERS["velocity_scale"]
    legacy = _velocity_spec(_TUNING_SECTIONS)
    # The same key, range and step: no stored value needs converting.
    assert (spec.key, spec.label, spec.min_value, spec.max_value, spec.step) == (
        legacy.key, legacy.label, legacy.min_value, legacy.max_value, legacy.step
    )
    text = spec.description.lower()
    assert "strikeouts" in text and "pitchers" in text and "reverse" in text
    # Nothing else in the catalog moves with it.
    before = tuning_sections(1.0, 1.0)
    assert [label for label, _ in sections] == [label for label, _ in before]
    for (_l, new_specs), (_m, old_specs) in zip(sections, before):
        assert [s.key for s in new_specs] == [s.key for s in old_specs]
        assert [s for s in new_specs if s.key != "velocity_scale"] == [
            s for s in old_specs if s.key != "velocity_scale"
        ]
    # The velocity swap alone, on a league without the Release 5 models.
    alone = tuning_sections(0.0, 0.0, 1.0)
    assert _velocity_spec(alone) is spec
    assert sum(len(specs) for _l, specs in alone) == sum(
        len(specs) for _l, specs in _TUNING_SECTIONS
    )


def test_more_velocity_helps_the_pitcher_on_generation_6_only():
    """The slider's claim, on the kernel: the same hitters strike out more
    against faster pitches under the generation 6 profile, and not under
    generation 5 (where speed only made the ball come off harder)."""
    import random

    import physics_sim.physics as physics

    def strikeout_share(tuning, n=6000):
        random.seed(31)
        batter = {"contact": 50.0, "power": 50.0, "eye": 50.0, "bats": "R"}
        pitcher = {"repertoire": {"fb": 50.0, "sl": 50.0}, "control": 50.0,
                   "movement": 50.0, "velocity": 93.0, "hand": "R"}
        swings = misses = 0
        for _ in range(n):
            res = physics.simulate_pitch(
                batter=batter, pitcher=pitcher, tuning=tuning, count=(1, 2)
            )
            if res.swing and res.outcome != "interference":
                swings += 1
                misses += not res.contact
        return misses / swings

    centres = {key: 50.0 for key in _g5_overrides("calibration")
               if key.endswith("_center") or "_center_" in key}
    g5 = {**engine_profile(5), **centres}
    g6 = {**g5, **kpis.load_tuning_overrides_file(PROFILE_PATH)}
    slow = strikeout_share(load_tuning({**g6, "velocity_scale": 0.97}))
    fast = strikeout_share(load_tuning({**g6, "velocity_scale": 1.03}))
    assert fast - slow > 0.03
    assert strikeout_share(load_tuning({**g5, "velocity_scale": 0.97})) == (
        pytest.approx(
            strikeout_share(load_tuning({**g5, "velocity_scale": 1.03})), abs=0.012
        )
    )
