"""Auto-assign gentler modes:

- ``dry_run=True`` computes the moves WITHOUT saving (drives the preview).
- ``mode="gaps"`` ("fill gaps only") preserves the owner's current placements
  and only makes the moves required for legality — it never wholesale-reshuffles
  a roster that is already legal.
"""

from datetime import date
from types import SimpleNamespace

from models.roster import Roster
from services import roster_auto_assign as ra


AS_OF = date(2025, 1, 1)


def _hitter(pid, pos, ovr=70, age=24, injured=False):
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions="", is_pitcher=False,
        ch=ovr, ph=ovr, sp=ovr, fa=ovr, arm=ovr, gf=ovr, eye=ovr,
        birthdate=f"{AS_OF.year - age}-06-15", injured=injured,
        first_name="First", last_name=pid,
    )


def _arm(pid, ovr=70, age=24, injured=False):
    return SimpleNamespace(
        player_id=pid, primary_position="P", other_positions="", is_pitcher=True,
        arm=ovr, control=ovr, movement=ovr, endurance=ovr, fb=ovr,
        ch=ovr, ph=ovr, sp=ovr, fa=ovr, gf=ovr, eye=ovr,
        birthdate=f"{AS_OF.year - age}-06-15", injured=injured,
        first_name="First", last_name=pid,
    )


def _legal_base():
    """A legal, full 25-man ACT (8 starters + 3 bench = 11 hitters, 14 pitchers),
    plus a small AAA and a young LOW. Returns (players_dict, Roster)."""
    players = {}
    act = []
    for pos in ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"):
        p = _hitter(f"ACT_{pos}", pos)
        players[p.player_id] = p
        act.append(p.player_id)
    for i in range(3):
        p = _hitter(f"ACT_B{i}", "1B")
        players[p.player_id] = p
        act.append(p.player_id)
    for i in range(14):
        p = _arm(f"ACT_P{i}")
        players[p.player_id] = p
        act.append(p.player_id)
    assert len(act) == 25
    aaa = []
    for i in range(4):
        p = _hitter(f"AAA_{i}", "1B", ovr=55, age=23)
        players[p.player_id] = p
        aaa.append(p.player_id)
    low = []
    for i in range(3):
        p = _hitter(f"LOW_{i}", "1B", ovr=50, age=19)
        players[p.player_id] = p
        low.append(p.player_id)
    roster = Roster(team_id="T", act=act, aaa=aaa, low=low)
    return players, roster


def _run(monkeypatch, players, roster, **kwargs):
    saved = {}
    monkeypatch.setattr(ra, "load_roster", lambda *a, **k: roster)
    monkeypatch.setattr(ra, "save_roster", lambda tid, r, **k: saved.update(r=r, called=True))
    monkeypatch.setattr(ra, "_resolve_strategy_profile_token", lambda *a, **k: "balanced")
    result = ra.auto_assign_team(
        "T", players_by_id=players, as_of_date=AS_OF, age_cache={}, **kwargs
    )
    return result, saved


def test_dry_run_does_not_save(monkeypatch):
    players, roster = _legal_base()
    result, saved = _run(monkeypatch, players, roster, mode="full", dry_run=True)
    assert saved.get("called") is not True
    assert result["dry_run"] is True
    assert result["mode"] == "full"
    assert isinstance(result["moved"], list)


def test_gaps_no_moves_on_already_legal_roster(monkeypatch):
    # The whole point of gaps mode: a legal roster is left completely alone.
    players, roster = _legal_base()
    result, saved = _run(monkeypatch, players, roster, mode="gaps")
    assert result["moved"] == []
    assert saved.get("called") is True  # it still saves (no dry_run)


def test_gaps_moves_only_injured_pitcher_to_dl(monkeypatch):
    # Injuring a pitcher leaves the 11 position players intact, so the ONLY move
    # is that pitcher to the DL — nothing else is disturbed.
    players, roster = _legal_base()
    players["ACT_P0"].injured = True
    result, _ = _run(monkeypatch, players, roster, mode="gaps")
    moves = {m["player_id"]: (m["from"], m["to"]) for m in result["moved"]}
    assert moves == {"ACT_P0": ("ACT", "DL")}, moves


def test_gaps_injured_hitter_is_backfilled(monkeypatch):
    # Injuring a position player drops ACT below the 11-hitter minimum, so gaps
    # both DLs the injured player AND promotes one replacement to stay legal.
    players, roster = _legal_base()
    players["ACT_B0"].injured = True
    result, saved = _run(monkeypatch, players, roster, mode="gaps")
    moves = {m["player_id"]: (m["from"], m["to"]) for m in result["moved"]}
    assert moves.get("ACT_B0") == ("ACT", "DL")
    promotions = [pid for pid, (frm, to) in moves.items() if to == "ACT"]
    assert len(promotions) == 1, moves
    r = saved["r"]
    act_hitters = [pid for pid in r.act if pid in players and not players[pid].is_pitcher]
    assert len(act_hitters) >= ra.MIN_POSITION_PLAYERS_ACT


def test_gaps_promotes_to_fix_act_coverage(monkeypatch):
    players, roster = _legal_base()
    # Pull the SS out of ACT down to AAA -> ACT now lacks SS coverage and drops
    # to 10 position players. Gaps must promote an SS-eligible player back up.
    roster.act.remove("ACT_SS")
    roster.aaa.append("ACT_SS")
    result, saved = _run(monkeypatch, players, roster, mode="gaps")
    r = saved["r"]
    covered = set()
    for pid in r.act:
        if pid in players and not players[pid].is_pitcher:
            covered |= ra._eligible_positions(players[pid])
    assert "SS" in covered
    assert "ACT_SS" in r.act  # the SS came back up


def test_gaps_promotes_overage_low_player_to_aaa(monkeypatch):
    players, roster = _legal_base()
    old = _hitter("OLD_LOW", "1B", ovr=55, age=31)  # aged out of LOW
    players[old.player_id] = old
    roster.low.append(old.player_id)
    result, saved = _run(monkeypatch, players, roster, mode="gaps")
    r = saved["r"]
    assert "OLD_LOW" in r.aaa
    assert "OLD_LOW" not in r.low
    assert ("OLD_LOW", ("LOW", "AAA")) in [
        (m["player_id"], (m["from"], m["to"])) for m in result["moved"]
    ]


def test_gaps_trims_over_cap_act_to_aaa(monkeypatch):
    players, roster = _legal_base()
    # Add two extra pitchers straight onto ACT (27 > 25). Gaps should demote the
    # two lowest-value droppable players to AAA and leave coverage intact.
    for i in range(2):
        p = _arm(f"EXTRA_P{i}", ovr=40)
        players[p.player_id] = p
        roster.act.append(p.player_id)
    result, saved = _run(monkeypatch, players, roster, mode="gaps")
    r = saved["r"]
    assert len(r.act) == 25
    covered = set()
    for pid in r.act:
        if pid in players and not players[pid].is_pitcher:
            covered |= ra._eligible_positions(players[pid])
    assert all(pos in covered for pos in ra.REQUIRED_POSITIONS)
