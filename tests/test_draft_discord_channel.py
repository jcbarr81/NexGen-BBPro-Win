"""8.6.6: amateur draft posts go to their own Discord channel.

``NEXGEN_DISCORD_DRAFT_WEBHOOK_URL`` receives the "on the clock" post and,
new here, each pick: one post per pick an owner (or the clock) makes, and one
post for a run of CPU picks (Discord rate-limits a webhook). Without it the
draft posts fall back to the main webhook, as before.
"""

from __future__ import annotations

import pytest

from api.routers import draft as D
from services import discord_notify
from services.draft_announcement import build_pick_messages


@pytest.fixture
def webhooks(monkeypatch):
    monkeypatch.setenv(discord_notify.WEBHOOK_ENV, "https://example.invalid/main")
    monkeypatch.delenv(discord_notify.DRAFT_WEBHOOK_ENV, raising=False)
    return monkeypatch


def test_draft_posts_use_their_own_webhook(webhooks):
    webhooks.setenv(discord_notify.DRAFT_WEBHOOK_ENV, "https://example.invalid/draft")
    assert discord_notify.webhook_url(discord_notify.DRAFT) == "https://example.invalid/draft"
    assert discord_notify.webhook_url() == "https://example.invalid/main"


def test_without_a_draft_webhook_draft_posts_use_the_main_one(webhooks):
    assert discord_notify.webhook_url(discord_notify.DRAFT) == "https://example.invalid/main"


def test_nothing_configured_means_nothing_posts(monkeypatch):
    monkeypatch.delenv(discord_notify.WEBHOOK_ENV, raising=False)
    monkeypatch.delenv(discord_notify.DRAFT_WEBHOOK_ENV, raising=False)
    assert discord_notify.is_configured(discord_notify.DRAFT) is False
    assert discord_notify.post("hi", channel=discord_notify.DRAFT) is False


def _pick(n, team="BAL", name="Joe Prospect", pos="SS"):
    return {"round": 1, "overall": n, "team_id": team, "name": name, "position": pos}


def test_one_pick_is_one_post_naming_team_player_and_position():
    posts = build_pick_messages(league_id="alpha-test", year=2027, picks=[_pick(7)])
    assert len(posts) == 1
    assert "Round 1, pick 7" in posts[0]
    assert "BAL" in posts[0] and "Joe Prospect (SS)" in posts[0]


def test_a_run_of_picks_is_one_post_with_a_line_each():
    posts = build_pick_messages(
        league_id="alpha-test", year=2027, picks=[_pick(n) for n in range(1, 11)]
    )
    assert len(posts) == 1
    assert "10 picks" in posts[0]
    assert posts[0].count("Round 1, pick") == 10


def test_a_long_run_splits_under_the_discord_limit():
    picks = [_pick(n, name="A Very Long Prospect Name Indeed") for n in range(1, 101)]
    posts = build_pick_messages(league_id="alpha-test", year=2027, picks=picks, limit=1900)
    assert len(posts) > 1
    assert all(len(p) <= 1900 for p in posts)
    assert sum(p.count("Round 1, pick") for p in posts) == 100


def test_the_last_pick_says_the_draft_is_over():
    posts = build_pick_messages(
        league_id="alpha-test", year=2027, picks=[_pick(100)], draft_complete=True
    )
    assert "completes the 2027 draft" in posts[-1]


def test_no_picks_no_post():
    assert build_pick_messages(league_id="alpha-test", year=2027, picks=[]) == []


def test_picks_are_announced_to_the_draft_channel(webhooks):
    sent = []
    webhooks.setattr(discord_notify, "post", lambda text, **k: sent.append((text, k)) or True)
    webhooks.setattr(D, "_prospect_lookup", lambda year: {
        "D1": {"first_name": "Joe", "last_name": "Prospect", "primary_position": "CF"},
    })
    D._announce_picks(
        2027,
        [{"round": 1, "overall": 3, "team_id": "BAL", "player_id": "D1"}],
        draft_complete=False,
    )
    assert len(sent) == 1
    text, kwargs = sent[0]
    assert kwargs.get("channel") == discord_notify.DRAFT
    assert "Joe Prospect (CF)" in text


def test_auto_advance_announces_its_run_once(monkeypatch):
    """A run of CPU picks is announced together, not pick by pick."""

    state = {"year": 2027, "round": 1, "overall_pick": 1, "order": ["AAA", "BBB", "CCC"], "selected": []}
    announced = []

    def fake_do_pick(year, st, *, player_id, season_date=None, announce=True, **_):
        assert announce is False
        team = D._team_on_clock(st)
        st["selected"] = list(st["selected"]) + [{"overall": st["overall_pick"], "team_id": team}]
        st["overall_pick"] += 1
        if (st["overall_pick"] - 1) % len(st["order"]) == 0:
            st["round"] += 1
        return {"round": 1, "overall": st["overall_pick"] - 1, "team_id": team, "player_id": player_id}

    monkeypatch.setattr(D.draft_state, "load_state", lambda year: state)
    monkeypatch.setattr(D, "_do_pick", fake_do_pick)
    monkeypatch.setattr(D, "_best_available", lambda y, s: {"player_id": f"P{s['overall_pick']}"})
    monkeypatch.setattr(D, "_load_settings_rounds", lambda: 1)
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: set()
    )
    monkeypatch.setattr(
        D, "_announce_picks",
        lambda year, picks, *, draft_complete: announced.append((len(picks), draft_complete)),
    )
    D.auto_advance({"year": 2027, "stop": "end_of_draft"}, identity={"r": "admin", "t": ""})
    assert announced == [(3, True)]
