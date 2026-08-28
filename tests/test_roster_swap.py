"""Roster swap validation: a swap exchanges two players' levels atomically, so a
promote into a FULL level is allowed (net headcount unchanged) — while caps, the
LOW age gate, and ACT composition are still enforced on the final state."""

from services.roster_validation import validate_roster_move, validate_roster_swap


def _pp(pos, age=25):
    return {"primary_position": pos, "other_positions": "", "is_pitcher": False, "age": age}


def _pitcher(age=25):
    return {"primary_position": "P", "other_positions": "", "is_pitcher": True, "age": age}


def _build():
    """A legal, full (25-man) ACT: 8 starters covering every position, 3 bench
    position players, 14 pitchers. Plus a full-ish AAA."""
    players = {}
    levels = {"act": [], "aaa": [], "low": [], "dl": [], "ir": []}
    for pos in ("C", "1B", "2B", "3B", "SS", "LF", "CF", "RF"):
        pid = f"ACT_{pos}"
        players[pid] = _pp(pos)
        levels["act"].append(pid)
    for i in range(3):
        pid = f"ACT_B{i}"
        players[pid] = _pp("1B")
        levels["act"].append(pid)
    for i in range(14):
        pid = f"ACT_P{i}"
        players[pid] = _pitcher()
        levels["act"].append(pid)
    assert len(levels["act"]) == 25  # full
    return players, levels


def test_move_into_full_level_allowed_as_warning():
    # An owner must be able to promote into a full ACT (going 26/25) intending to
    # demote someone next. That's now allowed (ok) with a WARNING, not blocked.
    players, levels = _build()
    players["AAA_POS"] = _pp("1B")
    levels["aaa"].append("AAA_POS")
    mv = validate_roster_move(
        current_levels=levels, player_id="AAA_POS", target_level="act", players=players
    )
    assert mv.ok, mv.errors
    assert any("cap" in w.lower() for w in mv.warnings)


def test_move_between_aaa_low_not_blocked_by_act_state():
    # A move that doesn't touch ACT (AAA<->LOW) must succeed even if ACT is
    # temporarily broken/empty — the sim gate enforces ACT legality, not a move.
    players = {"LOWP": _pp("1B", age=20)}
    levels = {"act": [], "aaa": [f"A{i}" for i in range(15)], "low": ["LOWP"], "dl": [], "ir": []}
    for i in range(15):
        players[f"A{i}"] = _pp("1B", age=22)
    mv = validate_roster_move(
        current_levels=levels, player_id="LOWP", target_level="aaa", players=players
    )
    assert mv.ok, mv.errors
    assert any("cap" in w.lower() for w in mv.warnings)


def test_move_to_low_still_blocks_over_age():
    # The LOW age gate is a real structural rule and stays a hard error.
    players = {"OLD": _pp("1B", age=30)}
    levels = {"act": [], "aaa": ["OLD"], "low": [], "dl": [], "ir": []}
    mv = validate_roster_move(
        current_levels=levels, player_id="OLD", target_level="low", players=players
    )
    assert not mv.ok


def test_swap_allows_promote_into_full_act():
    # The atomic swap endpoint also handles it (net headcount unchanged).
    players, levels = _build()
    players["AAA_POS"] = _pp("1B")
    levels["aaa"].append("AAA_POS")
    sw = validate_roster_swap(
        current_levels=levels, player_a_id="AAA_POS", player_b_id="ACT_P0", players=players
    )
    assert sw.ok, sw.errors


def test_swap_blocks_low_age_gate():
    players, levels = _build()
    players["ACT_B0"]["age"] = 30
    players["LOW_Y"] = _pp("1B", age=20)
    levels["low"].append("LOW_Y")
    # Swapping the 30-y/o down to LOW is illegal (age gate).
    sw = validate_roster_swap(
        current_levels=levels, player_a_id="ACT_B0", player_b_id="LOW_Y", players=players
    )
    assert not sw.ok


def test_swap_same_level_errors():
    players, levels = _build()
    sw = validate_roster_swap(
        current_levels=levels, player_a_id="ACT_C", player_b_id="ACT_1B", players=players
    )
    assert not sw.ok


def test_swap_blocks_broken_position_coverage():
    players, levels = _build()
    players["AAA_PIT"] = _pitcher()
    levels["aaa"].append("AAA_PIT")
    # Swapping the only catcher down for a pitcher leaves ACT without a C.
    sw = validate_roster_swap(
        current_levels=levels, player_a_id="ACT_C", player_b_id="AAA_PIT", players=players
    )
    assert not sw.ok


def test_swap_unknown_player_errors():
    players, levels = _build()
    sw = validate_roster_swap(
        current_levels=levels, player_a_id="ACT_C", player_b_id="NOPE", players=players
    )
    assert not sw.ok
