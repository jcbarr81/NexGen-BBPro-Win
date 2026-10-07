"""Audit M15 (2026-10-06): scripts/injury_rate_kpi.py counts IL stints only
and runs at its default length."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import injury_rate_kpi as inj  # noqa: E402
from playbalance.schedule_generator import generate_mlb_schedule  # noqa: E402


def test_il_stint_excludes_day_to_day():
    assert inj.is_il_stint({"dl_tier": "dl15"})
    assert inj.is_il_stint({"dl_tier": "il60"})
    assert inj.is_il_stint({"dl_tier": "il7"})
    assert not inj.is_il_stint({"dl_tier": "none"})
    assert not inj.is_il_stint({"dl_tier": ""})
    assert not inj.is_il_stint({})


def test_summarize_counts_il_stints_only():
    positions = {"P1": "SP", "P2": "RP", "H1": "SS", "H2": "CF"}
    events = [
        {"player_id": "P1", "dl_tier": "dl15", "days": 15, "trigger": "pitcher_overuse"},
        {"player_id": "P2", "dl_tier": "il60", "days": 60, "trigger": "pitcher_overuse"},
        {"player_id": "H1", "dl_tier": "dl15", "days": 10, "trigger": "swing"},
        # Day-to-day knocks: reported, never counted as IL stints.
        {"player_id": "H2", "dl_tier": "none", "days": 2, "trigger": "collision"},
        {"player_id": "P1", "dl_tier": "none", "days": 1, "trigger": "swing"},
    ]
    # 2 teams x 162 games = 324 team-games -> per-team-season = count / 2.
    m = inj.summarize_events(events, total_team_games=324, positions=positions)
    assert m["il_stints_total"] == 3
    assert m["il_stints_per_team_season"] == 1.5
    assert m["pitcher_il_stints_per_team_season"] == 1.0
    assert m["hitter_il_stints_per_team_season"] == 0.5
    assert m["pitcher_share_of_il"] == pytest.approx(0.667, abs=1e-3)
    assert m["avg_days_per_il_stint"] == pytest.approx(85 / 3, abs=0.05)
    assert m["all_injury_events_total"] == 5
    assert m["all_injury_events_per_team_season"] == 2.5
    assert m["il_by_trigger"] == {"pitcher_overuse": 2, "swing": 1}
    assert m["all_by_tier"] == {"dl15": 2, "il60": 1, "none": 2}


def test_summarize_handles_no_injuries():
    m = inj.summarize_events([], total_team_games=0, positions={})
    assert m["il_stints_per_team_season"] == 0.0
    assert m["pitcher_share_of_il"] is None
    assert m["avg_days_per_il_stint"] is None


def test_default_length_builds_a_schedule_for_the_fixture():
    # The old default (--games 54) was below the schedule generator's minimum
    # for the 30-team fixture and crashed before simulating anything.
    assert inj.SEASON_GAMES == 162
    teams = inj.kpi._team_ids(ROOT / inj.DEFAULT_BASE_DIR / "teams.csv")
    schedule = generate_mlb_schedule(teams, date(2025, 4, 1), inj.SEASON_GAMES)
    assert len(schedule) == len(teams) * inj.SEASON_GAMES // 2


def test_too_short_season_is_a_clean_cli_error(capsys):
    with pytest.raises(SystemExit) as exc:
        inj.main(["--games", "10"])
    assert exc.value.code == 2
    assert "smaller than the minimum" in capsys.readouterr().err
