"""Owners are told what their club must fill before Opening Day (8.1.2, #50).

- ``team_roster_shortfall`` reports the readiness check's own roster errors
  (``blocking``, the same list the sim gate and the readiness board read) plus
  the legal open active spots.
- After the rollover's roster steps, one news item and notification per short
  human-owned club; nothing for CPU clubs; stand down when ownership can't be
  read; never fail the rollover.
- ``GET /teams/{team_id}/roster/shortfall`` serves the Roster page.

Everything runs against a tmp data root; nothing touches data/leagues.
"""

from __future__ import annotations

import json

import pytest

POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
HEADER = (
    "player_id,first_name,last_name,primary_position,other_positions,"
    "is_pitcher,birthdate"
)


@pytest.fixture
def league(tmp_path, monkeypatch):
    """A tmp league: BAL is owned by a person, NYY is a CPU club.

    Returns ``build(team, hitters, pitchers, skip=())`` which adds that club's
    players and roster (``skip``: defensive positions no hitter covers).
    """

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
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils

    path_utils._DATA_DIR_CACHE.clear()
    # An offseason date: the base 26 / 13 caps.
    monkeypatch.setattr(
        "utils.sim_date.get_current_sim_date", lambda *a, **k: "2026-11-15"
    )
    rows: list[str] = []

    def build(team, hitters, pitchers, skip=()):
        ids = []
        cover = [p for p in POSITIONS if p not in skip]
        for i in range(hitters):
            pid = f"{team}H{i}"
            pos = cover[i] if i < len(cover) else "DH"
            if pos == "DH" and cover:
                pos = cover[0]
            rows.append(f"{pid},First,{pid},{pos},,0,2000-01-01")
            ids.append(pid)
        for i in range(pitchers):
            pid = f"{team}P{i}"
            rows.append(f"{pid},First,{pid},P,,1,2000-01-01")
            ids.append(pid)
        (root / "players.csv").write_text(
            "\n".join([HEADER] + rows) + "\n", encoding="utf-8"
        )
        (root / "rosters" / f"{team}.csv").write_text(
            "\n".join(f"{pid},ACT" for pid in ids) + "\n", encoding="utf-8"
        )

    assert path_utils.get_data_dir().resolve() == root.resolve()
    yield build, root
    path_utils._DATA_DIR_CACHE.clear()


def _news(root):
    path = root / "news_feed.txt"
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


# --- the report ---------------------------------------------------------------


def test_a_full_legal_roster_is_not_short(league):
    from services.roster_shortfall import team_roster_shortfall

    build, _ = league
    build("BAL", 13, 13)
    report = team_roster_shortfall("BAL")
    assert report["short"] is False
    assert report["ready"] is True
    assert report["blocking"] == []
    assert (report["active"], report["active_cap"], report["open_spots"]) == (26, 26, 0)
    assert report["message"] == ""


def test_an_expired_catcher_blocks_opening_day(league):
    """21 of 26 after the expirations, nobody left to catch."""

    from services.roster_shortfall import team_roster_shortfall

    build, _ = league
    build("BAL", 12, 9, skip=("C",))
    report = team_roster_shortfall("BAL")
    assert report["short"] is True
    assert report["ready"] is False
    assert report["open_spots"] == 5
    assert (report["pitchers"], report["position_players"]) == (9, 12)
    assert report["missing_positions"] == ["C"]
    assert report["blocking"] == [
        "Active roster is missing defensive coverage at: C."
    ]
    msg = report["message"]
    assert msg.startswith("BAL: 5 active-roster spots to fill: 21 of 26 active")
    assert "Fix before Opening Day: Active roster is missing defensive coverage at: C." in msg


def test_open_spots_alone_are_short_but_ready(league):
    """No active-roster minimum (7.46.0): the open spots are reported as legal."""

    from services.roster_shortfall import team_roster_shortfall

    build, _ = league
    build("BAL", 11, 10)
    report = team_roster_shortfall("BAL")
    assert report["short"] is True
    assert report["ready"] is True
    assert report["blocking"] == []
    assert report["open_spots"] == 5
    assert "does not hold up the season" in report["message"]


def test_too_few_position_players_is_reported_like_the_gate(league):
    from services.roster_shortfall import team_roster_shortfall

    build, _ = league
    build("BAL", 9, 13)
    report = team_roster_shortfall("BAL")
    assert report["position_players_short"] == 2
    assert "Active roster carries 9 position players (minimum 11)." in report["blocking"]


@pytest.mark.parametrize(
    "hitters,pitchers,skip",
    [(13, 13, ()), (12, 9, ("C",)), (9, 13, ()), (11, 10, ()), (12, 15, ()), (6, 4, ("SS", "CF"))],
)
def test_blocking_is_the_readiness_checks_own_list(league, hitters, pitchers, skip):
    """The report and the sim gate / readiness board can never disagree."""

    import api.routers.season as season
    from services.roster_shortfall import team_roster_shortfall

    build, _ = league
    build("BAL", hitters, pitchers, skip=skip)
    gate = season._team_roster_compliance_errors("BAL")
    report = team_roster_shortfall("BAL")
    assert [f"BAL: {e}" for e in report["blocking"]] == gate
    assert report["ready"] is (not gate)


# --- the rollover notices -----------------------------------------------------


def test_one_notice_per_short_owner_club_and_none_for_the_cpu(league):
    from services.notification_engine import load_history
    from services.roster_shortfall import notify_owner_shortfalls

    build, root = league
    build("BAL", 12, 9, skip=("C",))
    build("NYY", 10, 8)  # a short CPU club: the CPU's own business
    out = notify_owner_shortfalls(expired_teams=["BAL", "NYY"])
    assert out == {"status": "ok", "teams": ["BAL"]}
    lines = _news(root)
    assert len(lines) == 1
    assert "[roster] [BAL] BAL: 5 active-roster spots to fill (contracts expired):" in lines[0]
    history = load_history("BAL")
    assert len(history) == 1
    assert history[0]["rule_id"] == "roster_spot_open"
    assert history[0]["severity"] == "warning"
    assert history[0]["payload"]["open_spots"] == 5
    assert load_history("NYY") == []


def test_no_notice_for_a_full_owner_club(league):
    from services.roster_shortfall import notify_owner_shortfalls

    build, root = league
    build("BAL", 13, 13)
    assert notify_owner_shortfalls(expired_teams=["BAL"])["teams"] == []
    assert _news(root) == []


def test_stands_down_when_ownership_is_unreadable(league, monkeypatch):
    import services.team_ownership as ownership
    from services.roster_shortfall import notify_owner_shortfalls

    build, root = league
    build("BAL", 12, 9, skip=("C",))
    monkeypatch.setattr(ownership, "human_owned_team_ids_strict", lambda *a, **k: None)
    out = notify_owner_shortfalls(expired_teams=["BAL"])
    assert out == {"status": "ownership_unknown", "teams": []}
    assert _news(root) == []


def test_an_owner_who_muted_open_spot_alerts_still_hears_about_a_blocker(league):
    from services.notification_engine import load_history
    from services.notification_settings import save_notification_settings
    from services.roster_shortfall import notify_owner_shortfalls

    build, root = league
    save_notification_settings(
        "BAL", {"rules": {"roster_spot_open": {"enabled": False, "notify": False}}}
    )
    build("BAL", 11, 10)  # open spots only: muted
    notify_owner_shortfalls()
    assert load_history("BAL") == []
    assert len(_news(root)) == 1  # the news item is posted either way
    build("BAL", 12, 9, skip=("C",))  # now nobody can catch
    notify_owner_shortfalls()
    assert [e["severity"] for e in load_history("BAL")] == ["warning"]


def test_the_rollover_hook_passes_the_expired_clubs(league, monkeypatch):
    import services.roster_shortfall as rs
    from services.league_rollover import LeagueRolloverService

    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return {"status": "ok", "teams": ["BAL"]}

    monkeypatch.setattr(rs, "notify_owner_shortfalls", fake)
    service = object.__new__(LeagueRolloverService)
    artifacts: dict = {}
    service._notify_owner_roster_shortfalls({"release_teams": ["BAL", "NYY"]}, artifacts)
    assert seen == {"expired_teams": ["BAL", "NYY"]}
    assert json.loads(artifacts["roster_shortfall"]) == {"teams": ["BAL"]}


def test_the_rollover_hook_never_fails_the_rollover(league, monkeypatch):
    import services.roster_shortfall as rs
    from services.league_rollover import LeagueRolloverService

    def boom(**kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(rs, "notify_owner_shortfalls", boom)
    service = object.__new__(LeagueRolloverService)
    artifacts: dict = {}
    service._notify_owner_roster_shortfalls(None, artifacts)
    assert artifacts == {"roster_shortfall_error": "disk on fire"}


def test_a_club_that_cannot_be_read_is_skipped(league, monkeypatch):
    import services.roster_shortfall as rs

    build, root = league
    build("BAL", 12, 9, skip=("C",))

    def unreadable(*a, **k):
        raise OSError("locked")

    monkeypatch.setattr(rs, "team_roster_shortfall", unreadable)
    assert rs.notify_owner_shortfalls()["teams"] == []
    assert _news(root) == []


def test_the_rollover_runs_the_hook_after_its_roster_steps():
    """Placed after contracts, retirements and promotions, before the reset."""

    import inspect

    from services.league_rollover import LeagueRolloverService

    src = inspect.getsource(LeagueRolloverService.archive_season)
    hook = src.index("self._notify_owner_roster_shortfalls(")
    assert src.index("rollover_contracts_for_new_season(") < hook
    assert src.index("run_yearly_retirements(") < hook
    assert src.index("run_yearly_promotions(") < hook
    assert hook < src.index("self._reset_active_state(")


# --- the endpoint -------------------------------------------------------------


def test_endpoint_returns_the_report_and_the_phase(league):
    import api.routers.validation as val

    build, _ = league
    build("BAL", 12, 9, skip=("C",))
    out = val.roster_shortfall_endpoint("BAL")
    assert out["open_spots"] == 5
    assert out["blocking"] == ["Active roster is missing defensive coverage at: C."]
    assert "phase" in out


def test_endpoint_needs_a_signed_in_user(league):
    from fastapi.testclient import TestClient

    from api.app import create_app

    build, _ = league
    build("BAL", 11, 10)
    client = TestClient(create_app())
    path = "/teams/BAL/roster/shortfall"
    assert client.get(path).status_code == 401
    login = client.post("/auth/login", json={"username": "bal_owner", "password": "pass"})
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    res = client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    assert res.json()["open_spots"] == 5
