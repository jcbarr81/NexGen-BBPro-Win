from __future__ import annotations

import csv
from pathlib import Path

from services import standings_form


def _write_schedule(path: Path, games: list[tuple[str, str, str, int, int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["date", "home", "away", "result", "played", "boxscore"]
        )
        writer.writeheader()
        for date, home, away, hr, ar in games:
            writer.writerow(
                {
                    "date": date,
                    "home": home,
                    "away": away,
                    "result": f"{hr}-{ar}",
                    "played": "1",
                    "boxscore": "",
                }
            )


def test_streak_and_last10_from_schedule(tmp_path, monkeypatch):
    # BOS outcomes (home games): W L W W L W L W W L W W  -> trailing run W2,
    # last10 = last ten outcomes -> 7 W / 3 L.
    seq = ["W", "L", "W", "W", "L", "W", "L", "W", "W", "L", "W", "W"]
    games = []
    for i, outcome in enumerate(seq):
        hr, ar = (5, 3) if outcome == "W" else (2, 4)  # BOS is home
        games.append((f"2026-04-{i + 1:02d}", "BOS", "NYY", hr, ar))
    _write_schedule(tmp_path / "schedule.csv", games)

    monkeypatch.setattr(standings_form, "get_data_dir", lambda: tmp_path)
    out = standings_form.streak_last10_from_schedule()

    assert out["BOS"] == {"streak": "W2", "last10": "7-3"}
    # NYY is the mirror image (the away team in every game).
    assert out["NYY"] == {"streak": "L2", "last10": "3-7"}


def test_unplayed_and_malformed_games_are_skipped(tmp_path, monkeypatch):
    with (tmp_path / "schedule.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["date", "home", "away", "result", "played", "boxscore"]
        )
        writer.writeheader()
        writer.writerow({"date": "2026-04-01", "home": "BOS", "away": "NYY", "result": "4-1", "played": "1", "boxscore": ""})
        writer.writerow({"date": "2026-04-02", "home": "BOS", "away": "NYY", "result": "", "played": "", "boxscore": ""})  # unplayed
        writer.writerow({"date": "2026-04-03", "home": "BOS", "away": "NYY", "result": "3-3", "played": "1", "boxscore": ""})  # tie -> skip

    monkeypatch.setattr(standings_form, "get_data_dir", lambda: tmp_path)
    out = standings_form.streak_last10_from_schedule()

    assert out["BOS"] == {"streak": "W1", "last10": "1-0"}


def test_missing_schedule_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(standings_form, "get_data_dir", lambda: tmp_path)
    assert standings_form.streak_last10_from_schedule() == {}
