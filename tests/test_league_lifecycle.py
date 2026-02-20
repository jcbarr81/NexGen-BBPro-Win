import importlib
import json

import pytest


def _reload_modules():
    import utils.path_utils as path_utils

    importlib.reload(path_utils)
    path_utils._DATA_DIR = None

    import services.league_registry as league_registry
    import services.league_lifecycle as league_lifecycle

    importlib.reload(league_registry)
    importlib.reload(league_lifecycle)
    return path_utils, league_registry, league_lifecycle


def test_clone_league_copies_data_and_retags_context(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)

    path_utils, league_registry, league_lifecycle = _reload_modules()
    league_registry.register_league("alpha", display_name="Alpha League")
    source_data = league_registry.get_league_data_dir("alpha", create=True)
    (source_data / "teams.csv").write_text("team_id,name\nAAA,Alphas\n", encoding="utf-8")
    (source_data / "career_index.json").write_text(
        json.dumps(
            {
                "league": {"id": "alpha", "name": "Alpha League"},
                "current": {"league_year": 2026, "season_id": "alpha-2026"},
                "seasons": [{"league_year": 2025, "season_id": "alpha-2025"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (source_data / "trade_settings.json").write_text(
        json.dumps(
            {
                "version": 1,
                "leagues": {
                    "alpha": {
                        "trades_enabled": True,
                        "draft_pick_trading_enabled": False,
                        "require_commissioner_approval": False,
                        "max_pick_trade_years": 3,
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    cloned = league_lifecycle.clone_league("alpha", display_name="Beta League")
    assert cloned.id == "beta-league"

    cloned_data = league_registry.get_league_data_dir("beta-league", create=False)
    assert (cloned_data / "teams.csv").exists()
    assert path_utils.get_active_league_id() == "alpha"

    cloned_context = json.loads((cloned_data / "career_index.json").read_text(encoding="utf-8"))
    assert cloned_context["league"]["id"] == "beta-league"
    assert cloned_context["current"]["season_id"] == "beta-league-2026"
    assert cloned_context["seasons"][0]["season_id"] == "beta-league-2025"

    cloned_trade = json.loads((cloned_data / "trade_settings.json").read_text(encoding="utf-8"))
    assert "beta-league" in cloned_trade["leagues"]


def test_archive_and_switch_guards(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)

    path_utils, league_registry, league_lifecycle = _reload_modules()
    league_registry.register_league("alpha")
    league_registry.register_league("beta")
    league_registry.set_active_league("alpha")

    archived = league_lifecycle.archive_league("alpha")
    assert archived.status == "archived"
    assert path_utils.get_active_league_id() == "beta"

    with pytest.raises(ValueError):
        league_lifecycle.switch_active_league("alpha")
    restored = league_lifecycle.unarchive_league("alpha")
    assert restored.status == "active"

    league_lifecycle.switch_active_league("alpha")
    assert path_utils.get_active_league_id() == "alpha"

    league_lifecycle.archive_league("alpha")
    with pytest.raises(ValueError):
        league_lifecycle.archive_league("beta")


def test_delete_league_safeguards(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)

    path_utils, league_registry, league_lifecycle = _reload_modules()
    league_registry.register_league("alpha")
    league_registry.register_league("beta")
    league_registry.set_active_league("alpha")

    alpha_data = league_registry.get_league_data_dir("alpha", create=True)
    (alpha_data / "teams.csv").write_text("team_id,name\nAAA,Alphas\n", encoding="utf-8")

    with pytest.raises(ValueError):
        league_lifecycle.delete_league("alpha")

    removed = league_lifecycle.delete_league("alpha", force_if_active=True)
    assert removed is True
    assert league_registry.get_league("alpha") is None
    assert not (data_root / "leagues" / "alpha").exists()
    assert path_utils.get_active_league_id() == "beta"

    with pytest.raises(ValueError):
        league_lifecycle.delete_league("beta", force_if_active=True)
