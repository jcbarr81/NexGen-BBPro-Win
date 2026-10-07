"""Full-mode auto-assign under the 26-man rules (owner decision 8, 7.46.0).

- A full reassign seats exactly 13 pitchers and 13 hitters when the
  organisation allows it, and never more than 13 pitchers even when it is
  short of hitters (the active roster is left short instead).
- It keeps at least five starters.
- The September caps (28 / 14) are honoured when a caller passes them.
- Players are released only when the organisation is above ORG_LIMIT.
"""

from datetime import date
from types import SimpleNamespace

from models.roster import Roster
from services import roster_auto_assign as ra
from utils.roster_rules import (
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    ORG_LIMIT,
    SEPTEMBER_MAX_ACTIVE_PITCHERS,
    SEPTEMBER_ROSTER_SIZE,
    counts_as_pitcher,
)

POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
# Young enough for LOW, so the minors can seat everyone.
YOUNG = f"{date.today().year - 20}-06-15"


def _hitter(pid, pos, ovr=60):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions="", is_pitcher=False,
        ch=ovr, ph=ovr, sp=ovr, fa=ovr, arm=ovr, gf=ovr, eye=ovr, birthdate=YOUNG,
        first_name="H", last_name=pid,
    )


def _arm(pid, ovr=60, endurance=40):
    return SimpleNamespace(
        player_id=pid, primary_position="P", other_positions="", is_pitcher=True,
        arm=ovr, control=ovr, movement=ovr, endurance=endurance, fb=ovr,
        ch=ovr, ph=ovr, sp=ovr, fa=ovr, gf=ovr, eye=ovr, birthdate=YOUNG,
        first_name="P", last_name=pid,
    )


def _org(hitters, pitchers, *, starters=6):
    """``hitters`` position players (full coverage) and ``pitchers`` arms, the
    first ``starters`` of them high-endurance starters."""

    people = [_hitter(f"H{i}", POSITIONS[i % len(POSITIONS)]) for i in range(hitters)]
    people += [
        _arm(f"P{i}", endurance=80 if i < starters else 40) for i in range(pitchers)
    ]
    return {p.player_id: p for p in people}


def _run(monkeypatch, players, **kwargs):
    roster = Roster(team_id="CPU", act=list(players))
    saved = {}
    monkeypatch.setattr(ra, "load_roster", lambda *a, **k: roster)
    monkeypatch.setattr(ra, "save_roster", lambda tid, r, **k: saved.update(r=r))
    monkeypatch.setattr(ra, "_resolve_strategy_profile_token", lambda *a, **k: "balanced")
    monkeypatch.setattr("services.transaction_log.record_transaction", lambda **k: None)
    monkeypatch.setattr(
        "services.contracts_service.release_contracts_to_free_agency", lambda ids: None
    )
    result = ra.auto_assign_team("CPU", players_by_id=players, **kwargs)
    return result, saved["r"]


def _split(players, ids):
    pitchers = [pid for pid in ids if counts_as_pitcher(players[pid])]
    hitters = [pid for pid in ids if not counts_as_pitcher(players[pid])]
    return pitchers, hitters


def test_full_mode_seats_13_pitchers_and_13_hitters(monkeypatch):
    players = _org(20, 20)
    result, r = _run(monkeypatch, players)
    pitchers, hitters = _split(players, r.act)
    assert len(r.act) == ACTIVE_ROSTER_SIZE
    assert len(pitchers) == MAX_ACTIVE_PITCHERS
    assert len(hitters) == ACT_HITTER_TARGET
    assert result["released"] == []


def test_full_mode_never_seats_a_14th_pitcher_when_short_of_hitters(monkeypatch):
    # Only 12 position players in the whole organisation: the old top-off
    # branch filled the 26th spot with a 14th pitcher. Now the roster stays
    # one short instead.
    players = _org(ACT_HITTER_TARGET - 1, 30)
    result, r = _run(monkeypatch, players)
    pitchers, hitters = _split(players, r.act)
    assert len(pitchers) == MAX_ACTIVE_PITCHERS
    assert len(hitters) == ACT_HITTER_TARGET - 1
    assert len(r.act) == ACTIVE_ROSTER_SIZE - 1
    assert result["released"] == []


def test_full_mode_fills_with_hitters_when_short_of_pitchers(monkeypatch):
    players = _org(30, MAX_ACTIVE_PITCHERS - 2)
    _result, r = _run(monkeypatch, players)
    pitchers, _hitters = _split(players, r.act)
    assert len(pitchers) == MAX_ACTIVE_PITCHERS - 2
    assert len(r.act) == ACTIVE_ROSTER_SIZE


def test_full_mode_keeps_five_starters_over_better_relievers(monkeypatch):
    # The five starters rate below every reliever, yet all five make the staff.
    players = _org(20, 0)
    for i in range(5):
        p = _arm(f"SP{i}", ovr=40, endurance=85)
        players[p.player_id] = p
    for i in range(15):
        p = _arm(f"RP{i}", ovr=75, endurance=30)
        players[p.player_id] = p
    _result, r = _run(monkeypatch, players)
    pitchers, _hitters = _split(players, r.act)
    assert {f"SP{i}" for i in range(5)} <= set(pitchers)
    assert len(pitchers) == MAX_ACTIVE_PITCHERS


def test_full_mode_honours_the_september_caps(monkeypatch):
    players = _org(20, 20)
    _result, r = _run(
        monkeypatch,
        players,
        act_cap=SEPTEMBER_ROSTER_SIZE,
        pitcher_cap=SEPTEMBER_MAX_ACTIVE_PITCHERS,
    )
    pitchers, _hitters = _split(players, r.act)
    assert len(r.act) == SEPTEMBER_ROSTER_SIZE
    assert len(pitchers) == SEPTEMBER_MAX_ACTIVE_PITCHERS


def test_no_release_at_the_org_limit(monkeypatch):
    players = _org(25, ORG_LIMIT - 25)
    assert len(players) == ORG_LIMIT
    result, r = _run(monkeypatch, players)
    assert result["released"] == []
    assert result["overflow"] == []
    assert set(players) <= set(r.act) | set(r.aaa) | set(r.low)


def test_release_only_above_the_org_limit(monkeypatch):
    players = _org(25, ORG_LIMIT + 1 - 25)
    result, _r = _run(monkeypatch, players)
    assert len(result["released"]) == 1


def test_injured_players_do_not_count_toward_the_org_limit(monkeypatch):
    # One player over the limit, but he is injured and heads to the DL, which
    # sits outside the organisation count. Every player is a veteran LOW can't
    # seat, so some have no slot -- they are kept as overflow, not released.
    players = _org(25, ORG_LIMIT + 1 - 25)
    for p in players.values():
        p.birthdate = f"{date.today().year - 30}-06-15"
    players["H0"].injured = True
    result, r = _run(monkeypatch, players)
    assert result["released"] == []
    assert result["overflow"]
    assert "H0" in r.dl
