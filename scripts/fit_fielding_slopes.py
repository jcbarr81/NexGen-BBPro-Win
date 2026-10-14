"""Re-fit the Release 6a fielding numbers from logged chances.

``range_model`` 1 moves a ball's neutral out chance ``out0`` in log-odds by
the responsible fielder's rating, so a rating point is worth, to first
order, ``slope * out0 * (1 - out0)`` of an out on each of his balls. The
slope that makes a point worth ``T[pos]`` outs per 150 games is therefore

    slope[pos] = T[pos] / (babip_scale * sum of out0 * (1 - out0))

summed over that position's balls per 150 team-games, a line drive counting
``range_ld_ratio`` of itself (RELEASE6_PLAN.md 2.3; the design brief's
``derive.py``). ``out0`` and who a ball belongs to do not depend on the
slopes, so one logged season per fixture is the whole fit; the slopes agree
within a few percent across fixtures and the mean is the answer.

The same seasons give the two other numbers that hang on where the balls
go:

* the infield band cut points (``infield_band_*_min_deg``) that hand each
  infielder his target share of the ground balls, read off the ground
  balls' directions;
* the error bases (``error_base_<pos>``) that put each position on its
  target errors per team-game, from the error chances the season rolled:
  ``base * target / expected`` (only with ``--error-targets``; the bases
  the season was played with are re-levelled, so run it under
  ``error_model`` 1 or 2).

Re-run it whenever the batted ball changes (the spray fix, the band cut
points, the ball-flight step): every one of them moves ``out0`` or the
shares. Either play the seasons here::

    python scripts/fit_fielding_slopes.py --engine 6 \
        --tuning-overrides scripts/kpi_profiles/r6_fielding.json \
        --fixture data/calibration data/calibration_league \
        data/calibration_flat --seeds 1

or read seasons the KPI harness already wrote (``--from-json a.json ...``;
they must have been played with ``range_model`` 1, which is what makes the
logged average chance ``out0`` and gives each ball one responsible
fielder). Seasons played here have ``range_model`` 1 forced on. Nothing is
written to a profile: the numbers are printed (and saved with
``--output``) for whoever retunes to put in.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Range outs one rating point is worth per 150 games, by position. With
# the error slope beside it (measured on the built model: about .20 a
# point at first, .31 at second, .35 at third, .45 at short and .04-.07 in
# the outfield) a rating SD on the wide fixtures comes to 5-7 outs, first
# base 4-5 (owner decision 10), with shortstop and centre field worth at
# least as many runs a point as the corners. The design brief's budget,
# moved a little where the built model's errors asked for it: second .41
# -> .46, short .44 -> .42, first .30 -> .28; left .64 -> .65 and centre
# .825 -> .84 (the two fixtures' fa spreads there differ by more than the
# band is wide, so they sit at its two edges).
RANGE_BUDGET = {
    "1B": 0.28, "2B": 0.46, "3B": 0.40, "SS": 0.42,
    "LF": 0.65, "CF": 0.84, "RF": 0.64,
}
# Share of ground balls by infielder, 3B to 1B across the diamond (the
# plan's .20 / .29 / .07 / .27 / .14, which leave .03 for the catcher; the
# engine gives him no batted ball, so they are scaled to sum to 1).
BAND_SHARES = (("3B", 0.20), ("SS", 0.29), ("P", 0.07), ("2B", 0.27), ("1B", 0.14))
BAND_KEYS = {
    "3B": "infield_band_3b_min_deg",
    "SS": "infield_band_ss_min_deg",
    "P": "infield_band_p_min_deg",
    "2B": "infield_band_2b_min_deg",
}


def fit_slopes(
    sums: dict[str, Any], *, babip_scale: float, ld_ratio: float
) -> dict[str, float]:
    """``range_logit_slope_<pos>`` for one season's ``fielding_chance_sums``."""
    team_games = float(sums.get("team_games") or 0.0)
    slopes: dict[str, float] = {}
    for pos, budget in RANGE_BUDGET.items():
        row = (sums.get("by_position") or {}).get(pos) or {}
        spread = float(row.get("spread", 0.0)) + ld_ratio * float(
            row.get("spread_ld", 0.0)
        )
        if team_games <= 0.0 or spread <= 0.0:
            continue
        per_150 = spread * 150.0 / team_games
        slopes[pos] = budget / (babip_scale * per_150)
    return slopes


def fit_bands(sums: dict[str, Any]) -> dict[str, float]:
    """The band lower bounds that give ``BAND_SHARES``, from the season's
    ground balls by direction (0.5 degree bins, interpolated inside one)."""
    bins = sorted(
        ((float(k), float(v)) for k, v in (sums.get("grounder_direction") or {}).items()),
        reverse=True,
    )
    total = sum(count for _, count in bins)
    if total <= 0.0:
        return {}
    bounds: dict[str, float] = {}
    wanted = 0.0
    seen = 0.0
    index = 0
    whole = sum(share for _, share in BAND_SHARES)
    for pos, share in BAND_SHARES[:-1]:
        wanted += share / whole * total
        while index < len(bins) and seen + bins[index][1] < wanted:
            seen += bins[index][1]
            index += 1
        if index >= len(bins):
            break
        low, count = bins[index]
        # The bin covers [low, low + 0.5); balls are taken from its top.
        inside = (wanted - seen) / count if count else 0.0
        bounds[pos] = round(low + 0.5 * (1.0 - inside), 2)
    return bounds


def band_shares(sums: dict[str, Any]) -> dict[str, float]:
    """The share of ground balls each band owner was given in the season."""
    balls = {
        pos: float(row.get("balls_gb", 0.0))
        for pos, row in (sums.get("by_position") or {}).items()
    }
    total = sum(balls.values())
    return {pos: n / total for pos, n in balls.items() if n and total}


def fit_error_bases(
    report: dict[str, Any], targets: dict[str, float], bases: dict[str, float]
) -> dict[str, float]:
    """``error_base_<pos>`` re-levelled to ``targets`` (errors per team-game
    on batted balls, by the position charged): the base the season was
    played with times target over what the season charged."""
    charged = (report.get("tables") or {}).get("errors_by_source") or {}
    by_source = charged.get("by_source") or {}
    team_games = float(
        ((report.get("tables") or {}).get("fielding_chance_sums") or {}).get(
            "team_games"
        )
        or 0.0
    )
    out: dict[str, float] = {}
    for pos, target in targets.items():
        errors = float((by_source.get("roe") or {}).get(pos, 0.0))
        if pos == "P":
            errors = float((by_source.get("comebacker") or {}).get("P", 0.0))
        base = bases.get(pos)
        if not errors or not team_games or base is None:
            continue
        out[pos] = base * target / (errors / team_games)
    return out


def _season_report(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    overrides = dict((data.get("meta") or {}).get("tuning_overrides") or {})
    return data.get("report_only") or {}, overrides


def _play(
    fixture: Path, seed: int, overrides: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    import scripts.physics_sim_season_kpis as kpis

    played = dict(overrides)
    played["range_model"] = 1.0
    summary = kpis.run_sim(
        162, seed, fixture / "players.csv", tuning_overrides=played, base_dir=fixture
    )
    return summary.get("report_only") or {}, played


def _mean(rows: list[dict[str, float]]) -> dict[str, float]:
    keys = sorted({key for row in rows for key in row})
    return {
        key: statistics.fmean(row[key] for row in rows if key in row) for key in keys
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fixture", type=Path, nargs="*", default=[])
    parser.add_argument("--seeds", type=int, nargs="*", default=[1])
    parser.add_argument("--engine", type=int, default=None)
    parser.add_argument("--tuning-overrides", type=Path, default=None)
    parser.add_argument("--from-json", type=Path, nargs="*", default=[])
    parser.add_argument(
        "--error-targets", type=Path, default=None,
        help="JSON {position: errors per team-game on batted balls}",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    from physics_sim.config import load_tuning

    seasons: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for path in args.from_json:
        report, overrides = _season_report(path)
        seasons.append((path.name, report, overrides))
    if args.fixture:
        import scripts.physics_sim_season_kpis as kpis

        overrides = kpis.resolve_run_overrides(
            engine=args.engine, overrides_path=args.tuning_overrides
        ) or {}
        for fixture in args.fixture:
            for seed in args.seeds:
                report, played = _play(fixture, seed, overrides)
                seasons.append((f"{fixture.name} seed {seed}", report, played))
    if not seasons:
        parser.error("give --fixture or --from-json")

    targets = (
        json.loads(args.error_targets.read_text(encoding="utf-8"))
        if args.error_targets
        else {}
    )
    result: dict[str, Any] = {"seasons": {}}
    slope_rows, band_rows, base_rows = [], [], []
    for name, report, overrides in seasons:
        sums = (report.get("tables") or {}).get("fielding_chance_sums")
        if not sums:
            print(f"{name}: no fielding_chance_sums (no chance log)", file=sys.stderr)
            continue
        tuning = load_tuning(
            {k: v for k, v in overrides.items() if not isinstance(v, dict)}
        )
        if tuning.get("range_model", 0.0) < 0.5:
            print(
                f"{name}: not played with range_model 1; its sums are not out0",
                file=sys.stderr,
            )
            continue
        slopes = fit_slopes(
            sums,
            babip_scale=tuning.get("babip_scale", 1.0),
            ld_ratio=tuning.get("range_ld_ratio", 0.6),
        )
        bands = fit_bands(sums)
        row: dict[str, Any] = {
            "slopes": slopes, "bands": bands, "ground_ball_shares": band_shares(sums),
        }
        if targets:
            bases = {
                pos: tuning.get(f"error_base_{pos.lower()}", 0.0) for pos in targets
            }
            row["error_bases"] = fit_error_bases(report, targets, bases)
            base_rows.append(row["error_bases"])
        result["seasons"][name] = row
        slope_rows.append(slopes)
        band_rows.append(bands)
        print(f"== {name}")
        print("  slopes ", {k: round(v, 5) for k, v in slopes.items()})
        print("  bands  ", bands)
        print("  shares ", {k: round(v, 3) for k, v in row["ground_ball_shares"].items()})
        if targets:
            print("  errors ", {k: round(v, 4) for k, v in row["error_bases"].items()})
    if not slope_rows:
        return 1
    fitted: dict[str, float] = {}
    for pos, value in _mean(slope_rows).items():
        fitted[f"range_logit_slope_{pos.lower()}"] = round(value, 5)
    for pos, value in _mean(band_rows).items():
        fitted[BAND_KEYS[pos]] = round(value, 1)
    for pos, value in _mean(base_rows).items():
        fitted[f"error_base_{pos.lower()}"] = round(value, 4)
    result["fitted"] = fitted
    print("== mean over the seasons")
    print(json.dumps(fitted, indent=2))
    if args.output is not None:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
