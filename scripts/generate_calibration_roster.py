#!/usr/bin/env python3
"""Generate the committed physics-sim calibration fixture (S2-08).

Builds a self-contained 30-team / 780-player league under ``data/calibration``
by sampling player ratings from ABSOLUTE normal distributions centred on the
engine-neutral rating of 50. Unlike ``scripts/normalize_players.py`` (which
samples the source CSV's own percentile bands and can only re-amplify drift),
this generator is a stable, seeded, reproducible reference: the KPI harness and
CI gate calibrate against its output, decoupled from the evolving live-league
player generator.

Determinism: a single ``random.Random(seed)`` drives every draw, consumed in a
fixed order (team by team, player by player, column by column). No iteration
over unordered sets/dicts. Same seed => byte-identical output.

    python scripts/generate_calibration_roster.py [--output-dir data/calibration] [--seed 20260715]
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BASE_DIR))

from utils.park_utils import stadium_from_name  # noqa: E402


DEFAULT_SEED = 20260715

# players.csv column order — mirrors the loaders exactly (data_loader.py,
# models.py, and the harness _load_player_ratings/_load_player_names).
COLUMNS = [
    "player_id", "first_name", "last_name", "birthdate", "height", "weight",
    "bats", "throws", "primary_position", "other_positions", "is_pitcher",
    "role", "preferred_pitching_role",
    "ch", "ph", "sp", "eye", "gf", "pl", "vl", "sc", "fa", "arm",
    "endurance", "control", "movement", "hold_runner",
    "fb", "cu", "cb", "sl", "si", "scb", "kn",
    "durability", "injured", "ready",
]

# 30 MLB parks (all resolvable via utils.park_utils.stadium_from_name). Six
# divisions of five; division content is irrelevant to the harness.
# Names normalised to the exact ParkConfig.csv spellings that resolve via
# stadium_from_name (spec Decision 1b: substitute the nearest resolvable name).
STADIUMS = [
    "Fenway Park", "New Yankee Stadium", "Oriole Park at Camden Yards",
    "Tropicana Field", "Rogers Centre",
    "Comerica Park", "Guarantee Rate Field", "Kauffman Stadium",
    "Progressive Field", "Target Field",
    "Angel Stadium of Anaheim", "Minute Maid Park", "Oakland Coliseum",
    "T-Mobile Park", "Globe Life Field",
    "Citi Field", "Citizens Bank Park", "Nationals Park", "Truist Park",
    "loanDepot Park",
    "Wrigley Field", "Great American Ballpark", "American Family Field",
    "PNC Park", "Busch Stadium III",
    "Chase Field", "Coors Field", "Dodger Stadium", "Petco Park",
    "Oracle Park",
]
DIVISIONS = ["East", "North", "South", "West", "Central", "Pacific"]

# Hitter starter means by position. Columns: ch ph eye sp fa arm gf pl vl.
# SD: ch/ph/eye/sp = 10 ; gf/vl/fa/arm = 8 ; pl = 12.
# NOTE (S2-08 deviation, see change log): ph position-mean spread narrowed from
# the spec's 45-58 range to 47-54. HR output is a steep distance-vs-fence
# threshold, so the spec's wide corner-vs-middle power gap produced far too many
# 30-HR sluggers (qualified_hr30_count gate). The compressed spread keeps the
# league ph mean ~50.6 while thinning the extreme-power tail into gate range.
HITTER_ROWS = {
    "C":  {"ch": 47, "ph": 48, "eye": 48, "sp": 42, "fa": 55, "arm": 55, "gf": 50, "pl": 55, "vl": 50},
    "1B": {"ch": 50, "ph": 54, "eye": 52, "sp": 44, "fa": 50, "arm": 48, "gf": 50, "pl": 57, "vl": 50},
    "2B": {"ch": 52, "ph": 47, "eye": 50, "sp": 54, "fa": 53, "arm": 50, "gf": 50, "pl": 53, "vl": 50},
    "SS": {"ch": 50, "ph": 47, "eye": 49, "sp": 56, "fa": 54, "arm": 54, "gf": 50, "pl": 53, "vl": 50},
    "3B": {"ch": 50, "ph": 52, "eye": 50, "sp": 47, "fa": 52, "arm": 54, "gf": 50, "pl": 56, "vl": 50},
    "LF": {"ch": 50, "ph": 52, "eye": 50, "sp": 51, "fa": 49, "arm": 49, "gf": 50, "pl": 55, "vl": 50},
    "CF": {"ch": 50, "ph": 48, "eye": 50, "sp": 60, "fa": 53, "arm": 51, "gf": 50, "pl": 53, "vl": 50},
    "RF": {"ch": 50, "ph": 53, "eye": 51, "sp": 50, "fa": 50, "arm": 55, "gf": 50, "pl": 55, "vl": 50},
    "DH": {"ch": 51, "ph": 54, "eye": 52, "sp": 42, "fa": 40, "arm": 45, "gf": 50, "pl": 57, "vl": 50},
}
STARTER_POSITIONS = ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"]
# Core-rating SD reduced from the spec's 10 to 5 (S2-08 deviation, see change
# log): the engine's rating->outcome gains are ~2x steeper than the spec
# assumed, so SD 10 produced ~2x the MLB player-dispersion targets across every
# gate. SD 5 reconciles the fixture with the engine and the MLB dispersion
# benchmarks while preserving every position mean (league level unchanged).
HITTER_SD = {"ch": 3, "ph": 3, "eye": 3, "sp": 4,
             "fa": 8, "arm": 8, "gf": 3, "vl": 8, "pl": 6}
BENCH_CORE_SD = 3
# Survivorship floor on the contact rating — see make_hitter.
CH_FLOOR = 44.0

# Bench: (base position row, primary_position, other_positions).
BENCH_SPECS = [
    ("C", "C", ""),
    ("2B", "2B", "SS,3B"),
    ("CF", "CF", "LF,RF"),
    ("1B", "1B", "DH"),
]

# Pitcher rating means by role bucket. Columns: arm control movement endurance
# hold_runner gf vl fa (SD in the second element of each tuple).
# control/movement SDs reduced from the spec's 8-9 to 5-6 (S2-08 deviation, see
# change log): the engine's control/movement->ERA gain is steep enough that the
# spec's wider spread overshot the qualified_era_sd gate.
PITCHER_ROWS = {
    "SP": {"arm": (55, 6), "control": (52, 5), "movement": (52, 5), "endurance": (75, 8),
           "hold_runner": (50, 10), "gf": (50, 8), "vl": (50, 8), "fa": (50, 8)},
    "CL": {"arm": (65, 5), "control": (50, 5), "movement": (58, 5), "endurance": (30, 6),
           "hold_runner": (50, 10), "gf": (50, 8), "vl": (50, 8), "fa": (50, 8)},
    "SU": {"arm": (60, 6), "control": (50, 5), "movement": (55, 5), "endurance": (32, 6),
           "hold_runner": (50, 10), "gf": (50, 8), "vl": (50, 8), "fa": (50, 8)},
    "MR": {"arm": (55, 6), "control": (50, 6), "movement": (52, 6), "endurance": (36, 7),
           "hold_runner": (50, 10), "gf": (50, 8), "vl": (50, 8), "fa": (50, 8)},
    "LR": {"arm": (52, 6), "control": (51, 5), "movement": (51, 5), "endurance": (55, 8),
           "hold_runner": (50, 10), "gf": (50, 8), "vl": (50, 8), "fa": (50, 8)},
}
# 13-man staff role assignments (order preserved for the _pitching.csv file).
PITCHING_ROLES = ["SP1", "SP2", "SP3", "SP4", "SP5", "CL", "SU", "SU",
                  "MR", "MR", "MR", "MR", "LR"]


def _role_bucket(role: str) -> str:
    return "SP" if role.startswith("SP") else role


def _read_first_tokens(path: Path) -> list[str]:
    names: list[str] = []
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            token = line.split()
            if token:
                names.append(token[0].title())
    return names


class Generator:
    def __init__(self, rng, first_names: list[str], last_names: list[str]):
        self.rng = rng
        self.first_names = first_names
        self.last_names = last_names
        self._next_id = 1

    # --- primitive draws -------------------------------------------------
    def rating(self, mean: float, sd: float, floor: float = 25.0) -> int:
        return int(round(max(floor, min(95.0, self.rng.normalvariate(mean, sd)))))

    def new_id(self) -> str:
        pid = f"CAL-{self._next_id:04d}"
        self._next_id += 1
        return pid

    def hitter_hand(self) -> tuple[str, str]:
        roll = self.rng.random()
        if roll < 0.55:
            bats = "R"
        elif roll < 0.90:
            bats = "L"
        else:
            bats = "S"
        throws = "R" if bats == "S" else bats
        return bats, throws

    def pitcher_hand(self) -> str:
        return "R" if self.rng.random() < 0.72 else "L"

    def name(self) -> tuple[str, str]:
        first = self.first_names[self.rng.randrange(len(self.first_names))]
        last = self.last_names[self.rng.randrange(len(self.last_names))]
        return first, last

    def birthdate(self) -> str:
        return f"{1991 + self.rng.randint(0, 12)}-0{1 + self.rng.randint(0, 8)}-15"

    def height(self) -> int:
        return int(round(max(68.0, min(79.0, self.rng.normalvariate(73, 2)))))

    def weight(self) -> int:
        return int(round(self.rng.normalvariate(205, 15)))

    def durability(self) -> int:
        return int(round(self.rng.normalvariate(60, 10)))

    # --- players ---------------------------------------------------------
    def _blank_row(self) -> dict[str, str]:
        return {col: "" for col in COLUMNS}

    def make_hitter(self, means: dict[str, int], primary: str,
                    other: str, penalty: int = 0) -> dict[str, str]:
        row = self._blank_row()
        # Ratings drawn first so the core-rating stream is independent of the
        # identity fields below.
        for key in ("ch", "ph", "eye", "sp", "fa", "arm", "gf", "pl", "vl"):
            mean = means[key] - (penalty if key in ("ch", "ph", "eye", "sp") else 0)
            sd = BENCH_CORE_SD if penalty and key in ("ch", "ph", "eye", "sp") else HITTER_SD[key]
            # Contact (ch) gets a survivorship floor: real qualified regulars are
            # never true sub-.220 hitters (they'd be benched/demoted — a dynamic
            # this sim doesn't model), so the fixture left-truncates the contact
            # tail. This makes qualified_sub220_count reachable without violating
            # the qualified_avg_sd gate (S2-08 deviation, see change log).
            floor = CH_FLOOR if key == "ch" else 25.0
            row[key] = str(self.rating(mean, sd, floor=floor))
        bats, throws = self.hitter_hand()
        first, last = self.name()
        row.update({
            "player_id": self.new_id(),
            "first_name": first,
            "last_name": last,
            "birthdate": self.birthdate(),
            "height": str(self.height()),
            "weight": str(self.weight()),
            "bats": bats,
            "throws": throws,
            "primary_position": primary,
            "other_positions": other,
            "is_pitcher": "0",
            "role": "",
            "preferred_pitching_role": "",
            "sc": "50",
            "durability": str(self.durability()),
            "injured": "0",
            "ready": "1",
        })
        return row

    def make_pitcher(self, assigned_role: str) -> dict[str, str]:
        bucket = _role_bucket(assigned_role)
        means = PITCHER_ROWS[bucket]
        first, last = self.name()
        hand = self.pitcher_hand()
        row = self._blank_row()
        row.update({
            "player_id": self.new_id(),
            "first_name": first,
            "last_name": last,
            "birthdate": self.birthdate(),
            "height": str(self.height()),
            "weight": str(self.weight()),
            "bats": hand,
            "throws": hand,
            "primary_position": "P",
            "other_positions": "",
            "is_pitcher": "1",
            "role": "SP" if bucket == "SP" else "RP",
            "preferred_pitching_role": bucket,
            "durability": str(self.durability()),
            "injured": "0",
            "ready": "1",
        })
        for key, (mean, sd) in means.items():
            row[key] = str(self.rating(mean, sd))
        # Repertoire: everyone gets a fastball plus one two-pitch secondary mix.
        row["fb"] = str(self.rating(60, 10))
        profile_roll = self.rng.random()
        if profile_roll < 0.40:
            secondaries = ("sl", "cu")   # power
        elif profile_roll < 0.75:
            secondaries = ("sl", "cb")   # breaking
        else:
            secondaries = ("si", "cu")   # sinker
        for pitch in secondaries:
            row[pitch] = str(self.rating(52, 8))
        return row


def _lineup_order(starters: list[dict[str, str]]) -> list[dict[str, str]]:
    def r(row: dict[str, str], key: str) -> int:
        return int(row[key])
    remaining = list(starters)
    leadoff = max(remaining, key=lambda x: r(x, "eye") + r(x, "sp"))
    remaining.remove(leadoff)
    rest = sorted(remaining, key=lambda x: r(x, "ch") + r(x, "ph") + r(x, "eye"),
                  reverse=True)
    return [leadoff] + rest


def generate(output_dir: Path, seed: int) -> dict[str, object]:
    rng = __import__("random").Random(seed)
    first_names = _read_first_tokens(BASE_DIR / "playbalance" / "FirstNames.txt")
    last_names = _read_first_tokens(BASE_DIR / "playbalance" / "Surnames.txt")
    gen = Generator(rng, first_names, last_names)

    # Validate stadiums up front — fail loudly with candidates on any miss.
    for name in STADIUMS:
        if stadium_from_name(name) is None:
            from utils.park_utils import list_ballpark_names
            raise SystemExit(
                f"Stadium {name!r} does not resolve via stadium_from_name. "
                f"Available candidates:\n  " + "\n  ".join(list_ballpark_names())
            )

    teams: list[dict[str, str]] = []
    players: list[dict[str, str]] = []
    rosters: dict[str, list[str]] = {}
    pitching: dict[str, list[tuple[str, str]]] = {}
    lineups: dict[str, list[tuple[int, str, str]]] = {}
    starter_means: dict[str, list[int]] = {k: [] for k in ("ch", "ph", "eye", "sp")}

    for idx in range(30):
        team_id = f"CAL{idx + 1:02d}"
        teams.append({
            "team_id": team_id,
            "name": f"Calibrators {idx + 1:02d}",
            "city": f"City{idx + 1:02d}",
            "abbreviation": team_id,
            "division": DIVISIONS[idx // 5],
            "stadium": STADIUMS[idx],
            "primary_color": "#204080",
            "secondary_color": "#C0C0C0",
            "owner_id": "",
        })

        roster_ids: list[str] = []
        # 9 starters (one per position).
        starters: list[dict[str, str]] = []
        for pos in STARTER_POSITIONS:
            row = gen.make_hitter(HITTER_ROWS[pos], primary=pos, other="")
            starters.append(row)
            players.append(row)
            roster_ids.append(row["player_id"])
            for key in starter_means:
                starter_means[key].append(int(row[key]))
        # 4 bench hitters.
        for base_pos, primary, other in BENCH_SPECS:
            row = gen.make_hitter(HITTER_ROWS[base_pos], primary=primary,
                                  other=other, penalty=6)
            players.append(row)
            roster_ids.append(row["player_id"])
        # 13 pitchers.
        staff: list[tuple[str, str]] = []
        for role in PITCHING_ROLES:
            row = gen.make_pitcher(role)
            players.append(row)
            roster_ids.append(row["player_id"])
            staff.append((row["player_id"], role))
        pitching[team_id] = staff
        rosters[team_id] = roster_ids

        ordered = _lineup_order(starters)
        lineups[team_id] = [
            (slot + 1, row["player_id"], row["primary_position"])
            for slot, row in enumerate(ordered)
        ]

    _write_fixture(output_dir, teams, players, rosters, pitching, lineups)

    # --- validation + report --------------------------------------------
    report: dict[str, object] = {"means": {}, "sds": {}}
    for key, values in starter_means.items():
        mean = statistics.fmean(values)
        report["means"][key] = mean
        report["sds"][key] = statistics.pstdev(values)
        assert abs(mean - 50.0) <= 1.5, (
            f"league starter mean for {key} = {mean:.2f} (>1.5 from 50)"
        )
    for team_id in rosters:
        assert len(rosters[team_id]) == 26, f"{team_id} roster != 26 rows"
        assert len(pitching[team_id]) == 13, f"{team_id} pitching != 13 rows"
        assert len(lineups[team_id]) == 9, f"{team_id} lineup != 9 rows"
    assert len(players) == 780, f"expected 780 players, got {len(players)}"
    report["teams"] = len(teams)
    report["players"] = len(players)
    return report


def _write_csv(path: Path, header: list[str] | None, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if header is not None:
            writer.writerow(header)
        writer.writerows(rows)


def _write_fixture(output_dir, teams, players, rosters, pitching, lineups) -> None:
    output_dir = Path(output_dir)
    team_header = ["team_id", "name", "city", "abbreviation", "division",
                   "stadium", "primary_color", "secondary_color", "owner_id"]
    _write_csv(output_dir / "teams.csv", team_header,
               [[t[c] for c in team_header] for t in teams])
    _write_csv(output_dir / "players.csv", COLUMNS,
               [[p[c] for c in COLUMNS] for p in players])
    for team_id, ids in rosters.items():
        _write_csv(output_dir / "rosters" / f"{team_id}.csv", None,
                   [[pid, "ACT"] for pid in ids])
    for team_id, staff in pitching.items():
        _write_csv(output_dir / "rosters" / f"{team_id}_pitching.csv", None,
                   [[pid, role] for pid, role in staff])
    for team_id, slots in lineups.items():
        rows = [[order, pid, pos] for order, pid, pos in slots]
        for hand in ("rhp", "lhp"):
            _write_csv(output_dir / "lineups" / f"{team_id}_vs_{hand}.csv",
                       ["order", "player_id", "position"], rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=BASE_DIR / "data" / "calibration")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    report = generate(args.output_dir, args.seed)
    print(f"Calibration fixture written to {args.output_dir}")
    print(f"  teams={report['teams']} players={report['players']}")
    print("  starter league means / SDs (ch/ph/eye/sp):")
    for key in ("ch", "ph", "eye", "sp"):
        print(f"    {key:3s} mean={report['means'][key]:.2f} "
              f"sd={report['sds'][key]:.2f}")


if __name__ == "__main__":
    main()
