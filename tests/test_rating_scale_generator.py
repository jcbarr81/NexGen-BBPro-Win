"""Fabricated players: one stretch at the end, on the target league's scale.

The generator draws, floors and marks down ENGINE ratings (its donor file
and every constant are in engine points) and re-expresses the finished
player once on the scale of the league he is for
(``RATING_SCALE_DESIGN.md`` section 5). So, with the same random seed,

    generated on scale 2  ==  stretch(generated on scale 1)

for a player, a draft class and a whole league, and everything the league
creator decides from ratings along the way (staff roles, lineups) is the
same. No league is generated on scale 2 today: ``GENERATED_RATING_SCALE``
is 1 and the default output is exactly what it was.
"""

from __future__ import annotations

import dataclasses
import random

import pytest

from playbalance import player_generator
from playbalance.league_creator import create_league
from tests import rating_scale_support as support
from utils import rating_scale
from utils.rating_scale import stretch_row, stretch_rows

DIVISIONS = {
    "East": [("Albany", "Aces"), ("Boston", "Bears")],
    "West": [("Camden", "Cubs"), ("Dayton", "Ducks")],
}
SEED = 20261013


def _player(seed, **kwargs):
    random.seed(seed)
    player_generator.reset_name_cache()
    return player_generator.generate_player(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(is_pitcher=False, primary_position="SS"),
        dict(is_pitcher=True),
        dict(is_pitcher=True, pitcher_archetype="closer"),
        dict(is_pitcher=False, for_draft=True, age_range=(17, 21)),
        dict(is_pitcher=True, for_draft=True, age_range=(17, 21)),
    ],
)
def test_a_player_on_scale_2_is_the_stretch_of_the_same_player(kwargs, caplog):
    for seed in range(40):
        plain = _player(seed, **kwargs)
        assert "rating_scale" not in plain  # scale 1: the dict as it always was
        assert _player(seed, rating_scale=1, **kwargs) == plain
        full = _player(seed, rating_scale=2, **kwargs)
        expected, _clips = stretch_row(plain, 2)
        assert full == expected and full["rating_scale"] == 2


def test_the_stretch_draws_no_random_number():
    random.seed(5)
    player_generator.reset_name_cache()
    player_generator.generate_player(is_pitcher=False)
    after_plain = random.random()
    random.seed(5)
    player_generator.reset_name_cache()
    player_generator.generate_player(is_pitcher=False, rating_scale=2)
    assert random.random() == after_plain


def test_a_rating_that_does_not_fit_is_logged_not_silent(monkeypatch, caplog):
    """Draft-age ratings can be marked down below what scale 2 can store
    (an Eye under 33.67 is below stored 1)."""

    def tiny_eye(**kwargs):
        return {
            "player_id": "P1", "is_pitcher": False, "ch": 40, "ph": 40,
            "eye": 25, "fa": 50, "arm": 50, "pot_eye": 60,
        }

    monkeypatch.setattr(player_generator, "_generate_engine_player", tiny_eye)
    with caplog.at_level("WARNING", logger=player_generator.__name__):
        player = player_generator.generate_player(is_pitcher=False, rating_scale=2)
    assert player["eye"] == 1
    assert "eye does not fit rating scale 2" in caplog.text


def _draft_class(scale):
    from playbalance.draft_pool import generate_draft_pool

    player_generator.reset_name_cache()
    return [
        dataclasses.asdict(p)
        for p in generate_draft_pool(2031, size=120, seed=SEED, rating_scale=scale)
    ]


def test_a_draft_class_on_scale_2_is_the_stretch_of_the_same_class():
    plain, full = _draft_class(1), _draft_class(2)
    assert _draft_class(1) == plain  # the seed fixes the class
    stretched, clips = stretch_rows(plain, 2)
    assert full == stretched
    assert {p["rating_scale"] for p in plain} == {1}
    assert {p["rating_scale"] for p in full} == {2}
    # The low tail of a draft class does not all fit (see the report-only
    # count in the release notes): a handful of prospects, never most.
    off_scale = {c.player_id for c in clips if c.kind == "rating"}
    assert len(off_scale) <= 0.08 * len(plain)


@pytest.fixture(scope="module")
def created(tmp_path_factory):
    """The same-seed league three ways: default, scale 1 and scale 2."""

    root = tmp_path_factory.mktemp("created")
    out = {}
    for name, kwargs in (
        ("default", {}),
        ("one", {"rating_scale": 1}),
        ("two", {"rating_scale": 2}),
    ):
        random.seed(SEED)
        create_league(str(root / name), DIVISIONS, "Scale Test", **kwargs)
        out[name] = root / name
    return out


def _tree(directory, folder):
    return {
        path.name: path.read_bytes() for path in sorted((directory / folder).glob("*.csv"))
    }


def test_a_new_league_is_on_scale_1_today(created):
    assert rating_scale.GENERATED_RATING_SCALE == 1
    default, one = created["default"], created["one"]
    assert "rating_scale" not in (default / "players.csv").read_text(encoding="utf-8")
    # The default is the explicit scale 1, file for file.
    assert (default / "players.csv").read_bytes() == (one / "players.csv").read_bytes()
    for folder in ("rosters", "lineups"):
        assert _tree(default, folder) == _tree(one, folder)


def test_a_league_created_on_scale_2_is_the_stretch_of_the_same_league(created):
    fields, plain = support.read_player_rows(created["one"] / "players.csv")
    full_fields, full = support.read_player_rows(created["two"] / "players.csv")
    assert full_fields == fields + ["rating_scale"]
    stretched, _clips = stretch_rows(plain, 2)
    assert len(full) == len(plain) == 4 * 51
    assert full == stretched
    changed = sum(a["ch"] != b["ch"] or a["control"] != b["control"] for a, b in zip(plain, full))
    assert changed > 100


def test_the_league_creator_decides_the_same_on_either_scale(created):
    """Rosters, pitching-staff roles and both default lineups are picked
    from ratings while the league is built; they must not depend on the
    scale the ratings are stored on."""

    one, two = created["one"], created["two"]
    rosters, lineups = _tree(one, "rosters"), _tree(one, "lineups")
    assert len(rosters) == 8 and len(lineups) == 8  # roster + staff, vs L + vs R
    assert _tree(two, "rosters") == rosters
    assert _tree(two, "lineups") == lineups
    assert (two / "teams.csv").read_bytes() == (one / "teams.csv").read_bytes()


def test_a_created_scale_2_league_loads_and_reads_as_the_scale_1_league(created):
    plain = support.load_player_objects(created["one"])
    full = support.load_player_objects(created["two"])
    assert {p.rating_scale for p in full.values()} == {2}
    from utils.player_overall import player_overall_score

    for pid, player in plain.items():
        assert player_overall_score(full[pid]) == player_overall_score(player), pid
