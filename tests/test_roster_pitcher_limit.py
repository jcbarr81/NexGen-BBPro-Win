"""The active pitcher limit in the shared roster validators (decision 8).

At most 13 active pitchers (14 from Sept 1 in the regular season). A single
move or a trade that makes a 14th only WARNS, so an owner can call a pitcher
up and option another next; the swap check and the sim gate
(``validate_roster_state``) treat it as an ERROR. Injured-but-active pitchers
count; there is no two-way exemption.
"""

from services.roster_validation import (
    DEFAULT_LEVEL_CAPS,
    DEFAULT_PITCHER_CAP,
    validate_roster_move,
    validate_roster_state,
    validate_roster_swap,
    validate_trade,
)
from utils.roster_rules import (
    ACT_HITTER_TARGET,
    ACTIVE_ROSTER_SIZE,
    MAX_ACTIVE_PITCHERS,
    SEPTEMBER_MAX_ACTIVE_PITCHERS,
    SEPTEMBER_ROSTER_SIZE,
)

SEPT_CAPS = {**DEFAULT_LEVEL_CAPS, "act": SEPTEMBER_ROSTER_SIZE}
POSITIONS = ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")


def _pp(pos, age=25):
    return {"primary_position": pos, "other_positions": "", "is_pitcher": False, "age": age}


def _pitcher(age=25, **over):
    row = {"primary_position": "P", "other_positions": "", "is_pitcher": True, "age": age}
    row.update(over)
    return row


def _team(hitters=ACT_HITTER_TARGET, pitchers=MAX_ACTIVE_PITCHERS, prefix="ACT"):
    """An active roster with every position covered: ``hitters`` position
    players and ``pitchers`` pitchers."""
    players = {}
    levels = {"act": [], "aaa": [], "low": [], "dl": [], "ir": []}
    for i in range(hitters):
        pid = f"{prefix}_H{i}"
        players[pid] = _pp(POSITIONS[i] if i < len(POSITIONS) else "1B")
        levels["act"].append(pid)
    for i in range(pitchers):
        pid = f"{prefix}_P{i}"
        players[pid] = _pitcher()
        levels["act"].append(pid)
    return players, levels


def _pitcher_msgs(messages):
    return [m for m in messages if "pitchers" in m]


def test_defaults_are_the_rules():
    assert DEFAULT_PITCHER_CAP == MAX_ACTIVE_PITCHERS
    assert DEFAULT_LEVEL_CAPS["act"] == ACTIVE_ROSTER_SIZE


# --- the sim gate -----------------------------------------------------------


def test_state_passes_at_the_limit():
    players, levels = _team()
    assert len(levels["act"]) == ACTIVE_ROSTER_SIZE
    res = validate_roster_state(current_levels=levels, players=players)
    assert res.ok, res.errors


def test_state_errors_one_pitcher_over():
    players, levels = _team(hitters=ACT_HITTER_TARGET - 1, pitchers=MAX_ACTIVE_PITCHERS + 1)
    assert len(levels["act"]) == ACTIVE_ROSTER_SIZE  # size is fine; the arms aren't
    res = validate_roster_state(current_levels=levels, players=players)
    assert not res.ok
    msgs = _pitcher_msgs(res.errors)
    assert msgs == [
        f"Active roster carries {MAX_ACTIVE_PITCHERS + 1} pitchers "
        f"(maximum {MAX_ACTIVE_PITCHERS})."
    ]


def test_state_in_september_allows_one_more_arm():
    players, levels = _team(pitchers=SEPTEMBER_MAX_ACTIVE_PITCHERS)
    assert len(levels["act"]) <= SEPTEMBER_ROSTER_SIZE
    res = validate_roster_state(
        current_levels=levels,
        players=players,
        level_caps=SEPT_CAPS,
        pitcher_cap=SEPTEMBER_MAX_ACTIVE_PITCHERS,
    )
    assert res.ok, res.errors

    players, levels = _team(pitchers=SEPTEMBER_MAX_ACTIVE_PITCHERS + 1)
    res = validate_roster_state(
        current_levels=levels,
        players=players,
        level_caps=SEPT_CAPS,
        pitcher_cap=SEPTEMBER_MAX_ACTIVE_PITCHERS,
    )
    assert not res.ok
    assert _pitcher_msgs(res.errors)
    assert f"maximum {SEPTEMBER_MAX_ACTIVE_PITCHERS}" in _pitcher_msgs(res.errors)[0]


def test_state_accepts_the_pitcher_cap_inside_level_caps():
    """The compliance payload's caps shape ({..., "act_pitchers"}) works as
    ``level_caps`` and is not mistaken for a roster level."""
    players, levels = _team(pitchers=SEPTEMBER_MAX_ACTIVE_PITCHERS)
    caps = {**SEPT_CAPS, "act_pitchers": SEPTEMBER_MAX_ACTIVE_PITCHERS}
    res = validate_roster_state(current_levels=levels, players=players, level_caps=caps)
    assert res.ok, res.errors


def test_injured_but_active_pitchers_count():
    players, levels = _team(hitters=ACT_HITTER_TARGET - 1, pitchers=MAX_ACTIVE_PITCHERS + 1)
    players["ACT_P0"]["injured"] = True  # day-to-day, still on the active roster
    res = validate_roster_state(current_levels=levels, players=players)
    assert _pitcher_msgs(res.errors)


def test_a_pitcher_without_the_flag_still_counts():
    """counts_as_pitcher: primary position SP with an empty is_pitcher flag."""
    players, levels = _team()
    players["ACT_SP"] = {"primary_position": "SP", "other_positions": "", "is_pitcher": ""}
    levels["act"].append("ACT_SP")
    res = validate_roster_state(current_levels=levels, players=players)
    assert _pitcher_msgs(res.errors)


def test_short_roster_is_legal():
    """No active-roster minimum: a 25-man roster stays legal."""
    players, levels = _team(hitters=ACT_HITTER_TARGET - 1)
    assert len(levels["act"]) == ACTIVE_ROSTER_SIZE - 1
    res = validate_roster_state(current_levels=levels, players=players)
    assert res.ok, res.errors


# --- a single move: warning only --------------------------------------------


def test_move_warns_but_never_errors_on_the_pitcher_limit():
    players, levels = _team(hitters=ACT_HITTER_TARGET - 1)
    players["AAA_P"] = _pitcher()
    levels["aaa"].append("AAA_P")
    res = validate_roster_move(
        current_levels=levels, player_id="AAA_P", target_level="act", players=players
    )
    assert res.ok, res.errors
    assert _pitcher_msgs(res.warnings) == [
        f"ACT would carry {MAX_ACTIVE_PITCHERS + 1} pitchers "
        f"(max {MAX_ACTIVE_PITCHERS}) — send a pitcher down before the next game."
    ]


def test_move_pitcher_warning_uses_the_september_cap():
    players, levels = _team()
    players["AAA_P"] = _pitcher()
    levels["aaa"].append("AAA_P")
    res = validate_roster_move(
        current_levels=levels,
        player_id="AAA_P",
        target_level="act",
        players=players,
        level_caps=SEPT_CAPS,
        pitcher_cap=SEPTEMBER_MAX_ACTIVE_PITCHERS,
    )
    assert res.ok and not res.warnings, res.warnings


def test_move_sending_a_pitcher_down_is_quiet():
    players, levels = _team(hitters=ACT_HITTER_TARGET - 1, pitchers=MAX_ACTIVE_PITCHERS + 1)
    res = validate_roster_move(
        current_levels=levels, player_id="ACT_P0", target_level="aaa", players=players
    )
    assert res.ok and not _pitcher_msgs(res.warnings), res.warnings


# --- a swap: error ------------------------------------------------------------


def test_swap_that_makes_a_fourteenth_pitcher_errors():
    players, levels = _team()
    players["AAA_P"] = _pitcher()
    levels["aaa"].append("AAA_P")
    res = validate_roster_swap(
        current_levels=levels, player_a_id="AAA_P", player_b_id="ACT_H8", players=players
    )
    assert not res.ok
    assert _pitcher_msgs(res.errors) == [
        f"Active roster would carry {MAX_ACTIVE_PITCHERS + 1} pitchers "
        f"(maximum {MAX_ACTIVE_PITCHERS})."
    ]


def test_swap_pitcher_for_pitcher_at_the_limit_passes():
    players, levels = _team()
    players["AAA_P"] = _pitcher()
    levels["aaa"].append("AAA_P")
    res = validate_roster_swap(
        current_levels=levels, player_a_id="AAA_P", player_b_id="ACT_P0", players=players
    )
    assert res.ok, res.errors


def test_swap_that_fixes_an_over_limit_staff_passes():
    players, levels = _team(hitters=ACT_HITTER_TARGET - 1, pitchers=MAX_ACTIVE_PITCHERS + 1)
    players["AAA_H"] = _pp("1B")
    levels["aaa"].append("AAA_H")
    res = validate_roster_swap(
        current_levels=levels, player_a_id="AAA_H", player_b_id="ACT_P0", players=players
    )
    assert res.ok, res.errors


def test_unrelated_swap_on_an_over_limit_staff_is_an_error():
    """Owner decision 8: the swap check errors on the final state, like the
    level caps. Hitter for hitter leaves 14 pitchers: blocked."""
    players, levels = _team(hitters=ACT_HITTER_TARGET - 1, pitchers=MAX_ACTIVE_PITCHERS + 1)
    players["AAA_H"] = _pp("1B")
    levels["aaa"].append("AAA_H")
    res = validate_roster_swap(
        current_levels=levels, player_a_id="AAA_H", player_b_id="ACT_H8", players=players
    )
    assert not res.ok
    assert _pitcher_msgs(res.errors)


def test_a_swap_that_lowers_an_over_limit_staff_only_warns():
    """A hitter up for a pitcher down moves toward a legal roster: allowed."""
    players, levels = _team(hitters=ACT_HITTER_TARGET - 2, pitchers=MAX_ACTIVE_PITCHERS + 2)
    players["AAA_H"] = _pp("1B")
    levels["aaa"].append("AAA_H")
    pitcher = next(pid for pid in levels["act"] if players[pid].get("is_pitcher"))
    res = validate_roster_swap(
        current_levels=levels, player_a_id="AAA_H", player_b_id=pitcher, players=players
    )
    assert not _pitcher_msgs(res.errors)
    assert _pitcher_msgs(res.warnings)


def test_september_swap_at_27_active_passes():
    """Regression: the swap endpoint used the flat 25-man caps, so every
    September swap on an expanded roster failed with "(27/25)"."""
    players, levels = _team(hitters=ACT_HITTER_TARGET + 1, pitchers=MAX_ACTIVE_PITCHERS)
    assert len(levels["act"]) == ACTIVE_ROSTER_SIZE + 1
    players["AAA_H"] = _pp("1B")
    levels["aaa"].append("AAA_H")
    res = validate_roster_swap(
        current_levels=levels,
        player_a_id="AAA_H",
        player_b_id="ACT_H9",
        players=players,
        level_caps=SEPT_CAPS,
        pitcher_cap=SEPTEMBER_MAX_ACTIVE_PITCHERS,
    )
    assert res.ok, res.errors
    # The base caps still reject it outside September.
    res = validate_roster_swap(
        current_levels=levels, player_a_id="AAA_H", player_b_id="ACT_H9", players=players
    )
    assert not res.ok


# --- a trade: warning only -----------------------------------------------------


def _trade_sides():
    mine_players, mine = _team(prefix="MINE")
    theirs_players, theirs = _team(prefix="THEM")
    players = {**mine_players, **theirs_players}
    return players, mine, theirs


def test_trade_pitcher_for_hitter_warns_on_the_fourteenth_arm():
    players, mine, theirs = _trade_sides()
    res = validate_trade(
        give_player_ids=["MINE_H8"],
        receive_player_ids=["THEM_P0"],
        from_team_levels=mine,
        to_team_levels=theirs,
        players=players,
    )
    assert res.ok, res.errors
    assert _pitcher_msgs(res.warnings) == [
        f"Your Team would carry {MAX_ACTIVE_PITCHERS + 1} active pitchers "
        f"(max {MAX_ACTIVE_PITCHERS}) after the trade — send a pitcher down "
        "before the next sim."
    ]


def test_trade_accepts_september_caps():
    players, mine, theirs = _trade_sides()
    res = validate_trade(
        give_player_ids=["MINE_H8"],
        receive_player_ids=["THEM_P0"],
        from_team_levels=mine,
        to_team_levels=theirs,
        players=players,
        level_caps=SEPT_CAPS,
        pitcher_cap=SEPTEMBER_MAX_ACTIVE_PITCHERS,
    )
    assert res.ok and not res.warnings, res.warnings


def test_trade_level_cap_uses_the_passed_caps():
    """Two-for-one onto a full roster: over 26 warns; with September's 28 it
    is quiet."""
    players, mine, theirs = _trade_sides()
    kwargs = dict(
        give_player_ids=["MINE_H8"],
        receive_player_ids=["THEM_H8", "THEM_H9"],
        from_team_levels=mine,
        to_team_levels=theirs,
        players=players,
    )
    res = validate_trade(**kwargs)
    assert res.ok
    assert any(f"({ACTIVE_ROSTER_SIZE + 1}/{ACTIVE_ROSTER_SIZE})" in w for w in res.warnings)
    res = validate_trade(**kwargs, level_caps=SEPT_CAPS, pitcher_cap=SEPTEMBER_MAX_ACTIVE_PITCHERS)
    assert res.ok and not res.warnings, res.warnings
