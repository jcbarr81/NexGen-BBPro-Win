"""Rolling a converted league back (docs/rating_scale_switch_runbook.md):
the backup, the exact inverse, and the recorded engine generation."""

from __future__ import annotations

import json

from scripts import rating_scale_rollback
from services import rating_scale_migration as migration
from tests.r8_switch_support import (  # noqa: F401  (scratch is a fixture)
    game_tuning,
    header,
    read_rows,
    scale_log,
    scratch,
    stored_generation,
    switch_on,
    witness,
    write_schedule,
)
from utils.player_loader import _read_players_from_csv
from utils.rating_scale import players_file_rating_scale, stretch_row

MOVED = ("ch", "ph", "eye", "fa", "arm", "control", "movement")


def _prospect():
    return {
        "player_id": "D20260001", "first_name": "A", "last_name": "B",
        "is_pitcher": False, "height": 72, "ch": 45, "ph": 40, "eye": 44,
        "fa": 50, "arm": 50, "pot_ch": 60, "pot_ph": 55, "pot_eye": 50,
    }


def _moved_league(scratch, monkeypatch):
    switch_on(monkeypatch)
    write_schedule(scratch, 2026)
    game_tuning(monkeypatch, "2026-04-01")
    assert players_file_rating_scale(scratch / "players.csv") == 2
    return scratch


def test_rollback_from_the_backup(scratch, monkeypatch):
    original = (scratch / "players.csv").read_bytes()
    pool = scratch / "draft_pool_2026.json"
    pool_text = json.dumps([_prospect()], indent=2)
    pool.write_text(pool_text, encoding="utf-8")
    data = _moved_league(scratch, monkeypatch)
    assert json.loads(pool.read_text())[0]["rating_scale"] == 2
    event = migration.rollback_league(data, mode="backup")
    assert event["event"] == "rolled_back" and event["mode"] == "backup"
    assert (data / "players.csv").read_bytes() == original
    assert scale_log(data)["scale"] == 1
    assert pool.read_text(encoding="utf-8") == pool_text
    assert event["draft_pools"] == ["draft_pool_2026.json"]
    # The season stays on generation 6 (scale 1 plays correctly on it).
    assert stored_generation(data, 2026) == 6
    game_tuning(monkeypatch, "2026-04-02")
    # ... and a league recorded on generation 6 is converted again at its
    # next game unless the generation is set back too: the runbook pairs
    # the two whenever the league must stay on scale 1.
    assert players_file_rating_scale(data / "players.csv") == 2


def test_rollback_by_the_exact_inverse_keeps_every_change(scratch, monkeypatch):
    before = {r["player_id"]: r for r in read_rows(scratch / "players.csv")[1]}
    data = _moved_league(scratch, monkeypatch)
    # A change after the move (an injury, say) must survive the rollback.
    fields, rows = read_rows(data / "players.csv")
    rows[0]["injured"] = "True"
    from tests import rating_scale_support as support

    support.write_player_rows(data / "players.csv", fields, rows)
    migration.rollback_league(data, mode="inverse")
    out_fields, after_rows = read_rows(data / "players.csv")
    assert "height" in out_fields and "height_in" not in out_fields
    assert "rating_scale" not in out_fields
    after = {r["player_id"]: r for r in after_rows}
    assert after[rows[0]["player_id"]]["injured"] == "True"
    for pid, row in before.items():
        for key in MOVED + ("height", "sp", "endurance"):
            if row.get(key) not in ("", None):
                assert float(after[pid][key]) == float(row[key]), (pid, key)
        for key in MOVED:
            pot = row.get(f"pot_{key}")
            if pot in ("", None) or row.get(key) in ("", None):
                continue
            cut = any(
                c.key == f"pot_{key}" for c in stretch_row(row, 2)[1]
            )
            if float(pot) >= float(row[key]) and not cut:
                # A gap that fitted under 99 on scale 2 comes back exactly.
                assert float(after[pid][f"pot_{key}"]) == float(pot), (pid, key)
    players = _read_players_from_csv(data / "players.csv")
    assert {p.rating_scale for p in players} == {1}


def test_the_script_rolls_back_and_sets_the_generation(scratch, monkeypatch, capsys):
    original = (scratch / "players.csv").read_bytes()
    data = _moved_league(scratch, monkeypatch)
    assert rating_scale_rollback.main(["--league-dir", str(data), "--dry-run"]) == 0
    assert "players.scale1.2026.csv" in capsys.readouterr().out
    assert rating_scale_rollback.main(
        ["--league-dir", str(data), "--generation", "5"]
    ) == 0
    assert (data / "players.csv").read_bytes() == original
    assert stored_generation(data, 2026) == 5
    assert witness(data) == ("2026", 5)
    events = [e["event"] for e in scale_log(data)["events"]]
    assert events == ["converted", "rolled_back", "generation_set"]
    # The season now plays generation 5 on scale 1, and stays there.
    from services import league_rating_centers as centers

    centers.clear_rating_center_cache()
    tuning = game_tuning(monkeypatch, "2026-04-02")
    assert tuning.get("range_model", 0.0) == 0.0  # a generation 6 knob, off
    assert stored_generation(data, 2026) == 5
    assert (data / "players.csv").read_bytes() == original
    entry = json.loads((data / "rating_centers.json").read_text())["seasons"]["2026"]
    assert entry["engine_generation"] == 5
