"""Release 3 item F (audit M16 / M12): two catchers, best-fit auto-fill,
one-file lineup repair and the game-day settings endpoint.

* full-mode auto-assign carries two catchers; CPU upkeep calls one up;
* an owner team with one catcher gets an advisory warning, never an error;
* auto-fill fills a position nobody lists with the best fit, never a
  non-catcher at C while a catcher is active, and never cascades;
* the default game lineup covers every position from the club's own players;
* a broken owner lineup rewrites only that file and tells the owner.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import playbalance.game_runner as gr
import utils.lineup_loader as LL
from models.roster import Roster
from services.roster_fill import maintain_cpu_active_roster
from services.roster_validation import validate_catcher_depth
from utils.lineup_autofill import build_lineup
from utils.pitcher_role import get_role
from utils.player_loader import load_players_from_csv
from utils.roster_rules import (
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    counts_as_pitcher,
    is_catcher,
)

PLAYERS = Path(__file__).resolve().parents[1] / "data" / "players.csv"


# --- the catcher predicate ------------------------------------------------------


def test_is_catcher_reads_primary_and_listed_positions():
    assert is_catcher({"primary_position": "C"})
    assert is_catcher({"primary_position": "1B", "other_positions": "LF|C"})
    assert is_catcher(SimpleNamespace(primary_position="3B", other_positions=["C"], is_pitcher=False))
    assert not is_catcher({"primary_position": "1B", "other_positions": "['CF']"})
    assert not is_catcher({"primary_position": "P", "is_pitcher": "1"})


# --- auto-assign and CPU upkeep -------------------------------------------------


def _hp(pid, pos, score=50, injured=False, other=()):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions=list(other), injured=injured,
        is_pitcher=(pos == "P"), ch=score, ph=score, first_name=pid, last_name="",
    )


def test_full_auto_assign_puts_two_of_three_catchers_on_the_active_roster():
    from services.roster_auto_assign import _pick_active_roster

    players = load_players_from_csv(str(PLAYERS))
    hitters = [p for p in players if not counts_as_pitcher(p) and get_role(p) not in {"SP", "RP"}]
    pitchers = [p for p in players if counts_as_pitcher(p)]
    catchers = [p for p in hitters if is_catcher(p)]
    others = [p for p in hitters if not is_catcher(p)]
    assert len(catchers) >= 3 and len(others) >= 20 and len(pitchers) >= 20
    org_hitters = catchers[:3] + others[:20]
    act_ids, _rest_h, _rest_p = _pick_active_roster(org_hitters, pitchers[:20])
    by_id = {p.player_id: p for p in org_hitters + pitchers[:20]}
    act = [by_id[pid] for pid in act_ids]
    assert sum(1 for p in act if is_catcher(p)) == 2
    assert sum(1 for p in act if counts_as_pitcher(p)) == MAX_ACTIVE_PITCHERS
    assert len(act) - MAX_ACTIVE_PITCHERS == ACT_HITTER_TARGET


def test_full_auto_assign_carries_a_backup_infielder_and_outfielder():
    from services.roster_auto_assign import _pick_active_roster

    players = load_players_from_csv(str(PLAYERS))
    hitters = [p for p in players if not counts_as_pitcher(p) and get_role(p) not in {"SP", "RP"}]
    pitchers = [p for p in players if counts_as_pitcher(p)][:20]

    def prim(p):
        return str(p.primary_position).upper()

    def first(pos, n, *, best=True):
        pool = sorted(
            (p for p in hitters if prim(p) == pos and not p.other_positions),
            key=lambda p: float(getattr(p, "ph", 0) or 0), reverse=best,
        )
        return pool[:n]

    # One of each position, two catchers, and a deep pile of better corner
    # bats; the only spare SS / CF are the weakest hitters in the org.
    org = (
        first("C", 2) + first("1B", 1) + first("2B", 1) + first("3B", 1)
        + first("LF", 1) + first("RF", 1) + first("SS", 1) + first("CF", 1)
        + first("1B", 8)[1:] + first("SS", 1, best=False) + first("CF", 1, best=False)
    )
    act_ids, _rh, _rp = _pick_active_roster(org, pitchers)
    act = [p for p in org if p.player_id in act_ids]
    assert sum(1 for p in act if prim(p) == "SS") == 2
    assert sum(1 for p in act if prim(p) == "CF") == 2


def _cpu_club(catchers_on_act=1, catcher_in_aaa=True):
    players, act = {}, []
    for i in range(ACT_HITTER_TARGET):
        pos = "C" if i < catchers_on_act else ("SS" if i == catchers_on_act else "LF")
        players[f"h{i}"] = _hp(f"h{i}", pos, score=60 - i)
        act.append(f"h{i}")
    for i in range(MAX_ACTIVE_PITCHERS):
        players[f"p{i}"] = _hp(f"p{i}", "P", score=55)
        act.append(f"p{i}")
    aaa = ["mC"] if catcher_in_aaa else []
    players["mC"] = _hp("mC", "C", score=30)
    players["mLF"] = _hp("mLF", "LF", score=70)
    aaa.append("mLF")
    return players, Roster("CPU", act=act, aaa=aaa)


def test_cpu_upkeep_calls_up_a_second_catcher_and_keeps_13_and_13():
    players, roster = _cpu_club()
    moves = maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE,
    )
    assert ("mC", "aaa", "act") in moves
    assert sum(1 for pid in roster.act if is_catcher(players[pid])) == 2
    hitters = [pid for pid in roster.act if not counts_as_pitcher(players[pid])]
    assert len(hitters) == ACT_HITTER_TARGET and len(roster.act) == ACTIVE_ROSTER_SIZE
    # the weakest non-catcher went down, never the starting catcher
    assert "h0" in roster.act and ("h12", "act", "aaa") in moves


def test_cpu_upkeep_makes_no_catcher_move_without_a_catcher_in_the_minors():
    players, roster = _cpu_club(catcher_in_aaa=False)
    before = list(roster.act)
    moves = maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE,
    )
    assert moves == [] and roster.act == before


def test_cpu_upkeep_respects_option_vetoes_for_the_catcher_swap():
    players, roster = _cpu_club()
    before = list(roster.act)
    moves = maintain_cpu_active_roster(
        "CPU", roster, players, target_size=ACTIVE_ROSTER_SIZE, cap=ACTIVE_ROSTER_SIZE,
        option_allowed=lambda pid: False,
    )
    assert moves == [] and roster.act == before


def test_the_daily_upkeep_never_touches_an_owner_or_an_unknown_ownership(monkeypatch):
    import api.routers.season as season

    calls = []
    monkeypatch.setattr(
        "services.roster_fill.maintain_cpu_active_roster",
        lambda team_id, *a, **k: calls.append(team_id) or [],
    )
    monkeypatch.setattr("services.roster_fill.ensure_fieldable_roster", lambda *a, **k: [])
    monkeypatch.setattr("utils.player_loader.load_players_from_csv", lambda *a, **k: [])
    monkeypatch.setattr("utils.roster_loader.load_roster", lambda tid, *a, **k: Roster(tid))
    monkeypatch.setattr("utils.roster_loader.active_roster_cap", lambda *a, **k: 26)
    monkeypatch.setattr("services.injury_manager._promotion_allowed", lambda tid: None)
    sim = SimpleNamespace(schedule=[{"date": "2026-05-01", "home": "HUM", "away": "CPU"}])
    for owners, expected in (({"HUM"}, ["CPU"]), (None, [])):
        calls.clear()
        monkeypatch.setattr(
            "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: owners
        )
        season._prepare_rosters_for_date(sim, "2026-05-01")
        assert calls == expected


def test_one_catcher_is_an_advisory_warning_only():
    players = {"c": {"primary_position": "C"}, "x": {"primary_position": "1B"}}
    one = validate_catcher_depth(["c", "x"], players)
    assert one.ok and one.errors == [] and len(one.warnings) == 1
    two = validate_catcher_depth(
        ["c", "x", "u"], {**players, "u": {"primary_position": "LF", "other_positions": "C"}}
    )
    assert two.ok and two.warnings == []


def test_the_compliance_banner_carries_the_warning_and_stays_ok(monkeypatch):
    import api.routers.validation as v

    players = {
        f"h{i}": {"primary_position": pos, "is_pitcher": ""}
        for i, pos in enumerate(["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "1B", "LF", "RF"])
    }
    monkeypatch.setattr(v, "load_players_map", lambda: players)
    monkeypatch.setattr(v, "load_team_levels", lambda tid: {"act": list(players)})
    monkeypatch.setattr(
        v, "effective_caps", lambda: {"act": 26, "aaa": 15, "low": 10, "act_pitchers": 13}
    )
    payload = v.roster_compliance_endpoint("HUM")
    assert payload["ok"] is True and payload["errors"] == []
    assert any("catcher" in w for w in payload["warnings"])


# --- auto-fill: best fit, never a cascade ----------------------------------------


def _fp(pid, pos, *, other=(), bat=50, fa=50, arm=50):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions=list(other),
        is_pitcher=False, fa=fa, arm=arm, ch=bat, ph=bat,
    )


def _fill(team):
    players = {p.player_id: p for p in team}
    score = lambda pid: float(players[pid].ch)  # noqa: E731
    lineup, _ = build_lineup([p.player_id for p in team], players, score=score)
    return dict((pos, pid) for pid, pos in lineup)


def _full_team(**drop):
    team = [
        _fp("c", "C", bat=30), _fp("1b", "1B", bat=70), _fp("2b", "2B"), _fp("3b", "3B"),
        _fp("ss", "SS"), _fp("lf", "LF"), _fp("cf", "CF"), _fp("rf", "RF"),
        _fp("dh", "1B", bat=75),
    ]
    return [p for p in team if p.player_id not in drop]


def test_a_missing_shortstop_goes_to_the_best_fit_not_the_best_bat():
    team = _full_team(ss=True) + [
        _fp("slug", "1B", bat=90, fa=30), _fp("ut", "3B", bat=40, fa=60), _fp("bc", "C", bat=20)
    ]
    at = _fill(team)
    assert at["SS"] == "ut"           # a third baseman, not the slugging 1B
    assert at["2B"] == "2b" and at["3B"] == "3b" and at["1B"] in {"1b", "slug", "dh"}
    assert at["C"] == "c"


def test_a_listed_player_slides_over_before_anyone_plays_out_of_position():
    # The second baseman lists SS; a bench 2B takes his spot: nobody out of position.
    team = _full_team(ss=True)
    team[2] = _fp("2b", "2B", other=("SS",))
    team.append(_fp("b2", "2B", bat=40))
    at = _fill(team)
    assert at["SS"] == "2b" and at["2B"] == "b2"


def test_never_a_non_catcher_at_c_while_a_catcher_is_active():
    # The only catcher also lists 1B and is the best bat: he still catches.
    team = _full_team(c=True) + [_fp("cat", "C", other=("1B",), bat=95), _fp("x", "LF", fa=99)]
    at = _fill(team)
    assert at["C"] == "cat"


def test_no_cascade_when_a_position_is_missing():
    # Old behaviour: SS (missing) took the best bat -- the 2B -- and 2B then
    # fell back too. Now exactly one player is out of position.
    team = _full_team(ss=True) + [_fp("of", "LF", bat=45, fa=60), _fp("bc", "C", bat=20)]
    at = _fill(team)
    out_of_position = [
        pos for pos, pid in at.items()
        if pos != "DH" and pos != next(p for p in team if p.player_id == pid).primary_position
    ]
    assert out_of_position == ["SS"]
    assert at["SS"] != "bc"  # the backup catcher is kept for catching


# --- the default game lineup ------------------------------------------------------


@pytest.fixture
def team_state(monkeypatch, tmp_path):
    def build(act, aaa=()):
        roster = Roster("TST", act=[p.player_id for p in act], aaa=[p.player_id for p in aaa])
        monkeypatch.setattr(LL, "load_roster", lambda *a, **k: roster)
        return LL.build_default_game_state(
            "TST", players_file=str(PLAYERS), roster_dir=str(tmp_path), teams_file=""
        )

    return build


def _pool():
    players = load_players_from_csv(str(PLAYERS))
    hitters = [p for p in players if get_role(p) not in {"SP", "RP"}]
    pitchers = [p for p in players if get_role(p) in {"SP", "RP"}]
    hitters.sort(key=lambda p: getattr(p, "ph", 0), reverse=True)
    return hitters, pitchers


def test_the_default_lineup_covers_every_position(team_state):
    hitters, pitchers = _pool()
    weak_c = [p for p in hitters if str(p.primary_position).upper() == "C"][-1]
    weak_ss = [p for p in hitters if str(p.primary_position).upper() == "SS"][-1]
    sluggers = [
        p for p in hitters if str(p.primary_position).upper() not in {"C", "SS"}
    ][:10]
    state = team_state(sluggers + [weak_c, weak_ss] + pitchers[:13])
    positions = {getattr(p, "position") for p in state.lineup}
    assert {"C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"} <= positions | {"DH"}
    assert weak_c in state.lineup and weak_ss in state.lineup
    assert len(state.lineup) == 9


def test_the_default_lineup_never_borrows_another_clubs_players(team_state):
    hitters, pitchers = _pool()
    with pytest.raises(ValueError):
        team_state(hitters[:7] + pitchers[:12])  # 7 hitters, no minors: no game


# --- a broken owner lineup: one file rewritten, owner told -------------------------


def _write_lineup(path: Path, ids):
    rows = ["order,player_id,position"] + [
        f"{i},{pid},{pos}" for i, (pid, pos) in enumerate(ids, start=1)
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


@pytest.fixture
def lineup_dir(tmp_path, monkeypatch):
    good = [(f"g{i}", "DH") for i in range(9)]
    bad = [("gone", "C")] + good[1:]
    _write_lineup(tmp_path / "OWN_vs_lhp.csv", good)
    _write_lineup(tmp_path / "OWN_vs_rhp.csv", bad)
    calls, news = [], []

    def fake_fill(team_id, *, vs=None, persist=True, **_k):
        calls.append((vs, persist))
        new = [(f"g{i}", "DH") for i in range(8, -1, -1)]
        targets = [vs] if vs else ["lhp", "rhp"]
        if persist:
            for t in targets:
                _write_lineup(tmp_path / f"{team_id}_vs_{t}.csv", new)
        return new

    monkeypatch.setattr(gr, "auto_fill_lineup_for_team", fake_fill)
    monkeypatch.setattr(gr, "_game_hitter_ids", lambda *a, **k: {f"g{i}" for i in range(9)})
    monkeypatch.setattr(gr, "log_news_event", lambda msg, **k: news.append((msg, k)))
    return SimpleNamespace(path=tmp_path, good=good, bad=bad, calls=calls, news=news)


def test_an_owner_lineup_repair_rewrites_only_the_broken_file(lineup_dir, monkeypatch):
    monkeypatch.setattr(gr, "_team_is_cpu", lambda tid: False)
    before = (lineup_dir.path / "OWN_vs_lhp.csv").read_bytes()
    safe = gr._sanitize_lineup("OWN", lineup_dir.bad, lineup_dir=lineup_dir.path)
    assert len(safe) == 9 and ("gone", "C") not in safe
    assert (lineup_dir.path / "OWN_vs_lhp.csv").read_bytes() == before
    assert "gone" not in (lineup_dir.path / "OWN_vs_rhp.csv").read_text()
    assert lineup_dir.calls == [("rhp", True)]
    assert len(lineup_dir.news) == 1
    msg, kw = lineup_dir.news[0]
    assert "vs RHP" in msg and "vs LHP lineup was not changed" in msg
    assert kw.get("team_id") == "OWN"


def test_unknown_ownership_repairs_like_an_owner(lineup_dir, monkeypatch):
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: None
    )
    before = (lineup_dir.path / "OWN_vs_lhp.csv").read_bytes()
    gr._sanitize_lineup("OWN", lineup_dir.bad, lineup_dir=lineup_dir.path)
    assert (lineup_dir.path / "OWN_vs_lhp.csv").read_bytes() == before


def test_a_cpu_lineup_repair_still_rewrites_both_files(lineup_dir, monkeypatch):
    monkeypatch.setattr(gr, "_team_is_cpu", lambda tid: True)
    gr._sanitize_lineup("OWN", lineup_dir.bad, lineup_dir=lineup_dir.path)
    assert lineup_dir.calls == [(None, True)]
    assert lineup_dir.news == []


def test_a_lineup_that_came_from_nowhere_is_rebuilt_in_memory(lineup_dir, monkeypatch):
    monkeypatch.setattr(gr, "_team_is_cpu", lambda tid: False)
    _write_lineup(lineup_dir.path / "OWN_vs_rhp.csv", lineup_dir.good)
    before = {
        p.name: p.read_bytes() for p in lineup_dir.path.glob("OWN_vs_*.csv")
    }
    gr._sanitize_lineup("OWN", [("x", "C")] * 9, lineup_dir=lineup_dir.path)
    assert lineup_dir.calls == [(None, False)]
    assert {p.name: p.read_bytes() for p in lineup_dir.path.glob("OWN_vs_*.csv")} == before


# --- the engine's per-team rest policy -----------------------------------------------


def test_cpu_clubs_ignore_stored_rest_settings(tmp_path, monkeypatch):
    from services import team_play_settings as tps

    monkeypatch.setattr(tps, "get_data_dir", lambda: tmp_path)
    tps.save_team_play_settings("CPU", {"auto_rest_days": False})
    tps.save_team_play_settings("HUM", {"rest_subs_similar_positions": "off"})
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"HUM"}
    )
    assert gr._team_rest_policy("CPU") == {}
    assert gr._team_rest_policy("HUM") == {
        "auto_rest_days": True, "rest_subs_similar_positions": False,
    }


# --- the game-day settings endpoint ------------------------------------------------


@pytest.fixture
def play_api(tmp_path, monkeypatch):
    import api.routers.team_settings as ts
    from services import team_play_settings as tps

    monkeypatch.setattr(tps, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(ts, "_team", lambda tid: SimpleNamespace(team_id=tid))
    monkeypatch.setattr(
        "services.team_ownership.human_owned_team_ids_strict", lambda *a, **k: {"HUM"}
    )
    return ts


def test_the_owner_saves_game_day_settings(play_api):
    owner = {"u": "o", "r": "user", "t": "HUM"}
    out = play_api.save_play_settings("HUM", {"settings": {"auto_rest_days": False}}, owner)
    assert out["settings"]["auto_rest_days"] is False
    assert out["overrides"] == {"auto_rest_days": False} and out["owner_managed"] is True
    back = play_api.save_play_settings("HUM", {"auto_rest_days": "default"}, owner)
    assert back["settings"]["auto_rest_days"] is True and back["overrides"] == {}


def test_another_owner_is_refused_and_bad_values_are_a_400(play_api):
    with pytest.raises(HTTPException) as exc:
        play_api.save_play_settings(
            "HUM", {"auto_rest_days": False}, {"u": "r", "r": "user", "t": "RIV"}
        )
    assert exc.value.status_code == 403
    admin = {"u": "a", "r": "admin", "t": ""}
    with pytest.raises(HTTPException) as exc:
        play_api.save_play_settings("HUM", {"auto_rest_days": "maybe"}, admin)
    assert exc.value.status_code == 400
    assert play_api.get_play_settings("CPU")["owner_managed"] is False
