from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from services import roster_auto_assign


def test_auto_assign_all_teams_reports_progress(monkeypatch):
    teams = [SimpleNamespace(team_id="AAA"), SimpleNamespace(team_id="BBB")]
    players = [SimpleNamespace(player_id="P1"), SimpleNamespace(player_id="P2")]
    assign_calls: list[str] = []
    progress_events: list[tuple[str, int, int]] = []

    monkeypatch.setattr(roster_auto_assign, "load_teams", lambda _path: teams)
    monkeypatch.setattr(
        roster_auto_assign,
        "load_players_from_csv",
        lambda _path: players,
    )
    monkeypatch.setattr(roster_auto_assign, "load_users", lambda _path: [])
    monkeypatch.setattr(
        roster_auto_assign,
        "auto_assign_team",
        lambda team_id, **_kwargs: assign_calls.append(team_id),
    )
    monkeypatch.setattr(
        roster_auto_assign,
        "auto_fill_lineup_for_team",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        roster_auto_assign.load_roster,
        "cache_clear",
        lambda: None,
    )

    roster_auto_assign.auto_assign_all_teams(
        progress_callback=lambda phase, done, total: progress_events.append(
            (phase, done, total)
        )
    )

    assert assign_calls == ["AAA", "BBB"]
    assert progress_events
    assert progress_events[0] == ("Loading", 0, 2)
    assert ("Processing", 0, 2) in progress_events
    assert ("Processing", 1, 2) in progress_events
    assert ("Saving", 1, 2) in progress_events
    assert ("Saving", 2, 2) in progress_events
    assert progress_events[-1] == ("Complete", 2, 2)


def test_auto_assign_all_teams_passes_resolved_strategy_profiles(monkeypatch):
    teams = [SimpleNamespace(team_id="AAA"), SimpleNamespace(team_id="BBB")]
    players = [SimpleNamespace(player_id="P1"), SimpleNamespace(player_id="P2")]
    profile_map = {"AAA": "development_focus", "BBB": "power_offense"}
    assign_calls: list[tuple[str, str | None]] = []
    lineup_calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(roster_auto_assign, "load_teams", lambda _path: teams)
    monkeypatch.setattr(
        roster_auto_assign,
        "load_players_from_csv",
        lambda _path: players,
    )
    monkeypatch.setattr(roster_auto_assign, "load_users", lambda _path: [])
    monkeypatch.setattr(
        roster_auto_assign,
        "_resolve_strategy_profile_token",
        lambda team_id, **_kwargs: profile_map[team_id],
    )
    monkeypatch.setattr(
        roster_auto_assign,
        "auto_assign_team",
        lambda team_id, **kwargs: assign_calls.append(
            (team_id, kwargs.get("strategy_profile"))
        ),
    )
    monkeypatch.setattr(
        roster_auto_assign,
        "auto_fill_lineup_for_team",
        lambda team_id, **kwargs: lineup_calls.append(
            (team_id, kwargs.get("strategy_profile"))
        ),
    )
    monkeypatch.setattr(
        roster_auto_assign.load_roster,
        "cache_clear",
        lambda: None,
    )

    roster_auto_assign.auto_assign_all_teams()

    assert assign_calls == [
        ("AAA", "development_focus"),
        ("BBB", "power_offense"),
    ]
    assert lineup_calls == [
        ("AAA", "development_focus"),
        ("BBB", "power_offense"),
    ]


def test_prospect_sorting_changes_by_strategy_profile():
    as_of = date(2026, 7, 1)
    young = SimpleNamespace(
        player_id="YNG",
        is_pitcher=False,
        primary_position="CF",
        birthdate="2006-05-01",
        ch=58,
        ph=52,
        sp=65,
        pl=55,
        vl=55,
        sc=55,
        fa=60,
        arm=55,
        gf=55,
    )
    veteran = SimpleNamespace(
        player_id="VET",
        is_pitcher=False,
        primary_position="LF",
        birthdate="1994-05-01",
        ch=78,
        ph=80,
        sp=45,
        pl=55,
        vl=55,
        sc=55,
        fa=40,
        arm=40,
        gf=40,
    )

    dev_young = roster_auto_assign._prospect_sort_key(  # noqa: SLF001
        young,
        as_of_date=as_of,
        age_cache={},
        strategy_profile="development_focus",
    )[0]
    dev_veteran = roster_auto_assign._prospect_sort_key(  # noqa: SLF001
        veteran,
        as_of_date=as_of,
        age_cache={},
        strategy_profile="development_focus",
    )[0]
    win_young = roster_auto_assign._prospect_sort_key(  # noqa: SLF001
        young,
        as_of_date=as_of,
        age_cache={},
        strategy_profile="win_now",
    )[0]
    win_veteran = roster_auto_assign._prospect_sort_key(  # noqa: SLF001
        veteran,
        as_of_date=as_of,
        age_cache={},
        strategy_profile="win_now",
    )[0]

    assert dev_young > dev_veteran
    assert dev_young > win_young
    assert win_veteran > dev_veteran


def _make_hitter(pid: str, *, birth_year: int, ovr: int) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=pid,
        is_pitcher=False,
        primary_position="LF",
        other_positions=[],
        birthdate=f"{birth_year}-05-01",
        ch=ovr, ph=ovr, sp=ovr, pl=ovr, vl=ovr, sc=ovr, fa=ovr, arm=ovr, gf=ovr,
    )


def test_pick_minor_rosters_keeps_low_young_and_seats_vets_in_aaa():
    """Over-age players must never land at LOW; they belong in AAA (or are
    released), and younger players fill LOW. Regression for auto-assign
    producing a roster the LOW age gate rejects."""

    from datetime import date as _date

    this_year = _date.today().year
    # 8 over-age players (~33) + 17 young players (~22): a 25-man minor pool.
    over_age = [
        _make_hitter(f"OLD{i}", birth_year=this_year - 33, ovr=70 - i)
        for i in range(8)
    ]
    young = [
        _make_hitter(f"YNG{i}", birth_year=this_year - 22, ovr=60 - i)
        for i in range(17)
    ]

    aaa_ids, low_ids = roster_auto_assign._pick_minor_rosters(  # noqa: SLF001
        over_age + young,
        [],
        strategy_profile="balanced",
    )

    over_age_ids = {p.player_id for p in over_age}
    # No over-age player is parked at LOW.
    assert not (set(low_ids) & over_age_ids), "over-age players leaked into LOW"
    # Every over-age player is seated in AAA (pool has room), not released.
    assert over_age_ids.issubset(set(aaa_ids)), "over-age players were not seated in AAA"
    # Caps respected.
    assert len(aaa_ids) <= 15
    assert len(low_ids) <= 10
