from __future__ import annotations

import ast
import csv
import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

from utils.path_utils import get_base_dir, get_data_dir, get_data_root
from playbalance.field_geometry import Stadium


def _file_token(path: Path) -> tuple[str, int, int]:
    """A (path, mtime_ns, size) cache key — lets the park loaders below memoize
    their CSV parse and re-read only when the file actually changes. Park data
    is static during a sim, so this turns repeated per-game parses (which the
    profiler showed were ~25% of a game's wall time) into one parse per file."""
    try:
        st = path.stat()
        return (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(path), 0, 0)


@dataclass(frozen=True)
class ParkInfo:
    park_id: str
    name: str
    year: int
    lf: Optional[float]
    cf: Optional[float]
    rf: Optional[float]
    foul_territory: Optional[str]


def _park_data_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()

    for root in (get_data_dir(), get_data_root(), get_base_dir() / "data"):
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def _find_park_data_file(filename: str) -> Path:
    for root in _park_data_roots():
        candidate = root / "parks" / filename
        if candidate.exists():
            return candidate
        legacy = root / "ballparks" / filename
        if legacy.exists():
            return legacy
    return get_data_dir() / "parks" / filename


def _park_config_path() -> Path:
    return _find_park_data_file("ParkConfig.csv")


def _park_factors_path() -> Path:
    return _find_park_data_file("ParkFactors.csv")


def _parks_master_path() -> Path:
    return _find_park_data_file("Parks.csv")


def _norm(s: str) -> str:
    s = s.lower().strip()
    # Remove punctuation and collapse whitespace
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_float(v: str) -> Optional[float]:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _load_parks_master() -> tuple[dict[str, float], dict[str, float]]:
    path = _parks_master_path()
    if not path.exists():
        return {}, {}
    return _load_parks_master_cached(_file_token(path))


@functools.lru_cache(maxsize=32)
def _load_parks_master_cached(
    token: tuple[str, int, int],
) -> tuple[dict[str, float], dict[str, float]]:
    alt_by_id: dict[str, float] = {}
    alt_by_name: dict[str, float] = {}
    path = Path(token[0])
    if not path.exists():
        return alt_by_id, alt_by_name
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            park_id = (row.get("PARKID") or row.get("ParkID") or "").strip()
            name = (row.get("NAME") or row.get("Name") or "").strip()
            altitude = _parse_float(row.get("Altitude", ""))
            if altitude is None:
                continue
            if park_id:
                alt_by_id[park_id] = altitude
            if name:
                alt_by_name[_norm(name)] = altitude
    return alt_by_id, alt_by_name


def _load_latest_parks() -> Dict[str, ParkInfo]:
    """Return a mapping of normalized park name -> ParkInfo (latest year)."""
    path = _park_config_path()
    if not path.exists():
        return {}
    return _load_latest_parks_cached(_file_token(path))


@functools.lru_cache(maxsize=32)
def _load_latest_parks_cached(token: tuple[str, int, int]) -> Dict[str, ParkInfo]:
    latest: Dict[str, ParkInfo] = {}
    path = Path(token[0])
    if not path.exists():
        return latest
    with path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                year = int(row.get("Year") or 0)
            except Exception:
                continue
            name = (row.get("NAME") or row.get("Name") or "").strip()
            pid = (row.get("parkID") or row.get("ParkID") or "").strip()
            if not name:
                continue
            info = ParkInfo(
                park_id=pid,
                name=name,
                year=year,
                lf=_parse_float(row.get("LF_Dim", "")),
                cf=_parse_float(row.get("CF_Dim", "")),
                rf=_parse_float(row.get("RF_Dim", "")),
                foul_territory=(row.get("Foul") or "").strip() or None,
            )
            key = _norm(name)
            prev = latest.get(key)
            if prev is None or info.year > prev.year:
                latest[key] = info
    return latest


def _load_legacy_ballpark_names() -> list[str]:
    for root in _park_data_roots():
        path = root / "ballparks.py"
        if not path.exists():
            continue
        try:
            module_ast = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception:
            continue
        for node in module_ast.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "BALLPARKS":
                    try:
                        values = ast.literal_eval(node.value)
                    except Exception:
                        continue
                    names = [
                        str(value).strip()
                        for value in values
                        if str(value).strip()
                    ]
                    if names:
                        return sorted(set(names))
    return []


def list_ballpark_names() -> list[str]:
    """Return sorted unique park display names from ParkConfig."""

    try:
        parks = _load_latest_parks()
    except Exception:
        return []
    names = {info.name.strip() for info in parks.values() if info.name.strip()}
    sorted_names = sorted(names)
    if sorted_names:
        return sorted_names
    return _load_legacy_ballpark_names()


def stadium_from_name(name: str) -> Stadium | None:
    """Build a Stadium from ParkConfig for a given display name.

    Returns None when no match is found.
    """

    if not name:
        return None
    parks = _load_latest_parks()
    target = _norm(name)
    info = _park_info_for_name(name)
    if info is None:
        return None
    # Require at least one dimension to be present; otherwise return None
    if info.lf is None and info.cf is None and info.rf is None:
        return None
    # Compose Stadium; use defaults for any missing single fields
    return Stadium(
        left=info.lf if info.lf is not None else Stadium.left,
        center=info.cf if info.cf is not None else Stadium.center,
        right=info.rf if info.rf is not None else Stadium.right,
    )


def _park_info_for_name(name: str) -> ParkInfo | None:
    if not name:
        return None
    parks = _load_latest_parks()
    target = _norm(name)
    info = parks.get(target)
    if info is None:
        for key, value in parks.items():
            if target in key or key in target:
                info = value
                break
    return info


def park_altitude_for_name(name: str) -> float:
    if not name:
        return 0.0
    alt_by_id, alt_by_name = _load_parks_master()
    info = _park_info_for_name(name)
    if info and info.park_id:
        altitude = alt_by_id.get(info.park_id)
        if altitude is not None:
            return altitude
    altitude = alt_by_name.get(_norm(name))
    if altitude is not None:
        return altitude
    return 0.0


def park_foul_territory_for_name(name: str) -> float:
    info = _park_info_for_name(name)
    if not info or not info.foul_territory:
        return 1.0
    raw = info.foul_territory.strip().upper()
    if raw in {"L", "N", "S"}:
        return {"L": 1.15, "N": 1.0, "S": 0.9}[raw]
    value = _parse_float(raw)
    if value is None:
        return 1.0
    scale = value / 25.0
    return max(0.75, min(1.35, scale))
    return 1.0


@functools.lru_cache(maxsize=32)
def _load_park_factor_rows_cached(
    token: tuple[str, int, int],
) -> tuple[tuple[str, float], ...]:
    """Parse ParkFactors.csv into ordered (norm_venue, factor_value) rows, cached
    by file token. Preserves file order so park_factor_for_name's last-match-wins
    behavior is byte-identical."""
    rows: list[tuple[str, float]] = []
    path = Path(token[0])
    if not path.exists():
        return tuple()
    try:
        with path.open("r", newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                venue = (row.get("Venue") or "").strip()
                if not venue:
                    continue
                raw = (row.get("Park Factor") or "").replace(",", "").strip()
                try:
                    val = float(raw)
                except ValueError:
                    continue
                rows.append((_norm(venue), val))
    except Exception:
        return tuple()
    return tuple(rows)


def park_factor_for_name(name: str) -> float:
    """Return overall park factor (1.0 = neutral) for a venue name.

    Falls back to 1.0 when not found.
    """

    if not name:
        return 1.0
    target = _norm(name)
    path = _park_factors_path()
    if not path.exists():
        return 1.0
    best_val: Optional[float] = None
    for key, val in _load_park_factor_rows_cached(_file_token(path)):
        # Exact OR substring match; last matching row wins (matches the prior
        # single-pass loop over the CSV exactly).
        if key == target or target in key or key in target:
            best_val = val
    if best_val is None:
        return 1.0
    return best_val / 100.0


__all__ = [
    "stadium_from_name",
    "park_factor_for_name",
    "park_altitude_for_name",
    "park_foul_territory_for_name",
    "list_ballpark_names",
    "ParkInfo",
]
