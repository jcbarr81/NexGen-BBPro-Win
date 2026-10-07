"""Per-team owner play settings store (Release 3)."""

from __future__ import annotations

import json

import pytest

from services.team_play_settings import (
    AUTO_REST_DAYS,
    IL_AUTO_ACTIVATE_15,
    IL_AUTO_ACTIVATE_60,
    REST_SUBS_SIMILAR_POSITIONS,
    SETTINGS_FILENAME,
    TEAM_PLAY_SETTING_KEYS,
    default_team_play_settings,
    get_team_play_setting,
    load_team_play_overrides,
    load_team_play_settings,
    save_team_play_settings,
)
from utils.league_settings import set_auto_activate_il


@pytest.fixture
def data_dir(tmp_path):
    path = tmp_path / "league-data"
    path.mkdir()
    return path


def test_keys():
    assert TEAM_PLAY_SETTING_KEYS == (
        "auto_rest_days",
        "rest_subs_similar_positions",
        "il_auto_activate_15",
        "il_auto_activate_60",
    )


def test_defaults_match_todays_behaviour_without_a_file(data_dir):
    expected = {
        AUTO_REST_DAYS: True,
        REST_SUBS_SIMILAR_POSITIONS: True,
        IL_AUTO_ACTIVATE_15: True,   # league auto_activate_il defaults to on
        IL_AUTO_ACTIVATE_60: False,  # 60-day returns are manual today
    }
    assert default_team_play_settings(data_dir=data_dir) == expected
    assert load_team_play_settings("ABC", data_dir=data_dir) == expected
    assert load_team_play_overrides("ABC", data_dir=data_dir) == {}
    for key, value in expected.items():
        assert get_team_play_setting("ABC", key, data_dir=data_dir) is value
    assert not (data_dir / SETTINGS_FILENAME).exists(), "reads never write"


def test_15_day_default_follows_the_league_setting(data_dir):
    set_auto_activate_il(False, path=data_dir / "league_settings.json")
    assert get_team_play_setting("ABC", IL_AUTO_ACTIVATE_15, data_dir=data_dir) is False
    set_auto_activate_il(True, path=data_dir / "league_settings.json")
    assert get_team_play_setting("ABC", IL_AUTO_ACTIVATE_15, data_dir=data_dir) is True


def test_owner_choice_overrides_the_league_setting(data_dir):
    save_team_play_settings("ABC", {IL_AUTO_ACTIVATE_15: True}, data_dir=data_dir)
    set_auto_activate_il(False, path=data_dir / "league_settings.json")
    assert get_team_play_setting("ABC", IL_AUTO_ACTIVATE_15, data_dir=data_dir) is True
    assert get_team_play_setting("XYZ", IL_AUTO_ACTIVATE_15, data_dir=data_dir) is False


def test_save_and_load_round_trip_per_team(data_dir):
    resolved = save_team_play_settings(
        "abc", {AUTO_REST_DAYS: False, IL_AUTO_ACTIVATE_60: "on"}, data_dir=data_dir
    )
    assert resolved == {
        AUTO_REST_DAYS: False,
        REST_SUBS_SIMILAR_POSITIONS: True,
        IL_AUTO_ACTIVATE_15: True,
        IL_AUTO_ACTIVATE_60: True,
    }
    # Team ids are case-insensitive; other teams keep the defaults.
    assert load_team_play_settings("ABC", data_dir=data_dir) == resolved
    assert load_team_play_overrides(" Abc ", data_dir=data_dir) == {
        AUTO_REST_DAYS: False,
        IL_AUTO_ACTIVATE_60: True,
    }
    assert load_team_play_settings("DEF", data_dir=data_dir)[AUTO_REST_DAYS] is True

    payload = json.loads((data_dir / SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert payload == {
        "version": 1,
        "teams": {"ABC": {AUTO_REST_DAYS: False, IL_AUTO_ACTIVATE_60: True}},
    }


def test_partial_update_keeps_other_choices(data_dir):
    save_team_play_settings("ABC", {AUTO_REST_DAYS: False}, data_dir=data_dir)
    save_team_play_settings("ABC", {REST_SUBS_SIMILAR_POSITIONS: "off"}, data_dir=data_dir)
    save_team_play_settings("DEF", {IL_AUTO_ACTIVATE_60: 1}, data_dir=data_dir)
    assert load_team_play_overrides("ABC", data_dir=data_dir) == {
        AUTO_REST_DAYS: False,
        REST_SUBS_SIMILAR_POSITIONS: False,
    }
    assert load_team_play_overrides("DEF", data_dir=data_dir) == {IL_AUTO_ACTIVATE_60: True}


def test_default_token_clears_a_choice(data_dir):
    save_team_play_settings("ABC", {AUTO_REST_DAYS: False, IL_AUTO_ACTIVATE_60: True},
                            data_dir=data_dir)
    save_team_play_settings("ABC", {AUTO_REST_DAYS: None}, data_dir=data_dir)
    assert load_team_play_overrides("ABC", data_dir=data_dir) == {IL_AUTO_ACTIVATE_60: True}
    save_team_play_settings("ABC", {IL_AUTO_ACTIVATE_60: "default"}, data_dir=data_dir)
    assert load_team_play_overrides("ABC", data_dir=data_dir) == {}
    payload = json.loads((data_dir / SETTINGS_FILENAME).read_text(encoding="utf-8"))
    assert payload["teams"] == {}


@pytest.mark.parametrize(
    "team_id, updates",
    [
        ("ABC", {"auto_rest": True}),
        ("ABC", {AUTO_REST_DAYS: "maybe"}),
        ("", {AUTO_REST_DAYS: True}),
        (None, {AUTO_REST_DAYS: True}),
    ],
)
def test_invalid_saves_raise_and_write_nothing(data_dir, team_id, updates):
    with pytest.raises(ValueError):
        save_team_play_settings(team_id, updates, data_dir=data_dir)
    assert not (data_dir / SETTINGS_FILENAME).exists()


def test_unknown_key_lookup_raises(data_dir):
    with pytest.raises(KeyError):
        get_team_play_setting("ABC", "not_a_setting", data_dir=data_dir)


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", json.dumps({"teams": []}), json.dumps({"teams": {"ABC": "x"}})],
)
def test_unreadable_file_reads_as_defaults(data_dir, content):
    (data_dir / SETTINGS_FILENAME).write_text(content, encoding="utf-8")
    assert load_team_play_settings("ABC", data_dir=data_dir) == default_team_play_settings(
        data_dir=data_dir
    )
    # A save over a damaged file starts it afresh.
    save_team_play_settings("ABC", {AUTO_REST_DAYS: False}, data_dir=data_dir)
    assert get_team_play_setting("ABC", AUTO_REST_DAYS, data_dir=data_dir) is False


def test_stored_junk_values_and_keys_are_ignored(data_dir):
    (data_dir / SETTINGS_FILENAME).write_text(
        json.dumps({"version": 1, "teams": {"ABC": {
            AUTO_REST_DAYS: "nonsense",
            IL_AUTO_ACTIVATE_60: "yes",
            "legacy_key": True,
        }}}),
        encoding="utf-8",
    )
    assert load_team_play_overrides("ABC", data_dir=data_dir) == {IL_AUTO_ACTIVATE_60: True}
    assert get_team_play_setting("ABC", AUTO_REST_DAYS, data_dir=data_dir) is True


def test_defaults_to_the_active_league_data_dir(monkeypatch, data_dir):
    import services.team_play_settings as store
    import utils.league_settings as league_settings

    monkeypatch.setattr(store, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(league_settings, "get_data_dir", lambda: data_dir)
    save_team_play_settings("ABC", {AUTO_REST_DAYS: False})
    assert (data_dir / SETTINGS_FILENAME).exists()
    assert get_team_play_setting("ABC", AUTO_REST_DAYS) is False
    set_auto_activate_il(False)
    assert get_team_play_setting("ABC", IL_AUTO_ACTIVATE_15) is False
    assert not list(data_dir.glob("*.tmp*")), "atomic write leaves no temp files"
