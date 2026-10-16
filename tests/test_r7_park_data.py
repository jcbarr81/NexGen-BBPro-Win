"""Release 6b: the park files generation 7 needs, and what they do to the
others (docs/park_data_generation7_runbook.md).

Production reads park data from the data root's ``parks/`` folder (the
bucket), not from the image. The upload adds ``ParkFences.csv`` and
``ParkHRTargets.csv`` only: ``ParkConfig.csv`` and ``Parks.csv`` stay as
they are, and the two parks only generation 7 knows (Sutter Health Park,
George M. Steinbrenner Field) are named in ``ParkFences.csv`` alone, so no
earlier lookup (the substring fallback included) can reach them. Every
earlier generation reads the uploaded set exactly as today's files; a
generation 7 game refuses to start without ``ParkFences.csv``.
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
    """The park files earlier engines read, without the release's new ones."""
    root = tmp_path / "old"
    (root / "parks").mkdir(parents=True)
    for name in ("ParkConfig.csv", "Parks.csv", "ParkFactors.csv"):
        shutil.copy(PARKS / name, root / "parks" / name)
    return root


def test_the_files_earlier_engines_read_do_not_name_the_new_parks():
    for name in ("ParkConfig.csv", "Parks.csv", "ParkFactors.csv"):
        text = (PARKS / name).read_text(encoding="utf-8")
        for token in ("SAC01", "TAM02", "Sutter", "Steinbrenner"):
            assert token not in text, (name, token)


def test_only_generation_7_finds_the_new_parks(monkeypatch):
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(REPO / "data"))
    ballflight.clear_fence_cache()
    for probe in ("Sutter Health Park", "George M. Steinbrenner Field",
                  "Steinbrenner", "Sutter Health", "Health Park"):
        assert park_utils.stadium_from_name(probe) is None, probe
        assert park_utils._park_info_for_name(probe) is None, probe
    for pid in NEW_PARK_IDS:
        assert park_utils.park_info_for_id(pid) is None
    assert park_utils.park_fence_for_name("Sutter Health Park")[0] == "SAC01"
    assert park_utils.park_fence_for_name("George M. Steinbrenner Field")[0] == "TAM02"
    # A name that is not exact gets no new park from generation 7 either.
    assert park_utils.park_fence_for_name("Health Park") is None


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
    # And every id.
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(old))
    ids = sorted({info.park_id for info in park_utils._load_latest_parks().values()})
    old_ids = {pid: park_utils.park_info_for_id(pid) for pid in ids}
    old_list = park_utils.list_ballpark_names()
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(new))
    assert {pid: park_utils.park_info_for_id(pid) for pid in ids} == old_ids
    assert park_utils.list_ballpark_names() == old_list


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


UPLOADED = ("ParkFences.csv", "ParkHRTargets.csv")
UNCHANGED = ("ParkConfig.csv", "ParkFactors.csv", "Parks.csv")


@pytest.mark.parametrize("generation", [4, 5, 6])
def test_the_bucket_upload_leaves_earlier_generations_identical(
    tmp_path, monkeypatch, generation
):
    """The generation 7 runbook's step 1, as the bucket sees it: the park
    folder as it is today (the three files every engine reads), then the
    same folder with ONLY the two new files added. A legacy, generation 5
    or generation 6 game in a real park, a park with a tall wall, an
    altitude park and the generic park plays to the same digest."""
    # The release changes no file the bucket already holds: data/parks is
    # those three and the two uploaded, nothing else.
    assert sorted(p.name for p in PARKS.iterdir()) == sorted(UNCHANGED + UPLOADED)
    bucket = tmp_path / "bucket"
    (bucket / "parks").mkdir(parents=True)
    for name in UNCHANGED:
        shutil.copy(PARKS / name, bucket / "parks" / name)
    profile = engine_profile(generation, development=True)
    overrides = kpis.with_rating_centers(dict(profile), PLAYERS, CAL) if profile else None
    monkeypatch.setenv(park_utils.PARK_DATA_ROOT_ENV, str(bucket))

    def digests():
        out = []
        for home in ("CAL06", "CAL01", "CAL27", "CAL13"):  # Comerica, Fenway, Coors, Oakland
            game = engine.simulate_matchup_from_files(
                away_team="CAL02", home_team=home, base_dir=CAL, players_path=PLAYERS,
                seed=7, tuning_overrides=dict(overrides) if overrides else None,
            )
            out.append(_digest(game))
        return out

    before = digests()
    for name in UPLOADED:  # the upload: two new files, nothing else touched
        shutil.copy(PARKS / name, bucket / "parks" / name)
    for name in UNCHANGED:
        assert (bucket / "parks" / name).read_bytes() == (PARKS / name).read_bytes()
    ballflight.clear_fence_cache()
    assert digests() == before


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
