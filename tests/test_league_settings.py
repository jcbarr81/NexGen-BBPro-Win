import importlib

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    monkeypatch.setenv("NEXGEN_DATA_DIR", str(data_root))
    import utils.path_utils as path_utils
    path_utils._DATA_DIR = None
    import utils.league_settings as league_settings
    importlib.reload(league_settings)
    return data_root


def test_default_settings(data_dir):
    import utils.league_settings as league_settings

    settings = league_settings.load_league_settings()
    assert settings.get("mode") == "single_player"
    assert not league_settings.is_owner_league(settings)


def test_commissioner_password(data_dir):
    import utils.league_settings as league_settings

    league_settings.configure_league_settings(
        mode="owner_league",
        commissioner_password="secret123",
    )
    assert league_settings.is_owner_league()
    assert league_settings.verify_commissioner_password("secret123")
    assert not league_settings.verify_commissioner_password("wrong")


def test_commissioner_password_legacy_scheme_mismatch(data_dir):
    import utils.league_settings as league_settings

    legacy_hash, _scheme = league_settings._hash_password("secret123")
    settings = {
        "mode": "owner_league",
        "commissioner_password": legacy_hash,
        "commissioner_password_scheme": "bcrypt",
    }
    assert league_settings.verify_commissioner_password(
        "secret123",
        settings=settings,
    )
