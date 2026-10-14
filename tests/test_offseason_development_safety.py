"""The rollover's development step writes the players file safely.

Review of r8-develop (2026-10-14): retired players were developed; a write
by someone else between read and write was overwritten (only ids were
compared); a season could be developed twice; the file's line ending and
encoding were not kept; unset potentials were filled in; a failure was
silent; the long-term sim developed scale 2 players twice a year. One test
each.
"""

from __future__ import annotations

import csv
import inspect
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import league_rollover
from services import offseason_development as od
from tests import rating_scale_support as support
from tests.test_offseason_development import DEVELOPED, _league, _rows, no_history  # noqa: F401


def _developed(path: Path, season: int = 2027):
    return od.run_offseason_development(
        season_year=season, data_dir=path.parent, as_of=date(season - 1, 10, 31), record=False
    )


def _write(path: Path, fields, rows, ending="\n") -> None:
    with path.open("w", newline="", encoding=od._encoding()) as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator=ending)
        writer.writeheader()
        writer.writerows(rows)


def test_retired_players_are_not_developed(tmp_path, no_history):
    league = _league(tmp_path, scale2=True)
    path = league / "players.csv"
    _, before = _rows(path)
    retired = [row["player_id"] for row in before[:25]]
    (league / "retired_players.json").write_text(
        json.dumps({pid: {"player_id": pid} for pid in retired}), encoding="utf-8"
    )
    summary = _developed(path)
    assert summary["retired_not_developed"] == 25
    _, after = _rows(path)
    assert after[:25] == before[:25]
    assert after[25:] != before[25:]


def test_a_season_is_never_developed_twice(tmp_path, no_history, caplog):
    league = _league(tmp_path, scale2=True)
    path = league / "players.csv"
    assert _developed(path)["improved"] > 0
    once = path.read_bytes()
    with caplog.at_level("INFO", logger=od.__name__):
        again = _developed(path)
    assert again == {"season": 2027, "skipped": "already developed"}
    assert path.read_bytes() == once
    assert "already developed" in caplog.text
    assert _developed(path, 2028)["improved"] > 0  # the next season develops


@pytest.mark.parametrize("ending", ["\r\n", "\n"])
def test_the_files_line_ending_is_kept(tmp_path, no_history, ending):
    league = _league(tmp_path, scale2=True)
    path = league / "players.csv"
    fields, rows = _rows(path)
    _write(path, fields, rows, ending)
    _developed(path)
    data = path.read_bytes()
    assert data.count(b"\r\n") == (data.count(b"\n") if ending == "\r\n" else 0)


def test_the_file_is_read_and_written_in_the_players_writers_encoding(tmp_path, no_history):
    """The product's players loader and writer use the platform encoding;
    a name outside ASCII comes back byte for byte."""

    league = _league(tmp_path, scale2=True)
    path = league / "players.csv"
    fields, rows = _rows(path)
    rows[3]["first_name"], rows[3]["last_name"] = "José", "Muñoz"
    _write(path, fields, rows, "\r\n")
    name = "José,Muñoz".encode(od._encoding())
    assert name in path.read_bytes()
    _developed(path)
    assert name in path.read_bytes()
    from utils.player_loader import _read_players_from_csv

    loaded = {p.player_id: p for p in _read_players_from_csv(path)}
    assert loaded[rows[3]["player_id"]].first_name == "José"


def test_an_unset_potential_stays_unset(tmp_path, no_history):
    """A blank potential reads as the current rating (the loader's rule) and
    a 0 as unset (the trade evaluator's): development gives neither room to
    grow and leaves the cell as it is."""

    league = _league(tmp_path, scale2=True)
    path = league / "players.csv"
    fields, rows = _rows(path)
    hitters = [r for r in rows if r["is_pitcher"] == "0"][:30]
    for row in hitters:
        row["pot_ch"], row["pot_ph"] = "", "0"
    support.write_player_rows(path, fields, rows)
    _developed(path)
    by_id = {r["player_id"]: r for r in _rows(path)[1]}
    for row in hitters:
        new = by_id[row["player_id"]]
        assert new["pot_ch"] == "" and new["pot_ph"] == "0"
        assert int(new["ch"]) <= int(row["ch"]) and int(new["ph"]) <= int(row["ph"])


def _injure(path: Path, victim: str) -> None:
    fields, current = _rows(path)
    for r in current:
        if r["player_id"] == victim:
            r["injured"], r["injury_description"] = "True", "Hamstring strain"
    _write(path, fields, current)


def test_a_write_by_someone_else_is_never_overwritten(tmp_path, no_history, monkeypatch):
    """An injury written while the league develops: the step notices
    immediately before it would replace the file, keeps the injury, and
    develops the new file instead."""

    league = _league(tmp_path, scale2=True)
    path = league / "players.csv"
    _, rows = _rows(path)
    victim = rows[7]["player_id"]
    real = od.develop_row
    calls = {"n": 0}

    def develop_and_interfere(row, **kwargs):
        calls["n"] += 1
        if calls["n"] == 5:  # someone else writes during the first pass
            _injure(path, victim)
        return real(row, **kwargs)

    monkeypatch.setattr(od, "develop_row", develop_and_interfere)
    assert _developed(path)["improved"] > 0
    after = _rows(path)[1]
    hurt = next(r for r in after if r["player_id"] == victim)
    assert (hurt["injured"], hurt["injury_description"]) == ("True", "Hamstring strain")
    assert calls["n"] > len(rows)  # developed again, on the new file
    # Exactly what developing the injured file in one go gives.
    monkeypatch.setattr(od, "develop_row", real)
    clean = _league(tmp_path / "clean", scale2=True)
    _injure(clean / "players.csv", victim)
    _developed(clean / "players.csv")
    assert _rows(clean / "players.csv")[1] == after


def test_a_file_that_keeps_changing_is_left_alone(tmp_path, no_history, monkeypatch):
    league = _league(tmp_path, scale2=True)
    path = league / "players.csv"
    real = od.develop_row
    count = {"n": 0}

    def always_interfere(row, **kwargs):
        count["n"] += 1
        if count["n"] % 50 == 1:
            fields, current = _rows(path)
            current[0]["injury_rehab_days"] = str(count["n"])
            _write(path, fields, current)
        return real(row, **kwargs)

    monkeypatch.setattr(od, "develop_row", always_interfere)
    with pytest.raises(od.OffseasonDevelopmentError, match="kept changing"):
        _developed(path)
    fresh = _rows(_league(tmp_path / "fresh", scale2=True) / "players.csv")[1]
    for old, new in zip(fresh, _rows(path)[1]):
        for key in DEVELOPED & set(old):
            assert new[key] == old[key]  # no rating moved
    assert not (league / od.DEVELOPMENT_RECORD).exists()


def test_a_failed_development_is_logged_recorded_and_told(tmp_path, monkeypatch, caplog):
    saved = []
    record = {"season_id": "lg-2026", "artifacts": {"stats": "x"}}
    service = league_rollover.LeagueRolloverService.__new__(league_rollover.LeagueRolloverService)
    service.context = SimpleNamespace(
        league_id="lg", seasons=[record], save=lambda: saved.append(dict(record))
    )
    monkeypatch.setattr(league_rollover, "_DATA_DIR", tmp_path)
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"artifacts": {"stats": "x"}}), encoding="utf-8")
    with caplog.at_level("ERROR", logger=league_rollover.__name__):
        service._report_development_failure(
            od.OffseasonDevelopmentError("players.csv kept changing"), 2027, metadata
        )
    assert "league lg" in caplog.text and "did not run" in caplog.text
    assert record["artifacts"]["development_error"] == "players.csv kept changing"
    assert saved
    stored = json.loads(metadata.read_text(encoding="utf-8"))
    assert stored["artifacts"]["development_error"] == "players.csv kept changing"
    news = (tmp_path / "news_feed.txt").read_text(encoding="utf-8")
    assert "development did not run for the 2027 season" in news
    assert "players.csv kept changing" in news
    source = inspect.getsource(league_rollover.LeagueRolloverService.archive_season)
    assert "self._report_development_failure(" in source


def test_the_long_term_sim_develops_once_a_year(tmp_path):
    """Its rollover (archive_season) develops scale 2 players; its yearly
    age_and_retire must not develop them again."""

    from playbalance.aging_model import age_and_retire

    league = _league(tmp_path, scale2=True, rows=40)
    players = support.load_player_objects(league)
    before = {pid: dict(vars(p)) for pid, p in players.items()}
    age_and_retire(dict(players), season=2027, develop_scale_2=False)
    for pid, p in players.items():
        assert dict(vars(p)) == before[pid]
    source = (support.REPO / "scripts" / "run_long_term_physics_sim.py").read_text(encoding="utf-8")
    assert "age_and_retire(players, season=year, develop_scale_2=False)" in source
    assert "archive_season(" in source
