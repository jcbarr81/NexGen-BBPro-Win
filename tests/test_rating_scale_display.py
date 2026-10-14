"""What owners see once a league is on rating scale 2 (owner decisions 13, 14).

* A scale 1 league (every league today) is shown exactly as before: the
  rating and overall fields of every display payload of a fixed league are
  pinned to what the code served before the scale 2 display existed
  (commit 04364883a; the full responses were also compared byte for byte
  there, see the r8-display report).
* Its scale 2 twin shows each rating as stored, the overall through the
  fixed display map, stars re-anchored, and the same internal overall.
* No payload carries a potential (decision 14).
* The scouting error keeps its size in shown points (measured; see
  ``services.scouting_service.FULL_SCALE_SCOUTING_ERROR_FACTOR``).

Every league here is written under pytest's ``tmp_path``.
"""

from __future__ import annotations

import ast
import collections
import csv
import hashlib
from pathlib import Path

import pytest

from tests import rating_display_support as rds
from tests import rating_scale_support as support

# Rating and overall fields of each payload of the scale 1 display league
# (tests/rating_display_support.py), sha256 of their canonical JSON, as
# served before the scale 2 display was built. A change here is a change to
# what every league sees today: only re-pin it on purpose.
PINNED_SCALE_1 = {
    "contracts": "c1d44a4b8766418b23a66bc8fa97e590a419f5c7963d42a7e4d7fa1d4c6f9e47",
    "draft/pool": "c52539279e6f26a2e43ee2bf843d13fa04f1b1e950b4c749a93bad9436932011",
    "draft/state.selected": "3e9bcbe7019927b23a01479f3255eb17e0549f702b6b845b669a7fb53b5e1db1",
    "free-agents": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
    "players/browse": "5874bd35c4f39b178c1ab004d72885bff4eb318cc1c38cdaa9142c8458e94e3c",
    "players/list": "52550f6c499b2273abef1edad2343feb703d60d71c1aaf7e54c4bda8a9e33ded",
    "profile/P1195": "198cafd89660d062d94b4436dcf80c2baa7c5352e6a76b1d86d14cb14af12b87",
    "profile/P1940": "4a874beb0237c6bfc41302b91f65f2b93ab0eb8bd5afe423c8cd051e71bb56d6",
    "profile/P3017": "4306d9d37a132db3d3796449b233c5e8e4fc4cdd5ffee1a604a48d4e936cfded",
    "profile/P5964": "c9f0c3e22b870ed6f1a3677f7a0d9e2dd8fe3c786f09e75663b4ad5507e24e88",
    "profile/P8398": "5a5d7161f55e2308a411fd2d274f09304de424b8f2c474821be67e1636cce1df",
    "roster/ALB": "8de33130a2cbd01449a2927a87c49a077cebdf0a433af141dc4b772b96b11a38",
    "roster/DET": "5d1254306191f7ab5e4c319bb4396ed2318572e0b0a8a0e1924b9d853aaeda1e",
    "roster/LOU": "9cb69c8534df22eb4880a51d99e2737b45bab6d8b39a06a221d196ed587378cb",
}

MOVED_HITTER = ("ch", "ph", "eye", "fa", "arm")
MOVED_PITCHER = ("control", "movement", "arm")


def _serve(root: Path, scale: int, mutate=None):
    """Build the display league on ``scale`` under ``root`` and serve it."""

    import os

    from utils import path_utils
    import services.team_ownership as ownership

    data = rds.build_display_league(root, scale=scale)
    if mutate is not None:
        mutate(data)
    saved = {k: os.environ.get(k) for k in ("NEXGEN_DATA_ROOT", "NEXGEN_ACTIVE_LEAGUE")}
    os.environ["NEXGEN_DATA_ROOT"] = str(root)
    os.environ.pop("NEXGEN_ACTIVE_LEAGUE", None)
    path_utils._DATA_DIR_CACHE.clear()
    token = path_utils.set_request_league(rds.LEAGUE)
    real_owned = ownership.human_owned_team_ids
    ownership.human_owned_team_ids = lambda *a, **k: set()
    try:
        assert path_utils.get_data_dir().resolve() == data.resolve()
        return data, rds.display_payloads(data)
    finally:
        ownership.human_owned_team_ids = real_owned
        path_utils.reset_request_league(token)
        path_utils._DATA_DIR_CACHE.clear()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="module")
def plain(tmp_path_factory):
    return _serve(tmp_path_factory.mktemp("scale1"), 1)


@pytest.fixture(scope="module")
def twin(tmp_path_factory):
    return _serve(tmp_path_factory.mktemp("scale2"), 2)


def _rows(data: Path):
    _fields, rows = support.read_player_rows(data / "players.csv")
    return {row["player_id"]: row for row in rows}


def _is_pitcher(row) -> bool:
    return str(row.get("is_pitcher", "")).strip() in {"1", "true", "True"}


# --- scale 1: exactly as before ---------------------------------------------

def test_a_scale_1_league_shows_what_it_showed_before(plain):
    _data, payloads = plain
    projection = rds.display_projection(payloads)
    served = {
        name: hashlib.sha256(rds.canonical(payload).encode()).hexdigest()
        for name, payload in projection.items()
    }
    assert served == PINNED_SCALE_1


def test_a_scale_1_league_sees_no_scale_2_tutorial_text(plain):
    from services.tutorials import TUTORIALS

    _data, payloads = plain
    served = {t["tutorial_id"]: t for t in payloads["help/tutorials"]["tutorials"]}
    for tutorial in TUTORIALS:
        expected = [
            {"title": s.title, "body_html": s.body_html}
            for s in tutorial.steps
            if s.rating_scale in (None, 1)
        ]
        assert served[tutorial.tutorial_id]["steps"] == expected
    titles = [s["title"] for s in served["updated_engine"]["steps"]]
    assert "Ratings on the full 1 to 99 scale" not in titles


# --- scale 2: the stored rating, the stretched overall ----------------------

def _check_ratings(player, row, keys):
    for key in keys:
        if key not in player["ratings"]:
            continue
        stored = row.get(key, "")
        shown = player["ratings"][key]
        if stored in ("", None) or float(stored) == 0:
            assert shown in (0, None, "", "0")
            continue
        assert shown == int(float(stored)), (row["player_id"], key, shown, stored)


def test_every_list_page_shows_the_stored_rating(twin):
    data, payloads = twin
    rows = _rows(data)
    players = list(payloads["players/browse"]["players"])
    players += payloads["free-agents"]["free_agents"]
    players += payloads["players/list"]
    for name, payload in payloads.items():
        if name.startswith("roster/"):
            for group in payload["levels"].values():
                players += [p for p in group if p.get("ratings")]
    assert len(players) > 1600
    for player in players:
        row = rows[player["player_id"]]
        keys = list(player["ratings"])
        _check_ratings(player, row, keys)


def test_the_draft_page_shows_the_stored_rating_too(twin):
    import json

    data, payloads = twin
    pool = {
        p["player_id"]: p
        for p in json.loads((data / f"draft_pool_{rds.DRAFT_YEAR}.json").read_text())
    }
    prospects = payloads["draft/pool"]["prospects"]
    assert len(prospects) == 40
    for prospect in prospects:
        entry = pool[prospect["player_id"]]
        assert entry["rating_scale"] == 2
        for key, shown in prospect["ratings"].items():
            assert shown == entry[key], (prospect["player_id"], key)


def test_the_overall_is_stretched_for_display_only(plain, twin):
    from utils.player_overall import player_overall_score
    from utils.rating_display import full_scale_overall
    from utils.star_rating import full_scale_star_text

    data, payloads = twin
    rows = _rows(data)
    before = {p["player_id"]: p for p in plain[1]["players/browse"]["players"]}
    shown_any = 0
    for player in payloads["players/browse"]["players"]:
        old = before[player["player_id"]]
        # The overall every CPU decision reads does not move.
        assert player["overall_raw"] == old["overall_raw"]
        if player["overall_raw"] is None:
            continue
        score = player_overall_score(rows[player["player_id"]])
        expected = full_scale_overall(score, is_pitcher=player["is_pitcher"])
        assert player["overall_display"] == expected
        assert player["overall_stars_text"] == full_scale_star_text(expected)
        shown_any += 1
    assert shown_any > 1500


def test_stars_are_handed_out_about_as_before(plain, twin):
    def shares(payloads):
        stars = [p["overall_stars_text"] for p in payloads["players/browse"]["players"]]
        counts = collections.Counter(stars)
        return {k: 100.0 * v / len(stars) for k, v in counts.items()}

    before, after = shares(plain[1]), shares(twin[1])
    for key in set(before) | set(after):
        assert abs(before.get(key, 0.0) - after.get(key, 0.0)) <= 2.0, (key, before, after)


def test_the_profile_shows_stored_ratings_and_the_archived_season_on_scale_2(plain, twin):
    from utils.rating_scale import stretch_row

    data, payloads = twin
    rows = _rows(data)
    archived = {
        r["player_id"]: r
        for r in csv.DictReader(
            (data / "careers" / rds.ARCHIVED_SEASON / "players.csv").open(
                newline="", encoding="utf-8"
            )
        )
    }
    labels = {
        "Contact": "ch", "Power": "ph", "Eye": "eye", "Fielding": "fa", "Arm": "arm",
        "Control": "control", "Movement": "movement",
    }
    for pid in rds.profile_ids(data):
        profile = payloads[f"profile/{pid}"]
        row = rows[pid]
        for label, shown in profile["overview_ratings"]:
            if label in labels:
                assert int(shown) == int(row[labels[label]]), (pid, label)
        # The archived season (stored on scale 1) is shown on scale 2.
        expected = stretch_row(archived[pid], 2)[0]
        history = profile["ratings_history"][0]["ratings"]
        for key, value in history.items():
            assert value == int(float(expected[key])), (pid, key)
        assert profile["ratings_history"][-1]["ratings"] == history
        # The overall: stretched, and the same internal number.
        details = dict(profile["overall_details"])
        old = dict(plain[1][f"profile/{pid}"]["overall_details"])
        assert details["Raw"] == old["Raw"]
        assert profile["overall_display"] == float(details["Displayed"])


def test_a_stored_rating_under_35_is_shown_as_it_is(twin):
    """Scale 1 never showed a number under 35; a stored 20 is a 20."""

    data, payloads = twin
    rows = _rows(data)
    low = [
        (p["player_id"], key, value)
        for p in payloads["players/browse"]["players"]
        for key, value in p["ratings"].items()
        if isinstance(value, int) and 0 < value < 35
    ]
    assert len(low) > 50
    for pid, key, value in low:
        assert value == int(rows[pid][key])


def test_the_scale_2_tutorial_step_is_shown_on_scale_2(twin):
    _data, payloads = twin
    served = {t["tutorial_id"]: t for t in payloads["help/tutorials"]["tutorials"]}
    titles = [s["title"] for s in served["updated_engine"]["steps"]]
    assert "Ratings on the full 1 to 99 scale" in titles


# --- a mixed file -------------------------------------------------------------

def _unconvert(count):
    """Put the first ``count`` rows of a scale 2 file back on scale 1 (the
    rows as they were before the conversion, from the archived season)."""

    def mutate(data: Path) -> None:
        fields, rows = support.read_player_rows(data / "players.csv")
        _old_fields, old_rows = support.read_player_rows(
            data / "careers" / rds.ARCHIVED_SEASON / "players.csv"
        )
        for index in range(count):
            assert old_rows[index]["player_id"] == rows[index]["player_id"]
            rows[index] = {**old_rows[index], "rating_scale": ""}
        support.write_player_rows(data / "players.csv", fields, rows)

    return mutate


def test_a_few_stray_scale_1_rows_are_shown_on_the_leagues_scale(tmp_path, twin):
    data, payloads = _serve(tmp_path, 2, mutate=_unconvert(25))
    fields, rows = support.read_player_rows(data / "players.csv")
    stray = {r["player_id"] for r in rows[:25]}
    assert all(not r.get("rating_scale") for r in rows[:25])
    reference = {p["player_id"]: p for p in twin[1]["players/browse"]["players"]}
    seen = 0
    for player in payloads["players/browse"]["players"]:
        if player["player_id"] in stray:
            seen += 1
            ref = reference[player["player_id"]]
            assert player["ratings"] == ref["ratings"]
            assert player["overall_display"] == ref["overall_display"]
    assert seen == 25


def test_a_file_split_in_half_shows_each_row_on_its_own_scale(tmp_path, plain, twin):
    from utils.rating_display import league_display_scale

    probe = tmp_path / "players.csv"
    probe.write_text(
        "player_id,is_pitcher,ch,rating_scale\nA,0,50,2\nB,0,50,\n", encoding="utf-8"
    )
    assert league_display_scale(probe) is None
    probe.write_text(
        "player_id,is_pitcher,ch,rating_scale\nA,0,50,2\nB,0,50,2\nC,0,50,\n",
        encoding="utf-8",
    )
    assert league_display_scale(probe) == 2
    probe.write_text("player_id,is_pitcher,ch\nA,0,50\n", encoding="utf-8")
    assert league_display_scale(probe) == 1
    assert league_display_scale(tmp_path / "missing.csv") is None


# --- potentials stay hidden (decision 14) ----------------------------------

def _keys(value, out):
    if isinstance(value, dict):
        for key, item in value.items():
            out.add(str(key))
            _keys(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _keys(item, out)
    return out


def test_no_payload_carries_a_potential(plain, twin):
    for _data, payloads in (plain, twin):
        keys = _keys(payloads, set())
        leaked = sorted(k for k in keys if k.startswith("pot_") or "potential" in k.lower())
        assert leaked == []


DISPLAY_CODE = (
    "api/routers/_rating_presentation.py",
    "api/routers/contracts.py",
    "api/routers/draft.py",
    "api/routers/free_agency.py",
    "api/routers/players.py",
    "api/routers/roster.py",
    "services/player_profile_view_model.py",
    "utils/rating_display.py",
)


@pytest.mark.parametrize("rel", DISPLAY_CODE)
def test_no_display_code_names_a_potential(rel):
    """No display module names a potential (``pot_ch``, ``potential``).
    The bare prefix ``"pot_"`` appears only where a potential is recognised
    in order to be left out or converted (``utils.rating_display``)."""

    tree = ast.parse((support.REPO / rel).read_text(encoding="utf-8-sig"))
    named = sorted(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (
            (node.value.startswith("pot_") and node.value != "pot_")
            or node.value in {"potential", "potentials"}
        )
    )
    assert named == []


# --- the pieces -------------------------------------------------------------

def test_the_overall_display_map():
    from utils.rating_display import full_scale_overall

    assert full_scale_overall(50.0, is_pitcher=False) == 50
    assert full_scale_overall(53.0, is_pitcher=True) == 50
    assert full_scale_overall(59.0, is_pitcher=False) == 86
    assert full_scale_overall(61.0, is_pitcher=False) == 90
    assert full_scale_overall(64.0, is_pitcher=True) == 90
    assert full_scale_overall(40.0, is_pitcher=False) == 25
    assert full_scale_overall(20.0, is_pitcher=False) == 1
    assert full_scale_overall(80.0, is_pitcher=True) == 99
    assert full_scale_overall(None, is_pitcher=True) is None
    shown = [full_scale_overall(30 + i / 10, is_pitcher=False) for i in range(400)]
    assert shown == sorted(shown)


def test_the_best_overall_of_the_league_fixture_lands_near_the_top():
    """The league fixture's best hitter (58.9) and pitcher (62.9) read in
    the 80s; its average active hitter and pitcher read about 50-60."""

    from utils.pitcher_role import get_role
    from utils.player_overall import hitter_overall_score, pitcher_overall_score
    from utils.rating_display import full_scale_overall

    _fields, rows = support.read_player_rows(support.FIXTURES["calibration_league"] / "players.csv")
    hitters = [hitter_overall_score(r.get, r.get("primary_position")) for r in rows if not _is_pitcher(r)]
    pitchers = [pitcher_overall_score(r.get, get_role(r)) for r in rows if _is_pitcher(r)]
    assert 84 <= full_scale_overall(max(h for h in hitters if h), is_pitcher=False) <= 92
    assert 84 <= full_scale_overall(max(p for p in pitchers if p), is_pitcher=True) <= 92


def test_the_scouting_error_keeps_its_size_in_shown_points():
    from services.scouting_service import (
        FULL_SCALE_SCOUTING_ERROR_FACTOR,
        TeamScoutingProfile,
        scouting_error_spread,
        scouting_observed_value,
    )

    assert FULL_SCALE_SCOUTING_ERROR_FACTOR == 1.0
    for spread in range(0, 10):
        assert scouting_error_spread(spread, None) == spread
        assert scouting_error_spread(spread, 2) == spread
    profile = TeamScoutingProfile(
        enabled=True, team_id="ALB", scouting_multiplier=1.0,
        confidence_score=10, confidence_label="Low", max_rating_error=9,
    )
    offsets = set()
    for index in range(400):
        seen = scouting_observed_value(
            50, team_profile=profile, player_id=f"P{index}", metric_key="CH",
            team_id="ALB", minimum=1, maximum=99, rating_scale=2,
        )
        offsets.add(seen - 50)
        assert scouting_observed_value(
            50, team_profile=profile, player_id=f"P{index}", metric_key="CH",
            team_id="ALB", minimum=1, maximum=99,
        ) == seen
    assert min(offsets) == -9 and max(offsets) == 9
    # A low stored rating keeps its error on scale 2: the floor is 1, not 35.
    assert scouting_observed_value(
        10, team_profile=profile, player_id="P1", metric_key="CH",
        team_id="ALB", minimum=1, maximum=99, rating_scale=2,
    ) < 35
