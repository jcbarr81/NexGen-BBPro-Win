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
import contextlib
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from types import SimpleNamespace

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

# The whole /help/tutorials payload of a scale 1 league as 04364883a
# served it (sha256 of its canonical JSON): no scale 2 step may reach it.
# Re-pin only when a tutorial is edited on purpose (re-pinned for 8.2.0: the
# Dashboard tutorial's new Spotlight step, the same for every scale; for
# 8.3.0: the Player Avatars tutorial's "New club, new colors" step; for
# 8.4.0: the League Hub tutorial's "Postseason stats" step; for 8.5.0: the
# Finance tutorial's "Extending your players" step).
PINNED_SCALE_1_TUTORIALS = (
    "b9117bb165a67c6fccf3acf352b33f82a5063489cde511f159430545701020bd"
)

MOVED_HITTER = ("ch", "ph", "eye", "fa", "arm")
MOVED_PITCHER = ("control", "movement", "arm")


@contextlib.contextmanager
def _league(root: Path):
    """Make the display league under ``root`` the request's league."""

    import os

    from utils import path_utils
    import services.team_ownership as ownership

    saved = {k: os.environ.get(k) for k in ("NEXGEN_DATA_ROOT", "NEXGEN_ACTIVE_LEAGUE")}
    os.environ["NEXGEN_DATA_ROOT"] = str(root)
    os.environ.pop("NEXGEN_ACTIVE_LEAGUE", None)
    path_utils._DATA_DIR_CACHE.clear()
    token = path_utils.set_request_league(rds.LEAGUE)
    real_owned = ownership.human_owned_team_ids
    ownership.human_owned_team_ids = lambda *a, **k: set()
    try:
        yield path_utils.get_data_dir()
    finally:
        ownership.human_owned_team_ids = real_owned
        path_utils.reset_request_league(token)
        path_utils._DATA_DIR_CACHE.clear()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _serve(root: Path, scale: int, mutate=None):
    """Build the display league on ``scale`` under ``root`` and serve it."""

    data = rds.build_display_league(root, scale=scale)
    if mutate is not None:
        mutate(data)
    with _league(root) as active:
        assert active.resolve() == data.resolve()
        return data, rds.display_payloads(data)


def _shown_overall(score: float, pitcher: bool) -> int:
    """The scale 2 overall worked out by hand from the published map (not
    through ``utils.rating_display``): 4 shown points per overall point
    from the pivot (50 hitters, 53 pitchers) to pivot + 9, 2 per point
    above that, 2.5 per point below the pivot; rounded half up, 1-99."""

    pivot = 53.0 if pitcher else 50.0
    if score < pivot:
        shown = 50 - 2.5 * (pivot - score)
    elif score <= pivot + 9:
        shown = 50 + 4 * (score - pivot)
    else:
        shown = 86 + 2 * (score - pivot - 9)
    return max(1, min(99, math.floor(shown + 0.5)))


def _stars(shown: int) -> str:
    """Stars for a scale 2 overall, from the published cut-offs."""

    for cutoff, stars in ((97, "5"), (92, "4.5"), (77, "4"), (59, "3.5"),
                          (52, "3"), (48, "2.5"), (43, "2"), (26, "1.5")):
        if shown >= cutoff:
            return stars
    return "1"


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


def test_a_scale_1_league_sees_the_tutorials_it_saw_before(plain):
    _data, payloads = plain
    tutorials = payloads["help/tutorials"]
    served = hashlib.sha256(rds.canonical(tutorials).encode()).hexdigest()
    assert served == PINNED_SCALE_1_TUTORIALS
    steps = {t["tutorial_id"]: t for t in tutorials["tutorials"]}["updated_engine"]
    assert "Ratings on the full 1 to 99 scale" not in [s["title"] for s in steps["steps"]]


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
        expected = _shown_overall(score, player["is_pitcher"])
        assert player["overall_display"] == expected
        assert player["overall_stars_text"] == _stars(expected)
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


def _strings(value, out):
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            _strings(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _strings(item, out)
    return out


def test_no_payload_carries_a_potential(plain, twin):
    for _data, payloads in (plain, twin):
        owner_pages = {k: v for k, v in payloads.items() if k != "help/tutorials"}
        keys = _keys(owner_pages, set())
        leaked = sorted(k for k in keys if k.startswith("pot_") or "potential" in k.lower())
        assert leaked == []
        # No text names a potential either.
        texts = [t for t in _strings(owner_pages, []) if "potential" in t.lower()]
        assert texts == []
    # Values: on scale 2 every rating a list page carries is the player's
    # stored current rating, never his potential. (Scale 1 is pinned to
    # what it served before, which never carried a potential.)
    data, payloads = twin
    rows = _rows(data)
    checked = 0
    for player in payloads["players/browse"]["players"]:
        row = rows[player["player_id"]]
        for key, shown in player["ratings"].items():
            current, potential = row.get(key), row.get(f"pot_{key}")
            if not current or float(current) <= 0 or not potential:
                continue
            if float(potential) == float(current):
                continue
            assert shown == int(float(current)), (player["player_id"], key)
            checked += 1
    assert checked > 1000


# An admin-only export may name potentials, with the reason. Everything
# else in DISPLAY_CODE must name none.
POTENTIAL_EXEMPT = {
    # The commissioner's report export (POST /exports/reports, admin role
    # only: api/routers/exports.py _require_admin; owners get 403) averages
    # each age bucket's potentials into avg_potential. Not an owner page.
    "services/career_arc_analytics.py": {
        "avg_potential", "potential", "pot_arm", "pot_ch", "pot_control",
        "pot_endurance", "pot_eye", "pot_fa", "pot_movement", "pot_ph", "pot_sp",
    },
}

DISPLAY_CODE = (
    "api/routers/_rating_presentation.py",
    "api/routers/contracts.py",
    "api/routers/draft.py",
    "api/routers/free_agency.py",
    "api/routers/players.py",
    "api/routers/roster.py",
    "services/player_profile_view_model.py",
    "services/career_arc_analytics.py",
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
            or re.fullmatch(r"[a-z_]*potentials?[a-z_]*", node.value) is not None
        )
    )
    assert set(named) <= POTENTIAL_EXEMPT.get(rel, set()), sorted(set(named))


def test_the_report_export_is_admin_only():
    """The one place that averages potentials is behind the admin role."""

    tree = ast.parse((support.REPO / "api/routers/exports.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "export_reports":
            defaults = [ast.unparse(d) for d in node.args.defaults + node.args.kw_defaults if d]
            assert "AdminIdentity" in defaults
            break
    else:  # pragma: no cover
        raise AssertionError("export_reports not found")


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


# --- a draft class generated before the conversion --------------------------

def _old_pool(data: Path) -> None:
    """Replace the twin's draft class with the one the league had before it
    was converted: the same prospects, still on scale 1."""

    _fields, rows = support.read_player_rows(
        data / "careers" / rds.ARCHIVED_SEASON / "players.csv"
    )
    pool = rds._draft_class(rows, rds._levels(data))
    (data / f"draft_pool_{rds.DRAFT_YEAR}.json").write_text(
        json.dumps(pool), encoding="utf-8"
    )


def test_a_draft_class_from_before_the_conversion_shows_on_scale_2(tmp_path, twin):
    data, payloads = _serve(tmp_path, 2, mutate=_old_pool)
    pool = json.loads((data / f"draft_pool_{rds.DRAFT_YEAR}.json").read_text())
    assert all("rating_scale" not in p for p in pool)  # really a scale 1 class
    reference = {p["player_id"]: p for p in twin[1]["draft/pool"]["prospects"]}
    shown = {p["player_id"]: p for p in payloads["draft/pool"]["prospects"]}
    assert set(shown) == set(reference)
    for pid, prospect in shown.items():
        assert prospect["ratings"] == reference[pid]["ratings"], pid
        assert prospect["overall"] == reference[pid]["overall"], pid
    picks = [(p["player_id"], p["overall_display"]) for p in payloads["draft/state.selected"]]
    assert picks == [
        (p["player_id"], p["overall_display"]) for p in twin[1]["draft/state.selected"]
    ]


# --- the Pitchers page's SP / RP --------------------------------------------

@pytest.mark.parametrize(
    "preferred, endurance, staff, expected",
    [
        ("SP", 30, None, "SP"),
        ("SP1", 30, None, "SP"),
        ("SP2", 80, None, "SP"),
        ("SP5", 40, None, "SP"),
        ("STARTER", 40, None, "SP"),
        ("CL", 80, None, "RP"),
        ("MR3", 80, None, "RP"),
        ("", 70, None, "SP"),
        ("", 40, None, "RP"),
        ("CL", 30, "SP", "SP"),  # the staff file is the authority
        ("SP1", 80, "RP", "RP"),
    ],
)
def test_the_roster_payload_role_is_the_apps_role(preferred, endurance, staff, expected):
    from api.routers import roster

    player = SimpleNamespace(
        player_id="P1", is_pitcher=True, primary_position="P",
        preferred_pitching_role=preferred, endurance=endurance,
        role="RP",  # the stale stored column: never read
    )
    staff_roles = {"P1": staff} if staff else {}
    assert roster._pitcher_role(player, staff_roles) == expected


def test_the_staff_file_is_read_as_sp_or_rp(tmp_path):
    from api.routers import roster

    root = tmp_path / "root"
    data = rds.build_display_league(root)
    (data / "rosters" / "ALB_pitching.csv").write_text(
        "P1,SP1\nP2,SP\nP3,CL\nP4,MR2\nP5,LR\nP6,SU\n", encoding="utf-8"
    )
    with _league(root):
        assert roster._staff_roles("ALB") == {
            "P1": "SP", "P2": "SP", "P3": "RP", "P4": "RP", "P5": "RP", "P6": "RP",
        }
        assert roster._staff_roles("NOPE") == {}


def test_the_roster_role_follows_the_staff_file(plain):
    data, payloads = plain
    staff = {}
    text = (data / "rosters" / "ALB_pitching.csv").read_text(encoding="utf-8")
    for line in text.splitlines():
        pid, label = line.split(",")[:2]
        staff[pid] = "SP" if label.strip().upper().startswith("SP") else "RP"
    seen = 0
    for player in payloads["roster/ALB"]["levels"]["ACT"]:
        if player["is_pitcher"]:
            assert player["role"] == staff[player["player_id"]]
            seen += 1
    assert seen >= 10


# --- news and transaction text ----------------------------------------------

def test_news_quotes_the_overall_the_pages_show(twin, plain):
    from utils.player_loader import load_players_from_csv
    from utils.rating_display import overall_for_text

    browse = {p["player_id"]: p for p in twin[1]["players/browse"]["players"]}
    for player in load_players_from_csv(str(twin[0] / "players.csv"))[:200]:
        page = browse[player.player_id]["overall_display"]
        assert overall_for_text(player, 57, 2) == (57 if page is None else page)
    for player in load_players_from_csv(str(plain[0] / "players.csv"))[:200]:
        assert overall_for_text(player, 57, 1) == 57  # scale 1: as before


def test_a_callup_on_scale_2_writes_the_shown_overall(tmp_path, monkeypatch, twin):
    import services.inseason_callups as callups
    from utils.player_loader import load_players_from_csv
    from utils.roster_loader import load_roster

    root = tmp_path / "root"
    data = rds.build_display_league(root, scale=2)
    browse = {p["player_id"]: p for p in twin[1]["players/browse"]["players"]}
    texts = []
    monkeypatch.setattr(callups, "_record", lambda action, **kw: texts.append(kw["details"]))
    monkeypatch.setattr(callups, "_news", lambda message, **kw: texts.append(message))
    with _league(root):
        roster = load_roster("ALB")
        by_id = {p.player_id: p for p in load_players_from_csv(str(data / "players.csv"))}
        pid = next(
            p for p in roster.aaa
            if browse[p]["overall_display"] != callups._player_overall(by_id[p])
        )
        engine = callups._player_overall(by_id[pid])
        callups._promote(
            "ALB", roster, pid, by_id[pid], data_dir=data, current="2026-06-01",
            detail_suffix="", outlook="test",
        )
    shown = browse[pid]["overall_display"]
    assert shown != engine
    assert len(texts) == 2 and all(f"OVR {shown}" in text for text in texts), texts


def test_a_promotion_suggestion_quotes_what_it_is_given(tmp_path, monkeypatch):
    import services.prospect_promotion as promotion

    lines = []
    monkeypatch.setattr(
        "utils.news_logger.log_news_event", lambda message, **kw: lines.append(message)
    )
    entry = {
        "first_name": "A", "last_name": "B", "player_id": "P1",
        "primary_position": "SS", "team_id": "ALB", "age": 21,
        "from_level": "LOW", "to_level": "AAA", "overall": 56,
    }
    promotion._announce_suggestions([entry], tmp_path)
    promotion._announce_suggestions([entry], tmp_path, lambda e: 71)
    assert "OVR 56)" in lines[0] and "OVR 71)" in lines[1]


# --- the display-scale cache --------------------------------------------------

def test_back_to_back_same_size_writes_are_seen(tmp_path):
    from utils.players_file_writes import note_players_file_written
    from utils.rating_display import league_display_scale

    path = tmp_path / "players.csv"
    on_2 = "player_id,is_pitcher,ch,rating_scale\nA,0,50,2\nB,0,50,2\nC,0,50,1\n"
    on_1 = "player_id,is_pitcher,ch,rating_scale\nA,0,50,1\nB,0,50,1\nC,0,50,2\n"
    assert len(on_2) == len(on_1)
    for _ in range(300):
        path.write_text(on_2, encoding="utf-8")
        note_players_file_written(path)
        assert league_display_scale(path) == 2
        path.write_text(on_1, encoding="utf-8")
        note_players_file_written(path)
        assert league_display_scale(path) == 1


def test_every_players_file_writer_tells_the_cache(tmp_path, twin):
    from utils.player_loader import load_players_from_csv
    from utils.player_writer import save_players_to_csv
    from utils.players_file_writes import players_file_write_count

    path = tmp_path / "players.csv"
    players = load_players_from_csv(str(twin[0] / "players.csv"))[:5]
    before = players_file_write_count(path)
    save_players_to_csv(players, path)
    save_players_to_csv(players, path)
    assert players_file_write_count(path) == before + 2
    # The direct writers call the same hook (draft picks appended to the
    # file, the injury-date repair tool, the working copy's file copies).
    for rel, call in (
        ("services/draft_assignment.py", "note_players_file_written(path)"),
        ("scripts/repair_injury_list_dates.py", "note_players_file_written(players_path)"),
        ("api/working_copy.py", "note_players_file_written(dst)"),
    ):
        assert call in (support.REPO / rel).read_text(encoding="utf-8"), rel


# --- edge cases ---------------------------------------------------------------

def test_a_scale_2_archive_on_a_scale_1_page_is_rounded_not_blank(tmp_path):
    import services.player_profile_view_model as vm
    from utils.player_loader import load_players_from_csv

    root = tmp_path / "root"
    data = rds.build_display_league(root)
    # The archived season is stored on scale 2 (a league converted, then
    # put back on its scale 1 backup).
    archive = data / "careers" / rds.ARCHIVED_SEASON / "players.csv"
    support.stretch_players_file(archive, archive)
    with _league(root):
        players = {p.player_id: p for p in load_players_from_csv(str(data / "players.csv"))}
        pid = rds.profile_ids(data)[0]
        history = vm._collect_ratings_history_entries(players[pid], is_pitcher=False, scale=1)
    archived, current = history[0]["ratings"], history[-1]["ratings"]
    assert None not in archived.values()
    for key, value in archived.items():
        assert abs(value - current[key]) <= 1, key


def test_an_unknown_rating_scale_fails_with_a_clear_message(tmp_path):
    from fastapi import HTTPException

    from api.routers import players

    root = tmp_path / "root"
    data = rds.build_display_league(root, scale=2)
    fields, rows = support.read_player_rows(data / "players.csv")
    rows[0]["rating_scale"] = "7"
    support.write_player_rows(data / "players.csv", fields, rows)
    with _league(root):
        calls = (
            lambda: players.list_players(position=None, pitchers_only=False, limit=5000),
            lambda: players.browse_players(
                q=None, team_id=None, position=None, role=None,
                free_agents_only=False, limit=10000,
            ),
        )
        for call in calls:
            with pytest.raises(HTTPException) as caught:
                call()
            assert "rating scale" in caught.value.detail
            assert "restore the file or finish its conversion" in caught.value.detail
