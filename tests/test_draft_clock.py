"""The pick clock, and the message that tells an owner about it.

A draft with real owners stalls the moment one is unavailable, and nobody else
can do anything about it. So a team on the clock gets a deadline; when it
passes the CPU picks and the draft moves on.
"""

from datetime import datetime, timedelta, timezone

import pytest

from services import draft_clock
from services.draft_announcement import build_on_the_clock_message
from services.draft_settings import (
    DEFAULT_PICK_CLOCK_HOURS,
    DraftSettings,
    load_draft_settings,
    save_draft_settings,
)

T0 = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def on_clock():
    state = {}
    draft_clock.start(state, "BAL", now=T0)
    return state


# --- the clock -------------------------------------------------------------


def test_the_deadline_is_the_start_plus_the_configured_hours(on_clock):
    assert draft_clock.deadline(on_clock, "BAL", 24) == T0 + timedelta(hours=24)


def test_it_expires_only_after_the_deadline(on_clock):
    assert draft_clock.is_expired(on_clock, "BAL", 24, now=T0 + timedelta(hours=23)) is False
    assert draft_clock.is_expired(on_clock, "BAL", 24, now=T0 + timedelta(hours=24)) is True
    assert draft_clock.is_expired(on_clock, "BAL", 24, now=T0 + timedelta(hours=25)) is True


def test_zero_hours_means_the_draft_waits_forever(on_clock):
    """The old behaviour, still available: no deadline, no auto-pick."""
    assert draft_clock.deadline(on_clock, "BAL", 0) is None
    assert draft_clock.is_expired(on_clock, "BAL", 0, now=T0 + timedelta(days=365)) is False
    assert draft_clock.seconds_remaining(on_clock, "BAL", 0) is None


def test_a_clock_naming_another_team_is_never_read_as_this_one(on_clock):
    """It belongs to a pick already made; reading it would expire the wrong
    team instantly."""
    assert draft_clock.started_at(on_clock, "CHI") is None
    assert draft_clock.deadline(on_clock, "CHI", 24) is None
    assert draft_clock.is_expired(on_clock, "CHI", 24, now=T0 + timedelta(days=9)) is False


def test_team_ids_match_regardless_of_case():
    state = draft_clock.start({}, "bal", now=T0)
    assert draft_clock.started_at(state, "BAL") == T0


def test_seconds_remaining_counts_down_and_floors_at_zero(on_clock):
    assert draft_clock.seconds_remaining(on_clock, "BAL", 24, now=T0) == 86400
    assert draft_clock.seconds_remaining(on_clock, "BAL", 24, now=T0 + timedelta(hours=12)) == 43200
    assert draft_clock.seconds_remaining(on_clock, "BAL", 24, now=T0 + timedelta(days=3)) == 0


def test_starting_the_clock_again_restarts_it(on_clock):
    later = T0 + timedelta(hours=5)
    draft_clock.start(on_clock, "CHI", now=later)
    assert draft_clock.started_at(on_clock, "CHI") == later
    assert draft_clock.started_at(on_clock, "BAL") is None


def test_ensure_started_does_not_move_a_running_clock(on_clock):
    assert draft_clock.ensure_started(on_clock, "BAL", now=T0 + timedelta(hours=9)) == T0


def test_ensure_started_begins_one_for_a_draft_that_had_none():
    """A draft already mid-pick when the clock shipped must get one rather than
    waiting forever."""
    state = {}
    assert draft_clock.ensure_started(state, "BAL", now=T0) == T0
    assert draft_clock.deadline(state, "BAL", 24) == T0 + timedelta(hours=24)


def test_no_team_on_the_clock_clears_it(on_clock):
    draft_clock.start(on_clock, None)
    assert draft_clock.CLOCK_KEY not in on_clock


def test_a_corrupt_timestamp_does_not_raise():
    state = {draft_clock.CLOCK_KEY: {"team_id": "BAL", "since": "not-a-date"}}
    assert draft_clock.started_at(state, "BAL") is None
    assert draft_clock.is_expired(state, "BAL", 24) is False


# --- the setting -----------------------------------------------------------


def test_the_clock_is_off_by_default():
    """Turning it on is a deliberate choice; an existing draft must not start
    auto-picking the moment this ships."""
    assert DEFAULT_PICK_CLOCK_HOURS == 0
    assert DraftSettings().pick_clock_hours == 0


def test_the_setting_round_trips(tmp_path):
    save_draft_settings(DraftSettings(rounds=4, pool_size=100, pick_clock_hours=12), data_dir=tmp_path)
    assert load_draft_settings(tmp_path).pick_clock_hours == 12


def test_a_nonsense_clock_falls_back_rather_than_crashing(tmp_path):
    (tmp_path / "draft_settings.json").write_text(
        '{"rounds": 4, "pool_size": 100, "pick_clock_hours": "soon"}', encoding="utf-8"
    )
    assert load_draft_settings(tmp_path).pick_clock_hours == DEFAULT_PICK_CLOCK_HOURS


def test_an_absurd_clock_is_clamped(tmp_path):
    saved = save_draft_settings(
        DraftSettings(rounds=4, pool_size=100, pick_clock_hours=99999), data_dir=tmp_path
    )
    assert saved.pick_clock_hours == 336


def test_settings_written_before_this_existed_still_load(tmp_path):
    (tmp_path / "draft_settings.json").write_text(
        '{"rounds": 4, "pool_size": 100}', encoding="utf-8"
    )
    assert load_draft_settings(tmp_path).pick_clock_hours == 0


# --- the announcement ------------------------------------------------------


def test_the_post_names_the_team_and_the_pick():
    text = build_on_the_clock_message(
        league_id="alpha-test", team_id="BAL", round_no=2, overall_pick=31,
        deadline=T0 + timedelta(hours=24),
    )
    assert "BAL" in text
    assert "Round 2" in text and "31" in text


def test_the_deadline_is_a_discord_timestamp():
    """Owners are in different timezones; <t:..> renders in each reader's."""
    text = build_on_the_clock_message(
        league_id="alpha-test", team_id="BAL", round_no=1, overall_pick=1,
        deadline=T0 + timedelta(hours=24),
    )
    assert "<t:" in text
    assert "CPU will pick for you" in text


def test_with_no_clock_it_does_not_imply_a_deadline():
    text = build_on_the_clock_message(
        league_id="alpha-test", team_id="BAL", round_no=1, overall_pick=1
    )
    assert "waits for you" in text
    assert "<t:" not in text


def test_no_team_means_no_post():
    assert build_on_the_clock_message(
        league_id="alpha-test", team_id="", round_no=1, overall_pick=1
    ) is None
