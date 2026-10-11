"""Commissioner option: hold the amateur draft in the preseason (backlog #63).

Owner decisions (docs/future_work.md #63):

1. The preseason draft runs BEFORE spring training.
2. A change of the setting applies to the next draft; a regular season in
   progress keeps its July draft. Never two drafts in a league year, never
   none.
3. The order is the reverse of the last completed season's records.
4. Draft picks go to LOW; owners sort out their own limits before the season.
6. A new league's first draft follows its first completed season.
7. The pick clock and auto-draft work as they do for the mid-season draft.

Everything here runs in a scratch league (NEXGEN_DATA_ROOT + a request
league), never a real one.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi import HTTPException

import api.routers.draft as D
import api.routers.season as S
from playbalance.season_manager import SeasonManager, SeasonPhase
from services import draft_settings as ds
from services import draft_state

REPO = Path(__file__).resolve().parents[1]
CALIBRATION = REPO / "data" / "calibration"
ADMIN = {"u": "commish", "r": "admin", "mr": "admin", "t": ""}
LEAGUE = "t63"


@pytest.fixture
def league(tmp_path, monkeypatch):
    """A 30-team scratch league in the preseason of 2027, 2026 archived."""
    from utils import path_utils

    root = tmp_path / "root"
    data = root / "leagues" / LEAGUE / "data"
    data.mkdir(parents=True)
    # The league's own files go in BEFORE anything resolves the data dir: a
    # league folder missing teams.csv, players.csv or users.txt is seeded
    # with a full copy of the repo's data/ (its sample schedule and season
    # files included) the first time it is resolved. With all three present
    # only reference files (names, parks, MLB averages) are added.
    (root / "players.csv").write_text("player_id\n", encoding="utf-8")
    _copy_players(CALIBRATION / "players.csv", data / "players.csv")
    shutil.copy(CALIBRATION / "teams.csv", data / "teams.csv")
    (data / "users.txt").write_text("", encoding="utf-8")
    shutil.copytree(CALIBRATION / "rosters", data / "rosters")
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    path_utils._DATA_DIR_CACHE.clear()
    token = path_utils.set_request_league(LEAGUE)
    assert path_utils.get_data_dir().resolve() == data.resolve()
    # No season state was seeded in from the repo.
    seeded = {p.name for p in data.iterdir()}
    assert not seeded & {
        "schedule.csv", "season_state.json", "season_progress.json",
        "careers", "career_index.json", "draft_settings.json", "leagues",
    }, sorted(seeded)
    # The last pick starts a background avatar job; it must not outlive the
    # test (it would write into the next test's league) or call out.
    monkeypatch.setattr(D, "_generate_draft_avatars_async", lambda ids: None)
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: set()
    )
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids", lambda *a, **k: set()
    )
    yield data
    path_utils.reset_request_league(token)
    path_utils._DATA_DIR_CACHE.clear()


def _copy_players(src: Path, dest: Path) -> None:
    """Copy the calibration players with blank pitch ratings filled in.

    The KPI harness reads the fixture's blanks as "does not throw it"; the
    league loader (training camp, rosters) requires a number.
    """
    import csv

    with src.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for row in rows:
        for key in ("fb", "cu", "cb", "sl", "si", "scb", "kn"):
            if key in row and row[key] == "":
                row[key] = "0"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _team_ids(data: Path) -> list[str]:
    lines = (data / "teams.csv").read_text(encoding="utf-8").splitlines()[1:]
    return [line.split(",")[0] for line in lines if line.strip()]


def _archive_2026(data: Path) -> list[str]:
    """Finish and archive a 2026 season; returns the clubs worst record first."""
    from playbalance.season_context import CAREER_DATA_DIR, SeasonContext

    teams = _team_ids(data)
    ctx = SeasonContext.load()
    ctx.ensure_league(name="Scratch", league_id=LEAGUE)
    current = ctx.ensure_current_season(league_year=2026)
    season_dir = Path(str(CAREER_DATA_DIR)) / current["season_id"]
    season_dir.mkdir(parents=True, exist_ok=True)
    # Team i wins 60 + i games: the first club listed has the worst record.
    stats = {
        "teams": {
            tid: {"w": 60 + i, "l": 102 - i, "g": 162, "r": 600 + i, "ra": 700 - i}
            for i, tid in enumerate(teams)
        }
    }
    (season_dir / "stats.json").write_text(json.dumps(stats), encoding="utf-8")
    ctx.archive_current_season()
    return teams


def _preseason_2027(data: Path, *, timing: str = ds.DRAFT_TIMING_PRESEASON) -> None:
    teams = _team_ids(data)
    (data / "schedule.csv").write_text(
        "date,home,away,result,played,boxscore\n"
        f"2027-04-01,{teams[0]},{teams[1]},,,\n"
        f"2027-07-20,{teams[2]},{teams[3]},,,\n",
        encoding="utf-8",
    )
    (data / "season_progress.json").write_text(
        json.dumps({"preseason_done": {"training_camp": False}, "sim_index": 0}),
        encoding="utf-8",
    )
    manager = SeasonManager()
    manager.phase = SeasonPhase.PRESEASON
    manager.save()
    ds.save_draft_settings(ds.DraftSettings(rounds=1, pool_size=40, timing=timing))


def _finish_draft(year: int = 2027) -> dict:
    return D.auto_advance(
        {"year": year, "stop": "end_of_draft", "include_human_teams": True},
        identity=ADMIN,
    )


# --- the setting ---------------------------------------------------------------


def test_timing_defaults_to_midseason_and_round_trips(tmp_path):
    assert ds.load_draft_settings(tmp_path).timing == ds.DRAFT_TIMING_MIDSEASON
    ds.save_draft_settings(
        ds.DraftSettings(timing=ds.DRAFT_TIMING_PRESEASON), data_dir=tmp_path
    )
    assert ds.load_draft_settings(tmp_path).timing == ds.DRAFT_TIMING_PRESEASON


def test_a_file_from_before_the_setting_reads_as_midseason(tmp_path):
    (tmp_path / "draft_settings.json").write_text(
        json.dumps({"rounds": 12, "pool_size": 300, "pick_clock_hours": 24}),
        encoding="utf-8",
    )
    settings = ds.load_draft_settings(tmp_path)
    assert (settings.rounds, settings.pick_clock_hours) == (12, 24)
    assert settings.timing == ds.DRAFT_TIMING_MIDSEASON


@pytest.mark.parametrize("junk", ["", None, "spring", 7, "PRE SEASON"])
def test_junk_timing_falls_back_to_the_default(junk):
    assert ds.normalize_timing(junk) == ds.DRAFT_TIMING_MIDSEASON


@pytest.mark.parametrize("text", ["preseason", "Preseason", "pre-season", "pre_season"])
def test_spellings_of_preseason_normalise(text):
    assert ds.normalize_timing(text) == ds.DRAFT_TIMING_PRESEASON


def test_settings_endpoint_serves_and_saves_the_timing(league):
    _preseason_2027(league, timing=ds.DRAFT_TIMING_MIDSEASON)
    view = D.draft_settings_view()
    assert view["timing"] == "midseason"
    assert [o["id"] for o in view["timing_options"]] == ["midseason", "preseason"]

    # Timing alone: rounds, pool size and the clock are left as they were.
    saved = D.draft_settings_save({"timing": "preseason"}, ADMIN)
    assert saved["timing"] == "preseason"
    assert (saved["rounds"], saved["pool_size"]) == (1, 40)

    # A client that does not know about the timing cannot reset it.
    saved = D.draft_settings_save({"rounds": 3, "pool_size": 90}, ADMIN)
    assert saved["timing"] == "preseason" and saved["rounds"] == 3


def test_settings_endpoint_rejects_an_unknown_timing(league):
    _preseason_2027(league, timing=ds.DRAFT_TIMING_MIDSEASON)
    with pytest.raises(HTTPException) as exc:
        D.draft_settings_save({"timing": "whenever"}, ADMIN)
    assert exc.value.status_code == 400
    assert ds.load_draft_settings().timing == "midseason"


# --- the phase remembers where to go back to ----------------------------------------


def test_draft_return_phase_is_persisted_and_cleared(tmp_path):
    path = tmp_path / "season_state.json"
    manager = SeasonManager(path=path, enable_rollover=False)
    manager.begin_draft(SeasonPhase.PRESEASON)
    assert json.loads(path.read_text())["draft_return_phase"] == "PRESEASON"

    again = SeasonManager(path=path, enable_rollover=False)
    assert again.phase == SeasonPhase.AMATEUR_DRAFT
    assert again.phase_after_draft() == SeasonPhase.PRESEASON
    assert again.resume_after_draft() == SeasonPhase.PRESEASON
    assert json.loads(path.read_text()) == {"phase": "PRESEASON"}


def test_a_midseason_draft_returns_to_the_regular_season(tmp_path):
    path = tmp_path / "season_state.json"
    manager = SeasonManager(path=path, enable_rollover=False)
    manager.begin_draft()
    assert manager.resume_after_draft() == SeasonPhase.REGULAR_SEASON
    # A state file written before the setting existed has no return phase.
    path.write_text(json.dumps({"phase": "AMATEUR_DRAFT"}), encoding="utf-8")
    legacy = SeasonManager(path=path, enable_rollover=False)
    assert legacy.phase_after_draft() == SeasonPhase.REGULAR_SEASON
    assert legacy.advance_phase() == SeasonPhase.REGULAR_SEASON


def test_advance_phase_from_a_preseason_draft_goes_back_to_preseason(tmp_path):
    path = tmp_path / "season_state.json"
    manager = SeasonManager(path=path, enable_rollover=False)
    manager.begin_draft(SeasonPhase.PRESEASON)
    assert manager.advance_phase() == SeasonPhase.PRESEASON
    # And from there the year carries on as usual.
    assert manager.advance_phase() == SeasonPhase.REGULAR_SEASON


def test_a_junk_return_phase_is_ignored(tmp_path):
    path = tmp_path / "season_state.json"
    path.write_text(
        json.dumps({"phase": "AMATEUR_DRAFT", "draft_return_phase": "PLAYOFFS"}),
        encoding="utf-8",
    )
    manager = SeasonManager(path=path, enable_rollover=False)
    assert manager.phase_after_draft() == SeasonPhase.REGULAR_SEASON
    # resume_after_draft is a no-op outside the draft.
    manager.phase = SeasonPhase.PLAYOFFS
    assert manager.resume_after_draft() == SeasonPhase.PLAYOFFS


# --- when the draft opens -------------------------------------------------------------


def test_the_draft_opens_in_the_preseason_before_spring_training(league):
    worst_first = _archive_2026(league)
    _preseason_2027(league)
    manager = SeasonManager()
    assert S._preseason_draft_status(manager)["due"] is True

    opened = S._maybe_open_preseason_draft(manager)
    assert opened["opened"] is True and opened["year"] == 2027
    assert SeasonManager().phase == SeasonPhase.AMATEUR_DRAFT
    assert SeasonManager().phase_after_draft() == SeasonPhase.PRESEASON

    # Decision 3: the reverse of the last completed season's records.
    state = draft_state.load_state(2027)
    assert state["order"] == worst_first
    assert (league / "draft_pool_2027.csv").exists()
    # Opening twice changes nothing.
    again = S._maybe_open_preseason_draft(SeasonManager())
    assert again["opened"] is False and again["reason"] == "in_progress"


def test_a_new_leagues_first_preseason_has_no_draft(league):
    """Decision 6: the first draft follows the first completed season."""
    _preseason_2027(league)  # nothing archived
    manager = SeasonManager()
    status = S._preseason_draft_status(manager)
    assert (status["due"], status["reason"]) == (False, "first_season")
    assert S._maybe_open_preseason_draft(manager)["opened"] is False
    assert SeasonManager().phase == SeasonPhase.PRESEASON
    assert not (league / "draft_state_2027.json").exists()


def test_a_midseason_league_does_not_open_a_preseason_draft(league):
    _archive_2026(league)
    _preseason_2027(league, timing=ds.DRAFT_TIMING_MIDSEASON)
    status = S._preseason_draft_status(SeasonManager())
    assert (status["due"], status["reason"]) == (False, "midseason")
    assert S._maybe_open_preseason_draft(SeasonManager())["opened"] is False


def test_no_preseason_draft_once_spring_training_has_run(league):
    """Too late for this year: its draft stays the July one."""
    _archive_2026(league)
    _preseason_2027(league)
    S._mark_preseason_done("training_camp")
    status = S._preseason_draft_status(SeasonManager())
    assert (status["due"], status["reason"]) == (False, "after_training_camp")


def test_a_regular_season_in_progress_keeps_its_july_draft(league):
    """Decision 2: a change during the season does not move that season's draft."""
    _archive_2026(league)
    _preseason_2027(league)
    manager = SeasonManager()
    manager.phase = SeasonPhase.REGULAR_SEASON
    manager.save()
    status = S._preseason_draft_status(SeasonManager())
    assert (status["due"], status["reason"]) == (False, "not_preseason")
    # The July intercept asks only "has this year's draft been held?".
    assert S._draft_completed_for_current_year() is False


def _offseason_2027(data: Path, *, timing: str) -> None:
    """The offseason after 2026: no schedule yet, the phase about to advance."""
    (data / "season_progress.json").write_text(
        json.dumps({"preseason_done": {"training_camp": False}, "sim_index": 0}),
        encoding="utf-8",
    )
    manager = SeasonManager()
    manager.phase = SeasonPhase.OFFSEASON
    manager.save()
    ds.save_draft_settings(ds.DraftSettings(rounds=1, pool_size=40, timing=timing))


def test_advancing_into_the_preseason_opens_the_draft_end_to_end(league):
    """Offseason -> draft -> preseason -> spring training -> Opening Day."""
    worst_first = _archive_2026(league)
    _offseason_2027(league, timing=ds.DRAFT_TIMING_PRESEASON)

    out = S.advance_phase(payload={}, identity=ADMIN)
    # A schedule for the new year is generated first; the draft is filed
    # under that league year.
    assert out["schedule"]["generated"] is True and out["schedule"]["year"] == 2027
    assert out["phase"] == "AMATEUR_DRAFT" and out["new_phase"] == "AMATEUR_DRAFT"
    assert out["preseason_draft_open"]["opened"] is True
    assert out["draft_return_phase"] == "PRESEASON"
    assert draft_state.load_state(2027)["order"] == worst_first

    # The draft has to finish before the phase can move.
    with pytest.raises(HTTPException) as exc:
        S.advance_phase(payload={}, identity=ADMIN)
    assert "draft" in str(exc.value.detail).lower()

    _finish_draft()
    assert SeasonManager().phase == SeasonPhase.PRESEASON
    # Spring training is still to come: Opening Day waits for it.
    with pytest.raises(HTTPException) as exc:
        S.advance_phase(payload={}, identity=ADMIN)
    assert "Spring Training" in str(exc.value.detail)
    S.preseason_training_camp(identity=ADMIN)
    out = S.advance_phase(payload={}, identity=ADMIN)
    assert out["phase"] == "REGULAR_SEASON"
    assert out["draft_completed"] is True


def test_advancing_into_the_preseason_of_a_midseason_league_is_unchanged(league):
    _archive_2026(league)
    _offseason_2027(league, timing=ds.DRAFT_TIMING_MIDSEASON)
    out = S.advance_phase(payload={}, identity=ADMIN)
    assert out["phase"] == "PRESEASON" and out["new_phase"] == "PRESEASON"
    assert out["preseason_draft_open"]["opened"] is False
    assert out["preseason_draft_open"]["reason"] == "midseason"
    assert not (league / "draft_state_2027.json").exists()


# --- the draft itself, and after it ---------------------------------------------------------


def test_the_last_pick_returns_the_league_to_the_preseason(league):
    _archive_2026(league)
    _preseason_2027(league)
    S._maybe_open_preseason_draft(SeasonManager())

    result = _finish_draft()
    assert result["draft_complete"] is True
    assert SeasonManager().phase == SeasonPhase.PRESEASON
    assert S._draft_completed_for_current_year() is True
    # Never two: it does not reopen, and July finds the year's draft held.
    status = S._preseason_draft_status(SeasonManager())
    assert (status["due"], status["reason"]) == (False, "completed")
    assert S._maybe_open_preseason_draft(SeasonManager())["opened"] is False


def test_draft_picks_land_on_low(league):
    """Decision 4: every pick goes to LOW."""
    from utils.roster_loader import load_roster

    _archive_2026(league)
    _preseason_2027(league)
    S._maybe_open_preseason_draft(SeasonManager())
    _finish_draft()

    state = draft_state.load_state(2027)
    picks = state["selected"]
    assert len(picks) == len(_team_ids(league))
    load_roster.cache_clear() if hasattr(load_roster, "cache_clear") else None
    for pick in picks[:5]:
        roster = load_roster(pick["team_id"], league / "rosters")
        assert pick["player_id"] in roster.low, pick


def test_the_pick_clock_tick_runs_a_preseason_draft(league, monkeypatch):
    """Decision 7: the same clock and auto-draft as the mid-season draft."""
    _archive_2026(league)
    _preseason_2027(league)
    settings = ds.load_draft_settings()
    settings.pick_clock_hours = 12
    ds.save_draft_settings(settings)
    S._maybe_open_preseason_draft(SeasonManager())
    monkeypatch.setattr(S, "_iter_league_ids", lambda: [LEAGUE])

    rows = S._tick_draft_clocks()
    # Every club is a CPU club here, so one tick runs the draft to the end.
    assert rows and rows[0]["action"] == "advanced_cpu_picks"
    assert rows[0]["draft_complete"] is True
    assert SeasonManager().phase == SeasonPhase.PRESEASON


# --- the guards --------------------------------------------------------------------------


def test_spring_training_waits_for_the_draft(league):
    _archive_2026(league)
    _preseason_2027(league)
    S._maybe_open_preseason_draft(SeasonManager())
    with pytest.raises(HTTPException) as exc:
        S.preseason_training_camp(identity=ADMIN)
    assert exc.value.status_code == 400
    assert "before spring training" in str(exc.value.detail)
    assert S._read_preseason_done().get("training_camp") is not True


def test_training_camp_opens_a_due_draft_instead_of_running_past_it(league):
    """The setting was switched on after the league entered the preseason."""
    _archive_2026(league)
    _preseason_2027(league)  # due, but nobody has opened it
    with pytest.raises(HTTPException):
        S.preseason_training_camp(identity=ADMIN)
    assert SeasonManager().phase == SeasonPhase.AMATEUR_DRAFT
    assert S._read_preseason_done().get("training_camp") is not True


def test_spring_training_runs_after_the_draft_and_trains_the_draft_class(league):
    _archive_2026(league)
    _preseason_2027(league)
    S._maybe_open_preseason_draft(SeasonManager())
    _finish_draft()
    drafted = {p["player_id"] for p in draft_state.load_state(2027)["selected"]}

    result = S.preseason_training_camp(identity=ADMIN)
    assert S._read_preseason_done().get("training_camp") is True
    # Camp runs for every player in the league file, the draft class included.
    from utils.player_loader import load_players_from_csv

    in_league = {p.player_id for p in load_players_from_csv(league / "players.csv")}
    assert drafted <= in_league
    assert result["players_processed"] == len(in_league)


def test_the_scheduled_run_waits_for_a_draft_in_progress(league, monkeypatch):
    _archive_2026(league)
    _preseason_2027(league)
    S._maybe_open_preseason_draft(SeasonManager())
    filled = []
    monkeypatch.setattr(S, "_cpu_fill_all_unready", lambda: filled.append(1) or [])
    monkeypatch.setattr(S, "_cpu_activate_eligible", lambda: filled.append(2) or [])
    monkeypatch.setattr(S, "_sim_running", lambda: False)
    before = S._read_schedule()
    for force in (False, True):
        with pytest.raises(HTTPException) as exc:
            S._run_schedule(ADMIN, force=force)
        # 400, not 409: the tick stops at a 409 (sim lock taken).
        assert exc.value.status_code == 400
    assert filled == []
    assert S._read_schedule() == before


# --- changing the setting ---------------------------------------------------------------------


def test_switching_to_preseason_in_the_preseason_opens_the_draft_now(league):
    _archive_2026(league)
    _preseason_2027(league, timing=ds.DRAFT_TIMING_MIDSEASON)
    saved = D.draft_settings_save({"timing": "preseason"}, ADMIN)
    assert saved["timing_change"]["applies"] == "now"
    assert SeasonManager().phase == SeasonPhase.AMATEUR_DRAFT
    assert SeasonManager().phase_after_draft() == SeasonPhase.PRESEASON


def test_switching_during_the_regular_season_waits_for_the_next_draft(league):
    _archive_2026(league)
    _preseason_2027(league, timing=ds.DRAFT_TIMING_MIDSEASON)
    manager = SeasonManager()
    manager.phase = SeasonPhase.REGULAR_SEASON
    manager.save()
    saved = D.draft_settings_save({"timing": "preseason"}, ADMIN)
    assert saved["timing_change"]["applies"] == "next_draft"
    assert SeasonManager().phase == SeasonPhase.REGULAR_SEASON
    assert not (league / "draft_state_2027.json").exists()


def test_switching_back_during_a_preseason_draft_lets_it_finish(league):
    _archive_2026(league)
    _preseason_2027(league)
    S._maybe_open_preseason_draft(SeasonManager())
    D.draft_settings_save({"timing": "midseason"}, ADMIN)
    assert SeasonManager().phase == SeasonPhase.AMATEUR_DRAFT
    _finish_draft()
    # It still goes back to the preseason, and July will not hold a second.
    assert SeasonManager().phase == SeasonPhase.PRESEASON
    assert S._draft_completed_for_current_year() is True


# --- the offseason: next year's class is there to scout ------------------------------------


def test_rollover_seeds_next_years_pool_for_a_preseason_league(league):
    _archive_2026(league)  # the season context now points at 2027
    ds.save_draft_settings(
        ds.DraftSettings(rounds=1, pool_size=40, timing=ds.DRAFT_TIMING_PRESEASON)
    )
    seeded = S._seed_next_draft_pool_if_preseason()
    assert seeded == {"seeded": True, "year": 2027, "pool_size": 40}
    assert (league / "draft_pool_2027.csv").exists()
    assert S._seed_next_draft_pool_if_preseason()["already_existed"] is True


def test_rollover_seeds_nothing_for_a_midseason_league(league):
    _archive_2026(league)
    ds.save_draft_settings(ds.DraftSettings(rounds=1, pool_size=40))
    assert S._seed_next_draft_pool_if_preseason() is None
    assert not (league / "draft_pool_2027.csv").exists()


def test_the_draft_page_shows_next_years_class_in_the_offseason(league):
    _archive_2026(league)
    ds.save_draft_settings(
        ds.DraftSettings(rounds=1, pool_size=40, timing=ds.DRAFT_TIMING_PRESEASON)
    )
    manager = SeasonManager()
    manager.phase = SeasonPhase.OFFSEASON
    manager.save()
    assert D._resolve_year(None) == 2027
    assert D._resolve_year(2031) == 2031
    # A mid-season league keeps resolving the year the old way.
    ds.save_draft_settings(ds.DraftSettings(rounds=1, pool_size=40))
    assert D._upcoming_preseason_draft_year() is None


def test_switching_to_preseason_in_the_offseason_seeds_the_pool(league):
    _archive_2026(league)
    ds.save_draft_settings(ds.DraftSettings(rounds=1, pool_size=40))
    manager = SeasonManager()
    manager.phase = SeasonPhase.OFFSEASON
    manager.save()
    saved = D.draft_settings_save({"timing": "preseason"}, ADMIN)
    assert saved["timing_change"]["applies"] == "next_draft"
    assert saved["timing_change"]["draft_pool"]["seeded"] is True
    assert (league / "draft_pool_2027.csv").exists()


# --- what the UI is told ------------------------------------------------------------------------


def test_state_payload_reports_the_timing_and_the_draft(league):
    _archive_2026(league)
    _preseason_2027(league)
    manager, simulator, draft_date = S._build_manager_and_simulator()
    payload = S._state_payload(manager, simulator, draft_date)
    assert payload["draft_timing"] == "preseason"
    assert payload["preseason_draft"]["due"] is True
    assert payload["draft_return_phase"] is None

    S._maybe_open_preseason_draft(manager)
    payload = S._state_payload(manager, simulator, draft_date)
    assert payload["phase"] == "AMATEUR_DRAFT"
    assert payload["preseason_draft"]["in_progress"] is True
    assert payload["draft_return_phase"] == "PRESEASON"


def test_the_calendar_drops_the_july_marker_for_a_preseason_draft(league):
    from api.routers import schedule as schedule_router

    _archive_2026(league)
    _preseason_2027(league)
    july = schedule_router._compute_draft_date(2027)
    assert schedule_router._draft_marker(2027, "2027-04-01") == july

    S._maybe_open_preseason_draft(SeasonManager())
    assert schedule_router._draft_marker(2027, "2027-04-01") is None
    _finish_draft()
    assert schedule_router._draft_marker(2027, "2027-04-01") is None


def test_the_command_center_knows_a_preseason_draft_is_open(league):
    from services import league_command_center as lcc

    _archive_2026(league)
    _preseason_2027(league)
    assert lcc._preseason_draft_open(league) is False
    S._maybe_open_preseason_draft(SeasonManager())
    assert lcc._preseason_draft_open(league) is True
