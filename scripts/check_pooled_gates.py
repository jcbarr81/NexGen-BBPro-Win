"""Apply an engine generation's POOLED gates to a set of season JSONs.

``ENGINE_GATES[N]["pooled"]`` holds gates read as a mean over seeds (one
season's value is too noisy to gate): each metric's mean over the given
seasons must lie within the band of its target. One harness run cannot do
that; this reads the runs' ``--output`` files.

    python scripts/check_pooled_gates.py --engine 7 out/cal.s1.json out/cal.s2.json ...

Exit 1 when a pooled gate fails (or a metric is missing from every file).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _value(payload: dict, key: str) -> float | None:
    for part in (payload.get("metrics") or {}, (payload.get("report_only") or {}).get("metrics") or {}):
        value = part.get(key)
        if isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
    return None


def pooled_results(engine: int, paths: list[Path]) -> list[dict]:
    from scripts.physics_sim_season_kpis import ENGINE_GATES

    gates = ENGINE_GATES.get(engine, {}).get("pooled", {})
    payloads = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    rows = []
    for key, (target, band) in gates.items():
        values = [v for v in (_value(p, key) for p in payloads) if v is not None]
        mean = statistics.fmean(values) if values else None
        rows.append({
            "metric": key, "target": target, "band": band, "seasons": len(values),
            "mean": mean,
            "sd": statistics.stdev(values) if len(values) > 1 else None,
            "ok": mean is not None and abs(mean - target) <= band,
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", type=int, required=True)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    rows = pooled_results(args.engine, args.files)
    for row in rows:
        mean = "-" if row["mean"] is None else f"{row['mean']:.4f}"
        sd = "-" if row["sd"] is None else f"{row['sd']:.4f}"
        print(
            f"{'ok  ' if row['ok'] else 'FAIL'} {row['metric']:36s} mean {mean} (sd {sd},"
            f" {row['seasons']} seasons)  target {row['target']:g} +/- {row['band']:g}"
        )
    return 0 if all(row["ok"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
