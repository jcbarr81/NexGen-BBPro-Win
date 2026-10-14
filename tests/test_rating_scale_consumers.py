"""Every consumer outside the engine decides the same on a stretched twin.

Salaries, trades, CPU roster moves, lineups and the draft are tuned in
ENGINE rating points (the salary curve's 35-75 band, the 55 / 65 / 72
promotion bars, the trade evaluator's weights). They read ratings through
``utils.rating_scale.engine_rating`` / ``engine_potential``, so on a league
stored on scale 2 they must return exactly what they return on the same
league stored on scale 1. These tests compare a league with its stretched
twin (``tests/rating_scale_support.py``), consumer by consumer.

Potentials: scale 2 never stores a potential below the current rating and
cuts a gap at 99 (``stretch_row``), and its consumer view leaves out the part
of a gap development never closes (``engine_potential``,
``POTENTIAL_GAP_DISCOUNT``). That is a deliberate change of what a
potential is worth, not of the scale. So consumers that read potentials are
compared on the NOGAP league (every potential set to the current rating,
still scale 1), which isolates the scale; what the new potential view does
is tested on its own.
"""

from __future__ import annotations

import collections
import contextlib
import copy
import csv
import dataclasses
from datetime import date

import pytest

from models.roster import Roster
from models.trade import Trade
from tests import rating_scale_support as support

PROFILES = ("balanced", "win_now", "development_focus", "defense_first", "power_offense")
AS_OF = date(2026, 4, 1)


@pytest.fixture(scope="module")
def leagues(tmp_path_factory):
    """The league fixture four ways: plain and floored, each with its twin."""

    root = tmp_path_factory.mktemp("consumers")
    fixture = support.FIXTURES["calibration_league"]
    out = {}
    for name, floored in (("plain", False), ("floored", True), ("nogap", True)):
        league = support.copy_league(fixture, root / name, floored=floored)
        if name == "nogap":
            _flatten_potentials(league / "players.csv")
        clips = support.write_stretched_twin(league, root / f"{name}_twin")
        assert [c for c in clips if c.kind == "rating"] == []
        out[name] = league
        out[f"{name}_twin"] = root / f"{name}_twin"
        out[f"{name}_cut"] = {c.player_id for c in clips if c.kind == "potential"}
    out["players"] = {
        key: support.load_player_objects(out[key])
        for key in (
            "plain", "plain_twin", "floored", "floored_twin", "nogap", "nogap_twin"
        )
    }
    return out


def _flatten_potentials(path) -> None:
    """Every potential set to its current rating: no upside anywhere."""

    fields, rows = support.read_player_rows(path)
    for row in rows:
        for key in fields:
            if key.startswith("pot_") and key[4:] in row:
                row[key] = row[key[4:]]
    support.write_player_rows(path, fields, rows)


def _pairs(leagues, name="plain"):
    """(player on scale 1, the same player on scale 2), every player."""

    original = leagues["players"][name]
    twin = leagues["players"][f"{name}_twin"]
    assert list(original) == list(twin) and len(original) > 1400
    assert {p.rating_scale for p in twin.values()} == {2}
    assert {p.rating_scale for p in original.values()} == {1}
    return [(original[pid], twin[pid]) for pid in original]


def _same(leagues, score, name="plain", skip=(), distinct=10):
    """Assert ``score(player)`` is equal for every player and his twin;
    returns how many distinct values were seen, which must exceed
    ``distinct`` (a guard against a scorer that returns one constant)."""

    seen = set()
    for player, twin in _pairs(leagues, name):
        if player.player_id in skip:
            continue
        a, b = score(player), score(twin)
        assert a == b, (player.player_id, a, b)
        seen.add(repr(a))
    assert len(seen) > distinct, "the scorer did not tell players apart"
    return len(seen)


def _is_pitcher(player) -> bool:
    return bool(getattr(player, "is_pitcher", False))


# --- overall rating --------------------------------------------------------

def test_overall_rating_is_unchanged(leagues):
    from api.routers._rating_presentation import compute_overall
    from services.player_profile_view_model import _estimate_overall_rating
    from utils.player_overall import player_overall_score
    from utils.rating_display import overall_rating

    _same(leagues, player_overall_score)
    _same(leagues, overall_rating)
    _same(
        leagues,
        lambda p: compute_overall(
            lambda key: getattr(p, key, None),
            is_pitcher=_is_pitcher(p),
            position=p.primary_position,
        )["overall_raw"],
    )
    _same(leagues, lambda p: _estimate_overall_rating(p, is_pitcher=_is_pitcher(p)))


def test_overall_rating_from_raw_rows_is_unchanged(leagues):
    """The list views and the league distribution score CSV rows, with
    ``row.get`` as the reader; the row carries its own scale."""

    from utils.player_overall import hitter_overall_score, pitcher_overall_score
    from utils.pitcher_role import get_role
    from utils.rating_scale import is_pitcher_flag

    _f, plain = support.read_player_rows(leagues["plain"] / "players.csv")
    _f, twin = support.read_player_rows(leagues["plain_twin"] / "players.csv")
    scores = set()
    for row, twin_row in zip(plain, twin):
        if is_pitcher_flag(row["is_pitcher"]):
            a = pitcher_overall_score(row.get, get_role(row))
            b = pitcher_overall_score(twin_row.get, get_role(twin_row))
        else:
            a = hitter_overall_score(row.get, row["primary_position"])
            b = hitter_overall_score(twin_row.get, twin_row["primary_position"])
        assert a == b, row["player_id"]
        scores.add(a)
    assert len(scores) > 500


def test_the_overall_moves_if_the_stored_values_are_read_raw(leagues):
    """The control: without the engine view a stretched row scores
    differently, so the tests above are not comparing constants."""

    from utils.player_overall import _hitter_score

    moved = 0
    for player, twin in _pairs(leagues):
        if _is_pitcher(player):
            continue
        raw = _hitter_score(lambda key: getattr(twin, key, None), twin.primary_position)
        true = _hitter_score(lambda key: getattr(player, key, None), player.primary_position)
        moved += raw != true
    assert moved > 500


# --- money -----------------------------------------------------------------

def test_market_value_and_contract_asks_are_unchanged(leagues):
    from services import contract_negotiator as negotiator
    from services import contracts_service as contracts

    assert _same(leagues, contracts._player_quality_score) > 200
    assert _same(leagues, contracts.estimate_market_value_for_player) > 200
    _same(leagues, negotiator._talent_score)
    _same(leagues, negotiator._market_value)
    for days in (0, 400, 1100):
        _same(
            leagues,
            lambda p: negotiator.fair_market_salary(p, service_time_days=days),
            distinct=0,  # pre-arbitration service pays everyone the minimum
        )
        _same(
            leagues,
            lambda p: negotiator.fair_market_years(p, service_time_days=days),
            distinct=1,
        )
    # The total the league would pay is the same number of dollars.
    total = lambda players: sum(  # noqa: E731
        contracts.estimate_market_value_for_player(p) for p in players.values()
    )
    assert total(leagues["players"]["plain"]) == total(leagues["players"]["plain_twin"])


def test_talent_scores_behind_bids_arbitration_and_the_gm_queue(leagues):
    from services import finance_ai, free_agency, gm_finance_queue
    from services import offseason_finance_flow as offseason

    _same(leagues, finance_ai._free_agent_quality_score)
    for profile in PROFILES[1:]:
        _same(
            leagues,
            lambda p: finance_ai._strategy_fit_score(p, raw_strategy_profile=profile),
        )
    _same(leagues, gm_finance_queue._player_talent_score)
    _same(leagues, lambda p: offseason._player_talent_score(p, is_pitcher=_is_pitcher(p)))
    _same(leagues, free_agency._quality_score)


def test_promotion_retirement_and_callup_scores(leagues):
    from services import inseason_callups, player_retirement, prospect_promotion

    _same(leagues, player_retirement._player_overall)
    _same(leagues, prospect_promotion._player_overall)
    _same(leagues, inseason_callups._score)
    # The bars themselves pick the same players.
    bars = (
        prospect_promotion.LOW_TO_AAA_OVR,
        prospect_promotion.AAA_TO_ACT_OVR,
        prospect_promotion.AAA_TO_ACT_BLUECHIP_OVR,
    )
    for bar in bars:
        over = lambda players: {  # noqa: E731
            pid
            for pid, p in players.items()
            if prospect_promotion._player_overall(p) >= bar
        }
        assert over(leagues["players"]["plain"]) == over(leagues["players"]["plain_twin"])


# --- trades ----------------------------------------------------------------

def test_trade_value_pieces_are_unchanged(leagues):
    from services import cpu_trade_evaluator as evaluator
    from services import cpu_trade_proposals as proposals

    _same(leagues, proposals._player_trade_value)
    fit = {"needs": {"SS", "P"}, "surplus": {"1B"}, "pos_counts": {}, "pitchers": 11}
    for profile in PROFILES:
        _same(
            leagues,
            lambda p: evaluator._fit_value(p, roster_fit=fit, strategy_profile=profile),
            distinct=3,
        )
    # Current value and timeline read potentials. With the potential read
    # the scale 1 way (_scale_1_potentials) they are identical on the
    # floored league, skipping only the gaps cut at 99 ...
    cut = leagues["floored_cut"]
    assert 0 < len(cut) < 100
    with _scale_1_potentials():
        _same(leagues, evaluator._player_current_value, "floored", skip=cut)
        for window in ("contend", "rebuild", "balanced"):
            _same(
                leagues,
                lambda p: evaluator._timeline_value(
                    p, window=window, strategy_profile="balanced"
                ),
                "floored",
                skip=cut,
            )
    # ... and with no potential gap at all they are identical as they are.
    assert leagues["nogap_cut"] == set()
    _same(leagues, evaluator._player_current_value, "nogap")


@contextlib.contextmanager
def _scale_1_potentials():
    """The trade evaluator reading a scale 2 potential as scale 1 did: the
    engine rating plus the WHOLE stored gap, and a hitter's ``pot_*`` of 0
    as his potential. The two deliberate scale 2 changes
    (``POTENTIAL_GAP_DISCOUNT``, a scale 2 hitter's potential read) are
    the only difference from the shipped evaluator."""

    from services import cpu_trade_evaluator as evaluator
    from utils import rating_scale as rs

    def whole_gap(player, key, stored_potential):
        if rs.rating_scale_of(player) == rs.LEGACY_RATING_SCALE:
            return stored_potential
        potential = rs._set_number(stored_potential)
        stored = rs._set_number(rs._raw(player, key, None))
        if potential is None or stored is None:
            return stored_potential
        spec = rs.rating_map(key, rs.rating_scale_of(player), pitcher=rs.player_is_pitcher(player))
        if spec is None:
            return stored_potential
        return rs._tidy(spec.engine(stored) + (potential - stored))

    saved = (evaluator.engine_potential_value, evaluator.rating_scale_of)
    evaluator.engine_potential_value = whole_gap
    evaluator.rating_scale_of = lambda player: rs.LEGACY_RATING_SCALE
    try:
        yield
    finally:
        evaluator.engine_potential_value, evaluator.rating_scale_of = saved


def test_scale_2_upside_is_what_development_can_deliver(leagues):
    """On scale 2 a CPU club sees the part of a gap development closes
    (``engine_potential``): a pitcher's upside is never larger than on scale
    1, and a hitter's (which scale 1 never reaches: ``pot_*`` reads 0) is
    seen."""

    from services import cpu_trade_evaluator as evaluator

    def upside(p):
        return evaluator._overall_score(p, potential=True) - evaluator._overall_score(
            p, potential=False
        )

    players, twins = leagues["players"]["floored"], leagues["players"]["floored_twin"]
    pitchers_lower = hitters_seen = 0
    for pid, player in players.items():
        a, b = upside(player), upside(twins[pid])
        assert b >= -1e-9
        if _is_pitcher(player):
            assert b <= a + 1e-9, pid
            pitchers_lower += b < a
        else:
            assert a == 0
            hitters_seen += b > 0
    assert pitchers_lower > 100 and hitters_seen > 20


def _roster(league, team_id) -> Roster:
    levels = {"ACT": [], "AAA": [], "LOW": []}
    with (league / "rosters" / f"{team_id}.csv").open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) >= 2 and row[1].strip().upper() in levels:
                levels[row[1].strip().upper()].append(row[0].strip())
    return Roster(team_id=team_id, act=levels["ACT"], aaa=levels["AAA"], low=levels["LOW"])


def _team_ids(league):
    with (league / "teams.csv").open(newline="", encoding="utf-8") as fh:
        return [row["team_id"] for row in csv.DictReader(fh)]


def _trade_decisions(leagues, name, monkeypatch):
    """Every CPU decision of a fixed set of offers (8 offers to each of 6
    clubs, 3 strategy profiles: 144) on league ``name`` and its twin."""

    from services import cpu_trade_evaluator as evaluator

    monkeypatch.setattr(evaluator, "is_cpu_owned_team", lambda *a, **k: True)
    teams = _team_ids(leagues[name])[:6]
    rosters = {team: _roster(leagues[name], team) for team in teams}
    cut = leagues[f"{name}_cut"]

    def offers():
        made = 0
        for i, cpu in enumerate(teams):
            other = teams[(i + 1) % len(teams)]
            theirs = [p for p in rosters[other].act if p not in cut]
            ours = [p for p in rosters[cpu].act if p not in cut]
            for k in range(0, 24, 3):
                made += 1
                yield Trade(
                    trade_id=f"T{made:03d}",
                    from_team=other,
                    to_team=cpu,
                    give_player_ids=[theirs[k], theirs[k + 1]][: 1 + k % 2],
                    receive_player_ids=[ours[-1 - k]],
                )

    def decide(league, trade, profile):
        result = evaluator.evaluate_cpu_trade_offer(
            trade,
            players_by_id=leagues["players"][league],
            data_dir=leagues[league],
            rosters_by_team=rosters,
            win_pct_by_team={team: 0.5 for team in teams},
            strategy_profile=profile,
            current_year=2026,
        )
        return dataclasses.asdict(result)

    out = []
    for trade in offers():
        for profile in ("balanced", "win_now", "development_focus"):
            out.append((
                trade.trade_id,
                profile,
                decide(name, trade, profile),
                decide(f"{name}_twin", trade, profile),
            ))
    return out


def test_cpu_trade_decisions_are_identical(leagues, monkeypatch):
    """The scale itself changes no CPU trade decision: on the floored league
    every decision is identical once potentials are read the scale 1 way,
    and on the nogap league (no upside to read) as it is."""

    with _scale_1_potentials():
        decisions = _trade_decisions(leagues, "floored", monkeypatch)
    assert len(decisions) == 144
    for trade_id, profile, a, b in decisions:
        assert a == b, (trade_id, profile)
    assert len({a["action"] for _, _, a, _ in decisions}) >= 2
    for trade_id, profile, a, b in _trade_decisions(leagues, "nogap", monkeypatch):
        assert a == b, (trade_id, profile)


def test_cpu_trade_decisions_that_change_on_scale_2(leagues, monkeypatch):
    """Pinned: what converting a league to scale 2 changes in CPU trades.

    Two deliberate changes, both in what a player's upside is worth:
    the potential view leaves out the 20.5 engine points of every gap that
    development never closes (``POTENTIAL_GAP_DISCOUNT``), so young players'
    and especially 25-31-year-olds' upside drops; and a hitter's potential
    is read on scale 2 (scale 1 never sees it, a ``pot_*`` of 0 shadows
    it). On the floored league fixture, of 144 evaluations 105 change
    score and 9 change outcome, every one accept -> counter (the CPU gives
    less for the incoming players' upside). Nothing else differs:
    ``test_cpu_trade_decisions_are_identical``.
    """

    decisions = _trade_decisions(leagues, "floored", monkeypatch)
    changed = [(t, p, a, b) for t, p, a, b in decisions if a != b]
    outcomes = collections.Counter(
        (a["action"], b["action"]) for _, _, a, b in changed if a["action"] != b["action"]
    )
    assert len(decisions) == 144
    assert len(changed) == 105
    assert dict(outcomes) == {("accept", "counter"): 9}
    # Only the score moves: the same offer, the same parts.
    for _, _, a, b in changed:
        assert a["details"]["incoming_players"] == b["details"]["incoming_players"]


# --- rosters and lineups ---------------------------------------------------

def test_auto_assign_scoring_is_unchanged(leagues):
    from services import roster_auto_assign as assign

    _same(leagues, assign._overall_score)
    for profile in PROFILES[1:]:
        for prospect_mode in (False, True):
            _same(
                leagues,
                lambda p: assign._strategy_assignment_bonus(
                    p, strategy_profile=profile, age=24, prospect_mode=prospect_mode
                ),
            )
    pitchers = {p.player_id for p, _ in _pairs(leagues) if not _is_pitcher(p)}
    _same(leagues, assign._pitcher_score, skip=pitchers)


def test_auto_assign_gives_the_same_rosters(leagues, monkeypatch, tmp_path):
    import shutil

    from services import roster_auto_assign as assign

    # Its own copies: a real run may rewrite staff and lineup files.
    own = {}
    for name in ("plain", "plain_twin"):
        own[name] = tmp_path / name
        shutil.copytree(leagues[name], own[name])
    saved = {}
    current = {}
    monkeypatch.setattr(assign, "load_roster", lambda *a, **k: copy.deepcopy(current["r"]))
    monkeypatch.setattr(assign, "save_roster", lambda tid, r, **k: saved.update(r=r))
    monkeypatch.setattr("services.transaction_log.record_transaction", lambda **k: None)
    monkeypatch.setattr(
        "services.contracts_service.release_contracts_to_free_agency", lambda ids: None
    )

    def run(name, team, profile):
        monkeypatch.setattr(
            assign, "_resolve_strategy_profile_token", lambda *a, **k: profile
        )
        saved.clear()
        roster = _roster(own[name], team)
        # Start from one pile so the whole organisation is re-sorted, not
        # just confirmed where it already stands.
        everyone = sorted(roster.act + roster.aaa + roster.low)
        current["r"] = Roster(team_id=team, act=[], aaa=everyone, low=[])
        result = assign.auto_assign_team(
            team,
            players_by_id=leagues["players"][name],
            roster_dir=str(own[name] / "rosters"),
            age_cache={},
            as_of_date=AS_OF,
        )
        final = saved.get("r")
        levels = None
        if final is not None:
            levels = (list(final.act), list(final.aaa), list(final.low))
        return result, levels

    moved = 0
    for team in _team_ids(leagues["plain"])[:8]:
        for profile in PROFILES:
            a = run("plain", team, profile)
            b = run("plain_twin", team, profile)
            assert a == b, (team, profile)
            moved += a[1] is not None and bool(a[1][0])
    assert moved >= 30  # active rosters really were picked


def test_lineup_scores_are_unchanged(leagues):
    from physics_sim.config import load_tuning
    from utils import lineup_autofill as autofill
    from utils.position_fit import fielding_fit

    tuning = load_tuning({})
    hitters_only = {p.player_id for p, _ in _pairs(leagues) if _is_pitcher(p)}
    for hand in ("L", "R"):
        for profile in PROFILES:
            _same(
                leagues,
                lambda p: autofill.lineup_hitter_score(
                    p, vs_hand=hand, profile=profile, tuning=tuning
                ),
                skip=hitters_only,
            )
        _same(
            leagues,
            lambda p: tuple(
                sorted(autofill._slot_components(p, vs_hand=hand, tuning=tuning).items())
            ),
            skip=hitters_only,
        )
    for position in ("C", "SS", "1B", "CF"):
        _same(leagues, lambda p: fielding_fit(p, position), skip=hitters_only)


def test_auto_filled_lineups_are_identical(leagues):
    from physics_sim.config import load_tuning
    from utils.lineup_autofill import auto_fill_lineup_for_team

    tuning = load_tuning({})

    def fill(name, team, profile, hand):
        league = leagues[name]
        try:
            return auto_fill_lineup_for_team(
                team,
                players_file=league / "players.csv",
                roster_dir=league / "rosters",
                lineup_dir=league / "lineups",
                strategy_profile=profile,
                vs=hand,
                persist=False,
                tuning=tuning,
            )
        except ValueError as exc:
            # A fixture club with eight active hitters cannot field nine;
            # that outcome has to be the same too.
            return str(exc)

    lineups = set()
    for team in _team_ids(leagues["plain"])[:12]:
        for profile in PROFILES:
            for hand in ("lhp", "rhp"):
                a = fill("plain", team, profile, hand)
                b = fill("plain_twin", team, profile, hand)
                assert a == b, (team, profile, hand)
                if not isinstance(a, str):
                    assert len(a) == 9
                    lineups.add(tuple(a))
    assert len(lineups) > 20


def test_the_weakest_players_pool_orders_the_same(leagues):
    """utils.roster_loader's replacement pool ranks hitters by Contact and
    pitchers by movement + fastball."""

    from utils.rating_scale import engine_rating

    def order(players):
        hitters = [p for p in players.values() if not _is_pitcher(p)]
        pitchers = [p for p in players.values() if _is_pitcher(p)]
        return (
            [p.player_id for p in sorted(hitters, key=lambda p: engine_rating(p, "ch", 50))],
            [
                p.player_id
                for p in sorted(
                    pitchers,
                    key=lambda p: engine_rating(p, "movement", 50) + getattr(p, "fb", 50),
                    reverse=True,
                )
            ],
        )

    assert order(leagues["players"]["plain"]) == order(leagues["players"]["plain_twin"])


# --- the draft -------------------------------------------------------------

@pytest.fixture(scope="module")
def pools():
    from playbalance import player_generator
    from playbalance.draft_pool import generate_draft_pool
    from utils.rating_scale import stretch_row

    def pool(scale):
        # The generator remembers the names it has handed out, which moves
        # its random stream; a fresh league starts from a clean slate.
        player_generator.reset_name_cache()
        return [
            dataclasses.asdict(p)
            for p in generate_draft_pool(
                2031, size=240, seed=20261013, rating_scale=scale
            )
        ]

    # A scale 2 class marks Eye down less (a deliberate generator change,
    # tests/test_generated_player_dates.py); switched off here so the two
    # classes differ by the scale alone.
    saved = player_generator.SCALE2_DRAFT_EYE_MARKDOWN
    player_generator.SCALE2_DRAFT_EYE_MARKDOWN = None
    try:
        plain, full = pool(1), pool(2)
    finally:
        player_generator.SCALE2_DRAFT_EYE_MARKDOWN = saved
    # Prospects scale 2 cannot store exactly: a draft-age rating marked down
    # below the scale's floor (Eye under 33.67, say) is clipped to 1, and a
    # potential gap is cut at 99. Both are reported by the generator; here
    # they are set aside and counted.
    clipped, cut = set(), set()
    for prospect in plain:
        _row, clips = stretch_row(prospect, 2)
        for clip in clips:
            (clipped if clip.kind == "rating" else cut).add(prospect["player_id"])
    return plain, full, clipped, cut


def test_the_draft_board_ranks_the_same(pools):
    from api.routers import draft as draft_router
    from services.draft_ai import score_prospect

    plain, full, clipped, cut = pools
    assert {p["rating_scale"] for p in full} == {2}
    assert [p["player_id"] for p in plain] == [p["player_id"] for p in full]
    assert sum(a["ch"] != b["ch"] for a, b in zip(plain, full)) > 60
    # A few low-tail prospects do not fit the scale (see ``pools``).
    assert len(clipped) <= 0.05 * len(plain)
    plain = [p for p in plain if p["player_id"] not in clipped]
    full = [p for p in full if p["player_id"] not in clipped]
    needs = {"C": 0.5, "SS": 1.0, "CF": 0.25, "SP": 0.75, "RP": 0.1}

    # Best available: the auto-pick order.
    assert [draft_router._prospect_overall(p) for p in plain] == [
        draft_router._prospect_overall(p) for p in full
    ]
    board = lambda pool: [  # noqa: E731
        p["player_id"]
        for p in sorted(pool, key=draft_router._prospect_overall, reverse=True)
    ]
    assert board(plain) == board(full)

    # The CPU's need-aware score, every strategy profile.
    for profile in PROFILES:
        a = [score_prospect(p, needs, strategy_profile=profile) for p in plain]
        b = [score_prospect(p, needs, strategy_profile=profile) for p in full]
        if profile == "development_focus":
            # The one profile that reads potentials: equal, wherever the gap
            # was not cut at 99, to scale 1 with each potential worth what
            # development closes of it (engine_potential).
            a = [
                score_prospect(_closable(p), needs, strategy_profile=profile)
                for p in plain
            ]
            keep = [i for i, p in enumerate(plain) if p["player_id"] not in cut]
            assert len(keep) > 150
            assert [a[i] for i in keep] == [b[i] for i in keep]
        else:
            assert a == b, profile
        assert len(set(a)) > 50


def _closable(prospect):
    """A scale 1 prospect with every potential cut to what the development
    model closes of its gap (the scale 2 consumer view)."""

    from utils.rating_scale import POTENTIAL_GAP_DISCOUNT

    out = dict(prospect)
    for key, value in prospect.items():
        if not key.startswith("pot_") or key[4:] not in prospect:
            continue
        current = prospect[key[4:]]
        if isinstance(value, (int, float)) and value > 0 and current:
            out[key] = current + max(0, value - current - POTENTIAL_GAP_DISCOUNT)
    return out
