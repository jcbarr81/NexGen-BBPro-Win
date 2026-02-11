from types import SimpleNamespace
from datetime import date, timedelta

import pytest

from playbalance.playbalance_config import PlayBalanceConfig
from utils.pitcher_recovery import PitcherRecoveryTracker, _parse_date
from utils.path_utils import get_base_dir


def _set_overrides(**values):
    cfg = PlayBalanceConfig.from_file(get_base_dir() / "playbalance" / "PBINI.txt")
    vals = {
        "enableUsageModelV2": 1,
        "restDaysPitchesLvl0": 10,
        "restDaysPitchesLvl1": 20,
        "restDaysPitchesLvl2": 35,
        "restDaysPitchesLvl3": 50,
        "restDaysPitchesLvl4": 70,
        "restDaysPitchesLvl5": 95,
        "b2bMaxPriorPitches": 20,
        "forbidThirdConsecutiveDay": 1,
        "warmupTaxPitches": 50,  # bump for warmup test
        "reliefB2BBudgetFloor": 0.45,
    }
    vals.update(values)
    for k, v in vals.items():
        setattr(cfg, k, v)
    # Save will also update module defaults used by cfg.get fallbacks
    cfg.save_overrides()


def _dummy_state(pid: str, pitches: int):
    player = SimpleNamespace(player_id=pid, role="RP", assigned_pitching_role="CL")
    return SimpleNamespace(player=player, pitches_thrown=pitches)


def test_rest_curve_applied_in_record_game(tmp_path):
    _set_overrides()
    tracker = PitcherRecoveryTracker(path=tmp_path / "pitcher_recovery_test.json")
    team_id = "ATL"
    pid = "P6994"  # ATL closer per roster
    players_file = get_data_dir() / "players.csv"
    roster_dir = get_data_dir() / "rosters"

    # Day 1: 10 pitches -> 0 days rest
    d1 = "2025-04-01"
    tracker.record_game(team_id, d1, [_dummy_state(pid, 10)], players_file, roster_dir)
    entry = tracker.data.get("teams", {}).get(team_id, {})
    st = entry.get("pitchers", {}).get(pid, {})
    assert _parse_date(st.get("available_on")) == _parse_date(d1)

    # Day 2: 35 pitches -> 2 days rest
    d2 = "2025-04-02"
    tracker.record_game(team_id, d2, [_dummy_state(pid, 35)], players_file, roster_dir)
    entry = tracker.data.get("teams", {}).get(team_id, {})
    st = entry.get("pitchers", {}).get(pid, {})
    assert _parse_date(st.get("available_on")) == _parse_date(d2) + timedelta(days=2)


def test_b2b_allowed_then_third_day_block(tmp_path):
    _set_overrides()
    tracker = PitcherRecoveryTracker(path=tmp_path / "pitcher_recovery_test.json")
    team_id = "ATL"
    pid = "P6994"
    players_file = get_data_dir() / "players.csv"
    roster_dir = get_data_dir() / "rosters"

    # Day 1: small workload (10) → 0 rest
    d1 = "2025-04-01"
    tracker.record_game(team_id, d1, [_dummy_state(pid, 10)], players_file, roster_dir)
    ok, reason = tracker.is_available(team_id, pid, "CL", "2025-04-02", players_file, roster_dir)
    assert ok, f"Expected available on B2B with low pitches, got {reason}"

    # Day 2: another small workload (10)
    d2 = "2025-04-02"
    tracker.record_game(team_id, d2, [_dummy_state(pid, 10)], players_file, roster_dir)
    # Day 3: third consecutive day should be blocked
    ok, reason = tracker.is_available(team_id, pid, "CL", "2025-04-03", players_file, roster_dir)
    assert not ok and reason == "third_day_block"


def test_warmup_tax_for_closer_capped(tmp_path):
    _set_overrides(warmupTaxPitches=50)
    tracker = PitcherRecoveryTracker(path=tmp_path / "pitcher_recovery_test.json")
    team_id = "ATL"
    pid = "P6994"
    players_file = get_data_dir() / "players.csv"
    roster_dir = get_data_dir() / "rosters"

    d = "2025-04-01"
    # Ensure team exists
    tracker.ensure_team(team_id, players_file, roster_dir)
    # Record warmup only for the closer
    tracker.record_warmups(team_id, d, {pid: object()}, players_file, roster_dir)
    entry = tracker.data.get("teams", {}).get(team_id, {})
    st = entry.get("pitchers", {}).get(pid, {})
    # Warmup tax is capped for short relief arms: only a single day of rest
    assert _parse_date(st.get("available_on")) == _parse_date(d) + timedelta(days=1)
    max_pitches = float(st.get("max_pitches", 0) or 0)
    avail_pitches = float(st.get("available_pitches", 0) or 0)
    assert max_pitches > 0
    assert avail_pitches < max_pitches  # budget penalty applied
    # Once the next day begins, the closer should clear availability checks.
    tracker.start_day("2025-04-02")
    ok, reason = tracker.is_available(team_id, pid, "CL", "2025-04-02", players_file, roster_dir)
    assert ok, f"Expected closer to be available after warmup cap, got {reason}"


def test_closer_budget_override_allows_b2b(tmp_path):
    _set_overrides(reliefB2BBudgetFloor=0.45)
    tracker = PitcherRecoveryTracker(path=tmp_path / "pitcher_recovery_test.json")
    team_id = "ATL"
    pid = "P6994"
    players_file = get_data_dir() / "players.csv"
    roster_dir = get_data_dir() / "rosters"

    d1 = "2025-04-01"
    tracker.record_game(team_id, d1, [_dummy_state(pid, 28)], players_file, roster_dir)

    ok, reason = tracker.is_available(team_id, pid, "CL", "2025-04-02", players_file, roster_dir)
    assert ok, f"Expected budget override for B2B relief, got {reason}"
