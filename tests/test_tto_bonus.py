"""S2-07: times-through-order batter familiarity bonus + tto_ops_gap KPI."""
from collections import Counter
from pathlib import Path

import pytest

import scripts.physics_sim_season_kpis as kpis
from physics_sim.config import load_tuning
from physics_sim.engine import _batter_context, simulate_matchup_from_files
from physics_sim.models import BatterRatings, PitcherRatings

CAL = Path("data/calibration")
_TTO_FIELDS = ("pa", "ab", "h", "b1", "b2", "b3", "hr", "bb", "hbp", "sf", "so")


def _batter() -> BatterRatings:
    return BatterRatings.from_row(
        {"player_id": "b", "bats": "R", "primary_position": "LF", "ch": "50",
         "ph": "50", "vl": "50", "eye": "50", "gf": "50", "pl": "50",
         "fa": "50", "arm": "50", "sp": "50"}
    )


def _pitcher() -> PitcherRatings:
    return PitcherRatings.from_row(
        {"player_id": "p", "bats": "R", "throws": "R", "control": "50", "fb": "60"}
    )


def test_batter_context_tto_bonus():
    tuning = load_tuning()
    b, p = _batter(), _pitcher()
    c1 = _batter_context(b, p, tuning, tto=1)
    c3 = _batter_context(b, p, tuning, tto=3)
    # two extra passes * per-pass bonus.
    assert c3["contact"] - c1["contact"] == pytest.approx(2 * tuning.get("tto_contact_bonus"))
    assert c3["eye"] - c1["eye"] == pytest.approx(2 * tuning.get("tto_eye_bonus"))
    assert c3["power"] - c1["power"] == pytest.approx(2 * tuning.get("tto_power_bonus"))
    # tto=1 equals the default (no-kwarg) call.
    assert _batter_context(b, p, tuning) == c1


def test_tto_clamps_at_max_passes():
    tuning = load_tuning()
    b, p = _batter(), _pitcher()
    assert _batter_context(b, p, tuning, tto=6) == _batter_context(b, p, tuning, tto=3)


def test_tto_zero_knobs_neutral():
    tuning = load_tuning({"tto_contact_bonus": 0, "tto_eye_bonus": 0, "tto_power_bonus": 0})
    b, p = _batter(), _pitcher()
    assert _batter_context(b, p, tuning, tto=3) == _batter_context(b, p, tuning, tto=1)


def test_tto_splits_reconcile():
    r = simulate_matchup_from_files(
        away_team="CAL02", home_team="CAL01",
        players_path=CAL / "players.csv", base_dir=CAL,
        park_name="Fenway Park", seed=42,
    )
    splits = r.metadata["tto_splits"]
    agg = Counter()
    for side in ("away", "home"):
        for line in (r.metadata["batting_lines"] or {}).get(side, []):
            for f in _TTO_FIELDS:
                agg[f] += int(line.get(f, 0) or 0)
    ss = Counter()
    for bucket in splits.values():
        for f, v in bucket.items():
            ss[f] += v
    for f in _TTO_FIELDS:
        assert agg[f] == ss.get(f, 0), f"{f}: agg {agg[f]} != split {ss.get(f, 0)}"


def test_tto_ops_gap_direction(monkeypatch):
    import csv

    with (CAL / "teams.csv").open() as fh:
        teams = [r["team_id"] for r in csv.DictReader(fh)][:2]
    monkeypatch.setattr(
        kpis, "_team_ids", lambda *a, **k: [kpis._normalize_team_id(t) for t in teams]
    )
    monkeypatch.setattr(kpis, "_team_parks", lambda *a, **k: {})

    # gap can be None under the 500-PA guard at 20 games, so compute directly
    # from the raw split totals.
    def gap_value(overrides):
        summary = kpis.run_sim(
            games_per_team=20, seed=1, players_path=CAL / "players.csv",
            base_dir=CAL, tuning_overrides=overrides,
        )
        ts = summary["tto_splits"]
        o1 = kpis._split_batter_metrics(Counter(ts["1"]))["ops"]
        o3 = kpis._split_batter_metrics(Counter(ts["3"]))["ops"]
        return o3 - o1

    strong = gap_value({"tto_contact_bonus": 3.0, "tto_eye_bonus": 3.0, "tto_power_bonus": 2.0})
    zero = gap_value({"tto_contact_bonus": 0, "tto_eye_bonus": 0, "tto_power_bonus": 0})
    assert strong > zero
