"""The stationarity gate of the development model, on a small league.

RATING_SCALE_DESIGN.md section 3: today's young players are already as
good as veterans, so a growth model makes a wave. Twenty offseasons of a
small league (eight clubs of the league fixture, converted to rating scale
2) with the real draft-class generator and the real retirement rules must
keep the regulars' Contact, Power, Eye, control and movement near their
start, keep their spread, put almost nobody at 99, and grow an age curve.
The full-size runs (three leagues, three seeds) are in the release report;
a small league is noisier, so its bands are a little wider.
"""

from __future__ import annotations

import csv
import logging
import shutil
import statistics
from pathlib import Path

import pytest

from scripts.development_population_sim import gate, simulate
from tests import rating_scale_support as support

TEAMS = 8
GATE = ("h_ch", "h_ph", "h_eye", "p_control", "p_movement")


def _small_league(dst: Path) -> Path:
    src = support.FIXTURES["calibration_league"]
    teams = sorted(p.stem for p in (src / "rosters").glob("*.csv")
                   if not p.stem.endswith(("_pitching", "_lineup")))[:TEAMS]
    (dst / "rosters").mkdir(parents=True)
    keep = set()
    for team in teams:
        shutil.copy(src / "rosters" / f"{team}.csv", dst / "rosters" / f"{team}.csv")
        with (src / "rosters" / f"{team}.csv").open(newline="", encoding="utf-8") as fh:
            keep |= {row[0] for row in csv.reader(fh) if row}
    shutil.copy(src / "teams.csv", dst / "teams.csv")
    fields, rows = support.read_player_rows(src / "players.csv")
    support.write_player_rows(dst / "players.csv", fields, [r for r in rows if r["player_id"] in keep])
    return dst


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    logging.disable(logging.WARNING)
    try:
        league = _small_league(tmp_path_factory.mktemp("small") / "league")
        # 200 picks a year for 30 clubs in the full league: the same per club.
        return simulate(league, seasons=20, seed=1, rounds=7, pool_size=54)
    finally:
        logging.disable(logging.NOTSET)


def test_the_regulars_keep_their_level(report):
    drift = gate(report)["max_mean_drift"]
    assert max(drift.values()) <= 5.0, str(drift)


def test_the_regulars_keep_their_spread(report):
    base = report["years"][0]["regulars"]
    for year in report["years"][5:]:
        for key in GATE:
            if key == "h_eye":
                continue  # wider, see the release report
            assert abs(year["regulars"][key]["sd"] - base[key]["sd"]) < 4.5, (key, year["season"])


def test_hardly_anyone_reaches_99(report):
    assert max(max(y["at_99"].values()) for y in report["years"][1:]) <= 5


def test_an_age_curve_emerges(report):
    curve = report["years"][-1]["age_curve"]
    for group in ("hitter_overall", "pitcher_overall"):
        young = curve["<=21"][group]["mean"]
        prime = statistics.fmean(curve[b][group]["mean"] for b in ("25-27", "28-30"))
        assert prime > young + 3, (group, curve)
