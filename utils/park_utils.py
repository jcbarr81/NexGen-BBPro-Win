from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

from utils.path_utils import get_data_dir
from playbalance.field_geometry import Stadium


@dataclass(frozen=True)
class ParkInfo:
    park_id: str
    name: str
    year: int
    lf: Optional[float]
    cf: Optional[float]
    rf: Optional[float]
    foul_territory: Optional[str]


def _park_config_path() -> Path:
    base = get_data_dir()
    primary = base / "parks" / "ParkConfig.csv"
    if primary.exists():
        return primary
    return base / "ballparks" / "ParkConfig.csv"


def _park_factors_path() -> Path:
    base = get_data_dir()
    primary = base / "parks" / "ParkFactors.csv"
    if primary.exists():
        return primary
    return base / "ballparks" / "ParkFactors.csv"


def _parks_master_path() -> Path:
    base = get_data_dir()
    primary = base / "parks" / "Parks.csv"
    if primary.exists():
        return primary
    return base / "ballparks" / "Parks.csv"


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
    alt_by_id: dict[str, float] = {}
    alt_by_name: dict[str, float] = {}
    path = _parks_master_path()
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

    latest: Dict[str, ParkInfo] = {}
    path = _park_config_path()
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
    try:
        with path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            best_val: Optional[float] = None
            for row in reader:
                venue = (row.get("Venue") or "").strip()
                if not venue:
                    continue
                key = _norm(venue)
                match = key == target or target in key or key in target
                if not match:
                    continue
                raw = (row.get("Park Factor") or "").replace(",", "").strip()
                try:
                    val = float(raw)
                except ValueError:
                    continue
                # If multiple rows match (e.g., overlapping year ranges), prefer the last one encountered
                best_val = val
            if best_val is None:
                return 1.0
            return best_val / 100.0
    except Exception:
        return 1.0


__all__ = [
    "stadium_from_name",
    "park_factor_for_name",
    "park_altitude_for_name",
    "park_foul_territory_for_name",
    "ParkInfo",
]
