import importlib


def _reload_modules():
    import utils.path_utils as path_utils

    importlib.reload(path_utils)
    path_utils._DATA_DIR = None

    import services.league_registry as league_registry

    importlib.reload(league_registry)
    return path_utils, league_registry


def test_register_and_set_active_league(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)

    path_utils, league_registry = _reload_modules()

    league_registry.register_league("alpha", display_name="Alpha League")
    league_registry.register_league(
        "beta",
        display_name="Beta League",
        mode="owner_league",
    )
    league_registry.set_active_league("beta")

    leagues = league_registry.list_leagues()
    assert [league.id for league in leagues] == ["alpha", "beta"]
    assert path_utils.get_active_league_id() == "beta"
    assert (data_root / "active_league.txt").read_text(encoding="utf-8") == "beta"
    assert league_registry.get_active_league().id == "beta"

    beta_data = league_registry.get_league_data_dir("beta", create=True)
    assert beta_data == data_root / "leagues" / "beta" / "data"
    assert beta_data.exists()


def test_get_data_dir_legacy_mode_without_registry(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)

    path_utils, _league_registry = _reload_modules()

    resolved_data_dir = path_utils.get_data_dir()
    assert resolved_data_dir == data_root
    assert path_utils.resolve_app_path("data/teams.csv") == data_root / "teams.csv"


def test_get_data_dir_uses_active_league_context(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)

    path_utils, league_registry = _reload_modules()

    league_registry.register_league("alpha", display_name="Alpha League")
    league_registry.set_active_league("alpha")

    path_utils._DATA_DIR = None
    resolved_data_dir = path_utils.get_data_dir()
    expected_data_dir = data_root / "leagues" / "alpha" / "data"
    assert resolved_data_dir == expected_data_dir
    assert resolved_data_dir.exists()
    assert path_utils.resolve_app_path("data/players.csv") == expected_data_dir / "players.csv"


def test_env_active_league_override_wins_over_pointer(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)

    path_utils, league_registry = _reload_modules()
    league_registry.register_league("alpha")
    league_registry.register_league("beta")
    league_registry.set_active_league("alpha")

    monkeypatch.setenv("NEXGEN_ACTIVE_LEAGUE", "beta")
    path_utils._DATA_DIR = None

    resolved_data_dir = path_utils.get_data_dir()
    assert resolved_data_dir == data_root / "leagues" / "beta" / "data"
