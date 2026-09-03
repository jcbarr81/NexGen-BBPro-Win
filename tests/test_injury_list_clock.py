"""The injured list runs on the LEAGUE's clock, with MLB's tiers.

Two bugs are pinned here.

The clock: ``place_on_injury_list`` stamped ``date.today()`` over the sim dates
the simulator had just written, and both the recovery automation and the
injuries endpoint measured against the wall clock too. A 15-day stint therefore
expired 15 days after you happened to press the button — sim a season in an
afternoon and nobody healed; leave the league idle a fortnight and everyone did.

The tiers: ``DL_MINIMUM_DAYS`` was ``{"dl15": 15}`` and nothing else, so a
player on the 60-day IR had no minimum at all and was instantly activatable.
MLB is 10 days for position players, 15 for pitchers, 60 for the long list.
"""

from datetime import date, timedelta

import pytest

from models.player import Player
from models.roster import Roster
from services import injury_manager as im
from services.injury_manager import (
    IL_MINIMUM_DAYS,
    disabled_list_days_remaining,
    injury_list_for,
    is_player_dl_eligible,
    place_on_injury_list,
)


def _player(pid="p1", position="CF", pitcher=False):
    p = Player(
        player_id=pid,
        first_name="A",
        last_name="B",
        birthdate="2000-01-01",
        height=72,
        weight=180,
        bats="R",
        primary_position=position,
        other_positions=[],
        gf=0,
    )
    p.is_pitcher = pitcher
    return p


@pytest.fixture
def sim_clock(monkeypatch):
    """Drive the league date from the test."""
    state = {"date": "2026-04-26"}

    def _fake():
        return state["date"]

    monkeypatch.setattr("utils.sim_date.get_current_sim_date", _fake)
    return state


# --- MLB tiers --------------------------------------------------------------


def test_mlb_minimums():
    assert IL_MINIMUM_DAYS == {"il7": 7, "il10": 10, "il15": 15, "il60": 60}


def test_position_players_get_ten_days_pitchers_fifteen():
    assert injury_list_for(_player(position="CF"), "dl15") == "il10"
    assert injury_list_for(_player(position="P"), "dl15") == "il15"
    assert injury_list_for(_player(position="SS", pitcher=True), "dl15") == "il15"


def test_legacy_tier_names_still_resolve():
    """Rosters saved before the MLB tiers landed must keep counting down."""
    for legacy in ("ir", "dl45", "45-day", "injured reserve"):
        assert injury_list_for(_player(), legacy) == "il60"


def test_sixty_day_list_actually_holds_players(sim_clock):
    """The IR bug: no minimum meant instantly activatable."""
    p = _player()
    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    place_on_injury_list(p, roster, list_name="il60", today=date(2026, 4, 26))

    assert p.injury_list == "il60"
    assert disabled_list_days_remaining(p, date(2026, 4, 26)) == 60
    assert is_player_dl_eligible(p, date(2026, 5, 30)) is False
    assert is_player_dl_eligible(p, date(2026, 6, 25)) is True


def test_legacy_ir_player_is_not_instantly_eligible(sim_clock):
    """A player stored under the old 'ir' name, mid-stint, stays held."""
    p = _player()
    p.injury_list = "ir"
    p.injury_start_date = "2026-04-01"
    p.injury_eligible_date = "2026-05-31"
    assert disabled_list_days_remaining(p, date(2026, 4, 26)) == 35
    assert is_player_dl_eligible(p, date(2026, 4, 26)) is False


# --- the league clock -------------------------------------------------------


def test_placement_uses_the_league_date_not_the_wall_clock(sim_clock):
    p = _player()
    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    place_on_injury_list(p, roster, list_name="dl15")  # no explicit date

    assert p.injury_start_date == "2026-04-26"
    assert p.injury_eligible_date == "2026-05-06"  # +10, a position player
    assert p.injury_start_date != date.today().isoformat()


def test_countdown_advances_with_the_season_not_with_real_time(sim_clock):
    p = _player()
    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    place_on_injury_list(p, roster, list_name="dl15")
    assert disabled_list_days_remaining(p) == 10

    # Real time passing changes nothing; only the league's date moves it.
    sim_clock["date"] = "2026-04-30"
    assert disabled_list_days_remaining(p) == 6
    sim_clock["date"] = "2026-05-06"
    assert disabled_list_days_remaining(p) == 0
    assert is_player_dl_eligible(p) is True


def test_off_days_count_toward_the_minimum(sim_clock):
    """MLB counts calendar days, not games. Date arithmetic gives that for
    free — a stint spanning an off day still burns the day."""
    p = _player()
    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    place_on_injury_list(p, roster, list_name="dl15", today=date(2026, 4, 1))
    # Ten calendar days later, regardless of how many were game days.
    assert p.injury_eligible_date == "2026-04-11"


def test_a_long_injury_is_not_shortened_to_the_tier_minimum(sim_clock):
    """The minimum is a floor. A six-week hamstring doesn't heal in ten days
    because ten is the list minimum — the old code overwrote the simulator's
    duration with the flat tier value."""
    p = _player()
    p.injury_minimum_days = 42  # the simulator's actual recovery estimate
    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    place_on_injury_list(p, roster, list_name="dl15", today=date(2026, 4, 1))

    assert p.injury_minimum_days == 42
    assert p.injury_eligible_date == "2026-05-13"


def test_a_short_injury_still_serves_the_full_minimum(sim_clock):
    """The other direction: a 7-day injury on the 10-day list serves 10."""
    p = _player()
    p.injury_minimum_days = 7
    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    place_on_injury_list(p, roster, list_name="dl15", today=date(2026, 4, 1))

    assert p.injury_minimum_days == 10
    assert p.injury_eligible_date == "2026-04-11"


def test_return_date_and_eligible_date_agree(sim_clock):
    """They disagreed in production — one wall clock, one sim date — which is
    why the UI showed '15 days left' beside a date four months in the past."""
    p = _player()
    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    place_on_injury_list(p, roster, list_name="dl15", today=date(2026, 4, 26))
    assert p.return_date == p.injury_eligible_date


def test_day_to_day_players_have_no_minimum(sim_clock):
    p = _player()
    p.injury_list = "none"
    assert disabled_list_days_remaining(p) is None


def test_falls_back_to_the_wall_clock_without_a_schedule(monkeypatch):
    """A bare fixture or a league with no season yet must still work."""
    monkeypatch.setattr("utils.sim_date.get_current_sim_date", lambda: None)
    assert im._today() == date.today()


# --- the recovery automation ------------------------------------------------


def test_dl_automation_defaults_to_the_sim_date(sim_clock):
    """season.py calls process_disabled_lists(today=None) with a comment saying
    it defaults to the sim date. It didn't — it used the wall clock."""
    from services.dl_automation import _coerce_date

    assert _coerce_date(None) == date(2026, 4, 26)
    # An explicit date still wins.
    assert _coerce_date("2026-07-01") == date(2026, 7, 1)
    assert _coerce_date(date(2026, 8, 2)) == date(2026, 8, 2)


def test_injuries_router_reads_the_league_clock(sim_clock):
    from api.routers.injuries import _sim_today

    assert _sim_today() == date(2026, 4, 26)


def test_stint_survives_a_gap_in_real_time(sim_clock):
    """The headline regression: a player placed today must still be on the list
    after any amount of wall-clock time, so long as the league hasn't moved."""
    p = _player()
    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    place_on_injury_list(p, roster, list_name="dl15")

    later = date.today() + timedelta(days=365)
    assert is_player_dl_eligible(p, im._today()) is False
    assert disabled_list_days_remaining(p, im._today()) == 10
    # The wall clock is irrelevant to the league's countdown.
    assert later > date.today()


def test_sixty_day_list_uses_the_ir_roster_level(sim_clock):
    """The 60-day list is the one that clears the active roster, so it must
    land on the roster's `ir` level — the check compared against the old tier
    name and would have routed these players onto the short list."""
    p = _player()
    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    place_on_injury_list(p, roster, list_name="ir", today=date(2026, 4, 26))

    assert "p1" in roster.ir
    assert "p1" not in roster.dl


def test_short_lists_use_the_dl_roster_level(sim_clock):
    p = _player()
    roster = Roster(team_id="T", act=["p1"], aaa=[], low=[])
    place_on_injury_list(p, roster, list_name="dl15", today=date(2026, 4, 26))

    assert "p1" in roster.dl
    assert roster.dl_tiers["p1"] == "il10"
    assert "p1" not in roster.ir


# --- roster persistence -----------------------------------------------------


def _roundtrip(tmp_path, tier):
    """Save a roster holding one player on `tier`, reload it, report the level."""
    from utils.roster_io import read_roster_csv, write_roster_csv

    path = tmp_path / "T.csv"
    sixty = tier in {"il60", "ir", "dl45"}
    roster = Roster(
        team_id="T", act=[], aaa=[], low=[],
        dl=[] if sixty else ["p1"], ir=["p1"] if sixty else [],
    )
    roster.dl_tiers = {} if sixty else {"p1": tier}
    write_roster_csv(roster, path)
    back = read_roster_csv(path, "T")
    return "dl" if "p1" in back.dl else ("ir" if "p1" in back.ir else "lost")


@pytest.mark.parametrize("tier", ["il7", "il10", "il15", "dl15"])
def test_short_lists_survive_a_roster_roundtrip(tmp_path, tier):
    """Regression: the writer kept `DL15` for the legacy tier and wrote every
    OTHER tier as IR. Renaming the tiers to MLB's therefore moved a 10-day
    stint onto the 60-day list the first time the roster was saved."""
    assert _roundtrip(tmp_path, tier) == "dl"


def test_the_sixty_day_list_still_uses_the_ir_level(tmp_path):
    assert _roundtrip(tmp_path, "il60") == "ir"


def test_a_short_list_player_is_never_written_to_the_ir_level(tmp_path):
    from utils.roster_io import write_roster_csv

    path = tmp_path / "T.csv"
    roster = Roster(team_id="T", act=[], aaa=[], low=[], dl=["p1"], ir=[])
    roster.dl_tiers = {"p1": "il10"}
    write_roster_csv(roster, path)
    assert "IR" not in path.read_text()
    assert "p1,DL15" in path.read_text()
