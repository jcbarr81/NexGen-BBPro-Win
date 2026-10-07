#!/usr/bin/env python3
"""Generate a league-like KPI fixture with the product's own league code.

Audit 2026-10-06, finding H3 / Release 2: the committed calibration fixture
(``data/calibration``, built by ``scripts/generate_calibration_roster.py``)
passes the strict KPI gate partly because its hitters are rated ~3 CH / ~2 PH
lower than a real league's regulars and because it plays in the 30 real MLB
parks. Alpha-test, a real league, runs ~5.0 R/G and fails ~21 gates. This
script builds a SECOND fixture that looks like a league owners actually play:

* players come from :func:`playbalance.league_creator.create_league` -- the
  same generator and 51-player organisations a new league gets -- with the
  archetype speed tiers owner decision 3 keeps (the generator's default
  bootstrap path no longer applies them; see :func:`_with_speed_tiers`);
* every organisation's ACT roster is then re-picked by the product's
  auto-assign (:func:`services.roster_auto_assign.auto_assign_team`), so ACT
  holds each club's best 13 hitters and 13 pitchers (decision 8's 26-man
  roster), as in a league that has run auto-assign;
* the pitching staff is written by the product's Pitching auto-fill
  (:func:`utils.pitching_autofill.autofill_pitching_staff`, the same rows the
  ``/pitching/autofill`` endpoint writes: SP1-5, LR, CL, SU, MR1-MR3, and
  the optional MR4/MR5 for the 12th and 13th active pitchers);
* lineups come from the product's lineup auto-fill;
* every team plays in the GENERIC park: ``teams.csv`` carries an empty
  ``park_id`` (audit L13: real-park geometry only for an explicit pick).

NOT YET REFLECTED (owner decisions, DECISIONS.md, still to be implemented):

* decision 2 -- league-relative ratings. The engine still reads absolute
  ``rating - 50`` terms, so the run level depends on where the generator puts
  hitters against pitchers. Today's generator (bootstrap since 7.24.0) plus
  best-of-organisation ACT rosters gives pitchers the bigger edge, so this
  fixture runs COLD (~4.0 R/G), while alpha-test, built by the older
  generator, runs hot (~5.0). Neither matches the calibration fixture;
* decision 7 -- an MLB batting-side mix in the generator.

The fixture therefore reflects the CURRENT generator. When those land,
regenerate it with the same command (the defaults are the committed fixture's
parameters) and commit the new files together with the change that moved them:

    PYTHONHASHSEED=0 python scripts/generate_league_fixture.py

Determinism: one ``random.seed(seed)`` drives the generator; "today" is frozen
to ``--as-of`` for every age calculation the generator and auto-assign make;
and the script re-runs itself under ``PYTHONHASHSEED=0`` because some of the
product code iterates sets. Same seed and same code => byte-identical output.

Isolation: all product code runs against a throw-away data root
(``NEXGEN_DATA_ROOT`` in a temp dir), never ``data/`` or a real league. Only
the finished fixture files are copied to ``--output-dir``.

Run the KPI harness on it (report-only; it is EXPECTED to fail gates today):

    python scripts/physics_sim_season_kpis.py --base-dir data/calibration_league \
        --players data/calibration_league/players.csv --games 162 --seed 1 \
        --output tmp/league_fixture_kpis.json
"""
from __future__ import annotations

import argparse
import csv
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from datetime import date, datetime
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parents[1]

DEFAULT_SEED = 20261006
DEFAULT_TEAMS = 30
# Every age the generator and auto-assign compute is taken on this date, so the
# output does not drift with the calendar. Opening day of the alpha season.
DEFAULT_AS_OF = "2026-04-01"
DEFAULT_OUTPUT = BASE_DIR / "data" / "calibration_league"
# The rating source the generator samples from. ``player_generator`` prefers a
# curated normalized roster over a league players.csv; this is the bundled one.
DEFAULT_RATINGS_SOURCE = BASE_DIR / "data" / "players_normalized.csv"
LEAGUE_NAME = "KPI League Fixture"
FIXTURE_LEAGUE_ID = "kpi-league-fixture"
# Six divisions, so 30 teams split 5/5/5/5/5/5 like MLB.
DIVISIONS = ["AL East", "AL Central", "AL West", "NL East", "NL Central", "NL West"]
# Staff slots (utils.staff_roles): the 11 required, then the optional MR4/MR5
# that the auto-fill uses for the 12th and 13th active arms.
PITCHING_SLOTS = ["SP1", "SP2", "SP3", "SP4", "SP5", "LR", "CL", "SU",
                  "MR1", "MR2", "MR3"]
OPTIONAL_PITCHING_SLOTS = ["MR4", "MR5"]


def _reexec_with_hash_seed() -> None:
    """Re-run this script under PYTHONHASHSEED=0 when it is not already set.

    Parts of the product code iterate ``set`` objects of player ids; string
    hashing is randomised per process, so without a fixed hash seed two runs
    with the same ``--seed`` could order ties differently.
    """

    if os.environ.get("PYTHONHASHSEED") == "0":
        return
    env = dict(os.environ, PYTHONHASHSEED="0")
    completed = subprocess.run([sys.executable, *sys.argv], env=env)
    raise SystemExit(completed.returncode)


def _frozen_clock(as_of: date):
    """Return (date, datetime) subclasses whose today()/now() is ``as_of``."""

    class FrozenDate(date):
        @classmethod
        def today(cls):  # noqa: D401 - mirrors date.today
            return cls(as_of.year, as_of.month, as_of.day)

    class FrozenDateTime(datetime):
        @classmethod
        def today(cls):
            return cls(as_of.year, as_of.month, as_of.day)

        @classmethod
        def now(cls, tz=None):
            return cls(as_of.year, as_of.month, as_of.day, tzinfo=tz)

    return FrozenDate, FrozenDateTime


def _prepare_data_root(root: Path, league_dir: Path, ratings_source: Path) -> None:
    """Lay out an isolated data root shaped like the cloud's.

    The product resolves every ``data/...`` path through the ACTIVE league's
    data dir (roster_loader reads ``data/players.csv`` to count a club's
    pitchers, for one), so the league must be generated in
    ``<root>/leagues/<id>/data`` with that league active -- not in a loose
    folder. The root holds the bundled normalized roster, which
    ``player_generator._rating_distributions`` samples ratings from when the
    league has none of its own; the league dir starts with the static files
    ``create_league`` keeps through its purge (names.csv, MLB_avg).
    """

    league_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ratings_source, root / "players_normalized.csv")
    data = BASE_DIR / "data"
    shutil.copy2(data / "names.csv", league_dir / "names.csv")
    shutil.copytree(data / "MLB_avg", league_dir / "MLB_avg")


def _with_speed_tiers(player_generator):
    """Wrap the generator's bootstrap hitter draw with its archetype speed tiers.

    Owner decision 3 keeps the archetype speed tiers ("speed" floored at 70,
    "elite_speed" at 85; alpha-test has 15.5% of hitters at SP >= 70), and
    Release 2 asks for a fixture with that fast-runner tail. Since 7.24.0 the
    generator's default path bootstraps whole rating vectors from a donor
    roster that tops out at SP 67 and applies the tiers only when a caller
    names an archetype -- league creation never does -- so a new league has no
    fast runners at all. Until the generator applies the tiers itself (backlog),
    this draws each bootstrapped hitter's archetype with the generator's own
    position weights and, for the two speed archetypes, applies the generator's
    own template rules (``_adjust_hitter_constraints`` floor, then
    ``_apply_hitter_tail_boost``). Every other hitter keeps its donor vector.
    """

    original = player_generator._bootstrap_hitter_ratings
    speed_templates = {"speed", "elite_speed"}

    def bootstrap_with_tiers(primary_pos, bats):
        out = original(primary_pos, bats)
        if out is None:
            return out
        template = player_generator._choose_hitter_template(primary_pos)
        if template not in speed_templates:
            return out
        keys = ("ch", "ph", "sp", "eye", "pl", "gf")
        values = player_generator._adjust_hitter_constraints(
            template, *(out[k] for k in keys)
        )
        values = player_generator._apply_hitter_tail_boost(template, *values)
        out.update(zip(keys, values))
        out["hitter_archetype"] = template
        return out

    return bootstrap_with_tiers


def _divisions(team_count: int) -> dict[str, list[tuple[str, str]]]:
    from playbalance.team_name_generator import random_team, reset_name_pool

    reset_name_pool()
    structure: dict[str, list[tuple[str, str]]] = {d: [] for d in DIVISIONS}
    for idx in range(team_count):
        structure[DIVISIONS[idx % len(DIVISIONS)]].append(random_team())
    return {name: teams for name, teams in structure.items() if teams}


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _read_roster(path: Path) -> dict[str, list[str]]:
    levels: dict[str, list[str]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) >= 2 and row[0].strip():
                levels.setdefault(row[1].strip().upper(), []).append(row[0].strip())
    return levels


def _write_pitching_staff(league_dir: Path, team_id: str,
                          players: dict[str, dict[str, str]]) -> list[tuple[str, str]]:
    """Write ``<team>_pitching.csv`` exactly as the Pitching auto-fill does.

    Mirrors ``api/routers/lineups.py::autofill_pitching_staff_endpoint``: the
    ACT pitchers go through ``autofill_pitching_staff`` and its role rows
    are written in its order: the 11 required slots, then MR4/MR5 for the
    12th and 13th arms.
    """

    from utils.pitching_autofill import autofill_pitching_staff
    from utils.roster_rules import counts_as_pitcher

    act = _read_roster(league_dir / "rosters" / f"{team_id}.csv").get("ACT", [])
    candidates = []
    for pid in act:
        entry = players.get(pid)
        if not entry or not counts_as_pitcher(entry):
            continue
        candidates.append((pid, entry))
    assignments = autofill_pitching_staff(candidates)
    rows = [(pid, role) for role, pid in assignments.items() if pid]
    path = league_dir / "rosters" / f"{team_id}_pitching.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerows(rows)
    return rows


def build_league(work_dir: Path, *, seed: int, teams: int, as_of: date,
                 ratings_source: Path) -> Path:
    """Generate the league in ``work_dir`` and return its data directory."""

    root = work_dir / "root"
    league_dir = root / "leagues" / FIXTURE_LEAGUE_ID / "data"
    _prepare_data_root(root, league_dir, ratings_source)
    # Every get_data_dir() caller now lands in the throw-away league, never in
    # data/ or a real league. Set before the product modules are imported:
    # player_generator reads MLB_avg from the data dir at import time.
    os.environ["NEXGEN_DATA_ROOT"] = str(root)
    os.environ["NEXGEN_ACTIVE_LEAGUE"] = FIXTURE_LEAGUE_ID
    # A sim-date override would move ages off --as-of.
    for key in ("NEXGEN_DATA_DIR", "PB_SIM_DATE", "PB_SIM_YEAR"):
        os.environ.pop(key, None)

    import random

    import utils.path_utils as path_utils

    frozen_date, frozen_datetime = _frozen_clock(as_of)
    with ExitStack() as stack:
        # Locally, a league dir without teams.csv is seeded with a full copy of
        # the repo's data/ (real leagues included). The cloud image ships no
        # data/, so there the seed is a no-op; match the cloud.
        stack.enter_context(
            mock.patch.object(path_utils, "_seed_data_dir", lambda *_a, **_k: None)
        )
        import playbalance.aging as aging
        import playbalance.league_creator as league_creator
        import playbalance.player_generator as player_generator
        import services.roster_auto_assign as roster_auto_assign
        import utils.lineup_autofill as lineup_autofill
        from utils.player_loader import load_players_from_csv
        from utils.roster_loader import load_roster
        from utils.team_loader import load_teams

        for module in (league_creator, roster_auto_assign, lineup_autofill, aging):
            stack.enter_context(mock.patch.object(module, "date", frozen_date))
        stack.enter_context(
            mock.patch.object(player_generator, "datetime", frozen_datetime)
        )
        stack.enter_context(
            mock.patch.object(
                player_generator,
                "_bootstrap_hitter_ratings",
                _with_speed_tiers(player_generator),
            )
        )

        random.seed(seed)
        league_creator.create_league(
            league_dir, _divisions(teams), LEAGUE_NAME, rating_profile="normalized"
        )

        # Real roster selection: the generator hands every club 26 random
        # "ACT" players; a live league runs auto-assign, which puts each
        # organisation's best 13 hitters and 13 pitchers on ACT.
        players_file = str(league_dir / "players.csv")
        roster_dir = str(league_dir / "rosters")
        load_roster.cache_clear()
        players_by_id = {p.player_id: p for p in load_players_from_csv(players_file)}
        age_cache: dict[str, int | None] = {}
        team_ids = [t.team_id for t in load_teams(str(league_dir / "teams.csv"))]
        for team_id in team_ids:
            result = roster_auto_assign.auto_assign_team(
                team_id,
                players_file=players_file,
                roster_dir=roster_dir,
                players_by_id=players_by_id,
                as_of_date=as_of,
                age_cache=age_cache,
            )
            if result.get("released"):
                raise SystemExit(f"auto-assign released players from {team_id}: {result}")
        load_roster.cache_clear()

        player_rows = {r["player_id"]: r for r in _read_csv_rows(league_dir / "players.csv")}
        for team_id in team_ids:
            _write_pitching_staff(league_dir, team_id, player_rows)
            lineup_autofill.auto_fill_lineup_for_team(
                team_id,
                players_file=players_file,
                roster_dir=roster_dir,
                lineup_dir=str(league_dir / "lineups"),
            )
        load_roster.cache_clear()
    return league_dir


def _copy_lf(src: Path, dest: Path) -> None:
    """Copy a text file with LF line endings (AGENTS.md: commit LF only)."""

    dest.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8")
    dest.write_text(text.replace("\r\n", "\n"), encoding="utf-8", newline="\n")


def export_fixture(league_dir: Path, output_dir: Path) -> list[str]:
    """Copy the files the KPI harness reads into ``output_dir``."""

    team_ids = [r["team_id"] for r in _read_csv_rows(league_dir / "teams.csv")]
    if output_dir.exists():
        for sub in ("rosters", "lineups"):
            shutil.rmtree(output_dir / sub, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    _copy_lf(league_dir / "teams.csv", output_dir / "teams.csv")
    _copy_lf(league_dir / "players.csv", output_dir / "players.csv")
    for team_id in team_ids:
        for name in (f"{team_id}.csv", f"{team_id}_pitching.csv"):
            _copy_lf(league_dir / "rosters" / name, output_dir / "rosters" / name)
        for hand in ("lhp", "rhp"):
            name = f"{team_id}_vs_{hand}.csv"
            _copy_lf(league_dir / "lineups" / name, output_dir / "lineups" / name)
    return team_ids


def _num(row: dict[str, str], key: str) -> float | None:
    try:
        return float(row.get(key) or "")
    except ValueError:
        return None


def summarize(output_dir: Path) -> dict[str, object]:
    """Validate the fixture and return the numbers its README reports."""

    from utils.roster_rules import (
        ACTIVE_ROSTER_SIZE,
        MAX_ACTIVE_PITCHERS,
        ORG_LIMIT,
        counts_as_pitcher,
    )

    players = {r["player_id"]: r for r in _read_csv_rows(output_dir / "players.csv")}
    teams = _read_csv_rows(output_dir / "teams.csv")
    problems: list[str] = []
    lineup_hitters: list[dict[str, str]] = []
    act_hitters: list[dict[str, str]] = []
    act_pitchers: list[dict[str, str]] = []
    act_sizes: list[int] = []
    for team in teams:
        team_id = team["team_id"]
        if (team.get("park_id") or "") != "":
            problems.append(f"{team_id}: park_id {team['park_id']!r} is not generic")
        levels = _read_roster(output_dir / "rosters" / f"{team_id}.csv")
        act = levels.get("ACT", [])
        act_sizes.append(len(act))
        team_pitchers = 0
        for pid in act:
            row = players[pid]
            if counts_as_pitcher(row):
                act_pitchers.append(row)
                team_pitchers += 1
            else:
                act_hitters.append(row)
        if len(act) > ACTIVE_ROSTER_SIZE:
            problems.append(f"{team_id}: ACT holds {len(act)} (max {ACTIVE_ROSTER_SIZE})")
        if team_pitchers > MAX_ACTIVE_PITCHERS:
            problems.append(
                f"{team_id}: ACT carries {team_pitchers} pitchers "
                f"(max {MAX_ACTIVE_PITCHERS})"
            )
        org = sum(len(levels.get(level, [])) for level in ("ACT", "AAA", "LOW"))
        if org > ORG_LIMIT:
            problems.append(f"{team_id}: organisation of {org} (max {ORG_LIMIT})")
        with (output_dir / "rosters" / f"{team_id}_pitching.csv").open(
                newline="", encoding="utf-8") as fh:
            staff = [row for row in csv.reader(fh) if row]
        roles = sorted(role for _, role in staff)
        expected_slots = len(PITCHING_SLOTS) + len(OPTIONAL_PITCHING_SLOTS)
        if (
            not set(PITCHING_SLOTS) <= set(roles)
            or not set(roles) <= set(PITCHING_SLOTS + OPTIONAL_PITCHING_SLOTS)
            or len(set(roles)) != len(roles)
            or len(roles) != min(team_pitchers, expected_slots)
        ):
            problems.append(f"{team_id}: staff roles {roles}")
        if any(pid not in act for pid, _ in staff):
            problems.append(f"{team_id}: staff lists a non-ACT pitcher")
        for hand in ("lhp", "rhp"):
            slots = _read_csv_rows(output_dir / "lineups" / f"{team_id}_vs_{hand}.csv")
            if len(slots) != 9 or any(s["player_id"] not in act for s in slots):
                problems.append(f"{team_id}: vs_{hand} lineup is not 9 ACT hitters")
            if hand == "rhp":
                lineup_hitters.extend(players[s["player_id"]] for s in slots)
    if problems:
        raise SystemExit("Fixture failed validation:\n  " + "\n  ".join(problems))

    def mean(rows, key):
        values = [v for v in (_num(r, key) for r in rows) if v is not None]
        return statistics.fmean(values) if values else float("nan")

    speeds = [v for v in (_num(r, "sp") for r in act_hitters) if v is not None]
    return {
        "teams": len(teams),
        "players": len(players),
        "act_sizes": sorted(set(act_sizes)),
        "act_hitters": len(act_hitters),
        "act_pitchers": len(act_pitchers),
        "lineup_means": {k: mean(lineup_hitters, k) for k in ("ch", "ph", "eye", "sp")},
        "act_pitcher_means": {
            k: mean(act_pitchers, k)
            for k in ("arm", "control", "movement", "endurance")
        },
        "act_speed_70_share": (
            sum(1 for s in speeds if s >= 70) / len(speeds) if speeds else 0.0
        ),
        "act_speed_85_share": (
            sum(1 for s in speeds if s >= 85) / len(speeds) if speeds else 0.0
        ),
        "lhb_share": (
            sum(1 for r in act_hitters if r.get("bats") == "L") / len(act_hitters)
            if act_hitters else 0.0
        ),
    }


def _write_readme(output_dir: Path, args: argparse.Namespace,
                  summary: dict[str, object]) -> None:
    lm = summary["lineup_means"]
    pm = summary["act_pitcher_means"]
    text = f"""# League-like KPI fixture (generated -- do not hand-edit)

Built by `scripts/generate_league_fixture.py` for audit 2026-10-06 finding H3
(Release 2): a second KPI fixture that looks like a league owners play, next
to the hand-tuned `data/calibration` fixture that CI gates on.

How it is built (all product code, run in an isolated temp data root):

- players: `playbalance.league_creator.create_league` (the new-league
  generator), plus the archetype speed tiers owner decision 3 keeps, drawn
  with the generator's own archetype weights and floors (its default bootstrap
  path skips them, so the script applies them; see `_with_speed_tiers`);
- ACT rosters: `services.roster_auto_assign.auto_assign_team` per organisation
  (each club's best 13 hitters / 13 pitchers: the 26-man roster, decision 8);
- pitching staffs: `utils.pitching_autofill.autofill_pitching_staff`, written
  as the Pitching auto-fill does (SP1-5, LR, CL, SU, MR1-MR3, then MR4/MR5
  for the 12th and 13th active pitchers);
- lineups: `utils.lineup_autofill.auto_fill_lineup_for_team`;
- parks: generic for every team (`park_id` empty; audit L13).

Not yet reflected (owner decisions still to be implemented, DECISIONS.md):
decision 2 (league-relative ratings) and decision 7 (MLB batting-side mix).
The fixture reflects the CURRENT generator; regenerate it when those land.
Under today's absolute ratings its run level is set by where the generator
puts hitters against pitchers, so it differs from both alpha-test (older
generator) and `data/calibration`.

Parameters: seed {args.seed}, {summary['teams']} teams, ages as of {args.as_of},
ratings source `{_display_path(args.ratings_source)}`.

Regenerate (byte-identical for the same seed and code):

    PYTHONHASHSEED=0 python scripts/generate_league_fixture.py --seed {args.seed} --teams {summary['teams']}

Run the KPI harness on it (report-only; the current engine is expected to
fail gates here -- that is the point of the fixture):

    python scripts/physics_sim_season_kpis.py --base-dir data/calibration_league \\
        --players data/calibration_league/players.csv --games 162 --seed 1 \\
        --output tmp/league_fixture_kpis.json

Generated profile:

- {summary['players']} players; ACT {summary['act_hitters']} hitters / {summary['act_pitchers']} pitchers
- lineup regulars (vs RHP) mean CH {lm['ch']:.1f} / PH {lm['ph']:.1f} / EYE {lm['eye']:.1f} / SP {lm['sp']:.1f}
- ACT pitchers mean arm {pm['arm']:.1f} / control {pm['control']:.1f} / movement {pm['movement']:.1f} / endurance {pm['endurance']:.1f}
- ACT hitters with SP >= 70: {summary['act_speed_70_share']:.1%}; SP >= 85: {summary['act_speed_85_share']:.1%}
- ACT hitters batting left: {summary['lhb_share']:.1%}
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8", newline="\n")


def _display_path(path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(BASE_DIR).as_posix()
    except ValueError:
        return Path(path).name


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--teams", type=int, default=DEFAULT_TEAMS,
                        help="Number of teams (2-40; default 30).")
    parser.add_argument("--as-of", default=DEFAULT_AS_OF,
                        help="Date all ages are computed on (YYYY-MM-DD).")
    parser.add_argument("--ratings-source", type=Path,
                        default=DEFAULT_RATINGS_SOURCE,
                        help="Roster the generator samples rating distributions from.")
    args = parser.parse_args(argv)

    if not 2 <= args.teams <= 40:
        parser.error("--teams must be between 2 and 40")
    as_of = date.fromisoformat(args.as_of)
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    output_dir = output_dir.resolve()
    leagues_root = (BASE_DIR / "data" / "leagues").resolve()
    if output_dir == leagues_root or leagues_root in output_dir.parents:
        parser.error("refusing to write a fixture inside data/leagues")
    protected = {BASE_DIR.resolve(), (BASE_DIR / "data").resolve(),
                 (BASE_DIR / "data" / "calibration").resolve()}
    if output_dir in protected:
        parser.error(f"refusing to overwrite {output_dir}")
    # export_fixture replaces rosters/ and lineups/: only reuse an empty
    # folder or one this generator wrote before.
    if (output_dir.exists() and any(output_dir.iterdir())
            and not (output_dir / "README.md").exists()):
        parser.error(f"{output_dir} is not empty and holds no generated fixture")

    sys.path.insert(0, str(BASE_DIR))
    work_dir = Path(tempfile.mkdtemp(prefix="league_fixture_"))
    try:
        league_dir = build_league(
            work_dir, seed=args.seed, teams=args.teams, as_of=as_of,
            ratings_source=args.ratings_source.resolve(),
        )
        export_fixture(league_dir, output_dir)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    summary = summarize(output_dir)
    _write_readme(output_dir, args, summary)
    lm = summary["lineup_means"]
    print(f"League fixture written to {output_dir}")
    print(f"  teams={summary['teams']} players={summary['players']} "
          f"ACT hitters={summary['act_hitters']} pitchers={summary['act_pitchers']}")
    print(f"  lineup means CH {lm['ch']:.1f} PH {lm['ph']:.1f} "
          f"EYE {lm['eye']:.1f} SP {lm['sp']:.1f}; "
          f"SP>=70 share {summary['act_speed_70_share']:.1%}")


if __name__ == "__main__":
    _reexec_with_hash_seed()
    main()
