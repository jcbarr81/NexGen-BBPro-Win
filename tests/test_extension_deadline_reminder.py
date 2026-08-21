"""#9: the extension deadline is the end of the playoffs (owners can re-sign
walk-year players right through the postseason), and a reminder surfaces during
the season's final stretch so nobody forgets and loses players at the offseason.
"""

import csv

from api.routers import finance as fin
from services.contract_negotiator import check_extension_eligibility


# --- Deadline: extensions allowed through the playoffs, not the draft ---

def test_playoffs_no_longer_blocks_extensions():
    result = check_extension_eligibility(
        service_time_days=100,  # pre-arb
        current_years_left=1,
        current_phase="PLAYOFFS",
    )
    assert result.eligible is True


def test_amateur_draft_still_blocks_extensions():
    result = check_extension_eligibility(
        service_time_days=100,
        current_years_left=1,
        current_phase="AMATEUR_DRAFT",
    )
    assert result.eligible is False
    assert result.code == "phase_blocked"


def test_walk_year_still_locked_out():
    # years_left <= 0 = walk year over -> free agency, not extendable.
    result = check_extension_eligibility(
        service_time_days=100, current_years_left=0, current_phase="PLAYOFFS"
    )
    assert result.eligible is False
    assert result.code == "fa_year_lockout"


# --- Reminder helpers ---

def test_walk_year_count_only_counts_this_team_years_left_one(monkeypatch):
    monkeypatch.setattr(
        "services.contracts_service.load_contracts_payload",
        lambda **k: {
            "players": {
                "p1": {"team_id": "AAA", "years_left": 1},  # walk year, AAA ✓
                "p2": {"team_id": "AAA", "years_left": 3},  # not walk year
                "p3": {"team_id": "AAA", "years_left": 0},  # already expired
                "p4": {"team_id": "BBB", "years_left": 1},  # other team
            }
        },
    )
    assert fin._walk_year_count_for_team("AAA", data_dir=None) == 1


def test_days_remaining_counts_distinct_unplayed_dates(tmp_path):
    sched = tmp_path / "schedule.csv"
    with sched.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=["date", "home", "away", "result", "played"])
        w.writeheader()
        w.writerow({"date": "2025-04-01", "home": "A", "away": "B", "result": "5-3", "played": "1"})
        w.writerow({"date": "2025-04-02", "home": "A", "away": "B", "result": "", "played": ""})
        w.writerow({"date": "2025-04-02", "home": "C", "away": "D", "result": "", "played": ""})  # same date
        w.writerow({"date": "2025-04-03", "home": "A", "away": "B", "result": "", "played": ""})
    # Two distinct unplayed dates (04-02, 04-03); 04-01 is played.
    assert fin._regular_season_days_remaining(tmp_path) == 2


def test_days_remaining_none_without_schedule(tmp_path):
    assert fin._regular_season_days_remaining(tmp_path) is None
