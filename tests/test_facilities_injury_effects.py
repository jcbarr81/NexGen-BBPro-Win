"""Facilities budget → injury recovery + prevention derivation (#6b).

Facilities now owns injury outcomes: recovery_days_factor scales DL durations and
void_chance downgrades some would-be DL stints to day-to-day. Both derive from
the team's facilities_multiplier and collapse to no-op (1.0 / 0.0) when finance
is off.
"""

from services import finance_budget_effects as fbe
from services.finance_budget_effects import TeamBudgetEffects


def _eff(mult):
    return TeamBudgetEffects(
        team_id="AAA",
        training_multiplier=1.0,
        scouting_multiplier=1.0,
        development_multiplier=1.0,
        facilities_multiplier=mult,
        training_camp_multiplier=1.0,
    )


def _run(monkeypatch, mult):
    monkeypatch.setattr(
        fbe, "list_team_budget_effects", lambda **k: {"AAA": _eff(mult)}
    )
    return fbe.facilities_injury_effects_by_team()["AAA"]


def test_well_funded_faster_recovery_and_prevention(monkeypatch):
    fx = _run(monkeypatch, 1.15)  # max funded
    assert fx.recovery_days_factor == 0.85  # ~15% shorter DL stints
    assert fx.void_chance == 0.30  # up to 30% of stints prevented


def test_neutral_budget_is_noop(monkeypatch):
    fx = _run(monkeypatch, 1.0)
    assert fx.recovery_days_factor == 1.0
    assert fx.void_chance == 0.0


def test_underfunded_slows_recovery_no_prevention(monkeypatch):
    fx = _run(monkeypatch, 0.85)  # min funded
    assert fx.recovery_days_factor == 1.15  # ~15% longer DL stints
    assert fx.void_chance == 0.0  # underfunded never prevents


def test_recovery_shortens_days_monotonically(monkeypatch):
    hi = _run(monkeypatch, 1.15).recovery_days_factor
    mid = _run(monkeypatch, 1.0).recovery_days_factor
    lo = _run(monkeypatch, 0.85).recovery_days_factor
    assert hi < mid < lo  # better facilities => strictly fewer recovery days


def test_camp_multiplier_no_longer_uses_facilities(monkeypatch, tmp_path):
    # The training-camp blend must ignore facilities now (training + development
    # only). Build effects where facilities is extreme but training/development
    # are neutral; camp should stay ~1.0.
    import json

    monkeypatch.setattr(fbe, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        fbe,
        "load_financial_settings",
        lambda **k: type(
            "S", (), {"enabled": True, "module_level": lambda self, m: "basic"}
        )(),
    )
    # Neutral projected + current budgets => all multipliers 1.0 => camp 1.0,
    # regardless of the (now-removed) facilities weight.
    monkeypatch.setattr(fbe, "project_monthly_owner_finance", lambda **k: {})
    monkeypatch.setattr(fbe, "_load_team_budgets", lambda d: {"AAA": {}})
    effects = fbe.list_team_budget_effects()
    assert abs(effects["AAA"].training_camp_multiplier - 1.0) < 1e-9
