"""S2-06: pitcher `throws` loading + symmetric platoon adjustment."""
import pytest

from physics_sim.models import BatterRatings, PitcherRatings
from physics_sim.config import load_tuning
from physics_sim.engine import (
    _batter_context,
    _lineup_hand_from_starter,
    _platoon_bonus,
)


def _batter(bats: str = "R", vs_left: float = 50.0) -> BatterRatings:
    return BatterRatings.from_row(
        {
            "player_id": "b1",
            "bats": bats,
            "primary_position": "LF",
            "ch": "50",
            "ph": "50",
            "vl": str(vs_left),
            "eye": "50",
            "gf": "50",
            "pl": "50",
            "fa": "50",
            "arm": "50",
            "sp": "50",
        }
    )


def _pitcher(bats: str = "R", throws: str | None = "R") -> PitcherRatings:
    row = {"player_id": "p1", "bats": bats, "control": "50", "fb": "60"}
    if throws is not None:
        row["throws"] = throws
    return PitcherRatings.from_row(row)


# --- throws loading / fallback -------------------------------------------

def test_from_row_reads_throws():
    p = PitcherRatings.from_row({"player_id": "p", "bats": "L", "throws": "R", "fb": "60"})
    assert p.throws == "R"  # no bats proxying


def test_from_row_fallback_missing_column():
    p = PitcherRatings.from_row({"player_id": "p", "bats": "L", "fb": "60"})
    assert p.throws == "L"


def test_from_row_fallback_switch_bats():
    p = PitcherRatings.from_row({"player_id": "p", "bats": "S", "throws": "", "fb": "60"})
    assert p.throws == "R"


def test_from_row_rejects_garbage_token():
    p = PitcherRatings.from_row({"player_id": "p", "bats": "L", "throws": "X", "fb": "60"})
    assert p.throws == "L"


# --- symmetric platoon bonus ---------------------------------------------

def test_platoon_bonus_symmetric_r_batter():
    batter = _batter(bats="R", vs_left=80.0)
    vs_lhp = _platoon_bonus(batter, _pitcher(throws="L"))
    vs_rhp = _platoon_bonus(batter, _pitcher(throws="R"))
    assert vs_lhp == pytest.approx(2.0 * 1 + 0.2275 * 30.0)          # 8.825
    assert vs_rhp == pytest.approx(2.0 * -1 + 0.2275 * (-0.35 * 30.0))  # -4.38875
    assert vs_lhp > 0 > vs_rhp  # sign-flipped


def test_platoon_bonus_switch_hitter():
    batter = _batter(bats="S", vs_left=50.0)
    assert _platoon_bonus(batter, _pitcher(throws="L")) == pytest.approx(1.0)
    assert _platoon_bonus(batter, _pitcher(throws="R")) == pytest.approx(1.0)


def test_batter_context_shifts_both_hands():
    tuning = load_tuning()
    batter = _batter(bats="R", vs_left=90.0)
    base = batter.contact
    ctx_l = _batter_context(batter, _pitcher(throws="L"), tuning)
    ctx_r = _batter_context(batter, _pitcher(throws="R"), tuning)
    assert ctx_l["contact"] > base
    assert ctx_r["contact"] < base
    # batter_side / bats still derived from the batter, not the pitcher.
    assert ctx_l["bats"] == "R"
    assert ctx_r["bats"] == "R"


def test_lineup_hand_from_starter_uses_throws():
    starter = _pitcher(bats="R", throws="L")
    assert _lineup_hand_from_starter(starter) == "L"
