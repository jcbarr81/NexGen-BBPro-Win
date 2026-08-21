"""#10: the payroll outlook must surface payroll numbers whenever finance is
enabled — even when payroll enforcement (gm_payroll_rules) is off — so the owner
can always see their payroll and how an offer moves it. Enforcement details
(threshold / luxury tax / headroom) stay gated on the rules being active.
"""

from services import payroll_policy as pp


class _Settings:
    def __init__(self, enabled, preset, payroll_level):
        self.enabled = enabled
        self.preset = preset
        self._lvl = payroll_level

    def module_level(self, module):
        return self._lvl if module == "gm_payroll_rules" else "off"


def _setup(monkeypatch, *, enabled, preset, payroll_level):
    monkeypatch.setattr(
        pp, "load_financial_settings", lambda **k: _Settings(enabled, preset, payroll_level)
    )
    monkeypatch.setattr(pp, "_enforcement_mode", lambda s: "on")
    monkeypatch.setattr(pp, "calculate_annual_payroll_totals", lambda **k: {"AAA": 50_000_000})
    monkeypatch.setattr(pp, "project_monthly_owner_finance", lambda **k: {})
    monkeypatch.setattr(
        pp, "_load_team_financial_map", lambda **k: {"AAA": {"cash_on_hand": 10_000_000, "debt": 0}}
    )
    monkeypatch.setattr(pp, "_debt_cap_for_preset", lambda p: 20_000_000)
    monkeypatch.setattr(pp, "_projected_debt_after_delta", lambda **k: 0)
    monkeypatch.setattr(pp, "_payroll_threshold", lambda *a, **k: 60_000_000)
    monkeypatch.setattr(pp, "_payroll_floor", lambda *a, **k: 30_000_000)


def test_finance_off_returns_no_numbers(monkeypatch):
    _setup(monkeypatch, enabled=False, preset=pp.PRESET_OFF, payroll_level="off")
    out = pp.build_team_payroll_outlook("AAA", extra_annual_salary=5_000_000)
    assert out["active"] is False
    assert not out.get("info")
    assert "payroll" not in out


def test_finance_on_rules_off_shows_info_no_threshold(monkeypatch):
    _setup(monkeypatch, enabled=True, preset="simple", payroll_level="off")
    out = pp.build_team_payroll_outlook("AAA", extra_annual_salary=5_000_000)
    assert out["active"] is False
    assert out.get("info") is True
    assert out["payroll"] == 50_000_000
    assert out["projected_payroll"] == 55_000_000
    assert "cash_after_bonus" in out and "opening_day_solvent" in out
    # No enforcement threshold/tax when payroll rules are off.
    assert "threshold" not in out
    assert "estimated_tax" not in out


def test_finance_on_rules_active_full_detail(monkeypatch):
    _setup(monkeypatch, enabled=True, preset="mlb_like", payroll_level=pp.LEVEL_MLB_LIKE)
    out = pp.build_team_payroll_outlook("AAA", extra_annual_salary=5_000_000)
    assert out["active"] is True
    assert out.get("info") is True
    assert out["payroll"] == 50_000_000
    assert out["projected_payroll"] == 55_000_000
    assert out["threshold"] == 60_000_000
    assert out["headroom"] == 60_000_000 - 55_000_000  # under threshold
    assert out["zone"] == "safe"
