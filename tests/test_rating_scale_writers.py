"""Walking the code: every writer of player rows keeps the rating scale.

A writer that drops the ``rating_scale`` column turns a stretched league
into one that reads as scale 1: every rating then plays as the engine's own
(the design measured 4.36 -> 4.60 runs a game). So every file that could
write player rows (``players.csv``, the generator's donor file, a draft
class) is listed here with HOW it keeps the scale, and the walk fails when
a file appears that is not listed.

Behaviour, not just the list: test_rating_scale_rows.py drives the one
writer, the repository, the draft-pool files and the draft append on a
scale 2 league; test_rating_scale_generator.py drives league creation.
"""

from __future__ import annotations

from tests import rating_scale_support as support

REPO = support.REPO

THE_WRITER = "goes through utils.player_writer.save_players_to_csv"
OTHER_FILE = "writes another file, not player rows"
TOOL = "development tool, never run against a league"

PLAYER_ROW_WRITERS = {
    # -- the one writer, and what reaches it
    "utils/player_writer.py": (
        "THE writer: adds the column for a scale that is not 1, refuses a "
        "mixed list"
    ),
    "services/players_repository.py": THE_WRITER,
    "api/routers/admin_league.py": THE_WRITER + " (its DictWriter is schedule.csv)",
    "api/routers/injuries.py": THE_WRITER,
    "api/routers/season.py": THE_WRITER + "; draft pool through save_draft_pool",
    "services/dl_automation.py": THE_WRITER,
    "services/league_rollover.py": THE_WRITER,
    "playbalance/game_runner.py": THE_WRITER,
    "playbalance/league_creator.py": (
        THE_WRITER + ": _dict_to_model carries the generator's scale "
        "(its own csv writers are rosters, staff and teams)"
    ),
    "scripts/run_long_term_physics_sim.py": THE_WRITER + "; save_draft_pool",
    # -- direct writers of player rows
    "services/draft_assignment.py": (
        "appends picks under the file's own header: rows are put on the "
        "file's scale first, a scale 2 pick into a scale 1 file is refused"
    ),
    "playbalance/draft_pool.py": (
        "draft_pool_<year>.csv/.json: one scale per pool, written on every "
        "prospect when it is not 1"
    ),
    "api/routers/draft.py": "draft pool through save_draft_pool",
    "services/rating_scale_migration.py": (
        "the 8.0.0 conversion: reads players.csv raw, writes every row on "
        "scale 2 in the scale 2 format (and open draft pools), atomically; "
        "the rollback writes scale 1 back"
    ),
    "services/offseason_development.py": (
        "rewrites players.csv under its own header (rating_scale kept), only "
        "rating cells changed, ids and row count checked, atomic"
    ),
    "scripts/development_population_sim.py": (
        "temp files of a simulated league, header (rating_scale) kept"
    ),
    # -- not player rows
    "api/routers/trades.py": OTHER_FILE + " (trades_pending.csv)",
    "services/player_retirement.py": OTHER_FILE + " (roster files)",
    "services/departure_cleanup.py": OTHER_FILE + " (lineup and pitching-staff files)",
    "services/report_exporter.py": OTHER_FILE + " (report exports)",
    "services/transaction_log.py": OTHER_FILE + " (transactions.csv)",
    "utils/lineup_autofill.py": OTHER_FILE + " (lineup files)",
    "utils/roster_loader.py": OTHER_FILE + " (roster files)",
    "scripts/benchmark_workflows.py": OTHER_FILE + " (benchmark results)",
    "scripts/collect_batter_decisions.py": OTHER_FILE + " (diagnostics)",
    "scripts/collect_pitch_intent.py": OTHER_FILE + " (diagnostics)",
    "scripts/collect_pitch_survival.py": OTHER_FILE + " (diagnostics)",
    "scripts/dump_season_player_lines.py": OTHER_FILE + " (stat lines)",
    "scripts/injury_rate_kpi.py": OTHER_FILE + " (schedule; players.csv is copied whole)",
    # -- tools that write scale 1 rows by construction
    "playbalance/player_generator.py": TOOL + " (its __main__ exports a sample pool)",
    "scripts/generate_calibration_roster.py": TOOL + ": builds the scale 1 fixture",
    "scripts/generate_league_fixture.py": TOOL + ": builds the scale 1 fixtures",
    "scripts/normalize_players.py": TOOL + ": the donor file, engine scale",
    "scripts/regenerate_seed_players.py": TOOL + ": the seed file, scale 1",
    "scripts/repair_injury_list_dates.py": (
        "rewrites whole rows under the file's own header, so the column "
        "and its values pass through"
    ),
}


def test_every_possible_writer_of_player_rows_is_accounted_for():
    found = {}
    for path in support.code_files():
        reasons = support.scan_player_writer(path)
        if reasons:
            found[path.relative_to(REPO).as_posix()] = reasons
    unlisted = {rel: why for rel, why in found.items() if rel not in PLAYER_ROW_WRITERS}
    assert unlisted == {}, (
        "new code that may write player rows: make it keep the rating_scale "
        "column (or go through save_players) and list it in PLAYER_ROW_WRITERS"
    )
    stale = sorted(set(PLAYER_ROW_WRITERS) - set(found))
    assert stale == [], "no longer writers; drop them from PLAYER_ROW_WRITERS"


def test_the_walk_finds_writers(tmp_path):
    def reasons(source):
        path = tmp_path / "sample.py"
        path.write_text(source, encoding="utf-8")
        return support.scan_player_writer(path)

    assert reasons("import csv\nw = csv.writer(open('x.csv', 'w'))\n") == []
    assert reasons(
        "import csv\np = 'data/players.csv'\nw = csv.DictWriter(open(p, 'w'), [])\n"
    ) == ["DictWriter"]
    assert reasons("from x import save_players\nsave_players([], 'p')\n") == [
        "save_players"
    ]
    assert reasons(
        "import json\nn = f'draft_pool_{1}.json'\njson.dump([], open(n, 'w'))\n"
    ) == ["json.dump"]
    assert reasons("p = 'players.csv'\nopen(p).read()\n") == []


def test_whole_file_copies_keep_the_column(tmp_path):
    """The season archive and the working-copy sync copy players.csv as a
    file; a copy of a scale 2 file is a scale 2 file."""

    import shutil

    from utils.rating_scale import players_file_rating_scale

    twin = tmp_path / "twin"
    support.write_stretched_twin(support.FIXTURES["calibration"], twin)
    copy = tmp_path / "players.scale.csv"
    shutil.copy2(twin / "players.csv", copy)
    assert players_file_rating_scale(copy) == 2
