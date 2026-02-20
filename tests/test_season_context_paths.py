import importlib


def test_season_context_uses_path_parent_for_careers(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))

    import utils.path_utils as path_utils
    import playbalance.season_context as season_context

    path_utils._DATA_DIR = None
    importlib.reload(path_utils)
    importlib.reload(season_context)

    custom_index = data_root / "leagues" / "alpha" / "data" / "career_index.json"
    ctx = season_context.SeasonContext.load(path=custom_index)
    ctx.ensure_league(name="Alpha League", league_id="alpha")
    ctx.ensure_current_season(league_year=2026)
    ctx.save()

    assert custom_index.exists()
    season_dir = ctx.season_directory()
    assert season_dir.parent == custom_index.parent / "careers"
