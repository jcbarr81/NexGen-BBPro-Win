"""8.0.0 fix-up round after the review and the switch-on rehearsal: one test
(or more) per code fix.

1. The re-spread reads the active rosters the season ENDED with (taken
   before the rollover's contracts), and rotations limited to ACT arms.
2. The scale news item says the conversion changed no player and never
   mixes in the re-spread; the rollover posts a development item; spring
   camp says its gains are the offseason's development.
3. Box scores carry a fielding line from the game's recorded errors.
4. The rollback script counts a file without a rating_scale column.
5. A rollback after the offseason's development withholds scale 1 camp
   gains that spring (players never grow twice).
6. spring_training_last.json carries the league year.
7. Lock and temporary files never travel through the working copy.
12. A re-conversion after a rollback posts a short item of its own.
(8 and 9: tests/test_generated_player_dates.py, tests/test_r8_switch_move.py.)
"""

from __future__ import annotations

import csv
import json
import os
from types import SimpleNamespace

import pytest

from services import league_rating_centers as centers
from services import league_rollover
from services import rating_scale_migration as migration
from tests.r8_switch_support import (
    CALIBRATION_LEAGUE,
    LEAGUE,
    REPO,
    SWITCH,
    _clear,
    game_tuning,
    make_league,
    news,
    read_rows,
    scale_log,
    switch_on,
    write_schedule,
)
from utils.rating_scale import (
    FULL_RATING_SCALE,
    players_file_rating_scale,
    rating_map,
)

FLAT = REPO / "data" / "calibration_flat"


def _scratch(tmp_path, monkeypatch, source):
    monkeypatch.delenv(SWITCH, raising=False)
    data = make_league(tmp_path, monkeypatch, source=source)
    _clear()
    return data


@pytest.fixture
def cleanup():
    yield
    from utils import path_utils

    _clear()
    path_utils._REQUEST_LEAGUE.set(None)
    path_utils._DATA_DIR_CACHE.clear()


def _full_rollover(year):
    from playbalance.season_context import SeasonContext

    ctx = SeasonContext.load()
    ctx.ensure_league(name="Scratch", league_id=LEAGUE)
    ctx.ensure_current_season(league_year=year)
    return league_rollover.LeagueRolloverService(ctx).archive_season(force=True)


def _act_ids(data):
    out = []
    for roster in sorted((data / "rosters").glob("*.csv")):
        if roster.stem.endswith(("_pitching", "_lineup")):
            continue
        for line in roster.read_text(encoding="utf-8").splitlines():
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip().upper() == "ACT":
                out.append(parts[0].strip())
    return out


def _release_a_third_of_the_actives(data):
    """What expiring contracts do to the rosters: a third of each club's ACT
    players leave for free agency."""
    for roster in sorted((data / "rosters").glob("*.csv")):
        if roster.stem.endswith(("_pitching", "_lineup")):
            continue
        lines = roster.read_text(encoding="utf-8").splitlines()
        kept, act = [], 0
        for line in lines:
            parts = line.split(",")
            if len(parts) >= 2 and parts[1].strip().upper() == "ACT":
                act += 1
                if act % 3 == 0:
                    continue
            kept.append(line)
        roster.write_text("\n".join(kept) + "\n", encoding="utf-8")


# --- 1. the re-spread's population -------------------------------------------------

def test_the_rollover_respreads_on_the_rosters_the_season_ended_with(
    tmp_path, monkeypatch, cleanup
):
    data = _scratch(tmp_path, monkeypatch, FLAT)
    write_schedule(data, 2026, played=3)
    game_tuning(monkeypatch, "2026-04-04")
    switch_on(monkeypatch)
    monkeypatch.setenv(migration.RESPREAD_LEAGUES_ENV, LEAGUE)
    ended = migration.respread_population(data)
    assert ended["active_ids"] == sorted(_act_ids(data))
    assert set(ended["rotation_ids"]) <= set(ended["active_ids"])
    dry_run = migration.plan_move(data, respread=True)
    assert dry_run.respread_inputs == ended

    real = league_rollover.rollover_contracts_for_new_season

    def contracts(*args, **kwargs):
        out = real(*args, **kwargs)
        _release_a_third_of_the_actives(data)
        return out

    monkeypatch.setattr(league_rollover, "rollover_contracts_for_new_season", contracts)
    result = _full_rollover(2026)
    assert result.artifacts.get("rating_scale_move") == "converted"
    (event,) = scale_log(data)["events"]
    # The move read the end-of-season population, not the rosters the
    # contract rollover left behind ...
    assert event["respread"]["inputs"] == ended
    assert len(_act_ids(data)) < len(ended["active_ids"])
    # ... so it re-spread exactly what a dry run before the rollover said.
    assert [(r["group"], r["key"]) for r in event["respread"]["ratings"]] == [
        (r.group, r.key) for r in dry_run.respread.moved
    ]
    assert len(event["respread"]["ratings"]) == 12


def test_a_stale_staff_file_does_not_rank_a_departed_pitcher_as_a_starter(
    tmp_path, monkeypatch, cleanup
):
    data = _scratch(tmp_path, monkeypatch, FLAT)
    population = migration.respread_population(data)
    rotation = set(population["rotation_ids"])
    assert rotation and rotation <= set(population["active_ids"])
    # Release one rotation starter from his roster; his club's staff file
    # still names him.
    gone = sorted(rotation)[0]
    for roster in (data / "rosters").glob("*.csv"):
        if roster.stem.endswith(("_pitching", "_lineup")):
            continue
        lines = roster.read_text(encoding="utf-8").splitlines()
        roster.write_text(
            "\n".join(l for l in lines if l.split(",")[0].strip() != gone) + "\n",
            encoding="utf-8",
        )
    assert gone not in migration.respread_population(data)["rotation_ids"]
    # A population handed in is limited to its ACT players as well.
    plan = migration.plan_move(
        data, respread=True,
        population={"active_ids": population["active_ids"][1:],
                    "rotation_ids": population["rotation_ids"]},
    )
    assert set(plan.respread_inputs["rotation_ids"]) <= set(plan.respread_inputs["active_ids"])


# --- 2. what owners are told -------------------------------------------------------

def test_the_scale_item_reports_the_scale_change_alone(tmp_path, monkeypatch, cleanup):
    data = _scratch(tmp_path, monkeypatch, FLAT)
    spread = migration.plan_move(data, respread=True)
    plain = migration.plan_move(data, respread=False)
    assert spread.respread.moved
    # The re-spread changes the converted rows (Control among them) ...
    controls = lambda plan: max(  # noqa: E731
        float(r["control"]) for r in plan.converted if r.get("is_pitcher") in ("1", "True", "true")
    )
    assert controls(spread) != controls(plain)
    # ... but the scale item's numbers are the stretch of the ratings as
    # they were: the same with or without it.
    assert migration._scale_summary(spread) == migration._scale_summary(plain)
    spec = rating_map("control", FULL_RATING_SCALE, pitcher=True)
    item = migration._scale_summary(plain)["Control"]
    assert item["after_max"] == round(spec.stored(item["before_max"]))
    text = migration.engine_and_scale_news(
        migration._scale_summary(spread), players=10, season="2027", backup=None,
        previous_generation=4, respread=True,
    )
    assert "Nobody got better or worse" not in text
    assert "changed no player" in text and "development" in text
    assert "separate item" in text
    assert "separate item" not in migration.engine_and_scale_news(
        {}, players=10, season="2027", backup=None, previous_generation=5,
    )


def test_the_rollover_posts_a_development_item_and_camp_says_whose_gains(
    tmp_path, monkeypatch, cleanup
):
    data = _scratch(tmp_path, monkeypatch, CALIBRATION_LEAGUE)
    write_schedule(data, 2026, played=3)
    game_tuning(monkeypatch, "2026-04-04")
    switch_on(monkeypatch)
    result = _full_rollover(2026)
    developed = json.loads(result.artifacts["development"])
    feed = news(data)
    lines = [l for l in feed.splitlines() if "Offseason development for the 2027 season" in l]
    assert len(lines) == 1
    line = lines[0]
    assert (f"{developed['improved']} players improved and "
            f"{developed['declined']} declined") in line
    assert "Biggest risers:" in line and "Biggest declines:" in line
    # Each named change is "<Rating> <before> to <after>", after = the file.
    rows = {r["player_id"]: r for r in read_rows(data / "players.csv")[1]}
    record = json.loads((data / "development_last.json").read_text(encoding="utf-8"))
    top = max(record["players"].items(), key=lambda kv: sum(kv[1]["changes"].values()))
    pid, entry = top
    key, delta = max(entry["changes"].items(), key=lambda kv: (abs(kv[1]), kv[0]))
    now = int(round(float(rows[pid][key])))
    assert f"{rows[pid]['first_name']} {rows[pid]['last_name']}" in line
    assert f"{now - delta} to {now}" in line
    assert "Nobody got better or worse" not in feed

    # Spring camp: the gains it reports are this offseason's development,
    # and its record carries the league's year.
    from api.routers import season as season_router

    monkeypatch.setattr(season_router, "_maybe_open_preseason_draft", lambda manager: {})
    out = season_router.preseason_training_camp(identity={"r": "admin"})
    assert out["gains_are_offseason_development"] is True
    spring = json.loads((data / "spring_training_last.json").read_text(encoding="utf-8"))
    assert spring["year"] == 2027


# --- 3. box scores -----------------------------------------------------------------

def test_the_box_score_names_each_error_and_the_newer_kinds():
    from playbalance.simulation import (
        boxscore_errors,
        fielding_note,
        render_boxscore_html,
    )

    lookup = {
        "C1": SimpleNamespace(first_name="Ann", last_name="Catcher"),
        "P1": SimpleNamespace(first_name="Bo", last_name="Pitcher"),
        "S1": SimpleNamespace(first_name="Cy", last_name="Short"),
    }
    records = [
        (3, "steal", "C", "C1", "home"),
        (9, "roe", "P", "P1", "home"),
        (12, "roe", "SS", "S1", "away"),
        (15, "relay", "SS", "S1", "away"),
        (20, "steal", "C", "C1", "home"),
    ]
    by_side = boxscore_errors(records, lookup)
    assert fielding_note(by_side["home"]) == "E: Ann Catcher 2 (throw on a steal), Bo Pitcher (comebacker)."
    assert fielding_note(by_side["away"]) == "E: Cy Short 2 (relay throw)."
    assert fielding_note([]) == ""
    for kind, label in (("pickoff", "pickoff throw"), ("of_hit", "misplayed a hit")):
        note = fielding_note(boxscore_errors([(1, kind, "LF", "S1", "away")], lookup)["away"])
        assert label in note
    box = {
        side: {"score": 0, "batting": [], "pitching": [], "fielding": [],
               "inning_runs": [], "errors": by_side[side]}
        for side in ("home", "away")
    }
    html = render_boxscore_html(box, home_name="Home", away_name="Away")
    assert "E: Ann Catcher 2 (throw on a steal), Bo Pitcher (comebacker)." in html
    assert "E: Cy Short 2 (relay throw)." in html
    # A box score without error records (the old simulation) has no line.
    for side in box:
        box[side].pop("errors")
    assert "E: " not in render_boxscore_html(box, home_name="Home", away_name="Away")


def test_the_physics_game_path_hands_the_errors_to_the_box_score():
    import inspect

    from playbalance import game_runner

    source = inspect.getsource(game_runner._run_physics_game)
    assert 'boxscore_errors(' in source and 'play_records' in source
    assert 'box[side]["errors"]' in source


# --- 4 and 5. rollback -------------------------------------------------------------

def _moved_scratch(tmp_path, monkeypatch, source=CALIBRATION_LEAGUE):
    data = _scratch(tmp_path, monkeypatch, source)
    write_schedule(data, 2026, played=3)
    game_tuning(monkeypatch, "2026-04-04")
    switch_on(monkeypatch)
    _full_rollover(2026)
    assert players_file_rating_scale(data / "players.csv") == 2
    return data


def test_the_rollback_script_counts_the_rows_it_wrote(tmp_path, monkeypatch, capsys, cleanup):
    import importlib.util

    data = _moved_scratch(tmp_path, monkeypatch)
    rows = len(read_rows(data / "players.csv")[1])
    spec = importlib.util.spec_from_file_location(
        "rating_scale_rollback", REPO / "scripts" / "rating_scale_rollback.py"
    )
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert script.main(["--league-dir", str(data), "--mode", "inverse"]) == 0
    out = capsys.readouterr().out
    after = [l for l in out.splitlines() if l.startswith("players.csv after:")][0]
    assert after == f"players.csv after: {rows} on scale 1"


def test_a_rollback_after_development_withholds_scale_1_camp_gains(
    tmp_path, monkeypatch, cleanup
):
    from playbalance import training_camp
    from services import offseason_development as od
    from utils.player_loader import load_players_from_csv

    data = _moved_scratch(tmp_path, monkeypatch)
    migration.rollback_league(data, mode="inverse")
    record = od.load_development_record(data)
    assert record.get(od.CAMP_WITHHELD_KEY) is True and record["season"] == 2027
    load_players_from_csv.cache_clear()
    players = list(load_players_from_csv(str(data / "players.csv")))[:60]
    before = [dict(vars(p)) for p in players]
    monkeypatch.setattr(training_camp, "record_training_session", lambda reports: None)
    monkeypatch.setattr(training_camp, "_current_league_year", lambda: 2027)
    reports = training_camp.run_training_camp(players)
    assert all(p.ready for p in players)
    keys = ("ch", "ph", "eye", "sp", "fa", "arm", "control", "movement", "fb", "endurance")
    for old, player in zip(before, players):
        for key in keys:
            assert old.get(key) == getattr(player, key, None), (player.player_id, key)
    assert {r.tier for r in reports} == {od.DEVELOPMENT_TIER}
    # The next spring (another league year) trains as usual.
    monkeypatch.setattr(training_camp, "_current_league_year", lambda: 2028)
    assert training_camp._camp_gains_withheld() is False


# --- 7. the working copy -----------------------------------------------------------

def test_lock_and_temporary_files_never_travel(tmp_path):
    from api import working_copy as wc

    remote = tmp_path / "remote"
    league = remote / "leagues" / "l1" / "data"
    league.mkdir(parents=True)
    for name in ("players.csv", ".players.csv.lock", "season_stats.json.lock",
                 ".players.csv.123.456.tmp", "players.csv.pull.12.34",
                 "news_feed.txt"):
        (league / name).write_text("x", encoding="utf-8")
    pulled = {p.name for p in wc._iter_pull_files(remote)}
    assert pulled == {"players.csv", "news_feed.txt"}
    assert wc._transient(league / ".players.csv.lock")
    assert not wc._transient(league / "rating_scale.json")


# --- 12. a re-conversion after a rollback --------------------------------------------

def test_a_reconversion_after_a_rollback_posts_its_own_short_item(
    tmp_path, monkeypatch, cleanup
):
    data = _scratch(tmp_path, monkeypatch, CALIBRATION_LEAGUE)
    switch_on(monkeypatch)
    migration.convert_league(data, "2026", previous_generation=5)
    migration.rollback_league(data, mode="inverse")
    payload = scale_log(data)
    del payload["hold"]
    (data / "rating_scale.json").write_text(json.dumps(payload), encoding="utf-8")
    migration.clear_caches()
    result = migration.convert_league(data, "2026", previous_generation=6)
    assert result.news == [migration.reconversion_news("2026")]
    feed = news(data)
    assert feed.count("re-converted to the full 1-99 scale after a rollback") == 1
    assert feed.count("now plays on the updated game engine") == 1
