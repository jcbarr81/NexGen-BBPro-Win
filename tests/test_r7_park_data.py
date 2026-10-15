"""Release 6b: the park files generation 7 needs, and what they do to the
others (docs/park_data_generation7_runbook.md).

Production reads park data from the data root's ``parks/`` folder (the
bucket), not from the image. The upload adds ``ParkFences.csv`` and
``ParkHRTargets.csv`` and appends two parks to ``ParkConfig.csv`` and
``Parks.csv``. Every earlier generation must read the uploaded set exactly
as it reads today's files; a generation 7 game must refuse to start without
``ParkFences.csv`` instead of falling back to the ParkConfig rows.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

import physics_sim.engine as engine
import scripts.physics_sim_season_kpis as kpis
from physics_sim import ballflight
from physics_sim.config import load_tuning
from physics_sim.engine_generation import engine_profile
from tests.test_r5_discipline import _digest
from utils import park_utils

REPO = Path(__file__).resolve().parents[1]
PARKS = REPO / "data" / "parks"
CAL = REPO / "data" / "calibration"
PLAYERS = CAL / "players.csv"
NEW_PARK_IDS = ("SAC01", "TAM02")


def _old_root(tmp_path: Path) -> Path:
    """The park files as they were before this release: the two appended
    parks taken out, and neither new file."""
    root = tmp_path / "old"
    (root / "parks").mkdir(parents=True)
    for name in ("ParkConfig.csv", "Parks.csv"):
        lines = (PARKS / name).read_bytes().splitlines(keepends=True)
        kept = [line for line in lines if not line.startswith(tuple(p.encode() for p in NEW_PARK_IDS))]
        assert len(lines) - len(kept) == 2, name
        (root / "parks" / name).write_bytes(b"".join(kept))
    shutil.copy(PARKS / "ParkFactors.csv", root / "parks" / "ParkFactors.csv")
    return root


def _new_root(tmp_path: Path) -> Path:
    """The uploaded set: every file of this release's data/parks."""
    root = tmp_path / "new"
    shutil.copytree(PARKS, root / "parks")
    return root


def _read_all(monkeypatch, root: Path, names: list[str]) -> dict:
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(root))
    out = {}
    for name in names:
        stadium = park_utils.stadium_from_name(name)
        out[name] = (
            None if stadium is None else (stadium.left, stadium.center, stadium.right),
            park_utils.park_factor_for_name(name),
            park_utils.park_altitude_for_name(name),
            park_utils.park_foul_territory_for_name(name),
            park_utils.park_lookup_name(name, None),
        )
    return out


def _old_names(root: Path) -> list[str]:
    with (root / "parks" / "ParkConfig.csv").open(newline="", encoding="utf-8") as fh:
        names = {row["NAME"].strip() for row in csv.DictReader(fh) if row.get("NAME")}
    return sorted(names)


def test_every_old_park_reads_the_same_from_the_uploaded_files(tmp_path, monkeypatch):
    old, new = _old_root(tmp_path), _new_root(tmp_path)
    names = _old_names(old)
    assert len(names) > 200
    before = _read_all(monkeypatch, old, names)
    after = _read_all(monkeypatch, new, names)
    assert after == before
    # The only new names a club can choose are the two appended parks.
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(old))
    old_list = set(park_utils.list_ballpark_names())
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(new))
    new_list = set(park_utils.list_ballpark_names())
    assert new_list - old_list == {"Sutter Health Park", "George M. Steinbrenner Field"}
    assert old_list <= new_list


@pytest.mark.parametrize("generation", [4, 5, 6])
def test_an_earlier_generation_plays_the_same_game_on_either_set(
    tmp_path, monkeypatch, generation
):
    old, new = _old_root(tmp_path), _new_root(tmp_path)
    profile = engine_profile(generation, development=True)
    overrides = kpis.with_rating_centers(dict(profile), PLAYERS, CAL) if profile else None
    digests = []
    for root in (old, new):
        monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(root))
        game = engine.simulate_matchup_from_files(
            away_team="CAL01", home_team="CAL06",  # Comerica Park
            base_dir=CAL, players_path=PLAYERS, seed=4,
            tuning_overrides=dict(overrides) if overrides else None,
        )
        digests.append(_digest(game))
    assert digests[0] == digests[1]


def test_generation_7_refuses_a_park_folder_without_its_fences(tmp_path, monkeypatch):
    old, new = _old_root(tmp_path), _new_root(tmp_path)
    seven = kpis.with_rating_centers(engine_profile(7, development=True), PLAYERS, CAL)
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(old))
    with pytest.raises(ballflight.ParkFencesMissing, match="ParkFences.csv"):
        engine.simulate_matchup_from_files(
            away_team="CAL01", home_team="CAL06", base_dir=CAL, players_path=PLAYERS,
            seed=4, tuning_overrides=dict(seven),
        )
    # Generation 6 needs no such file.
    ballflight.require_park_fences(load_tuning(engine_profile(6, development=True)))
    # The uploaded set plays.
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(new))
    ballflight.clear_fence_cache()
    game = engine.simulate_matchup_from_files(
        away_team="CAL01", home_team="CAL06", base_dir=CAL, players_path=PLAYERS,
        seed=4, tuning_overrides=dict(seven),
    )
    assert game.totals["pa"] > 50
    assert ballflight.park_fence(
        engine.load_park("Comerica Park"), load_tuning(seven)
    ).distances[2] == pytest.approx(412.0 + 0.5 * (
        seven["bb6_park_fence_shift_left_ft"]["DET05"]
        + seven["bb6_park_fence_shift_right_ft"]["DET05"]
    ))


def test_every_fitted_park_is_in_generation_7s_fence_file():
    fences = park_utils._load_park_fences_cached(
        park_utils._file_token(PARKS / park_utils.PARK_FENCES_FILE)
    )
    assert set(ballflight.FITTED_PARK_IDS) <= set(fences)
