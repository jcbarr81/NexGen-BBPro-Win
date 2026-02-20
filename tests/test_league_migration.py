import importlib
import json


def _reload_modules():
    import utils.path_utils as path_utils
    import services.league_registry as league_registry
    import services.league_migration as league_migration

    importlib.reload(path_utils)
    path_utils._DATA_DIR = None
    importlib.reload(league_registry)
    importlib.reload(league_migration)
    return path_utils, league_registry, league_migration


def _write_legacy_fixture(data_root):
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "league.txt").write_text("Legacy Test League", encoding="utf-8")
    (data_root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,Alphas,Alpha,AAA,East,Alpha Park,#000000,#FFFFFF,\n",
        encoding="utf-8",
    )
    (data_root / "players.csv").write_text(
        "player_id,first_name,last_name,is_pitcher\nP1,Test,Player,0\n",
        encoding="utf-8",
    )
    (data_root / "users.txt").write_text("admin,pass,admin,\n", encoding="utf-8")
    (data_root / "schedule.csv").write_text(
        "date,home,away,result,played,boxscore\n2026-04-01,AAA,BBB,,0,\n",
        encoding="utf-8",
    )


def test_migrate_legacy_layout_moves_files_and_registers_league(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    _write_legacy_fixture(data_root)

    path_utils, league_registry, league_migration = _reload_modules()
    result = league_migration.migrate_legacy_layout_if_needed()

    assert result.status == "migrated"
    assert result.backup_path is not None and result.backup_path.exists()
    assert result.league_id == "legacy-test-league"

    assert not (data_root / "teams.csv").exists()
    assert not (data_root / "users.txt").exists()

    league_data = data_root / "leagues" / "legacy-test-league" / "data"
    assert (league_data / "teams.csv").exists()
    assert (league_data / "users.txt").exists()
    assert path_utils.get_active_league_id() == "legacy-test-league"

    marker = json.loads(result.marker_path.read_text(encoding="utf-8"))
    assert marker.get("status") == "completed"
    assert league_registry.get_league("legacy-test-league") is not None


def test_migrate_legacy_layout_skips_when_registry_exists(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    _write_legacy_fixture(data_root)

    path_utils, league_registry, league_migration = _reload_modules()
    league_registry.register_league("alpha", display_name="Alpha")
    path_utils._DATA_DIR = None

    result = league_migration.migrate_legacy_layout_if_needed()
    assert result.status == "skipped"
    assert "Registry already present" in result.message


def test_migrate_repairs_registry_from_existing_league_dirs(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    league_data = data_root / "leagues" / "alpha" / "data"
    league_data.mkdir(parents=True, exist_ok=True)
    (league_data / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,secondary_color,owner_id\n"
        "AAA,Alphas,Alpha,AAA,East,Alpha Park,#000000,#FFFFFF,\n",
        encoding="utf-8",
    )
    (league_data / "users.txt").write_text("admin,pass,admin,\n", encoding="utf-8")

    path_utils, league_registry, league_migration = _reload_modules()
    result = league_migration.migrate_legacy_layout_if_needed()

    assert result.status == "repaired_registry"
    assert league_registry.get_league("alpha") is not None
    assert path_utils.get_active_league_id() == "alpha"


def test_restore_pre_multi_league_layout_from_backup(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    _write_legacy_fixture(data_root)

    path_utils, league_registry, league_migration = _reload_modules()
    migrate_result = league_migration.migrate_legacy_layout_if_needed()
    assert migrate_result.status == "migrated"
    assert migrate_result.backup_path is not None and migrate_result.backup_path.exists()
    assert (data_root / "leagues").exists()

    blocked = league_migration.restore_pre_multi_league_layout()
    assert blocked.status == "blocked"

    restored = league_migration.restore_pre_multi_league_layout(force=True)
    assert restored.status == "restored"
    assert (data_root / "teams.csv").exists()
    assert (data_root / "users.txt").exists()
    assert not (data_root / "leagues").exists()
    assert not (data_root / "league_registry.json").exists()
    assert not (data_root / "active_league.txt").exists()
    assert restored.marker_path.exists()
