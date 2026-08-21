"""Self-healing playoff bracket: if the league is in PLAYOFFS but the bracket
file was lost (write missed the working-copy push), the /playoffs read path
regenerates a fresh year-stamped bracket from standings instead of stranding
the league. The heal is self-contained (generates directly) so it can't latch
onto an orphan no-year playoffs.json.
"""

from types import SimpleNamespace

import api.routers.playoffs as pv


def _patch_phase(monkeypatch, phase_attr):
    import playbalance.season_manager as sm

    monkeypatch.setattr(sm.SeasonManager, "__init__", lambda self: None, raising=False)
    monkeypatch.setattr(
        sm.SeasonManager,
        "phase",
        property(lambda self: getattr(sm.SeasonPhase, phase_attr)),
        raising=False,
    )


def test_no_heal_when_bracket_exists(monkeypatch):
    monkeypatch.setattr(pv, "_list_years", lambda: [2026])
    # Should short-circuit before touching phase/generation.
    assert pv._self_heal_bracket_if_missing() is False


def test_no_heal_when_not_playoffs(monkeypatch):
    monkeypatch.setattr(pv, "_list_years", lambda: [])
    _patch_phase(monkeypatch, "REGULAR_SEASON")
    assert pv._self_heal_bracket_if_missing() is False


def test_heals_when_playoffs_and_missing(monkeypatch):
    calls = {"saved": False}

    def _years():
        return [2026] if calls["saved"] else []

    monkeypatch.setattr(pv, "_list_years", _years)
    _patch_phase(monkeypatch, "PLAYOFFS")

    import playbalance.playoffs as pf
    import playbalance.playoffs_config as pc
    import utils.team_loader as tl
    import api.routers.season as season
    import api.working_copy as wc

    monkeypatch.setattr(season, "_sync_standings_from_stats", lambda *a, **k: None)
    monkeypatch.setattr(tl, "load_teams", lambda: [object()])
    monkeypatch.setattr(pf, "_load_standings_snapshot", lambda: {"AUS": {"wins": 91}})
    monkeypatch.setattr(pc, "load_playoffs_config", lambda: object())
    monkeypatch.setattr(pf, "generate_bracket", lambda s, t, c: SimpleNamespace(year=2026))

    def _save(bracket):
        calls["saved"] = True  # bracket now "exists"

    monkeypatch.setattr(pf, "save_bracket", _save)
    monkeypatch.setattr(wc, "is_enabled", lambda: False)

    assert pv._self_heal_bracket_if_missing() is True
    assert pv._list_years() == [2026]


def test_heal_false_when_standings_missing(monkeypatch):
    monkeypatch.setattr(pv, "_list_years", lambda: [])
    _patch_phase(monkeypatch, "PLAYOFFS")

    import playbalance.playoffs as pf
    import utils.team_loader as tl
    import api.routers.season as season

    monkeypatch.setattr(season, "_sync_standings_from_stats", lambda *a, **k: None)
    monkeypatch.setattr(tl, "load_teams", lambda: [object()])
    monkeypatch.setattr(pf, "_load_standings_snapshot", lambda: {})  # empty
    called = {"gen": False}
    monkeypatch.setattr(
        pf, "generate_bracket",
        lambda *a, **k: called.__setitem__("gen", True) or SimpleNamespace(year=2026),
    )

    assert pv._self_heal_bracket_if_missing() is False
    assert called["gen"] is False  # never attempted with no standings
