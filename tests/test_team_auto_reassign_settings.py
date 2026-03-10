from __future__ import annotations

from services.team_auto_reassign_settings import (
    auto_reassign_team_if_enabled,
    load_team_auto_reassign_settings,
    resolve_team_auto_reassign,
    save_team_auto_reassign_settings,
    set_team_auto_reassign,
    update_league_default_auto_reassign,
)


def test_team_auto_reassign_defaults_to_disabled(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    settings = load_team_auto_reassign_settings(data_dir=data_dir, league_id="alpha")

    assert settings["default_enabled"] is False
    assert settings["team_overrides"] == {}


def test_team_auto_reassign_save_and_resolve_override(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)

    update_league_default_auto_reassign(
        True,
        data_dir=data_dir,
        league_id="alpha",
    )
    set_team_auto_reassign(
        "BBB",
        "disabled",
        data_dir=data_dir,
        league_id="alpha",
    )

    aaa = resolve_team_auto_reassign("AAA", data_dir=data_dir, league_id="alpha")
    bbb = resolve_team_auto_reassign("BBB", data_dir=data_dir, league_id="alpha")

    assert aaa.enabled is True
    assert aaa.source == "league_default"
    assert bbb.enabled is False
    assert bbb.source == "team_override"


def test_set_team_auto_reassign_clears_to_default(tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    save_team_auto_reassign_settings(
        default_enabled=False,
        team_overrides={"AAA": True},
        data_dir=data_dir,
        league_id="alpha",
    )

    result = set_team_auto_reassign(
        "AAA",
        "default",
        data_dir=data_dir,
        league_id="alpha",
    )

    assert result["saved"] is True
    settings = load_team_auto_reassign_settings(data_dir=data_dir, league_id="alpha")
    assert settings["team_overrides"] == {}


def test_auto_reassign_team_if_enabled_runs_assignment(monkeypatch, tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    save_team_auto_reassign_settings(
        default_enabled=False,
        team_overrides={"AAA": True},
        data_dir=data_dir,
        league_id="alpha",
    )
    captured: dict[str, object] = {}

    def fake_auto_assign_team(team_id: str, **kwargs):
        captured["team_id"] = team_id
        captured["kwargs"] = kwargs

    monkeypatch.setattr(
        "services.roster_auto_assign.auto_assign_team",
        fake_auto_assign_team,
    )
    monkeypatch.setattr(
        "utils.roster_loader.load_roster.cache_clear",
        lambda **kwargs: captured.setdefault("cache_clear", kwargs),
        raising=False,
    )

    applied = auto_reassign_team_if_enabled(
        "AAA",
        players_file="data/players.csv",
        roster_dir="data/rosters",
        data_dir=data_dir,
        league_id="alpha",
    )

    assert applied is True
    assert captured["team_id"] == "AAA"
    kwargs = dict(captured["kwargs"])
    assert str(kwargs["players_file"]).endswith("players.csv")
    assert str(kwargs["roster_dir"]).endswith("rosters")


def test_auto_reassign_team_if_enabled_skips_when_disabled(monkeypatch, tmp_path):
    data_dir = tmp_path / "league-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    save_team_auto_reassign_settings(
        default_enabled=False,
        team_overrides={},
        data_dir=data_dir,
        league_id="alpha",
    )
    called = {"value": False}

    def fake_auto_assign_team(_team_id: str, **_kwargs):
        called["value"] = True

    monkeypatch.setattr(
        "services.roster_auto_assign.auto_assign_team",
        fake_auto_assign_team,
    )

    applied = auto_reassign_team_if_enabled(
        "AAA",
        data_dir=data_dir,
        league_id="alpha",
    )

    assert applied is False
    assert called["value"] is False
