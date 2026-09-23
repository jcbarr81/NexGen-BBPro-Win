"""A draft in progress must keep the season paused.

alpha-test simulated a week of games on 2026-09-23 with 12 of 80 picks made.
The gate that resumes the regular season asked "does a draft results file with
at least one row exist?" -- which is true from the FIRST pick onward. So the
moment a league started drafting, the next auto-run decided the draft was over,
flipped the phase out of AMATEUR_DRAFT and played baseball through the rest of
the draft.

The draft state is the authority now: it knows the order, the round count and
any compensation picks. The file check remains only for a draft that has no
state -- an import or a hand-committed one -- which is what it was written for.
"""

import csv

import pytest

import api.routers.season as S


@pytest.fixture
def league(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr("services.trade_settings.current_league_year", lambda: 2026)

    def setup(*, state=None, rounds=4, results_rows=0):
        monkeypatch.setattr("services.draft_state.load_state", lambda year: state or {})
        monkeypatch.setattr("api.routers.draft._load_settings_rounds", lambda: rounds)
        if results_rows:
            with (tmp_path / "draft_results_2026.csv").open(
                "w", newline="", encoding="utf-8"
            ) as fh:
                w = csv.writer(fh)
                w.writerow(["overall", "round", "team_id", "player_id"])
                for i in range(1, results_rows + 1):
                    w.writerow([i, 1, "CHA", f"D{i}"])
        return tmp_path

    return setup


ORDER = [f"T{i}" for i in range(1, 21)]


def _state(overall, rounds_done=1):
    return {"year": 2026, "round": rounds_done, "overall_pick": overall, "order": list(ORDER), "selected": []}


# --- the regression --------------------------------------------------------


def test_one_pick_does_not_end_the_draft(league):
    """The exact bug: 12 picks of 80 read as "complete" and the league simmed."""
    league(state=_state(overall=13), rounds=4, results_rows=12)
    assert S._draft_completed_for_current_year() is False


def test_the_first_pick_does_not_end_the_draft(league):
    league(state=_state(overall=2), rounds=4, results_rows=1)
    assert S._draft_completed_for_current_year() is False


def test_the_last_pick_of_a_middle_round_does_not_end_it(league):
    """Round 1 finished is not the draft finished."""
    league(state=_state(overall=21, rounds_done=2), rounds=4, results_rows=20)
    assert S._draft_completed_for_current_year() is False


# --- and it does end when it is actually over ------------------------------


def test_the_draft_ends_after_its_final_pick(league):
    league(state=_state(overall=81, rounds_done=5), rounds=4, results_rows=80)
    assert S._draft_completed_for_current_year() is True


def test_a_single_round_draft_ends_after_one_round(league):
    league(state=_state(overall=21, rounds_done=2), rounds=1, results_rows=20)
    assert S._draft_completed_for_current_year() is True


# --- drafts with no live state ---------------------------------------------


def test_an_imported_draft_still_counts_as_done(league):
    """No state to read; a results file is the only evidence there is, and it
    is what the file check was written for."""
    league(state={}, rounds=4, results_rows=80)
    assert S._draft_completed_for_current_year() is True


def test_no_draft_at_all_is_not_complete(league):
    league(state={}, rounds=4, results_rows=0)
    assert S._draft_completed_for_current_year() is False


def test_an_empty_order_falls_back_to_the_file(league):
    """A seeded-but-unordered draft has no picks to count."""
    league(state={"year": 2026, "order": [], "overall_pick": 1}, rounds=4, results_rows=5)
    assert S._draft_completed_for_current_year() is True
