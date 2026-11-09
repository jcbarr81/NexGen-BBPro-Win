"""8.15.2 (owner rule): a CF covers LF and RF, an RF covers LF.

alpha-test's AUS could not reach Opening Day: nobody in the organization
listed LF, so the roster check said "missing coverage at LF" and auto-assign
had no one to call up, although the active roster carried a CF and an RF.
The rule applies wherever coverage is decided; the engine's fielding
(the out-of-position table) is not touched.
"""

from __future__ import annotations

from types import SimpleNamespace

from utils.position_coverage import implied_positions, with_implied


def _hitter(pid, primary, others=()):
    return SimpleNamespace(
        player_id=pid, primary_position=primary, other_positions=list(others),
        is_pitcher=False, role="", injured=False,
    )


def _row(pid, primary, others=""):
    return {
        "player_id": pid, "primary_position": primary, "other_positions": others,
        "is_pitcher": "0", "role": "", "first_name": pid, "last_name": "",
    }


# The AUS active hitters of 2026-11-09: no LF anywhere, one CF and one RF.
AUS_ACT = [
    ("C1", "C"), ("C2", "C"), ("SS1", "SS"), ("2B1", "2B"), ("2B2", "2B"),
    ("3B1", "3B"), ("1B1", "1B"), ("CF1", "CF"), ("RF1", "RF"),
]


def test_the_rule():
    assert with_implied(["CF"]) == {"CF", "LF", "RF"}
    assert with_implied(["RF"]) == {"RF", "LF"}
    assert with_implied(["LF"]) == {"LF"}
    assert with_implied(["SS", "2B"]) == {"SS", "2B"}
    assert implied_positions(["RF", "CF"]) == ["LF"]
    assert implied_positions(["LF", "CF"]) == ["RF"]


def test_roster_gate_counts_a_cf_and_an_rf_for_left_field():
    from services.roster_validation import active_roster_shape

    players = {pid: _row(pid, pos) for pid, pos in AUS_ACT}
    assert active_roster_shape(list(players), players)["missing_positions"] == []

    # A left fielder alone does not cover center or right.
    players = {pid: _row(pid, pos) for pid, pos in AUS_ACT if pos not in ("CF", "RF")}
    players["LF1"] = _row("LF1", "LF")
    assert active_roster_shape(list(players), players)["missing_positions"] == ["CF", "RF"]

    # An RF covers left, not center.
    players = {pid: _row(pid, pos) for pid, pos in AUS_ACT if pos != "CF"}
    assert active_roster_shape(list(players), players)["missing_positions"] == ["CF"]


def test_command_center_missing_positions_agree():
    from models.roster import Roster
    from utils.roster_validation import missing_positions

    players = {pid: _hitter(pid, pos) for pid, pos in AUS_ACT}
    roster = Roster(team_id="AUS", act=list(players))
    assert missing_positions(roster, players) == []


def test_lineup_does_not_warn_a_cf_in_left_but_still_warns_the_reverse():
    from services.roster_validation import validate_lineup

    players = {pid: _row(pid, pos) for pid, pos in AUS_ACT}
    players["LF9"] = _row("LF9", "LF")
    rows = [
        {"player_id": "C1", "position": "C"}, {"player_id": "1B1", "position": "1B"},
        {"player_id": "2B1", "position": "2B"}, {"player_id": "3B1", "position": "3B"},
        {"player_id": "SS1", "position": "SS"}, {"player_id": "CF1", "position": "LF"},
        {"player_id": "LF9", "position": "CF"}, {"player_id": "RF1", "position": "RF"},
        {"player_id": "C2", "position": "DH"},
    ]
    res = validate_lineup(lineup_rows=rows, players=players, vs="rhp")
    text = " ".join(res.warnings)
    assert "is not listed at LF" not in text
    assert "is not listed at CF" in text


def test_auto_assign_and_roster_fill_see_the_corners():
    from services.roster_auto_assign import _eligible_positions
    from services.roster_fill import can_play, covers_of, positions_of

    cf = _hitter("CF1", "CF")
    assert _eligible_positions(cf) == {"CF", "LF", "RF"}
    # A full rebuild still looks for a listed LF.
    assert _eligible_positions(cf, implied=False) == {"CF"}
    assert can_play(cf, "LF") and can_play(cf, "RF")
    assert covers_of(_hitter("X", "RF", ["1B"])) == ["RF", "1B", "LF"]
    # positions_of stays what the player lists.
    assert positions_of(_hitter("X", "RF", ["1B"])) == ["RF", "1B"]
    assert not can_play(_hitter("L", "LF"), "CF")
    assert not can_play(_hitter("R", "RF"), "CF")


def test_gaps_assignment_leaves_the_aus_roster_alone():
    """Before 8.15.2 step 3a looked for an LF to call up and found none; now
    the roster is already covered and nothing moves for coverage."""

    from models.roster import Roster
    from services.roster_auto_assign import _gaps_assignment

    from services.roster_auto_assign import MIN_POSITION_PLAYERS_ACT

    # Enough infielders that the position-player minimum moves nobody either.
    act_rows = list(AUS_ACT) + [
        (f"IF{i}", "2B") for i in range(MIN_POSITION_PLAYERS_ACT - len(AUS_ACT))
    ]
    players = {pid: _hitter(pid, pos) for pid, pos in act_rows}
    players["CF2"] = _hitter("CF2", "CF")
    roster = Roster(team_id="AUS", act=[pid for pid, _ in act_rows], aaa=["CF2"])
    act, aaa, low, dl, overflow = _gaps_assignment(roster, players)
    assert sorted(act) == sorted(pid for pid, _ in act_rows)
    assert aaa == ["CF2"]
