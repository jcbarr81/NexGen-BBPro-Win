"""The dashboard hero's streak and last-10 come from the played schedule (8.12.4).

standings.json carries only wins and losses, so the hero card read "--" for
Streak and Last 10 while the division table beside it, which already rebuilt
them from the schedule, read W3 and 7-3.
"""

from api.routers import dashboard


def _metrics(**over):
    base = {"record": "56-36", "run_diff": "+62", "streak": "--", "last10": "--",
            "next_opponent": "DEN", "next_date": "2026-07-21", "injuries": 0, "prob_sp": None}
    base.update(over)
    return base


def test_the_hero_fills_streak_and_last10_from_the_schedule(monkeypatch):
    import services.standings_form as form

    monkeypatch.setattr(dashboard, "_safe_metrics", lambda tid: _metrics())
    monkeypatch.setattr(form, "streak_last10_from_schedule",
                        lambda: {"WAS": {"streak": "W3", "last10": "7-3"}})
    snap = dashboard.team_snapshot("WAS")
    assert snap["streak"] == "W3"
    assert snap["last10"] == "7-3"


def test_a_known_streak_is_kept(monkeypatch):
    import services.standings_form as form

    monkeypatch.setattr(dashboard, "_safe_metrics", lambda tid: _metrics(streak="L2", last10="4-6"))
    monkeypatch.setattr(form, "streak_last10_from_schedule",
                        lambda: {"WAS": {"streak": "W3", "last10": "7-3"}})
    snap = dashboard.team_snapshot("WAS")
    assert (snap["streak"], snap["last10"]) == ("L2", "4-6")


def test_no_schedule_form_leaves_the_dashes(monkeypatch):
    import services.standings_form as form

    monkeypatch.setattr(dashboard, "_safe_metrics", lambda tid: _metrics())
    monkeypatch.setattr(form, "streak_last10_from_schedule", lambda: {})
    snap = dashboard.team_snapshot("WAS")
    assert (snap["streak"], snap["last10"]) == ("--", "--")


# --- the lineup check reads "LF|RF" (8.12.4) -----------------------------------


def test_pipe_separated_positions_count_as_eligible():
    from services.roster_validation import _player_positions

    player = {"primary_position": "CF", "other_positions": "LF|RF"}
    assert _player_positions(player) == {"CF", "LF", "RF"}


def test_older_position_formats_still_parse():
    from services.roster_validation import _player_positions

    assert _player_positions({"primary_position": "2B", "other_positions": "SS,3B"}) == {"2B", "SS", "3B"}
    assert _player_positions({"primary_position": "2B", "other_positions": "SS/3B"}) == {"2B", "SS", "3B"}
    assert _player_positions({"primary_position": "C", "other_positions": "['1B']"}) == {"C", "1B"}
    assert _player_positions({"primary_position": "C", "other_positions": ""}) == {"C"}
