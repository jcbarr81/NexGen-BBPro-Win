"""League benchmark ingestion utilities.

The project contains a CSV of aggregated MLB statistics that serve as
target values for tuning the simulation.  This module loads that file into a
plain ``dict`` for convenient lookups used throughout the engine.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict
import csv

from utils.path_utils import get_data_dir, resolve_app_path


BENCHMARK_CSV = get_data_dir() / "MLB_avg" / "mlb_league_benchmarks_2025_filled.csv"


def load_benchmarks(path: str | Path = BENCHMARK_CSV) -> Dict[str, float]:
    """Load benchmark metrics from ``path``.

    Parameters
    ----------
    path:
        CSV file with two columns: ``metric_key`` and ``value``.
    """
    path = Path(path)
    if not path.is_absolute():
        path = resolve_app_path(path)
    benchmarks: Dict[str, float] = {}
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                # Store each metric under its key.  Invalid rows are ignored to
                # keep the loader resilient to partial data sets.
                benchmarks[row["metric_key"]] = float(row["value"])
            except (KeyError, ValueError):
                continue
    return benchmarks


def park_factors(benchmarks: Dict[str, float]) -> Dict[str, float]:
    """Extract park factor metrics from ``benchmarks``.

    Parameters
    ----------
    benchmarks:
        Mapping of metric keys to values as returned by :func:`load_benchmarks`.
    """

    return {
        "overall": benchmarks.get("park_factor_overall", 100.0),
        "1b": benchmarks.get("park_factor_1b", 100.0),
        "2b": benchmarks.get("park_factor_2b", 100.0),
        "3b": benchmarks.get("park_factor_3b", 100.0),
        "hr": benchmarks.get("park_factor_hr", 100.0),
    }


def get_park_factor(
    benchmarks: Dict[str, float], metric: str, park: str | None = None, default: float = 100.0
) -> float:
    """Return the park factor for ``metric``.

    Parameters
    ----------
    benchmarks:
        Mapping of metric keys to values as returned by :func:`load_benchmarks`.
    metric:
        Statistic name such as ``"hr"`` or ``"overall"``.
    park:
        Optional park identifier. When provided the function looks for keys of
        the form ``"{park}_park_factor_{metric}"`` before falling back to the
        league-wide ``"park_factor_{metric}"`` entry.  Missing data returns
        ``default``.
    default:
        Value returned when no matching key exists.
    """

    if park:
        key = f"{park.lower()}_park_factor_{metric}"
        if key in benchmarks:
            return benchmarks[key]
    # Fall back to league-wide factor or provided default.
    return benchmarks.get(f"park_factor_{metric}", default)


def weather_profile(benchmarks: Dict[str, float]) -> Dict[str, float]:
    """Return typical weather conditions from the benchmark data."""
    # Only the mean values are exposed as they are sufficient for most tests.
    return {
        "temperature": benchmarks.get("weather_temp_mean", 72.0),
        "wind_speed": benchmarks.get("wind_speed_mean", 0.0),
    }


def league_averages(benchmarks: Dict[str, float]) -> Dict[str, float]:
    """Return only metrics prefixed with ``avg_`` from ``benchmarks``."""
    # Strip the common ``avg_`` prefix so callers can reference metrics by name.
    return {k[4:]: v for k, v in benchmarks.items() if k.startswith("avg_")}


def league_average(benchmarks: Dict[str, float], metric: str, default: float = 0.0) -> float:
    """Return league average for ``metric`` or ``default`` when missing."""
    # Some benchmark CSVs include metrics without the ``avg_`` prefix.  The
    # lookup first attempts to find the prefixed version and then falls back to
    # the unprefixed key to support both formats.
    return benchmarks.get(f"avg_{metric}", benchmarks.get(metric, default))


__all__ = [
    "load_benchmarks",
    "park_factors",
    "get_park_factor",
    "weather_profile",
    "league_averages",
    "league_average",
]
