"""Release 6a (power): switched off, the engine plays the game it played.

Every key this work registered -- the Power table, Power's share of the
doubles gap credit, the line-drive credit, the Power term on contact --
defaults to a value that leaves the legacy engine and generation 5 exactly
as they were and draws no extra random number. The digests below were
taken on the commit before this work (3abbbc251, the Release 6a tooling
merge, exported with ``git archive``).

The switched-on values are ``scripts/kpi_profiles/r6_power.json``, run with
``--engine 6 --tuning-overrides`` until the lead folds them into the
generation 6 profile (which this branch does not touch).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import physics_sim.engine as engine
import physics_sim.physics as physics
import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import DEFAULT_TUNING, load_tuning
from physics_sim.engine_generation import engine_profile

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
CALIBRATION_LEAGUE = REPO / "data" / "calibration_league"
PROFILE_PATH = REPO / "scripts" / "kpi_profiles" / "r6_power.json"
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

# Every key this work registered, with the value that leaves the engine as
# it was.
OFF_VALUES = {
    "power_curve_model": 0.0,
    "double_gap_power_weight": 0.5,
    "double_line_drive_scale": 0.0,
    "contact_logit_power": 0.0,
}
GAMES = {
    "cal": (CALIBRATION, "CAL01", "CAL02", (1, 2, 3)),
    "league": (CALIBRATION_LEAGUE, "ALB", "DET", (1, 2)),
}
# sha256 of the canonical JSON (every float at full precision, as its repr)
# of the pitch log, totals and metadata of seeded games, legacy engine and
# generation 5, each with its fixture's rating centres. RE-BASELINE only
# when the default-tuning stream changes on purpose.
PINNED_DIGESTS = {
    "legacy_cal1": "4d35f48aaf285ec561d508d98d1388dba9be0ffc8c5b438d71355a2b27a81cf3",
    "legacy_cal2": "50bf57034e8703bd1bca879382566fba8377e5a489d481604e2f68e8de42a33d",
    "legacy_cal3": "45c579301769bff5b03684d1e1e9fdc7467827146aad667e18e2f458bda57622",
    "gen5_cal1": "ae207bbf85cecbca180b270b4fbeb884edb18e1cd7ea1d7e02e53efb5dd85182",
    "gen5_cal2": "11f807f5d043c297552db41c765b22cb73a0d748d945e1b5a2947d2630dfa2ea",
    "gen5_cal3": "45ef91c39708c07fdfe799a9c7e2a4f59c371226b6fd3a1662e31b5531e9bef0",
    "legacy_league1": "9464f264b60018c334d95be029483f8c96f982101a154a15366a600a4529ce7d",
    "legacy_league2": "54d9c6386ce7db1f3b7e7b9600b097ced38712f6dfcfd456283e96e7152e7dcd",
    "gen5_league1": "2b8bdb2e01dc5256a799b75c1ec95fb190104fd8c65c1fe49d5df539c2f39942",
    "gen5_league2": "d527f323e142643e94a9e2731fd99a77e2b1afadab97267dd7a5f6562d14ac1f",
}


def _canon(value):
    if isinstance(value, float):
        # Full precision: a number moved in its last bit changes the digest.
        return float.__repr__(value)
    if isinstance(value, dict):
        return {str(k): _canon(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    return value


def _digest(result) -> str:
    blob = json.dumps(
        _canon(
            {"pitch_log": result.pitch_log, "totals": result.totals,
             "meta": result.metadata}
        ),
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _play(name: str, seed: int, profile: dict, extra: dict | None = None):
    base, away, home, _seeds = GAMES[name]
    players = base / "players.csv"
    overrides = kpis.with_rating_centers(profile, players, base)
    overrides.update(extra or {})
    return engine.simulate_matchup_from_files(
        away_team=away, home_team=home, base_dir=base, players_path=players,
        seed=seed, tuning_overrides=overrides,
    )


def _all_digests(extra: dict | None = None) -> dict[str, str]:
    out = {}
    for name, (_base, _away, _home, seeds) in GAMES.items():
        for label, profile in (("legacy", {}), ("gen5", engine_profile(5))):
            for seed in seeds:
                game = _play(name, seed, profile, extra)
                out[f"{label}_{name}{seed}"] = _digest(game)
    return out


def test_every_new_key_is_registered_at_its_off_value():
    for key, value in OFF_VALUES.items():
        assert DEFAULT_TUNING[key] == value, key
    assert isinstance(DEFAULT_TUNING["bat_speed_power_table"], dict)
    assert DEFAULT_TUNING["double_line_drive_span"] > 0.0
    profile = engine_profile(5)
    assert not (set(OFF_VALUES) | {"bat_speed_power_table"}) & set(profile)
    # Generation 6 holds this work's values since the Release 6a integration.
    profile = engine_profile(6, development=True)
    assert {key: profile[key] for key in PROFILE} == PROFILE


def test_legacy_and_generation_5_games_match_the_pinned_digests():
    got = _all_digests()
    assert got == PINNED_DIGESTS, f"got {got}"


def test_the_off_values_spelled_out_play_the_same_games():
    assert _all_digests(dict(OFF_VALUES)) == PINNED_DIGESTS


def test_the_profile_is_valid_and_sits_on_top_of_generation_6():
    for key in PROFILE:
        assert key in DEFAULT_TUNING, key
    # Built over generation 5 (generation 6 was its copy then); since the
    # integration generation 6 holds it, so laying it over 6 is a no-op.
    six = engine_profile(6, development=True)
    run = kpis.resolve_run_overrides(engine=6, overrides_path=PROFILE_PATH)
    assert run == six
    base = engine_profile(5)
    overrides = kpis.load_tuning_overrides_file(PROFILE_PATH, base=base)
    assert set(overrides) == set(PROFILE)
    tuning = load_tuning({**base, **overrides})
    assert tuning.get("power_curve_model") == 1.0
    assert tuning.get("double_line_drive_scale") > 0.0
    assert tuning.get("double_gap_power_weight") < 0.5
    assert tuning.get("contact_logit_power") == 0.0
    # Nothing else of generation 5 moves: the home run level is re-set with
    # the table's centre, not with hr_scale.
    assert set(PROFILE) == {
        "power_curve_model", "bat_speed_power_table", "double_gap_power_weight",
        "double_gap_scale", "double_line_drive_scale", "double_line_drive_span",
        "double_distance_scale",
    }
    before = load_tuning(base)
    assert all(tuning.values[key] != before.values[key] for key in PROFILE)
    assert tuning.get("hr_scale") == before.get("hr_scale") == 0.91
    # Generation 6's hr_scale is the pitching work's (a joint-retune lever).
    assert load_tuning(six).get("hr_scale") == 0.9195


def test_the_profile_reaches_the_engine():
    """The profile over generation 5 (what this work was built on) is a
    different game from generation 5, and each of its three parts moves it
    by itself."""
    base = engine_profile(5)
    overrides = kpis.load_tuning_overrides_file(PROFILE_PATH, base=base)
    games = [("cal", 1), ("cal", 2), ("cal", 3), ("league", 1), ("league", 2)]

    def digests(extra=None):
        return [_digest(_play(name, seed, base, extra)) for name, seed in games]

    plain = digests()
    assert plain == [PINNED_DIGESTS[f"gen5_{name}{seed}"] for name, seed in games]
    assert all(a != b for a, b in zip(digests(overrides), plain))
    curve = {k: overrides[k] for k in ("power_curve_model", "bat_speed_power_table")}
    line_drive = {
        "double_line_drive_scale": overrides["double_line_drive_scale"],
        "double_line_drive_span": load_tuning(overrides).get("double_line_drive_span"),
    }
    # A doubles term moves a game only when it moves a hit type in it, so
    # it is asked to change one of the five games, not every one. (Power's
    # share of the gap credit moves the double line by a foot or two for a
    # typical hitter and can leave five games alone; the distance itself is
    # checked in tests/test_r6a_power_doubles.py.)
    assert all(a != b for a, b in zip(digests(curve), plain))
    assert digests(line_drive) != plain


@pytest.mark.parametrize("profile", [{}, engine_profile(5)], ids=["legacy", "gen5"])
def test_off_a_plate_appearance_draws_the_random_numbers_it_always_drew(
    profile, monkeypatch
):
    """The same count of ``random.random`` and ``random.gauss`` calls in a
    seeded game whether the new keys are absent or spelled out off."""
    import random as random_module

    def count(extra):
        calls = {"random": 0, "gauss": 0}
        real_random, real_gauss = random_module.random, random_module.gauss

        def counted_random():
            calls["random"] += 1
            return real_random()

        def counted_gauss(mu, sigma):
            calls["gauss"] += 1
            return real_gauss(mu, sigma)

        monkeypatch.setattr(physics.random, "random", counted_random)
        monkeypatch.setattr(physics.random, "gauss", counted_gauss)
        try:
            result = _play("cal", 2, profile, extra)
        finally:
            monkeypatch.undo()
        return calls, _digest(result)

    plain = count(None)
    assert plain[0]["random"] > 500 and plain[0]["gauss"] > 500
    assert count(dict(OFF_VALUES)) == plain
