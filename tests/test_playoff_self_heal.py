"""Self-healing playoff bracket: if the league is in PLAYOFFS but the bracket
file was lost (write missed the working-copy push), the /playoffs read path
regenerates it from standings instead of stranding the league.
"""

from types import SimpleNamespace

import api.routers.playoffs as pv


class _Phase:
    def __init__(self, value):
        self.value = value


def _patch_phase(monkeypatch, phase_value):
    class _Mgr:
        phase = _Phase(phase_value)

    import playbalance.season_manager as sm

    monkeypatch.setattr(sm, "SeasonManager", lambda *a, **k: _Mgr())
    monkeypatch.setattr(sm, "SeasonPhase", SimpleNamespace(PLAYOFFS=_Phase("PLAYOFFS")))
    # Compare by .value in the module under test.
    monkeypatch.setattr(
        _Mgr.__class__ if False else _Mgr, "phase", _Phase(phase_value), raising=False
    )


def test_no_heal_when_bracket_exists(monkeypatch):
    monkeypatch.setattr(pv, "_list_years", lambda: [2026])
    called = {"gen": False}

    def _boom(*a, **k):
        called["gen"] = True
        return {"saved": True}

    # Should short-circuit before touching season/generation.
    assert pv._self_heal_bracket_if_missing() is False
    assert called["gen"] is False


def test_no_heal_when_not_playoffs(monkeypatch):
    monkeypatch.setattr(pv, "_list_years", lambda: [])

    import playbalance.season_manager as sm

    monkeypatch.setattr(sm.SeasonManager, "__init__", lambda self: None, raising=False)
    monkeypatch.setattr(
        sm.SeasonManager, "phase", property(lambda self: sm.SeasonPhase.REGULAR_SEASON),
        raising=False,
    )
    assert pv._self_heal_bracket_if_missing() is False


def test_heals_when_playoffs_and_missing(monkeypatch):
    # No bracket yet, then present after generation.
    calls = {"n": 0}

    def _years():
        return [] if calls["n"] == 0 else [2026]

    monkeypatch.setattr(pv, "_list_years", _years)

    import playbalance.season_manager as sm

    monkeypatch.setattr(sm.SeasonManager, "__init__", lambda self: None, raising=False)
    monkeypatch.setattr(
        sm.SeasonManager, "phase", property(lambda self: sm.SeasonPhase.PLAYOFFS),
        raising=False,
    )

    import api.routers.season as season

    def _gen():
        calls["n"] = 1  # bracket now "exists"
        return {"saved": True, "path": "playoffs_2026.json"}

    monkeypatch.setattr(season, "_sync_standings_from_stats", lambda *a, **k: None)
    monkeypatch.setattr(season, "_ensure_playoff_bracket", _gen)

    import api.working_copy as wc

    monkeypatch.setattr(wc, "is_enabled", lambda: False)

    assert pv._self_heal_bracket_if_missing() is True
    assert pv._list_years() == [2026]


def test_heal_reports_false_on_generation_error(monkeypatch):
    monkeypatch.setattr(pv, "_list_years", lambda: [])

    import playbalance.season_manager as sm

    monkeypatch.setattr(sm.SeasonManager, "__init__", lambda self: None, raising=False)
    monkeypatch.setattr(
        sm.SeasonManager, "phase", property(lambda self: sm.SeasonPhase.PLAYOFFS),
        raising=False,
    )

    import api.routers.season as season

    monkeypatch.setattr(season, "_sync_standings_from_stats", lambda *a, **k: None)
    monkeypatch.setattr(season, "_ensure_playoff_bracket", lambda: {"error": "no standings"})

    assert pv._self_heal_bracket_if_missing() is False
