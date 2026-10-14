"""Rollover leaves ratings alone, and spring pitch training is a capped bump.

Until 7.51.2 a rollover added the aging table to every player (an
18-year-old gained 18 Contact, a 25-year-old 11 Power) with no ceiling but
99, and every pitcher had one pitch multiplied by 1.35. Ratings in a league
span about 5 points of spread, so one rollover of a live league's copy put
53 hitters past the league's best Contact. The step is paused until the
rating re-spread brings a development model.
"""

from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from models.pitcher import Pitcher
from playbalance import aging
from playbalance.aging import PITCH_TRAINING_GAIN, spring_training_pitch
from playbalance.player_development import _run_pitch_lab
from services import league_rollover

REPO = Path(__file__).resolve().parents[1]
RATINGS = ("ch", "ph", "sp", "fa", "arm", "control", "endurance", "fb", "sl")


def _league_file(tmp_path: Path) -> Path:
    source = REPO / "data" / "calibration_league" / "players.csv"
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    target = tmp_path / "players.csv"
    target.write_text("".join(lines[:61]), encoding="utf-8")
    return target


def _ratings(path: Path) -> dict[str, tuple[str, ...]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            row["player_id"]: tuple(row.get(key, "") for key in RATINGS)
            for row in csv.DictReader(handle)
        }


def _pitcher(**ratings) -> Pitcher:
    values = dict(
        player_id="p",
        first_name="Test",
        last_name="Pitcher",
        birthdate="2000-01-01",
        height=72,
        weight=180,
        bats="R",
        primary_position="P",
        other_positions=[],
        gf=50,
        fb=60,
    )
    values.update(ratings)
    return Pitcher(**values)


def test_rollover_does_not_change_a_rating(tmp_path, monkeypatch):
    assert league_rollover.YEARLY_AGING_PAUSED is True
    players = _league_file(tmp_path)
    before = players.read_bytes()
    monkeypatch.setattr(league_rollover, "_DATA_DIR", tmp_path)
    monkeypatch.setenv("PB_SIM_YEAR", "2026")

    league_rollover.LeagueRolloverService._apply_yearly_aging(SimpleNamespace())

    assert players.read_bytes() == before


def test_the_pause_is_what_holds_the_ratings(tmp_path, monkeypatch):
    # With the pause lifted the same call rewrites the file with moved
    # ratings, so the test above is not passing for some other reason.
    players = _league_file(tmp_path)
    before = _ratings(players)
    monkeypatch.setattr(league_rollover, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(league_rollover, "YEARLY_AGING_PAUSED", False)
    monkeypatch.setenv("PB_SIM_YEAR", "2026")

    league_rollover.LeagueRolloverService._apply_yearly_aging(SimpleNamespace())

    after = _ratings(players)
    assert set(after) == set(before)
    assert sum(after[pid] != before[pid] for pid in before) > len(before) // 2


def test_pitch_training_adds_a_few_points():
    pitcher = _pitcher(fb=60, potential={"fb": 90})
    spring_training_pitch(pitcher)
    assert pitcher.fb == 60 + PITCH_TRAINING_GAIN
    assert PITCH_TRAINING_GAIN <= 5


def test_pitch_training_stops_at_potential():
    close = _pitcher(fb=60, potential={"fb": 61})
    spring_training_pitch(close)
    assert close.fb == 61

    there = _pitcher(fb=70, potential={"fb": 70})
    spring_training_pitch(there)
    assert there.fb == 70

    # A potential below the current rating never pulls the pitch down.
    past = _pitcher(fb=70, potential={"fb": 64})
    spring_training_pitch(past)
    assert past.fb == 70


def test_pitch_training_intensity_scales_the_gain_under_the_ceiling():
    hard = _pitcher(fb=60, potential={"fb": 90})
    spring_training_pitch(hard, intensity_multiplier=1.35)
    assert hard.fb == 60 + int(round(PITCH_TRAINING_GAIN * 1.35))

    capped = _pitcher(fb=60, potential={"fb": 62})
    spring_training_pitch(capped, intensity_multiplier=1.35)
    assert capped.fb == 62


def test_pitch_lab_reports_the_capped_gain():
    pitcher = _pitcher(fb=60, sl=0, potential={"fb": 62})
    with patch.object(aging.random, "choice", return_value="fb"):
        changes = _run_pitch_lab(pitcher, intensity_multiplier=1.35)
    assert changes == {"fb": 2}
    assert pitcher.fb == 62
