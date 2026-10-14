"""The rating scale map (``utils.rating_scale``): properties and constants.

Scale 2 stores each moved rating through a fixed piecewise-linear map with
integer slopes (``RATING_SCALE_DESIGN.md`` section 1). These tests pin the
table, the exact round trip that makes the scale change play-neutral, and
the rules for rows, potentials and the accessor.
"""

from __future__ import annotations

import pytest

from utils import rating_scale as rs
from utils.rating_scale import (
    FULL_RATING_SCALE,
    LEGACY_RATING_SCALE,
    MixedRatingScaleError,
    engine_potential,
    engine_rating,
    engine_row,
    moved_rating_keys,
    normalize_rating_scale,
    rating_scale_of,
    stretch_row,
    to_engine,
    to_stored,
    to_stored_exact,
)

# (key, pitcher): pivot, slope below, slope above, knee, "99 means engine".
TABLE = {
    ("ch", False): (50, 2, 3, 63, 73.0),
    ("ph", False): (50, 2, 3, None, 50 + 49 / 3),
    ("eye", False): (50, 3, 5, None, 59.8),
    ("fa", False): (52, 1, 2, None, 76.5),
    ("arm", False): (52, 1, 2, None, 76.5),
    ("control", True): (52, 2, 3, 66, 73.0),
    ("movement", True): (54, 2, 3, 68, 75.0),
    ("arm", True): (56, 1, 2, None, 80.5),
}
UNMOVED_HITTER = ("sp", "gf", "pl", "vl", "sc", "durability")
UNMOVED_PITCHER = (
    "endurance", "hold_runner", "fa", "gf", "vl", "durability",
    "fb", "cu", "cb", "sl", "si", "scb", "kn",
)


def test_the_table_is_the_design_table():
    assert moved_rating_keys(2, pitcher=False) == {"ch", "ph", "eye", "fa", "arm"}
    assert moved_rating_keys(2, pitcher=True) == {"control", "movement", "arm"}
    for (key, pitcher), (pivot, below, above, knee, _top) in TABLE.items():
        spec = rs.rating_map(key, 2, pitcher=pitcher)
        assert (spec.pivot, spec.slope_below, spec.slope_above, spec.knee) == (
            pivot, below, above, knee,
        ), key


def test_scale_one_moves_nothing():
    assert moved_rating_keys(1, pitcher=False) == frozenset()
    assert moved_rating_keys(1, pitcher=True) == frozenset()
    for key in ("ch", "ph", "eye", "fa", "arm", "control", "movement"):
        for pitcher in (False, True):
            assert to_stored(key, 61, 1, pitcher=pitcher) == 61
            assert to_engine(key, 61, 1, pitcher=pitcher) == 61


@pytest.mark.parametrize("key,pitcher", sorted(TABLE))
def test_every_integer_inside_the_scale_round_trips_exactly(key, pitcher):
    inside = 0
    for engine in range(1, 100):
        exact = to_stored_exact(key, engine, 2, pitcher=pitcher)
        stored = to_stored(key, engine, 2, pitcher=pitcher)
        assert isinstance(stored, int) and 1 <= stored <= 99
        if not 1 <= exact <= 99:
            assert stored in (1, 99)  # clipped, and the caller can tell
            continue
        inside += 1
        assert stored == exact  # an integer maps to an integer
        back = to_engine(key, stored, 2, pitcher=pitcher)
        assert back == engine and float(back).is_integer()
    assert inside >= 24


@pytest.mark.parametrize("key,pitcher", sorted(TABLE))
def test_the_map_is_strictly_monotone_both_ways(key, pitcher):
    stored = [to_stored_exact(key, e, 2, pitcher=pitcher) for e in range(1, 100)]
    assert all(b > a for a, b in zip(stored, stored[1:]))
    engine = [to_engine(key, s, 2, pitcher=pitcher) for s in range(1, 100)]
    assert all(b > a for a, b in zip(engine, engine[1:]))


@pytest.mark.parametrize("key,pitcher", sorted(TABLE))
def test_what_fifty_and_ninety_nine_mean(key, pitcher):
    pivot, _below, _above, knee, top = TABLE[(key, pitcher)]
    assert to_stored(key, pivot, 2, pitcher=pitcher) == 50
    assert to_engine(key, 50, 2, pitcher=pitcher) == pivot
    assert to_engine(key, 99, 2, pitcher=pitcher) == pytest.approx(top, abs=1e-9)
    if knee is not None:
        stored_knee = to_stored(key, knee, 2, pitcher=pitcher)
        assert stored_knee == {63: 89, 66: 92, 68: 92}[knee]
        # One stored point is one engine point above the knee.
        assert to_engine(key, stored_knee + 4, 2, pitcher=pitcher) == knee + 4


def test_the_design_examples():
    # RATING_SCALE_DESIGN.md, "Before and after, stats-clean".
    ramos = dict(ch=54, ph=65, eye=50, fa=43, arm=49)
    assert [to_stored(k, v, 2) for k, v in ramos.items()] == [62, 95, 50, 41, 47]
    laurenceau = dict(control=69, movement=55, arm=60)
    assert [
        to_stored(k, v, 2, pitcher=True) for k, v in laurenceau.items()
    ] == [95, 53, 58]
    # BRIEF_BUILD: stored Power 60 / 80 / 90 / 99 is engine 53.33 / 60 / 63.33 / 66.33.
    assert [round(to_engine("ph", s, 2), 2) for s in (60, 80, 90, 99)] == [
        53.33, 60.0, 63.33, 66.33,
    ]


def test_the_unmoved_ratings_are_untouched():
    for key in UNMOVED_HITTER:
        assert rs.rating_map(key, 2, pitcher=False) is None
        assert to_stored(key, 77, 2) == 77 and to_engine(key, 77, 2) == 77
    for key in UNMOVED_PITCHER:
        assert rs.rating_map(key, 2, pitcher=True) is None
        assert to_stored(key, 77, 2, pitcher=True) == 77
    # Pitcher fielding is not moved, hitter fielding is; the two arms differ.
    assert to_stored("fa", 60, 2, pitcher=True) == 60
    assert to_stored("fa", 60, 2) == 66
    assert to_stored("arm", 60, 2) == 66
    assert to_stored("arm", 60, 2, pitcher=True) == 58


def test_fractional_engine_ratings_round_half_up_and_unstretch_unrounded():
    assert to_stored("ph", 53.5, 2) == 61  # 60.5 -> 61
    assert to_engine("ph", 61, 2) == pytest.approx(53.6666666667)
    assert not float(to_engine("eye", 53, 2)).is_integer()


def test_scale_numbers():
    assert normalize_rating_scale(None) == 1
    assert normalize_rating_scale("") == 1
    assert normalize_rating_scale("  ") == 1
    assert normalize_rating_scale("1") == 1
    assert normalize_rating_scale("2") == 2
    assert normalize_rating_scale(2.0) == 2
    for bad in ("3", 0, "x", 1.5, True, float("nan")):
        with pytest.raises(ValueError):
            normalize_rating_scale(bad)
    # No league is fabricated on scale 2 yet.
    assert rs.GENERATED_RATING_SCALE == LEGACY_RATING_SCALE


def _hitter(**over):
    row = {
        "player_id": "H1", "is_pitcher": "0", "ch": "54", "ph": "65",
        "sp": "40", "eye": "50", "gf": "50", "pl": "50", "vl": "50",
        "sc": "50", "fa": "43", "arm": "49", "pot_ch": "64", "pot_ph": "68",
        "pot_sp": "38", "pot_eye": "59", "pot_fa": "43", "pot_arm": "40",
    }
    row.update(over)
    return row


def _pitcher(**over):
    row = {
        "player_id": "P1", "is_pitcher": "1", "arm": "60", "fa": "45",
        "control": "69", "movement": "55", "endurance": "70",
        "hold_runner": "50", "gf": "50", "fb": "70", "sl": "0",
        "pot_control": "72", "pot_movement": "66", "pot_arm": "55",
        "pot_fa": "40", "pot_fb": "75", "pot_sl": "0", "pot_endurance": "60",
    }
    row.update(over)
    return row


def test_stretch_row_hitter():
    out, clips = stretch_row(_hitter(), 2)
    assert clips == []
    assert (out["ch"], out["ph"], out["eye"], out["fa"], out["arm"]) == (
        "62", "95", "50", "41", "47",
    )
    assert out["sp"] == "40" and out["gf"] == "50"
    # Potential keeps the gap in points; never below current.
    assert out["pot_ch"] == "72"  # 62 + (64 - 54)
    assert out["pot_ph"] == "98"  # 95 + (68 - 65)
    assert out["pot_eye"] == "59"
    assert out["pot_fa"] == "41"  # equal to current stays at current
    assert out["pot_arm"] == "47"  # 40 < 49: raised to current
    assert out["pot_sp"] == "40"  # unmoved rating: floored at current
    assert out["rating_scale"] == "2"


def test_a_potential_gap_cut_at_99_is_reported():
    out, clips = stretch_row(_hitter(pot_ph="69"), 2)  # Power 95 + 4
    assert out["pot_ph"] == "99" and clips == []
    out, clips = stretch_row(_hitter(pot_ph="80"), 2)  # 95 + 15
    assert out["pot_ph"] == "99"
    assert [(c.key, c.kind, c.unclipped, c.stored) for c in clips] == [
        ("pot_ph", "potential", 110.0, 99)
    ]


def test_stretch_row_pitcher():
    out, clips = stretch_row(_pitcher(), 2)
    assert clips == []
    assert (out["control"], out["movement"], out["arm"]) == ("95", "53", "58")
    assert out["fa"] == "45" and out["endurance"] == "70" and out["fb"] == "70"
    assert out["pot_control"] == "98"  # 95 + (72 - 69)
    assert out["pot_movement"] == "64"
    assert out["pot_arm"] == "58"  # below current: raised to current
    assert out["pot_fa"] == "45" and out["pot_endurance"] == "70"
    assert out["pot_fb"] == "75"
    assert out["sl"] == "0" and out["pot_sl"] == "0"  # an unthrown pitch


def test_a_clipped_rating_is_reported():
    out, clips = stretch_row(_hitter(ph="23", eye="33", pot_ph="", pot_eye=""), 2)
    assert out["ph"] == "1" and out["eye"] == "1"
    assert {(c.key, c.kind, c.engine_value, c.unclipped) for c in clips} == {
        ("ph", "rating", 23.0, -4.0),
        ("eye", "rating", 33.0, -1.0),
    }
    out, clips = stretch_row(_hitter(ch="80", pot_ch=""), 2)
    assert out["ch"] == "99" and clips[0].unclipped == 106.0


def test_blank_and_zero_are_not_ratings():
    out, clips = stretch_row(_hitter(fa="0", sp="", pot_fa=""), 2)
    assert out["fa"] == "0" and out["sp"] == "" and clips == []
    back = engine_row(out)
    assert back["fa"] == "0" and back["sp"] == ""
    assert engine_rating(out, "fa", 0) == "0"
    assert engine_rating(out, "nope", 7) == 7
    # A zero Eye is not a blank one: the loader keeps it, and so does this.
    out, _ = stretch_row(_hitter(eye="0", pot_eye=""), 2)
    assert out["eye"] == "0"


@pytest.mark.parametrize("blank", ["", None])
def test_a_blank_eye_is_filled_from_contact_on_the_engine_scale(blank):
    row = _hitter(ch="55", eye=blank, pot_eye="61")
    if blank is None:
        del row["eye"]  # no column at all reads the same way
    out, clips = stretch_row(row, 2)
    # Engine Eye 55 (= Contact), stored 50 + 5 * 5; the potential keeps its
    # gap over the FILLED Eye: 75 + (61 - 55).
    assert (out["eye"], out["pot_eye"], clips) == ("75", "81", [])
    assert engine_rating(out, "eye") == 55 and engine_potential(out, "eye") == 61
    assert float(engine_row(out)["eye"]) == 55.0


def test_a_filled_value_that_does_not_fit_is_reported_with_its_source():
    # Contact 62 is Eye 62, past the 59.8 that stored Eye 99 means.
    out, clips = stretch_row(_hitter(ch="62", eye="", pot_eye="66"), 2)
    assert (out["eye"], out["pot_eye"]) == ("99", "99")
    assert [(c.key, c.kind, c.engine_value, c.source) for c in clips] == [
        ("eye", "rating", 62.0, "ch"),
        ("pot_eye", "potential", 66.0, ""),
    ]
    # Below the floor too (Contact 30 is Eye 30, stored 50 + 3 * -20).
    out, clips = stretch_row(_hitter(ch="30", eye="", pot_eye=""), 2)
    assert out["eye"] == "1" and clips[0].unclipped == -10.0


@pytest.mark.parametrize("arm", ["", "0", None])
def test_a_missing_pitcher_arm_is_filled_from_his_fastball(arm):
    row = _pitcher(arm=arm, fb="70", pot_arm="76")
    if arm is None:
        del row["arm"]
    out, clips = stretch_row(row, 2)
    # Engine arm 70 (= fastball), stored 50 + 2 * 14; potential gap 6.
    assert (out["arm"], out["pot_arm"], out["fb"], clips) == ("78", "84", "70", [])
    assert engine_rating(out, "arm") == 70 and engine_potential(out, "arm") == 76
    # Fastball 85 is past the 80.5 that stored arm 99 means: reported.
    out, clips = stretch_row(_pitcher(arm=arm or "", fb="85", pot_arm="0"), 2)
    assert out["arm"] == "99" and out["pot_arm"] == "0"
    assert [(c.key, c.engine_value, c.source) for c in clips] == [("arm", 85.0, "fb")]
    # No fastball either: nothing to borrow, nothing written.
    out, clips = stretch_row(_pitcher(arm="", fb="0"), 2)
    assert out["arm"] == "" and clips == []


def test_generated_dicts_are_filled_in_their_own_form():
    out, _ = stretch_row(
        {"player_id": "H", "is_pitcher": False, "ch": 55, "ph": 50, "eye": None}, 2
    )
    assert out["eye"] == 75 and isinstance(out["eye"], int)


def test_stretch_is_idempotent_and_refuses_an_unknown_scale():
    once, _ = stretch_row(_hitter(), 2)
    twice, clips = stretch_row(once, 2)
    assert twice == once and clips == []
    with pytest.raises(ValueError):
        stretch_row(_hitter(rating_scale="3"), 2)
    with pytest.raises(ValueError):
        stretch_row(once, LEGACY_RATING_SCALE)


def test_the_target_scale_is_required():
    import inspect

    for function in (stretch_row, rs.stretch_rows):
        scale = inspect.signature(function).parameters["scale"]
        assert scale.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        stretch_row(_hitter())  # type: ignore[call-arg]


def test_generated_dicts_keep_their_types():
    row = {
        "player_id": "P1", "is_pitcher": True, "arm": 60, "fa": 45,
        "control": 52, "movement": 54, "pot_control": 60, "pot_arm": 70,
        "pot_fielding": {"P": 50}, "other_positions": [],
    }
    out, clips = stretch_row(row, 2)
    assert clips == []
    assert out["control"] == 50 and out["movement"] == 50 and out["arm"] == 58
    assert out["pot_control"] == 58 and out["pot_arm"] == 68
    assert out["rating_scale"] == 2 and out["pot_fielding"] == {"P": 50}
    assert all(isinstance(out[k], int) for k in ("control", "arm", "pot_arm"))
    assert engine_rating(out, "control") == 52
    assert engine_potential(out, "control") == 60


def test_engine_row_is_the_exact_inverse_for_ratings():
    for row in (_hitter(), _pitcher()):
        stretched, _ = stretch_row(row, 2)
        back = engine_row(stretched)
        keys = moved_rating_keys(2, pitcher=row["is_pitcher"] == "1")
        for key in keys:
            assert float(back[key]) == float(row[key]), key
        assert back["rating_scale"] == ""
        assert engine_row(back) is back  # an honest scale 1 row
    # A scale 1 row is not copied.
    row = _hitter()
    assert engine_row(row) is row


def test_engine_row_text_values_parse_as_the_loaders_parse_them():
    stretched, _ = stretch_row(_hitter(), 2)
    back = engine_row(stretched)
    assert back["ch"] == "54" and back["ph"] == "65"  # whole numbers stay ints
    stretched["ph"] = "96"  # a development point on the stored scale
    assert float(engine_row(stretched)["ph"]) == pytest.approx(65.3333333333)


def test_potentials_engine_view():
    row = _hitter()
    stretched, _ = stretch_row(row, 2)
    # At or above current and under 99: the scale 1 potential comes back.
    assert engine_potential(stretched, "ch") == 64
    assert engine_potential(stretched, "eye") == 59
    # Below current: raised to current (not an exact inverse, by design).
    assert engine_potential(stretched, "arm") == 49
    assert engine_potential(stretched, "ph") == 68
    # Cut at 99: the gap that survived.
    cut, _ = stretch_row(_hitter(pot_ph="80"), 2)
    assert engine_potential(cut, "ph") == 65 + (99 - 95)
    # Unmoved rating: the stored potential.
    assert engine_potential(stretched, "sp") == "40"
    assert engine_potential(row, "ch") == "64"  # scale 1: as stored
    assert engine_potential(stretched, "nope", 5) == 5
    assert float(engine_row(stretched)["pot_ch"]) == 64.0


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_the_accessor_on_objects():
    plain = _Obj(ch=62, ph=95, fa=41, is_pitcher=False, potential={"ch": 72})
    assert engine_rating(plain, "ch") == 62  # no rating_scale: scale 1
    assert engine_rating(plain, "ch") is plain.ch
    assert engine_potential(plain, "ch") == 72
    full = _Obj(
        ch=62, ph=95, fa=41, sp=40, is_pitcher=False, rating_scale=2,
        potential={"ch": 72, "sp": 44},
    )
    assert engine_rating(full, "ch") == 54 and isinstance(engine_rating(full, "ch"), int)
    assert engine_rating(full, "ph") == 65
    assert engine_rating(full, "fa") == 43
    assert engine_rating(full, "sp") == 40
    assert engine_rating(full, "missing", 0) == 0
    assert engine_potential(full, "ch") == 64
    assert engine_potential(full, "sp") == 44
    assert engine_potential(full, "ph", 0) == 0
    arm = _Obj(arm=58, fa=60, control=95, is_pitcher=True, rating_scale=2)
    assert engine_rating(arm, "arm") == 60  # the pitcher map, not the hitter one
    assert engine_rating(arm, "fa") == 60  # pitcher fielding is not moved
    assert engine_rating(arm, "control") == 69
    assert rating_scale_of(full) == 2 and rating_scale_of(plain) == 1


def test_counting_and_the_majority_scale():
    one, two = _Obj(rating_scale=1), _Obj(rating_scale=2)
    assert rs.rating_scale_counts([]) == {}
    assert rs.rating_scale_counts([one, _Obj()]) == {1: 2}
    assert rs.rating_scale_counts([one, two, two]) == {1: 1, 2: 2}
    assert rs.describe_rating_scales({1: 1, 2: 2}) == "2 on scale 2, 1 on scale 1"
    assert rs.majority_rating_scale({}) == 1
    assert rs.majority_rating_scale({1: 1, 2: 2}) == 2
    assert rs.majority_rating_scale({1: 40, 2: 3}) == 1
    with pytest.raises(MixedRatingScaleError, match="split evenly"):
        rs.majority_rating_scale({1: 5, 2: 5})


def test_players_file_rating_scale_never_raises_for_a_mixed_file(tmp_path):
    path = tmp_path / "players.csv"
    assert rs.players_file_rating_scale(path) == 1
    assert rs.players_file_rating_scales(path) == {}
    path.write_text("player_id,ch\nA,50\n", encoding="utf-8")
    assert rs.players_file_rating_scale(path) == 1
    path.write_text("player_id,ch,rating_scale\nA,50,2\nB,60,2\n", encoding="utf-8")
    assert rs.players_file_rating_scale(path) == FULL_RATING_SCALE
    path.write_text("player_id,ch,rating_scale\nA,50,\nB,60,\n", encoding="utf-8")
    assert rs.players_file_rating_scale(path) == 1
    path.write_text(
        "player_id,ch,rating_scale\nA,50,2\nB,60,\nC,70,2\n", encoding="utf-8"
    )
    assert rs.players_file_rating_scale(path) == rs.MIXED_RATING_SCALES
    assert rs.players_file_rating_scales(path) == {2: 2, 1: 1}


def test_the_module_imports_only_the_standard_library():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(rs.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    # ``os``: the 8.0.0 switch is an environment setting.
    assert imported <= {"__future__", "csv", "math", "dataclasses", "os", "typing"}
