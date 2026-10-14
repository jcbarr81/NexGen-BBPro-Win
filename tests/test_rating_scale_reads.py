"""Walking the code: who reads a moved rating, and who writes player rows.

A league stored on rating scale 2 is only safe if NOTHING that feeds the
game or a decision reads a moved rating (Contact, Power, Eye, fielding, arm,
control, movement) straight off a player object or a ``players.csv`` row.
The identity tests (test_rating_scale_engine.py, _consumers.py) prove the
readers that exist today; this file is what catches the next one.

Rule for new code: read a rating with ``utils.rating_scale.engine_rating``
(or ``engine_potential``), or a whole row with ``engine_row``. Where the
STORED value really is what you want (showing it, copying it), say so on the
line: ``# rating-scale: <why>``. A whole file is exempt only through
``STORED_VALUE_FILES`` below, with its reason.

Limits, stated plainly: the walk sees attribute reads and string literals.
It does not see ``getattr(player, key)`` where ``key`` arrives from another
module; every key list in this repository is a literal and is seen.
"""

from __future__ import annotations

import ast

import pytest

from tests import rating_scale_support as support

REPO = support.REPO

# Files that hold or handle STORED values by design, or sit behind the row
# boundary. Anything else must have no unreviewed read.
STORED_VALUE_FILES = {
    # -- the scale itself, and row <-> object
    "utils/rating_scale.py": "the map and the accessors",
    "utils/player_loader.py": "row to object: objects hold stored values",
    "utils/player_writer.py": "object to row: writes stored values",
    "models/player.py": "field declarations",
    "models/pitcher.py": "field declarations",
    # -- behind the row boundary: BatterRatings / PitcherRatings are built
    #    by from_row, which un-stretches the row first
    "physics_sim/models.py": "from_row calls engine_row before reading",
    "physics_sim/engine.py": "reads BatterRatings / PitcherRatings",
    "physics_sim/fielding.py": "reads BatterRatings",
    "physics_sim/physics.py": "reads engine rating contexts",
    "physics_sim/arm_injury.py": "\"arm\" is an injury stream name",
    "services/league_rating_centers.py": "rows go through engine_row at the parse",
    "scripts/kpi_extras.py": "rows come from engine_rows",
    "scripts/physics_sim_season_kpis.py": "rows come from engine_rows",
    # -- what an owner is shown: stored values, owned by the display step
    "utils/rating_display.py": "display: percentile blend of stored ratings",
    "services/player_profile_view_model.py": "display: the profile page",
    "services/career_arc_analytics.py": "report export: shows stored ratings",
    "services/training_settings.py": "\"movement\" is a training track name",
    # -- changes ratings
    "playbalance/aging.py": "scale 1 aging (paused since 7.51.2); refuses scale 2",
    "playbalance/player_development.py": "scale 1 training camp; refuses scale 2",
    "playbalance/development.py": "the scale 2 development model: stored points, maps itself",
    "scripts/development_population_sim.py": "measures stored ratings of a simulated league",
    # -- engine scale by construction
    "playbalance/player_generator.py": "builds on the engine scale; one stretch at the end",
    "playbalance/archetypes.py": "not imported by production code",
    "scripts/generate_calibration_roster.py": "fixture tool: writes scale 1 rows",
    "scripts/generate_league_fixture.py": "fixture tool: writes scale 1 rows",
    "scripts/normalize_players.py": "donor-file tool: engine scale",
    "scripts/regenerate_seed_players.py": "seed-file tool: scale 1 rows",
    # -- the archived engine: GameSimulation refuses a player not on scale 1
    "playbalance/simulation.py": "archived engine (refuses scale 2)",
    "playbalance/batter_ai.py": "archived engine",
    "playbalance/pitch_resolution.py": "archived engine",
    "playbalance/substitution_manager.py": "archived engine",
    "playbalance/substitutions.py": "archived engine",
}


def _rel(path) -> str:
    return path.relative_to(REPO).as_posix()


def test_no_unreviewed_read_of_a_moved_rating():
    offenders = {}
    for path in support.code_files():
        rel = _rel(path)
        if rel in STORED_VALUE_FILES:
            continue
        hits = support.scan_rating_reads(path)
        if hits:
            offenders[rel] = [f"{line}: {text}" for line, text in hits]
    assert offenders == {}, (
        "direct reads of a moved rating; use utils.rating_scale.engine_rating "
        "or mark the line '# rating-scale: <why the stored value is right>'"
    )


def test_the_exempt_list_is_not_stale():
    files = {_rel(path) for path in support.code_files()}
    for rel in STORED_VALUE_FILES:
        assert rel in files, f"{rel} is gone; drop it from STORED_VALUE_FILES"
        assert support.scan_rating_reads(REPO / rel), (
            f"{rel} no longer reads a moved rating; drop it from STORED_VALUE_FILES"
        )


def test_the_walk_sees_what_it_should(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from utils.rating_scale import engine_rating, engine_potential\n"
        "KEYS = ('ch', 'sp')\n"                        # 2: literal key list
        "def a(p):\n"
        "    return p.ch + p.sp\n"                      # 4: attribute
        "def b(p):\n"
        "    return getattr(p, 'control', 0)\n"         # 6: getattr literal
        "def c(row):\n"
        "    return row['pot_arm'], row.get('movement')\n"  # 8
        "def ok(p):\n"
        "    x = engine_rating(p, 'ch', 0) + engine_potential(p, 'ph')\n"
        "    y = p.gf + p.endurance + getattr(p, 'fb', 0)\n"
        "    return x, y, p.eye  # rating-scale: shown to the owner\n"
        "# rating-scale: copies stored values\n"
        "def copy(p):\n"
        "    return {'fa': p.fa, 'arm': p.arm}\n"
        "def d(p):\n"
        "    # rating-scale: keys read through engine_rating below\n"
        "    if p.is_pitcher:\n"
        "        keys = ('arm', 'control')\n"
        "    return [engine_rating(p, k) for k in keys]\n",
        encoding="utf-8",
    )
    assert [line for line, _ in support.scan_rating_reads(sample)] == [2, 4, 6, 8]


# --- the row boundary is where the design says it is ------------------------

def _calls(tree, names):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in names:
                found.add(name)
    return found


def _functions(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


# Functions that parse some OTHER csv (schedule, lineups, benchmarks).
OTHER_CSV_READERS = {
    "services/league_rating_centers.py": {
        "_read_season_started", "_saved_lineup_rows", "_saved_lineup_ids",
    },
    "scripts/physics_sim_season_kpis.py": {"_load_benchmarks"},
    "scripts/kpi_extras.py": {"_load_lineup_positions", "load_reference"},
}


@pytest.mark.parametrize("rel", sorted(OTHER_CSV_READERS))
def test_every_player_row_parse_on_the_engine_side_converts(rel):
    """In the centres and the harness, a function that parses a CSV either
    reads another file (listed above) or reads rows as the engine does."""

    raw, converting = [], []
    for function in _functions(REPO / rel):
        calls = _calls(function, {"DictReader", "engine_row", "engine_rows"})
        if calls & {"engine_row", "engine_rows"}:
            converting.append(function.name)
        elif "DictReader" in calls:
            raw.append(function.name)
    assert sorted(raw) == sorted(OTHER_CSV_READERS[rel])
    assert len(converting) >= 2


def test_the_engines_row_constructors_convert_first():
    for function in _functions(REPO / "physics_sim" / "models.py"):
        if function.name != "from_row":
            continue
        first = function.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            first = function.body[1]  # past a docstring
        assert isinstance(first, ast.Assign), ast.dump(first)
        assert _calls(ast.Module(body=[first], type_ignores=[]), {"engine_row"})
    # Nothing else in the engine package parses player rows itself.
    for path in sorted((REPO / "physics_sim").glob("*.py")):
        for function in _functions(path):
            if "DictReader" in _calls(function, {"DictReader"}):
                assert (path.name, function.name) in {
                    ("data_loader.py", "load_players"),  # -> from_row
                    ("team_data.py", "load_lineup"),  # a lineup file
                }, (path.name, function.name)


# Readers handed to the shared overall (utils.player_overall and
# compute_overall). The overall asks the reader itself for the row's
# ``rating_scale`` and ``is_pitcher``; a reader over a few picked-out
# ratings cannot answer and would be scored as scale 1. Each of these reads
# the whole player object or the whole row.
OVERALL_READERS = {
    ("api/routers/_rating_presentation.py", "get_raw"),  # its caller's reader
    ("api/routers/contracts.py", "lambda key: getattr(player, key, None)"),
    ("api/routers/draft.py", "lambda k, p=player: getattr(p, k, None)"),
    ("api/routers/free_agency.py", "lambda k: getattr(player, k, None)"),
    ("api/routers/players.py", "lambda k: _row_raw_int(row, k)"),
    ("api/routers/roster.py", "lambda k: getattr(player, k, None)"),
    ("services/player_profile_view_model.py", "lambda key: getattr(player, key, None)"),
    ("utils/rating_display.py", "row.get"),
    ("utils/player_overall.py", "get_raw"),  # overall_score passes it down
}
OVERALL_FUNCTIONS = {
    "compute_overall", "_compute", "overall_score",
    "hitter_overall_score", "pitcher_overall_score",
}


def test_every_reader_handed_to_the_overall_can_tell_the_rows_scale():
    seen = set()
    for path in support.code_files():
        text = path.read_text(encoding="utf-8-sig")
        if not any(name in text for name in OVERALL_FUNCTIONS):
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name not in OVERALL_FUNCTIONS:
                continue
            reader = ast.get_source_segment(text, node.args[0]) or ""
            if name == "overall_score" and reader == "pid":
                continue  # utils.lineup_autofill's own per-player callable
            seen.add((_rel(path), " ".join(reader.split())))
    assert seen == OVERALL_READERS


def test_the_archived_engine_refuses_a_scale_2_player():
    from playbalance import simulation
    from types import SimpleNamespace

    def team(scale):
        player = SimpleNamespace(player_id="X", rating_scale=scale)
        return SimpleNamespace(lineup=[player], bench=[], pitchers=[])

    with pytest.raises(RuntimeError, match="rating scale 2"):
        simulation.GameSimulation(team(1), team(2), config=None)


def test_training_camp_never_trains_a_scale_2_player(tmp_path, monkeypatch):
    """Training adds engine-sized points to stored values. A scale 2 player
    develops at the rollover instead (playbalance.development): camp marks
    him ready and leaves his ratings alone, while the scale 1 mechanics
    still refuse him outright."""

    import copy

    from playbalance import player_development, training_camp

    monkeypatch.setattr(training_camp, "record_training_session", lambda reports: None)
    monkeypatch.setattr(training_camp, "_offseason_development", lambda: {})
    league = support.copy_league(support.FIXTURES["calibration_league"], tmp_path / "lg")
    support.write_stretched_twin(league, tmp_path / "twin")
    plain = list(support.load_player_objects(league).values())[:6]
    full = list(support.load_player_objects(tmp_path / "twin").values())[:3]
    before = copy.deepcopy(full)
    reports = training_camp.run_training_camp(plain + full)
    assert len(reports) == 9
    for player, was in zip(full, before):
        assert player.ready
        assert {k: v for k, v in vars(player).items() if k != "ready"} == {
            k: v for k, v in vars(was).items() if k != "ready"
        }
    assert [r.changes for r in reports[6:]] == [{}, {}, {}]
    for call in (
        lambda: player_development.execute_training_cycle(full),
        lambda: player_development.build_training_plan(full[0]),
    ):
        with pytest.raises(RuntimeError, match="rating scale 2"):
            call()
    # A scale 1 camp runs as it always did.
    reports = player_development.execute_training_cycle(copy.deepcopy(plain))
    assert len(reports) == 6


def test_the_archived_loader_reads_rows_on_the_engine_scale(tmp_path):
    from playbalance import player_loader

    path = tmp_path / "players.csv"
    path.write_text(
        "player_id,first_name,last_name,is_pitcher,ch,pl,fb,sl,control,movement,"
        "rating_scale\n"
        "H,A,B,0,62,50,,,,,2\n"
        "P,C,D,1,,,70,60,95,53,2\n"
        "Q,E,F,1,,,70,60,95,53,\n",
        encoding="utf-8",
    )
    players = player_loader.load_players(path)
    assert players["H"].ratings["contact"] == 54
    assert players["P"].ratings["control"] == 69
    assert players["P"].ratings["movement"] == 55
    assert players["Q"].ratings["control"] == 95  # a scale 1 row, as it is
