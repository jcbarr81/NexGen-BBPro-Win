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
from utils.roster_rules import (
    AAA_CAP,
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    SEPTEMBER_MAX_ACTIVE_PITCHERS,
    SEPTEMBER_ROSTER_SIZE,
)

STARTER_POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
BENCH = ACT_HITTER_TARGET - len(STARTER_POSITIONS)


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
    """A legal, full 26-man ACT (8 starters + 5 bench = 13 hitters, 13 pitchers),
    plus a small AAA and a young LOW. Returns (players_dict, Roster)."""
    players = {}
    act = []
    for pos in STARTER_POSITIONS:
        p = _hitter(f"ACT_{pos}", pos)
        players[p.player_id] = p
        act.append(p.player_id)
    for i in range(BENCH):
        p = _hitter(f"ACT_B{i}", "1B")
        players[p.player_id] = p
        act.append(p.player_id)
    for i in range(MAX_ACTIVE_PITCHERS):
        p = _arm(f"ACT_P{i}")
        players[p.player_id] = p
        act.append(p.player_id)
    assert len(act) == ACTIVE_ROSTER_SIZE
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
    # Injuring a pitcher leaves the position players intact, so the ONLY move
    # is that pitcher to the DL — nothing else is disturbed.
    players, roster = _legal_base()
    players["ACT_P0"].injured = True
    result, _ = _run(monkeypatch, players, roster, mode="gaps")
    moves = {m["player_id"]: (m["from"], m["to"]) for m in result["moved"]}
    assert moves == {"ACT_P0": ("ACT", "DL")}, moves


def test_gaps_single_injured_bench_hitter_needs_no_backfill(monkeypatch):
    # A 13-hitter ACT that loses one bench bat still clears the minimum, so the
    # only move is that player to the DL (the roster is left one short).
    players, roster = _legal_base()
    players["ACT_B0"].injured = True
    result, _ = _run(monkeypatch, players, roster, mode="gaps")
    moves = {m["player_id"]: (m["from"], m["to"]) for m in result["moved"]}
    assert moves == {"ACT_B0": ("ACT", "DL")}, moves


def test_gaps_injured_hitter_is_backfilled(monkeypatch):
    # Injuring bench players until ACT drops one below the hitter minimum makes
    # gaps both DL the injured players AND promote exactly one replacement.
    players, roster = _legal_base()
    injured = [
        f"ACT_B{i}" for i in range(ACT_HITTER_TARGET - ra.MIN_POSITION_PLAYERS_ACT + 1)
    ]
    for pid in injured:
        players[pid].injured = True
    result, saved = _run(monkeypatch, players, roster, mode="gaps")
    moves = {m["player_id"]: (m["from"], m["to"]) for m in result["moved"]}
    for pid in injured:
        assert moves.get(pid) == ("ACT", "DL")
    promotions = [pid for pid, (frm, to) in moves.items() if to == "ACT"]
    assert len(promotions) == 1, moves
    r = saved["r"]
    act_hitters = [pid for pid in r.act if pid in players and not players[pid].is_pitcher]
    assert len(act_hitters) >= ra.MIN_POSITION_PLAYERS_ACT


def test_gaps_promotes_to_fix_act_coverage(monkeypatch):
    players, roster = _legal_base()
    # Pull the SS out of ACT down to AAA -> ACT now lacks SS coverage. Gaps
    # must promote an SS-eligible player back up.
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


def _act_pitchers(players, roster):
    return [pid for pid in roster.act if players[pid].is_pitcher]


def test_gaps_trims_over_cap_act_to_aaa(monkeypatch):
    players, roster = _legal_base()
    # Add two extra hitters straight onto ACT (over the size cap). Gaps should
    # demote the two lowest-value droppable players to AAA and leave coverage
    # intact.
    for i in range(2):
        p = _hitter(f"EXTRA_H{i}", "1B", ovr=40)
        players[p.player_id] = p
        roster.act.append(p.player_id)
    result, saved = _run(monkeypatch, players, roster, mode="gaps")
    r = saved["r"]
    assert len(r.act) == ACTIVE_ROSTER_SIZE
    assert {"EXTRA_H0", "EXTRA_H1"} <= set(r.aaa)
    covered = set()
    for pid in r.act:
        if pid in players and not players[pid].is_pitcher:
            covered |= ra._eligible_positions(players[pid])
    assert all(pos in covered for pos in ra.REQUIRED_POSITIONS)
    assert result["released"] == []


def test_gaps_demotes_pitchers_above_the_cap_to_aaa(monkeypatch):
    # Swap two bench bats for two weak arms: ACT is at the size cap but carries
    # two pitchers too many. Gaps demotes exactly those two to AAA (it never
    # releases) and leaves the hitters alone.
    players, roster = _legal_base()
    for i in range(2):
        roster.act.remove(f"ACT_B{i}")
        roster.aaa.append(f"ACT_B{i}")
        p = _arm(f"EXTRA_P{i}", ovr=40)
        players[p.player_id] = p
        roster.act.append(p.player_id)
    assert len(_act_pitchers(players, roster)) == MAX_ACTIVE_PITCHERS + 2
    result, saved = _run(monkeypatch, players, roster, mode="gaps")
    r = saved["r"]
    assert len(_act_pitchers(players, r)) == MAX_ACTIVE_PITCHERS
    assert {"EXTRA_P0", "EXTRA_P1"} <= set(r.aaa)
    moves = {m["player_id"]: (m["from"], m["to"]) for m in result["moved"]}
    assert moves == {"EXTRA_P0": ("ACT", "AAA"), "EXTRA_P1": ("ACT", "AAA")}, moves
    assert result["released"] == []


def test_gaps_counts_sp_rp_positions_as_pitchers(monkeypatch):
    # A pitcher recorded only by primary position (RP, no is_pitcher flag)
    # still counts toward the cap (utils.roster_rules.counts_as_pitcher).
    players, roster = _legal_base()
    roster.act.remove("ACT_B0")
    roster.aaa.append("ACT_B0")
    extra = _arm("EXTRA_RP", ovr=40)
    extra.is_pitcher = False
    extra.primary_position = "RP"
    players[extra.player_id] = extra
    roster.act.append(extra.player_id)
    result, saved = _run(monkeypatch, players, roster, mode="gaps")
    assert "EXTRA_RP" in saved["r"].aaa
    assert result["released"] == []


def test_gaps_pitcher_trim_never_releases_when_aaa_is_full(monkeypatch):
    # AAA already full of veterans (too old for LOW): the surplus arm still
    # leaves ACT, AAA is reported as overflow for the owner to trim, and nobody
    # is released.
    players, roster = _legal_base()
    for pid in roster.aaa:
        players[pid].birthdate = f"{AS_OF.year - 30}-06-15"
    while len(roster.aaa) < AAA_CAP:
        p = _arm(f"AAA_P{len(roster.aaa)}", ovr=55, age=30)
        players[p.player_id] = p
        roster.aaa.append(p.player_id)
    roster.act.remove("ACT_B0")
    roster.low.append("ACT_B0")
    extra = _arm("EXTRA_P", ovr=40, age=30)
    players[extra.player_id] = extra
    roster.act.append(extra.player_id)
    result, saved = _run(monkeypatch, players, roster, mode="gaps")
    r = saved["r"]
    assert len(_act_pitchers(players, r)) == MAX_ACTIVE_PITCHERS
    assert "EXTRA_P" in r.aaa
    assert result["released"] == []
    assert result["overflow"], "the over-cap AAA is reported, not cut"
    everyone = set(r.act) | set(r.aaa) | set(r.low) | set(r.dl)
    assert set(players) <= everyone


def test_gaps_keeps_a_legal_september_roster(monkeypatch):
    # With the September caps (28 active, 14 pitchers) a 28-man roster carrying
    # 14 pitchers is legal and gaps leaves it alone.
    players, roster = _legal_base()
    extra_arms = SEPTEMBER_MAX_ACTIVE_PITCHERS - MAX_ACTIVE_PITCHERS
    for i in range(extra_arms):
        p = _arm(f"SEPT_P{i}")
        players[p.player_id] = p
        roster.act.append(p.player_id)
    for i in range(SEPTEMBER_ROSTER_SIZE - ACTIVE_ROSTER_SIZE - extra_arms):
        p = _hitter(f"SEPT_H{i}", "1B")
        players[p.player_id] = p
        roster.act.append(p.player_id)
    assert len(roster.act) == SEPTEMBER_ROSTER_SIZE
    result, saved = _run(
        monkeypatch,
        players,
        roster,
        mode="gaps",
        act_cap=SEPTEMBER_ROSTER_SIZE,
        pitcher_cap=SEPTEMBER_MAX_ACTIVE_PITCHERS,
    )
    assert result["moved"] == []
    assert len(saved["r"].act) == SEPTEMBER_ROSTER_SIZE
