"""Release 3 live-path fix: a CPU-CPU trade leaves both rosters legal.

Arrivals land on the active roster, so a pitcher-for-hitter deal in the
post-sim automations saved one CPU club with 14 active pitchers (the limit is
13) and its partner with 12 until each club's next game-day upkeep. The lane
now runs the CPU roster upkeep for both clubs straight after the commit.
"""

from __future__ import annotations

import random
import uuid
from types import SimpleNamespace

import pytest

from models.trade import Trade
from services.cpu_trade_proposals import _CandidateOffer, run_cpu_trade_proposal_cycle
from utils.roster_rules import ACT_HITTER_TARGET, ACTIVE_ROSTER_SIZE, MAX_ACTIVE_PITCHERS

_TEAMS = ("CPUA", "CPUB")


def _p(pid: str, pos: str, score: int = 50) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=pid, primary_position=pos, other_positions=[], injured=False,
        is_pitcher=(pos == "P"), ch=score, ph=score, sp=score, fa=score,
        arm=score, sc=score, first_name=pid, last_name="", age=28,
        birthdate="1998-06-15",
    )


def _org(team: str, players: dict) -> dict[str, list[str]]:
    """13 pitchers / 13 hitters active (two catchers, spare SS and CF), plus
    two arms and two bats in AAA."""

    hitter_positions = ["C", "C", "1B", "2B", "SS", "SS", "3B", "LF", "CF",
                        "CF", "RF", "1B", "LF"]
    assert len(hitter_positions) == ACT_HITTER_TARGET
    act: list[str] = []
    for i, pos in enumerate(hitter_positions):
        pid = f"{team}_h{i}"
        players[pid] = _p(pid, pos, score=60)
        act.append(pid)
    for i in range(MAX_ACTIVE_PITCHERS):
        pid = f"{team}_p{i}"
        players[pid] = _p(pid, "P", score=60)
        act.append(pid)
    aaa: list[str] = []
    for i in range(2):
        for kind, pos in (("ap", "P"), ("ah", "LF")):
            pid = f"{team}_{kind}{i}"
            players[pid] = _p(pid, pos, score=45)
            aaa.append(pid)
    return {"act": act, "aaa": aaa}


@pytest.fixture
def league(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "rosters").mkdir(parents=True)
    (root / "users.txt").write_text("", encoding="utf-8")
    # Sentinel so get_data_dir() resolves this root, never a real league.
    (root / "players.csv").write_text(
        "player_id,first_name,last_name,primary_position,is_pitcher\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXGEN_DATA_ROOT", str(root))
    monkeypatch.delenv("NEXGEN_ACTIVE_LEAGUE", raising=False)
    import utils.path_utils as path_utils
    from utils.roster_loader import load_roster

    path_utils._DATA_DIR_CACHE.clear()
    load_roster.cache_clear()
    assert path_utils.get_data_dir().resolve() == root.resolve()

    players: dict[str, SimpleNamespace] = {}
    for team in _TEAMS:
        levels = _org(team, players)
        lines = [f"{pid},ACT" for pid in levels["act"]]
        lines += [f"{pid},AAA" for pid in levels["aaa"]]
        (root / "rosters" / f"{team}.csv").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    teams = [SimpleNamespace(team_id=t, owner_id="cpu") for t in _TEAMS]
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trade_settings",
        lambda **_kw: SimpleNamespace(
            league_id="alpha", trades_enabled=True,
            cpu_initiated_trades_enabled=True, cpu_proposal_cadence="high",
            draft_pick_trading_enabled=False, max_pick_trade_years=3,
        ),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_teams", lambda *_a, **_kw: teams
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_players_from_csv",
        lambda *_a, **_kw: list(players.values()),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_trades", lambda *_a, **_kw: []
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals._window_probability", lambda *_a, **_kw: 1.0
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.load_outlooks",
        lambda **_kw: {"CPUA": "contend", "CPUB": "rebuild"},
    )

    def _offer(**kwargs):
        # CPUA ships a hitter for one of CPUB's pitchers.
        ranked = int(kwargs.get("return_ranked", 0) or 0)
        targets = list(kwargs.get("target_team_ids") or [])
        if not targets or not ranked:
            # The CPU-to-human pass is not under test here.
            return [] if ranked else None
        proposer, receiver = kwargs["cpu_team_id"], targets[0]
        trade = Trade(
            trade_id=uuid.uuid4().hex[:8], from_team=proposer, to_team=receiver,
            give_player_ids=[f"{proposer}_h12"],
            receive_player_ids=[f"{receiver}_p12"],
            initiated_by="cpu",
        )
        return [_CandidateOffer(trade=trade, score_margin=0.5,
                                cpu_team_id=proposer, target_team_id=receiver)]

    monkeypatch.setattr("services.cpu_trade_proposals._build_best_offer", _offer)
    monkeypatch.setattr(
        "services.cpu_trade_proposals.evaluate_cpu_trade_offer",
        lambda *_a, **_kw: SimpleNamespace(
            action="accept", total_score=1.0, threshold=0.6, counter_offer=None
        ),
    )
    monkeypatch.setattr(
        "services.payroll_policy.evaluate_trade_payroll_impact",
        lambda *_a, **_kw: SimpleNamespace(allowed=True),
    )
    monkeypatch.setattr(
        "services.cpu_trade_proposals.save_trade", lambda *_a, **_kw: None
    )
    monkeypatch.setattr(
        "services.trade_execution.announce_trade", lambda *_a, **_kw: None
    )
    yield SimpleNamespace(root=root, players=players)
    path_utils._DATA_DIR_CACHE.clear()
    load_roster.cache_clear()


def _saved_shape(root, team, players):
    act = [
        line.split(",")[0]
        for line in (root / "rosters" / f"{team}.csv").read_text("utf-8").splitlines()
        if line.strip().endswith(",ACT")
    ]
    arms = sum(1 for pid in act if players[pid].is_pitcher)
    return arms, len(act) - arms


def test_pitcher_for_hitter_trade_saves_legal_shapes(league):
    result = run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-15"], data_dir=league.root,
        rng=random.Random(1),
    )
    executed = result["cpu_cpu_trades"]["executed"]
    assert len(executed) == 1, result
    trade = executed[0]
    shapes = {
        team: _saved_shape(league.root, team, league.players) for team in _TEAMS
    }
    # The trade went through (the pitcher changed clubs) ...
    receiver_of_arm = trade["from_team"]
    giver_of_arm = trade["to_team"]
    act_text = (league.root / "rosters" / f"{receiver_of_arm}.csv").read_text("utf-8")
    assert f"{giver_of_arm}_p12,ACT" in act_text or f"{giver_of_arm}_p12,AAA" in act_text
    # ... and neither club is left over the pitcher limit or short of arms.
    for team, (arms, bats) in shapes.items():
        assert arms <= MAX_ACTIVE_PITCHERS, (team, shapes)
        assert arms + bats <= ACTIVE_ROSTER_SIZE, (team, shapes)
    assert shapes[receiver_of_arm] == (MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET), shapes
    assert shapes[giver_of_arm] == (MAX_ACTIVE_PITCHERS, ACT_HITTER_TARGET), shapes


def test_upkeep_is_recorded_as_transactions(league):
    run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-15"], data_dir=league.root,
        rng=random.Random(1),
    )
    from services.transaction_log import load_transactions

    rows = load_transactions()
    details = [str(r.get("details", "") if isinstance(r, dict)
                   else getattr(r, "details", "")) for r in rows]
    assert any("CPU roster upkeep after trade" in d for d in details), details


def test_human_club_is_never_upkept(league, monkeypatch):
    """Strict ownership: when a club is owned, the lane neither trades with
    it nor touches its roster."""

    (league.root / "users.txt").write_text(
        "owner_b,pw,owner,CPUB\n", encoding="utf-8"
    )
    before = (league.root / "rosters" / "CPUB.csv").read_text("utf-8")
    run_cpu_trade_proposal_cycle(
        simulated_dates=["2026-07-15"], data_dir=league.root,
        rng=random.Random(1),
    )
    assert (league.root / "rosters" / "CPUB.csv").read_text("utf-8") == before
