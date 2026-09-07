"""A finished simulation announces itself to Discord.

Several leagues will be running at once, so every post has to name its league.
Beyond that an owner wants three things: how much baseball just happened, where
the league now sits, and when the next batch is coming.

The posting transport and the wording are separated so this can all be checked
without a network call or a simulation.
"""

import pytest

from services import discord_notify
from services.sim_announcement import build_message, count_games


@pytest.fixture(autouse=True)
def _named_league(monkeypatch):
    monkeypatch.setattr(
        "services.sim_announcement.league_display_name",
        lambda lid: {"alpha-test": "Alpha Test"}.get(lid, lid),
    )


def _msg(**kw):
    kw.setdefault("league_id", "alpha-test")
    kw.setdefault("played_dates", ["2026-05-01", "2026-05-02"])
    kw.setdefault("games", 20)
    return build_message(**kw)


# --- what the post has to contain ------------------------------------------


def test_the_post_names_the_league():
    """With several leagues running, an unlabelled post is useless."""
    assert "Alpha Test" in _msg()


def test_the_post_states_days_and_games():
    text = _msg(played_dates=["2026-05-01"] * 7, games=70)
    assert "7 days" in text
    assert "70 games" in text


def test_singulars_read_properly():
    text = _msg(played_dates=["2026-05-01"], games=1)
    assert "1 day simulated" in text
    assert "1 game" in text
    assert "1 days" not in text and "1 games" not in text


def test_the_post_says_when_the_next_sim_is():
    text = _msg(
        next_deadline="2026-09-06T21:00:00+00:00",
        next_run_label="simulate 1 week",
        auto_run=True,
    )
    assert "Next:" in text
    assert "simulate 1 week" in text
    # Rendered as a Discord timestamp so each reader sees their own local time.
    assert "<t:" in text


def test_a_manual_league_is_described_as_waiting_on_the_commissioner():
    text = _msg(next_deadline="2026-09-06T21:00:00+00:00", auto_run=False)
    assert "commissioner" in text
    assert "<t:" in text


def test_no_schedule_says_so_rather_than_going_silent():
    text = _msg(next_deadline=None)
    assert "No next simulation scheduled" in text


def test_where_the_league_now_sits_is_included():
    text = _msg(current_sim_date="2026-05-02", phase="REGULAR_SEASON")
    assert "2026-05-02" in text
    assert "Regular Season" in text


def test_an_early_stop_is_called_out():
    """Otherwise a short day count looks like the sim just ran less."""
    text = _msg(stopped_reason="Player injured")
    assert "Stopped early" in text
    assert "Player injured" in text


# --- when NOT to post -------------------------------------------------------


def test_a_sim_that_played_nothing_is_not_announced():
    """A draft pause or an empty schedule is not an event; posting it would be
    noise in a shared channel."""
    assert build_message(league_id="alpha-test", played_dates=[], games=0) is None


# --- counting ---------------------------------------------------------------


def test_games_counts_only_the_simulated_dates():
    schedule = [
        {"date": "2026-05-01", "played": "1", "result": "3-2"},
        {"date": "2026-05-01", "played": "1", "result": "5-4"},
        {"date": "2026-05-02", "played": "1", "result": "1-0"},
        {"date": "2026-05-03", "played": "", "result": ""},
    ]
    assert count_games(schedule, ["2026-05-01"]) == 2
    assert count_games(schedule, ["2026-05-01", "2026-05-02"]) == 3
    assert count_games(schedule, ["2026-05-03"]) == 0


def test_games_counts_what_was_played_not_what_was_scheduled():
    """A partially simulated day must not be overstated."""
    schedule = [
        {"date": "2026-05-01", "played": "1", "result": "3-2"},
        {"date": "2026-05-01", "played": "", "result": ""},
    ]
    assert count_games(schedule, ["2026-05-01"]) == 1


def test_counting_survives_a_junk_schedule():
    assert count_games([], ["2026-05-01"]) == 0
    assert count_games([{"nope": 1}], ["2026-05-01"]) == 0


# --- the transport ----------------------------------------------------------


def test_posting_is_off_without_a_webhook(monkeypatch):
    monkeypatch.delenv(discord_notify.WEBHOOK_ENV, raising=False)
    assert discord_notify.is_configured() is False
    assert discord_notify.post("anything") is False


def test_posting_never_raises(monkeypatch):
    """The sim has already run and been persisted; a Discord outage must not
    turn that into a failure."""
    monkeypatch.setenv(discord_notify.WEBHOOK_ENV, "https://example.invalid/hook")

    def boom(*a, **k):
        raise OSError("network is down")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    monkeypatch.setattr(discord_notify, "_record", lambda *a, **k: None)
    assert discord_notify.post("hello") is False


def test_empty_content_is_not_posted(monkeypatch):
    monkeypatch.setenv(discord_notify.WEBHOOK_ENV, "https://example.invalid/hook")
    assert discord_notify.post("   ") is False


def test_long_content_is_truncated_not_dropped(monkeypatch):
    monkeypatch.setenv(discord_notify.WEBHOOK_ENV, "https://example.invalid/hook")
    sent = {}

    class _Resp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout=None):
        sent["body"] = request.data.decode("utf-8")
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert discord_notify.post("x" * 5000) is True
    assert len(sent["body"]) < 5000


# --- the sim hook -----------------------------------------------------------


def test_the_hook_does_nothing_without_a_webhook(monkeypatch):
    """It must not touch the schedule or registry when Discord is off."""
    import api.routers.season as S

    monkeypatch.delenv(discord_notify.WEBHOOK_ENV, raising=False)

    def explode():
        raise AssertionError("_schedule_view must not be called when unconfigured")

    monkeypatch.setattr(S, "_schedule_view", explode)
    S._announce_sim_to_discord("alpha-test", object(), object(), {"played_dates": ["x"]})


def test_the_hook_swallows_its_own_failures(monkeypatch):
    import api.routers.season as S

    monkeypatch.setenv(discord_notify.WEBHOOK_ENV, "https://example.invalid/hook")
    monkeypatch.setattr(
        S, "_schedule_view", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    # Must not raise: the sim is already done and persisted.
    S._announce_sim_to_discord("alpha-test", object(), object(), {"played_dates": ["x"]})
