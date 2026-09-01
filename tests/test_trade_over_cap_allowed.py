"""A trade may leave a team over a roster cap — that's a WARNING, not a blocker.

Owners get their rosters compliant before the next sim; the season/sim gate
(validate_roster_state) still hard-errors on caps, so an over-limit roster can
never actually start a game. See the roster-editing philosophy (edit = warn,
sim = enforce).
"""

from services.roster_validation import DEFAULT_LEVEL_CAPS, validate_trade


def _levels(act):
    return {"act": list(act), "aaa": [], "low": []}


def test_over_cap_trade_is_allowed_with_warning():
    cap = DEFAULT_LEVEL_CAPS["act"]  # 25
    # From-team is full on ACT; it gives 1 and receives 2 -> 26 on ACT.
    from_levels = _levels([f"F{i}" for i in range(cap)])
    to_levels = _levels(["T1", "T2"])
    players = {pid: {} for pid in [f"F{i}" for i in range(cap)] + ["T1", "T2"]}

    result = validate_trade(
        give_player_ids=["F0"],
        receive_player_ids=["T1", "T2"],
        from_team_levels=from_levels,
        to_team_levels=to_levels,
        players=players,
    )

    # The trade is NOT blocked...
    assert result.ok is True
    assert not result.errors
    # ...but the owner is warned to get compliant.
    assert any("over the limit" in w for w in result.warnings)


def test_in_cap_trade_has_no_cap_warning():
    from_levels = _levels(["F0", "F1"])
    to_levels = _levels(["T1"])
    result = validate_trade(
        give_player_ids=["F0"],
        receive_player_ids=["T1"],
        from_team_levels=from_levels,
        to_team_levels=to_levels,
        players={"F0": {}, "F1": {}, "T1": {}},
    )
    assert result.ok is True
    assert not any("over the limit" in w for w in result.warnings)
