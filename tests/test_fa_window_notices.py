"""Owners hear when free-agent bidding opens and as it moves (8.2.0).

- Opening the window posts one league news item and a ``fa_bidding``
  notification to each human-owned club (none for CPU clubs).
- Each window day posts a signings line, and a notification to each owner
  now outbid on someone, by name.
- Ownership unreadable: the notifications stand down (the news still posts).
- The notices write only the news feed and notification files, never the
  window, the negotiations or a roster, and a failing notice never fails the
  window step. A window run on a directory other than the active league
  posts nothing.

Everything runs on a tmp data root.
"""

from __future__ import annotations

import hashlib
import json

import pytest

import services.fa_window as w
from services import fa_negotiations as neg


@pytest.fixture
def league(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "rosters").mkdir(parents=True)
    (root / "teams.csv").write_text(
        "team_id,name,city,abbreviation,division,stadium,primary_color,"
        "secondary_color,owner_id\n",
        encoding="utf-8",
    )
    (root / "users.txt").write_text(
        "commish,pass,admin,\nbal_owner,pass,owner,BAL\n", encoding="utf-8"
    )
    (root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\n"
        "P1,Ann,Able,SS,0\nP2,Ben,Baker,CF,0\nP3,Cal,Cole,P,1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()
    monkeypatch.setattr(w, "finance_fa_enabled", lambda **k: True)
    # The CPU market is not under test: no seeding, no signings.
    monkeypatch.setattr(w, "_seed_cpu_for_day", lambda *a, **k: 7)
    monkeypatch.setattr(
        neg, "process_negotiations", lambda *a, **k: {"signed": [], "deferred": []}
    )
    yield root
    path_utils._DATA_DIR_CACHE.clear()


def _news(root):
    path = root / "news_feed.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _history(team):
    from services.notification_engine import load_history

    return load_history(team)


def _hashes(root, *, skip=("news_feed.txt", "notifications")):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.relative_to(root).parts[0] not in skip
    }


def test_opening_posts_news_and_tells_each_owner(league):
    w.open_window("2026-11-01")
    news = _news(league)
    assert len(news) == 1
    assert news[0].endswith(
        "[free_agency] Free-agent bidding is open: 14 bidding days; "
        "bids for day 1 are due before the commissioner advances the day."
    )
    history = _history("BAL")
    assert len(history) == 1
    event = history[0]
    assert event["rule_id"] == "fa_bidding"
    assert event["title"] == "Free-agent bidding is open"
    assert event["message"] == (
        "Bidding runs 14 bidding days. Bids for day 1 are due "
        "before the commissioner advances the day. CPU clubs have posted opening "
        "offers on 7 players. Make your offers on the Free Agency page; each day "
        "the market moves and players sign."
    )
    assert _history("NYY") == []


def test_reopening_the_same_window_posts_nothing_more(league):
    w.open_window("2026-11-01")
    w.open_window("2026-11-01")
    assert len(_news(league)) == 1
    assert len(_history("BAL")) == 1


def test_a_set_deadline_is_named(league):
    (league / "fa_window_schedule.json").write_text(
        json.dumps({"deadline": "2026-11-02T18:00:00+00:00", "auto_advance": True}),
        encoding="utf-8",
    )
    w.open_window("2026-11-01")
    assert _news(league)[0].endswith(
        "bids for day 1 are due by Nov 2, 2026 18:00 UTC, when the day advances "
        "on its own."
    )


def test_a_day_names_the_signings_and_the_outbid_owner(league, monkeypatch):
    w.open_window("2026-11-01")
    for pid, team, salary in (
        ("P1", "BAL", 1_000_000), ("P1", "NYY", 3_000_000),
        ("P2", "BAL", 5_000_000), ("P2", "NYY", 2_000_000),
    ):
        neg.submit_offer(pid, team, years=1, annual_salary=salary,
                         sim_date="2026-11-01", data_dir=league)
    monkeypatch.setattr(
        neg, "process_negotiations",
        lambda *a, **k: {"signed": [{"player_id": "P3", "signed_team": "NYY",
                                     "annual_salary": 1, "years": 1}]},
    )
    result = w.advance_day()
    assert result["ok"] is True
    assert _news(league)[-1].endswith(
        "[free_agency] Free agency day 1 of 14: 1 signing. Day 2 is open."
    )
    event = _history("BAL")[0]  # newest first
    assert event["title"] == "Outbid on 1 free agent"
    assert event["message"] == (
        "You've been outbid on Ann Able. Day 2 of 14 is open: counter on the Free "
        "Agency page; bids are due before the commissioner advances the day."
    )
    assert event["payload"]["players"] == ["Ann Able"]


def test_no_outbid_notice_when_you_lead(league):
    w.open_window("2026-11-01")
    neg.submit_offer("P2", "BAL", years=1, annual_salary=5_000_000,
                     sim_date="2026-11-01", data_dir=league)
    w.advance_day()
    assert [e["title"] for e in _history("BAL")] == ["Free-agent bidding is open"]
    assert _news(league)[-1].endswith("Free agency day 1 of 14: 0 signings. Day 2 is open.")


def test_closing_day_news(league):
    w.open_window("2026-11-01")
    for _ in range(13):
        w.advance_day()
    w.advance_day()
    assert _news(league)[-1].endswith(
        "Free-agent bidding has closed: 0 signings on day 14 of 14; the remaining "
        "players took their best offer."
    )


def test_a_forced_close_names_the_day_it_ended(league):
    """A phase advance closes the window early; the news says when."""

    w.open_window("2026-11-01")
    w.advance_day()
    w.advance_day()
    w.close_window()
    assert _news(league)[-1].endswith(
        "Free-agent bidding closed early on day 3 of 14 (0 signings at the close); "
        "the remaining players took their best offer."
    )


def test_utc_times_read_the_same_whatever_the_day():
    from services.fa_window_notices import format_utc

    assert format_utc("2026-10-19T08:00:00+00:00") == "Oct 19, 2026 08:00 UTC"
    assert format_utc("2026-10-09T08:00:00+00:00") == "Oct 9, 2026 08:00 UTC"


def test_stands_down_when_ownership_is_unreadable(league, monkeypatch):
    import services.team_ownership as ownership

    monkeypatch.setattr(ownership, "human_owned_team_ids_strict", lambda *a, **k: None)
    w.open_window("2026-11-01")
    assert len(_news(league)) == 1  # league news is not about ownership
    assert _history("BAL") == []


def test_an_owner_who_muted_it_hears_nothing(league):
    from services.notification_settings import save_notification_settings

    save_notification_settings("BAL", {"rules": {"fa_bidding": {"enabled": False}}})
    w.open_window("2026-11-01")
    assert _history("BAL") == []


def test_the_rule_is_on_by_default(league):
    from services.notification_settings import load_notification_settings

    rule = load_notification_settings("BAL").rule("fa_bidding")
    assert rule.enabled and rule.notify and not rule.stop_sim


def test_notices_write_only_news_and_notifications(league):
    from services.fa_window_notices import day_advanced, window_opened

    state = w.open_window("2026-11-01")
    neg.submit_offer("P1", "BAL", years=1, annual_salary=1, sim_date="2026-11-01",
                     data_dir=league)
    neg.submit_offer("P1", "NYY", years=1, annual_salary=9, sim_date="2026-11-01",
                     data_dir=league)
    before = _hashes(league)
    window_opened(state, data_dir=league)
    out = day_advanced(state, day=1, signed=[], data_dir=league)
    assert out["notified"] == {"BAL": ["Ann Able"]}
    assert _hashes(league) == before


def test_a_failing_notice_never_fails_the_window(league, monkeypatch):
    import services.fa_window_notices as notices

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(notices, "window_opened", boom)
    monkeypatch.setattr(notices, "day_advanced", boom)
    assert w.open_window("2026-11-01")["status"] == "open"
    assert w.advance_day()["ok"] is True
    assert _news(league) == []


def test_window_state_is_the_same_with_or_without_notices(league, tmp_path, monkeypatch):
    """The CPU market and the window see no difference: compare a run with
    notices against one with them switched off."""

    import services.fa_window_notices as notices

    def run():
        for name in ("fa_window.json", "fa_negotiations.json"):
            (league / name).unlink(missing_ok=True)
        w.open_window("2026-11-01")
        neg.submit_offer("P1", "BAL", years=1, annual_salary=1, sim_date="2026-11-01",
                         data_dir=league)
        w.advance_day()
        return {
            name: json.loads((league / name).read_text(encoding="utf-8"))
            for name in ("fa_window.json", "fa_negotiations.json")
        }

    with_notices = run()
    monkeypatch.setattr(notices, "window_opened", lambda *a, **k: None)
    monkeypatch.setattr(notices, "day_advanced", lambda *a, **k: None)
    assert run() == with_notices


def test_a_window_on_another_directory_posts_nothing(league, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    w.open_window("2026-11-01", data_dir=other)
    w.advance_day(data_dir=other)
    assert not (other / "news_feed.txt").exists()
    assert _news(league) == [] and _history("BAL") == []
