"""Report-only KPIs for the physics-sim season harness.

Audit 2026-10-06, REPORT section 6, Release 2 ("Add KPIs, report-only
first"). The strict harness gates each event's volume in isolation, so
whole classes of problems the audit found passed every gate: broken bullpen
usage (H1), count-blind swings (M1), walk skill (H4), the velocity fade
(H10), extra-base aggression (M7), runs on inning-ending double plays (L15),
late-inning scoring (M19), the LHP gap (H7), team talent spread (M17) and the
missing situational KPIs (L18). This module measures them from the per-game
results the harness already produces.

``physics_sim_season_kpis.py`` writes the result to the JSON under
``report_only`` and prints it. ``--strict`` ignores it, except for the keys
promoted to strict gates after the engine release that fixed them (Release
3: ``STRICT_EXTRAS_TARGETS`` there, copied into the gated ``metrics``).
Promote a metric to a gate only after the engine release that fixes it.

Base-out state (L18) is read from the first ``pitch_log`` entry of each plate
appearance (written by the engine)::

    "pa_start": true, "inning": int, "half": "top" | "bottom",
    "outs_before": 0-2, "bases_before": bitmask (1 = 1st, 2 = 2nd, 4 = 3rd),
    "bat_score_before": int, "fld_score_before": int

A game whose log lacks those keys is "not logged": every metric that needs
the base-out state (RE24, run probability, XBT, GIDP per opportunity,
late & close, RISP, runs on inning-ending plays) skips it and reports None
when no game was logged. Everything else works on any engine version.
"""
from __future__ import annotations

import csv
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_PATH = (
    BASE_DIR / "data" / "MLB_avg" / "mlb_report_only_reference.csv"
)

# FanGraphs-style wOBA weights, the same set the harness platoon KPI uses.
WOBA_WEIGHTS = {"bb": 0.69, "hbp": 0.72, "1b": 0.88, "2b": 1.25, "3b": 1.59, "hr": 2.05}
HIT_TOKENS = frozenset({"1b", "2b", "3b", "hr"})
AB_TOKENS = HIT_TOKENS | {"so", "out", "roe"}
BASE_NAMES = {
    0: "empty", 1: "1b", 2: "2b", 4: "3b",
    3: "1b2b", 5: "1b3b", 6: "2b3b", 7: "loaded",
}
COUNTS = [f"{b}-{s}" for b in range(4) for s in range(3)]
# Pitches thrown before the PA, as in the audit's H10 velocity table.
FATIGUE_EARLY = (0, 25)
FATIGUE_LATE = (91, 105)
INFIELD_RANGE_POSITIONS = ("2B", "3B", "SS")  # range shows up as assists
OUTFIELD_RANGE_POSITIONS = ("LF", "CF", "RF")  # range shows up as putouts


# ---------------------------------------------------------------- helpers
def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _ratio(num: float, den: float) -> float | None:
    return (num / den) if den else None


def _event_tokens(entry: dict[str, Any]) -> set[str]:
    raw = entry.get("runner_event")
    if not raw:
        return set()
    return set(str(raw).split("+"))


def woba_from_tokens(counts: Counter) -> tuple[float | None, int]:
    """wOBA over PA result tokens. IBB and sacrifice bunts are excluded from
    both sides, as in the harness platoon KPI."""
    den = sum(counts[t] for t in AB_TOKENS) + counts["bb"] + counts["sf"] + counts["hbp"]
    if not den:
        return None, 0
    num = sum(counts[t] * w for t, w in WOBA_WEIGHTS.items())
    return num / den, den


def ops_from_tokens(counts: Counter) -> float | None:
    ab = sum(counts[t] for t in AB_TOKENS)
    hits = sum(counts[t] for t in HIT_TOKENS)
    walks = counts["bb"] + counts["ibb"]
    obp_den = ab + walks + counts["hbp"] + counts["sf"]
    if not ab or not obp_den:
        return None
    tb = counts["1b"] + 2 * counts["2b"] + 3 * counts["3b"] + 4 * counts["hr"]
    return (hits + walks + counts["hbp"]) / obp_den + tb / ab


def true_sd(rows: Iterable[tuple[int, int]]) -> tuple[float | None, float | None, int]:
    """(true sd, unclipped true variance, n) of a binomial rate.

    ``rows`` are (events, trials) per player. True variance = observed sample
    variance minus mean binomial noise. The unclipped variance is reported
    too: it can be pooled across seeds, where the clipped sd cannot (H4).
    """
    rows = [(k, n) for k, n in rows if n > 0]
    if len(rows) < 10:
        return None, None, len(rows)
    rates = [k / n for k, n in rows]
    mean = statistics.fmean(rates)
    var = statistics.variance(rates)
    noise = statistics.fmean(mean * (1.0 - mean) / n for _k, n in rows)
    diff = var - noise
    return math.sqrt(max(0.0, diff)), diff, len(rows)


def _slope(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def late_and_close(inning: int, bat: int, fld: int, mask: int) -> bool:
    """MLB definition: 7th inning or later, and the batting team is tied,
    ahead by one, or has the tying run on base, at bat or on deck."""
    if inning < 7:
        return False
    diff = bat - fld
    if 0 <= diff <= 1:
        return True
    runners = bin(mask & 7).count("1")
    return diff < 0 and -diff <= runners + 2


# ------------------------------------------------------- PA reconstruction
class PlateAppearance:
    __slots__ = (
        "batter_id", "pitcher_id", "token", "first", "last", "pitches",
        "mid_event", "state",
    )

    def __init__(self, first: dict[str, Any]) -> None:
        self.batter_id = str(first.get("batter_id", ""))
        self.pitcher_id = str(first.get("pitcher_id", ""))
        self.token: str | None = None
        self.first = first
        self.last = first
        self.pitches = 1 if "pitch_type" in first else 0
        # A runner event before the final entry (steal, WP, PB, balk) moved
        # runners mid-PA, so the PA-start state no longer describes the play.
        self.mid_event = False
        self.state: tuple[int, str, int, int, int, int] | None = None
        if first.get("pa_start"):
            try:
                self.state = (
                    int(first["inning"]),
                    str(first["half"]),
                    int(first["outs_before"]),
                    int(first["bases_before"]) & 7,
                    int(first["bat_score_before"]),
                    int(first["fld_score_before"]),
                )
            except (KeyError, TypeError, ValueError):
                self.state = None

    def add(self, entry: dict[str, Any]) -> None:
        if self.last.get("runner_event"):
            self.mid_event = True
        self.last = entry
        if "pitch_type" in entry:
            self.pitches += 1


def split_plate_appearances(pitch_log: list[dict[str, Any]]) -> list[PlateAppearance]:
    """Group a game's pitch_log into plate appearances.

    With base-out logging every PA's first entry carries ``pa_start``. Older
    logs fall back to a heuristic: a PA starts at a 0-0 pitch or at a
    pitchless entry (intentional walk, bunt). A count only reads 0-0 on the
    first pitch of a PA, so the heuristic also splits a PA cut short by a
    caught stealing from the next inning's leadoff PA.
    """
    logged = bool(pitch_log) and "pa_start" in pitch_log[0]
    pas: list[PlateAppearance] = []
    cur: PlateAppearance | None = None
    for entry in pitch_log:
        if logged:
            starts = bool(entry.get("pa_start"))
        else:
            starts = "count" not in entry or entry.get("count") == "0-0"
        if cur is None or starts or cur.token is not None:
            cur = PlateAppearance(entry)
            pas.append(cur)
        else:
            cur.add(entry)
        token = entry.get("pa_result")
        if token:
            cur.token = str(token)
    return pas


# ------------------------------------------------------------- accumulator
class ReportOnlyKpis:
    """Accumulates report-only KPIs game by game; ``finalize`` computes them."""

    def __init__(
        self,
        *,
        players_path: Path,
        games_per_team: int,
        lineup_dir: Path | None = None,
    ) -> None:
        self.games_per_team = games_per_team
        self.bats: dict[str, str] = {}
        self.throws: dict[str, str] = {}
        self.primary_pos: dict[str, str] = {}
        self.fa: dict[str, float] = {}
        # Release 4 (W0): hitter speed for the running-game tier tables.
        self.sp: dict[str, float] = {}
        self._load_players(Path(players_path))
        self.lineup_pos = _load_lineup_positions(lineup_dir) if lineup_dir else {}

        self.games = 0
        self.totals: Counter = Counter()
        # usage
        self.usage: Counter = Counter()
        self.closer_outs_by_pid: Counter = Counter()
        # Release 3 bullpen usage (H1): relief outs/apps by canonical role.
        self.relief_by_role: dict[str, Counter] = defaultdict(Counter)
        # discipline
        self.count_pitches: Counter = Counter()
        self.count_swings: Counter = Counter()
        self.pitched_pa = 0
        self.first_pitch_pa_end = 0
        # per-player lines
        self.batters: dict[str, Counter] = defaultdict(Counter)
        self.pitchers: dict[str, Counter] = defaultdict(Counter)
        self.batter_team: dict[str, str] = {}
        self.fielders: dict[tuple[str, str], Counter] = defaultdict(Counter)
        # fatigue / TTO (within pitcher)
        self.fb_velo: dict[tuple[int, str], dict[str, list[float]]] = {}
        self.fb_velo_league: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
        self.fatigue_woba: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: defaultdict(lambda: [0.0, 0])
        )
        self.tto_woba: dict[str, dict[int, list[float]]] = defaultdict(
            lambda: defaultdict(lambda: [0.0, 0])
        )
        # league / team
        self.platoon: dict[str, Counter] = defaultdict(Counter)
        self.home: Counter = Counter()
        self.team_wl: dict[str, Counter] = defaultdict(Counter)
        self.team_def: dict[str, Counter] = defaultdict(Counter)
        self.hand_ra: dict[str, Counter] = defaultdict(Counter)
        # line scores
        self.half_runs: Counter = Counter()  # (inning bucket) -> runs
        self.half_count: Counter = Counter()
        self.half_dist: Counter = Counter()  # runs (capped at 3), innings 1-8
        self.extra_halves = Counter()
        self.extra_games = 0
        # base-out (needs pa_start logging)
        self.logged_games = 0
        self.re24: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0, 0.0, 0])
        self.situ: dict[str, Counter] = defaultdict(Counter)
        self.xbt: Counter = Counter()
        self.gidp: Counter = Counter()
        self.ending: Counter = Counter()
        self.ending_examples: list[dict[str, Any]] = []

    # -- setup
    def _load_players(self, path: Path) -> None:
        if not path.exists():
            return
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                pid = str(row.get("player_id") or "")
                if not pid:
                    continue
                bats = str(row.get("bats") or "R").strip().upper() or "R"
                throws = str(row.get("throws") or "").strip().upper()
                if throws not in {"L", "R"}:
                    # Same fallback as PitcherRatings.from_row.
                    throws = "R" if bats == "S" else (bats if bats in {"L", "R"} else "R")
                self.bats[pid] = bats
                self.throws[pid] = throws
                self.primary_pos[pid] = str(row.get("primary_position") or "").strip().upper()
                try:
                    self.fa[pid] = float(row.get("fa") or "")
                except ValueError:
                    pass
                try:
                    self.sp[pid] = float(row.get("sp") or "")
                except ValueError:
                    pass

    # -- per game
    def add_game(
        self,
        result: Any,
        *,
        away: str,
        home: str,
    ) -> None:
        meta = getattr(result, "metadata", None) or {}
        totals = getattr(result, "totals", None) or {}
        log = getattr(result, "pitch_log", None) or []
        game_index = self.games
        self.games += 1
        for key in ("pa", "e", "wp", "pb", "sf", "ibb", "hbp"):
            self.totals[key] += _int(totals.get(key))

        teams = {"away": away, "home": home}
        starters: set[str] = set()
        roles: dict[str, str] = {}
        for side in ("away", "home"):
            for usage in (meta.get("pitcher_usage") or {}).get(side, []) or []:
                roles[str(usage.get("player_id", ""))] = str(
                    usage.get("staff_role") or ""
                ).upper()

        for side, team in teams.items():
            other = "home" if side == "away" else "away"
            tdef = self.team_def[team]
            for line in (meta.get("pitcher_lines") or {}).get(side, []) or []:
                pid = str(line.get("player_id", ""))
                pitches = _int(line.get("pitches"))
                outs = _int(line.get("outs"))
                pc = self.pitchers[pid]
                for key in ("bf", "bb", "ibb", "so", "hr", "hbp", "outs", "r", "h"):
                    pc[key] += _int(line.get(key))
                for key in ("bf", "h", "hr", "bb", "so", "hbp"):
                    tdef[key] += _int(line.get(key))
                hand = self.throws.get(pid, "R")
                self.hand_ra[hand]["r"] += _int(line.get("r"))
                self.hand_ra[hand]["outs"] += outs
                if _int(line.get("gs")) >= 1:
                    starters.add(pid)
                    self.usage["starts"] += 1
                    self.usage["starts_120"] += pitches >= 120
                elif pid:  # same relief rule as the harness's S2-12 usage KPIs
                    self.usage["relief"] += 1
                    self.usage["relief_60"] += pitches >= 60
                    self.usage["relief_outs"] += outs
                    self.usage["relief_pitches"] += pitches
                    if roles.get(pid) == "CL":
                        self.usage["closer_apps"] += 1
                        self.usage["closer_outs"] += outs
                        self.closer_outs_by_pid[pid] += outs
            for line in (meta.get("batting_lines") or {}).get(side, []) or []:
                pid = str(line.get("player_id", ""))
                bc = self.batters[pid]
                for key in ("pa", "bb", "ibb", "so", "hr", "hbp", "sh", "sf", "gs"):
                    bc[key] += _int(line.get(key))
                self.batter_team.setdefault(pid, team)
                # Reached on error counts against the FIELDING team's DER.
                self.team_def[teams[other]]["roe"] += _int(line.get("roe"))
            for line in (meta.get("fielding_lines") or {}).get(side, []) or []:
                if _int(line.get("gs")) < 1:
                    continue
                pid = str(line.get("player_id", ""))
                pos = self.lineup_pos.get((team, pid)) or self.primary_pos.get(pid, "")
                fc = self.fielders[(pid, pos)]
                fc["gs"] += 1
                fc["po"] += _int(line.get("po"))
                fc["a"] += _int(line.get("a"))

        self._add_bullpen_usage(meta, log)

        score = meta.get("score") or {}
        s_away, s_home = _int(score.get("away")), _int(score.get("home"))
        if s_home != s_away and not meta.get("ended_in_tie"):
            self.home["decided"] += 1
            self.home["wins"] += s_home > s_away
            win, lose = (home, away) if s_home > s_away else (away, home)
            self.team_wl[win]["w"] += 1
            self.team_wl[lose]["l"] += 1

        inning_runs = meta.get("inning_runs") or {}
        for side in ("away", "home"):
            for idx, runs in enumerate(inning_runs.get(side, []) or []):
                runs = _int(runs)
                inning = idx + 1
                if inning <= 8:
                    self.half_count["1-8"] += 1
                    self.half_runs["1-8"] += runs
                    self.half_dist[min(runs, 3)] += 1
                    if inning == 1:
                        self.half_count["1"] += 1
                        self.half_runs["1"] += runs
                    if 3 <= inning <= 6:
                        self.half_count["3-6"] += 1
                        self.half_runs["3-6"] += runs
                if 7 <= inning <= 9:
                    self.half_count["7-9"] += 1
                    self.half_runs["7-9"] += runs
                # Extra halves: top halves only. A bottom half exists only
                # when the home side hasn't won yet and stops at the winning
                # run, so including (or excluding) them biases the mean.
                if inning >= 10 and side == "away":
                    self.extra_halves["n"] += 1
                    self.extra_halves["runs"] += runs
                    self.extra_halves["scored"] += runs > 0
        if _int(meta.get("innings")) > 9:
            self.extra_games += 1

        pas = split_plate_appearances(log)
        self._add_pitch_level(log, starters, game_index)
        self._add_pa_level(pas, starters)
        if pas and pas[0].state is not None:
            self.logged_games += 1
            self._add_base_out(pas, inning_runs, s_away, s_home)
        self._add_bench(meta, teams)

    def _add_bullpen_usage(
        self, meta: dict[str, Any], log: list[dict[str, Any]] | None = None
    ) -> None:
        """Release 3 (H1) bullpen tallies from the engine's ``pitcher_usage``.

        Relief outings only (same rule as the usage block: no start). The
        role is the engine's canonical ``staff_role``; ``prior_streak`` is how
        many days in a row the arm had pitched up to yesterday, so a closer
        outing with ``prior_streak >= 2`` is a third straight day. With a
        pitch log, a closer whose first pitch came before the 7th is an early
        entry.
        """
        first_inning: dict[str, int] = {}
        for entry in log or []:
            pid = str(entry.get("pitcher_id") or "")
            if pid and pid not in first_inning and "inning" in entry:
                first_inning[pid] = _int(entry.get("inning"))
        for side in ("away", "home"):
            usage = {
                str(u.get("player_id", "")): u
                for u in (meta.get("pitcher_usage") or {}).get(side, []) or []
            }
            emergencies = 0
            for line in (meta.get("pitcher_lines") or {}).get(side, []) or []:
                pid = str(line.get("player_id", ""))
                if not pid or _int(line.get("gs")) >= 1:
                    continue
                u = usage.get(pid) or {}
                role = str(u.get("staff_role") or "").upper() or "?"
                rc = self.relief_by_role[role]
                rc["apps"] += 1
                rc["outs"] += _int(line.get("outs"))
                self.usage["relief_fallback"] += bool(u.get("fallback"))
                self.usage["relief_emergency"] += bool(u.get("emergency"))
                emergencies += bool(u.get("emergency"))
                if role == "CL" and _int(u.get("prior_streak")) >= 2:
                    self.usage["closer_third_straight_day"] += 1
                if role == "CL" and pid in first_inning:
                    self.usage["closer_logged_apps"] += 1
                    self.usage["closer_before_7th"] += first_inning[pid] < 7
            # Release 3 second fix round: club-games with an emergency arm,
            # and with more than one (the engine allows one, bar an injury).
            self.usage["emergency_team_games"] += emergencies > 0
            self.usage["emergency_multi_games"] += emergencies > 1

    def _add_pitch_level(
        self, log: list[dict[str, Any]], starters: set[str], game_index: int
    ) -> None:
        for entry in log:
            count = entry.get("count")
            if count is None or "pitch_type" not in entry:
                continue
            self.count_pitches[count] += 1
            if entry.get("swing"):
                self.count_swings[count] += 1
            pid = str(entry.get("pitcher_id", ""))
            if pid in starters and entry.get("pitch_type") == "fb":
                velo = entry.get("velocity")
                bucket = _fatigue_bucket(_int(entry.get("pitch_count")) - 1)
                if velo is None or bucket is None:
                    continue
                key = (game_index, pid)
                outing = self.fb_velo.setdefault(key, {})
                acc = outing.setdefault(bucket, [0.0, 0])
                acc[0] += float(velo)
                acc[1] += 1
                league = self.fb_velo_league[bucket]
                league[0] += float(velo)
                league[1] += 1

    def _add_pa_level(self, pas: list[PlateAppearance], starters: set[str]) -> None:
        for pa in pas:
            token = pa.token
            if not token:
                continue
            b_hand = self.bats.get(pa.batter_id, "R")
            p_hand = self.throws.get(pa.pitcher_id, "R")
            self.platoon[f"{b_hand}{p_hand}"][token] += 1
            if pa.pitches == 0:
                continue  # intentional walk or bunt: no pitch-level data
            self.pitched_pa += 1
            if pa.pitches == 1 and pa.last.get("count") == "0-0":
                self.first_pitch_pa_end += 1
            if token in ("ibb", "sh"):
                continue
            weight = WOBA_WEIGHTS.get(token, 0.0)
            tto = _int(pa.first.get("tto"))
            if tto >= 1:
                acc = self.tto_woba[pa.pitcher_id][min(tto, 3)]
                acc[0] += weight
                acc[1] += 1
            if pa.pitcher_id in starters:
                bucket = _fatigue_bucket(_int(pa.first.get("pitch_count")) - 1)
                if bucket is not None:
                    acc = self.fatigue_woba[pa.pitcher_id][bucket]
                    acc[0] += weight
                    acc[1] += 1

    def _add_base_out(
        self,
        pas: list[PlateAppearance],
        inning_runs: dict[str, list[int]],
        s_away: int,
        s_home: int,
    ) -> None:
        halves: dict[tuple[int, str], list[PlateAppearance]] = {}
        order: list[tuple[int, str]] = []
        for pa in pas:
            if pa.state is None:
                continue
            key = (pa.state[0], pa.state[1])
            if key not in halves:
                halves[key] = []
                order.append(key)
            halves[key].append(pa)
        last_key = order[-1] if order else None
        for key in order:
            inning, half = key
            side = "away" if half == "top" else "home"
            runs_list = inning_runs.get(side) or []
            if inning - 1 >= len(runs_list):
                continue
            half_pas = halves[key]
            start = half_pas[0].state[4]
            end = start + _int(runs_list[inning - 1])
            # Only the game's final half can end before three outs (walk-off).
            walkoff = (
                key == last_key and half == "bottom" and inning >= 9 and s_home > s_away
            )
            for idx, pa in enumerate(half_pas):
                _inn, _half, outs, mask, bat, fld = pa.state
                runs_rest = end - bat
                if inning <= 8:
                    cell = self.re24[(mask, outs)]
                    cell[0] += 1
                    cell[1] += runs_rest
                    cell[2] += runs_rest > 0
                token = pa.token
                if token:
                    self.situ["all"][token] += 1
                    if late_and_close(inning, bat, fld, mask):
                        self.situ["late_close"][token] += 1
                    self.situ["risp" if mask & 6 else "no_risp"][token] += 1
                    self.situ["men_on" if mask else "empty"][token] += 1
                if outs < 2 and mask & 1:
                    self.gidp["opp"] += 1
                    tokens = _event_tokens(pa.last)
                    if token == "out" and ("dp" in tokens or "tp" in tokens):
                        self.gidp["gidp"] += 1
                nxt = half_pas[idx + 1].state if idx + 1 < len(half_pas) else None
                if token in ("1b", "2b") and not pa.mid_event:
                    if nxt is not None:
                        self._add_xbt(token, outs, mask, bat, nxt)
                    elif not walkoff:
                        # The hit's play made the third out on the bases;
                        # the log can't say which runner was out.
                        self.xbt["skipped_out_on_play"] += 1
            if walkoff:
                continue
            last = half_pas[-1]
            if last.token in ("out", "so", "sh") and not last.mid_event:
                ground = last.last.get("ball_type") == "gb" or last.last.get("outcome") == "bunt"
                if ground or last.token == "so":
                    runs = end - last.state[4]
                    self.ending["plays"] += 1
                    self.ending["runs"] += runs
                    if runs > 0:
                        self.ending["plays_with_runs"] += 1
                        if len(self.ending_examples) < 5:
                            self.ending_examples.append(
                                {
                                    "inning": inning,
                                    "half": half,
                                    "outs_before": last.state[2],
                                    "bases_before": last.state[3],
                                    "result": last.token,
                                    "runner_event": last.last.get("runner_event"),
                                    "runs": runs,
                                }
                            )

    def _add_xbt(
        self,
        token: str,
        outs: int,
        mask: int,
        bat: int,
        nxt: tuple[int, str, int, int, int, int],
    ) -> None:
        """Extra bases taken (B-Ref XBT%): a runner going more than one base
        on a single, or more than two on a double, when he could (M7).

        Plays with an out on the bases are skipped: the engine throws out
        non-eligible runners too (the runner from 3rd on a single), and the
        log does not say whose out it was. The headline XBT% and runner-out
        rate come from the engine's own counters (``extra_base_advance_rate``
        / ``extra_base_out_rate`` in the gated metrics); this feeds only the
        first-to-third rate, which therefore excludes outs.

        Runners never pass each other, so with no out on the play the lead
        runner takes the furthest destination; that makes the before/after
        base masks plus the runs scored unambiguous.
        """
        standard = 1 if token == "1b" else 2
        runners = sorted((b for b in (3, 2, 1) if mask & (1 << (b - 1))), reverse=True)
        eligible = [b for b in runners if b + standard <= 3]
        outs_added = nxt[2] - outs
        runs = nxt[4] - bat
        if outs_added > 0:
            self.xbt["skipped_out_on_play"] += 1
            return
        if outs_added < 0 or runs < 0:
            self.xbt["skipped"] += 1
            return
        dests = [4] * runs + sorted(
            (b for b in (3, 2, 1) if nxt[3] & (1 << (b - 1))), reverse=True
        )
        movers = runners + [0]  # the batter trails every runner
        if len(dests) != len(movers):
            self.xbt["skipped"] += 1
            return
        for start, dest in zip(movers, dests):
            if start == 0:
                continue
            if dest < start:
                self.xbt["skipped"] += 1
                return
        for start, dest in zip(movers, dests):
            if start in eligible:
                self.xbt["opp"] += 1
                self.xbt["taken"] += dest > start + standard
                if start == 1 and token == "1b":
                    self.xbt["first_to_third_opp"] += 1
                    self.xbt["first_to_third"] += dest >= 3

    # -- results
    def finalize(
        self, reference: dict[str, dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Compute every report-only metric. ``reference`` (default: the MLB
        reference CSV) is only used for the RE24 cell-error summary."""
        if reference is None:
            reference = load_reference()
        metrics: dict[str, Any] = {}
        tables: dict[str, Any] = {}
        team_games = self.games * 2
        gpt = self.games_per_team or 162

        # Usage (H1). relievers_per_team_game and reliever_b2b_share are
        # already gated harness metrics (S2-12), so they are not repeated here.
        u = self.usage
        metrics["starts_120plus_pct"] = _ratio(u["starts_120"], u["starts"])
        metrics["relief_60plus_pct"] = _ratio(u["relief_60"], u["relief"])
        metrics["relief_outs_per_app"] = _ratio(u["relief_outs"], u["relief"])
        metrics["relief_pitches_per_app"] = _ratio(u["relief_pitches"], u["relief"])
        metrics["closer_ip_per_app"] = (
            u["closer_outs"] / 3.0 / u["closer_apps"] if u["closer_apps"] else None
        )
        metrics["closer_top_ip_per_162"] = (
            max(self.closer_outs_by_pid.values()) / 3.0 * 162.0 / gpt
            if self.closer_outs_by_pid
            else None
        )
        # Release 3 bullpen usage (H1). closer_third_straight_day and
        # emergency_starter_relief_apps are season totals (target 0 and about
        # one per club); the fallback share is rest-flagged relief entries.
        metrics["closer_third_straight_day"] = u["closer_third_straight_day"]
        metrics["emergency_starter_relief_apps"] = u["relief_emergency"]
        metrics["bullpen_fallback_share"] = _ratio(u["relief_fallback"], u["relief"])
        # Release 3 second fix round: emergency outings per club per 162
        # (owner target: about one) and club-games with two or more.
        n_clubs = len(self.team_def)
        metrics["emergency_apps_per_team_season"] = (
            u["relief_emergency"] * 162.0 / gpt / n_clubs if n_clubs else None
        )
        metrics["emergency_multi_games"] = u["emergency_multi_games"]
        metrics["closer_entries_before_7th_share"] = _ratio(
            u["closer_before_7th"], u["closer_logged_apps"]
        )
        tables["relief_outs_per_app_by_role"] = {
            role: {"apps": c["apps"], "outs_per_app": _ratio(c["outs"], c["apps"])}
            for role, c in sorted(self.relief_by_role.items())
        }
        for role in ("CL", "SU", "MR", "LR"):
            c = self.relief_by_role.get(role) or Counter()
            metrics[f"relief_outs_per_app_{role.lower()}"] = _ratio(c["outs"], c["apps"])

        # Plate discipline (M1).
        swing = {}
        for count in COUNTS:
            rate = _ratio(self.count_swings[count], self.count_pitches[count])
            swing[count] = {"pitches": self.count_pitches[count], "swing_rate": rate}
            metrics[f"swing_rate_{count.replace('-', '_')}"] = rate
        tables["swing_by_count"] = swing
        metrics["first_pitch_pa_end_pct"] = _ratio(self.first_pitch_pa_end, self.pitched_pa)

        # Dispersion (H4, H6, M1, M21).
        min_pa = max(50, round(400 * gpt / 162))
        hitters = [c for c in self.batters.values() if c["pa"] >= min_pa]
        pitchers = [c for c in self.pitchers.values() if c["bf"] >= min_pa]

        def h_den(c: Counter) -> int:
            return c["pa"] - c["ibb"] - c["sh"]

        def p_den(c: Counter) -> int:
            return c["bf"] - c["ibb"]

        disp = {}
        for name, group, den, key in (
            ("hitter_bb_pct", hitters, h_den, "bb"),
            ("hitter_k_pct", hitters, h_den, "so"),
            ("hitter_hr_rate", hitters, h_den, "hr"),
            ("pitcher_bb_pct", pitchers, p_den, "bb"),
            ("pitcher_k_pct", pitchers, p_den, "so"),
            ("pitcher_hr_rate", pitchers, p_den, "hr"),
        ):
            rows = [
                (c[key] - (c["ibb"] if key == "bb" else 0), den(c)) for c in group
            ]
            sd, var, n = true_sd(rows)
            metrics[f"{name}_true_sd"] = sd
            disp[name] = {"true_sd": sd, "true_var": var, "n": n, "min_pa": min_pa}
        tables["dispersion"] = disp
        hsd, psd = metrics["hitter_hr_rate_true_sd"], metrics["pitcher_hr_rate_true_sd"]
        metrics["pitcher_hitter_hr_true_sd_ratio"] = (
            (psd / hsd) if (hsd and psd is not None) else None
        )
        min_outs_q = 3 * max(1, round(gpt * 1.0))
        qual_k = [
            c["so"] / c["bf"] for c in self.pitchers.values()
            if c["outs"] >= min_outs_q and c["bf"]
        ]
        # Observed sd over ERA-qualified pitchers: the pitcher counterpart of
        # the gated (hitter) qualified_k_pct_sd (H6).
        metrics["pitcher_k_pct_sd"] = statistics.pstdev(qual_k) if len(qual_k) >= 10 else None

        # Fatigue (H10, L14).
        drops = []
        for outing in self.fb_velo.values():
            early, late = outing.get("early"), outing.get("late")
            if early and late and early[1] and late[1]:
                drops.append(early[0] / early[1] - late[0] / late[1])
        metrics["starter_fb_velo_drop_91_105"] = statistics.fmean(drops) if drops else None
        tables["starter_fb_velo_by_bucket"] = {
            bucket: {"mph": (acc[0] / acc[1]) if acc[1] else None, "pitches": acc[1]}
            for bucket, acc in sorted(self.fb_velo_league.items())
        }
        tables["starter_fb_velo_outings"] = len(drops)
        metrics["starter_woba_delta_91_105"], n_late = _within_delta(
            self.fatigue_woba, "early", "late"
        )
        tables["starter_woba_late_pa"] = n_late
        for k in (2, 3):
            value, n = _within_delta(self.tto_woba, 1, k)
            metrics[f"tto_pass{k}_woba_delta"] = value
            tables[f"tto_pass{k}_pa"] = n

        # Running and defense (M7, M8, M10, M22).
        x = self.xbt
        metrics["first_to_third_on_single_pct"] = (
            _ratio(x["first_to_third"], x["first_to_third_opp"]) if self.logged_games else None
        )
        tables["xbt_counts"] = dict(x)
        tables["gidp_counts"] = dict(self.gidp)
        metrics["sf_per_pa"] = _ratio(self.totals["sf"], self.totals["pa"])
        metrics["gidp_per_opp"] = (
            _ratio(self.gidp["gidp"], self.gidp["opp"]) if self.logged_games else None
        )
        metrics["e_per_team_game"] = _ratio(self.totals["e"], team_games)
        metrics["wp_per_team_game"] = _ratio(self.totals["wp"], team_games)
        metrics["pb_per_team_game"] = _ratio(self.totals["pb"], team_games)
        range_table = self._range_table(gpt)
        tables["fielding_range_proxy"] = range_table
        for pos, row in range_table.items():
            metrics[f"range_plays_per_fa_sd_{pos.lower()}"] = row["plays_per_150g_per_fa_sd"]
        ders = []
        for team, c in self.team_def.items():
            bip = c["bf"] - c["bb"] - c["so"] - c["hbp"] - c["hr"]
            if bip > 0:
                ders.append(1.0 - (c["h"] - c["hr"] + c["roe"]) / bip)
        metrics["team_der_mean"] = statistics.fmean(ders) if ders else None
        metrics["team_der_sd"] = statistics.pstdev(ders) if len(ders) >= 2 else None

        # Situational (L15, L17, L18, M19).
        self._situational(metrics, tables, reference)

        # League and team (L1, H7, L5, L3, M16, M17).
        metrics["home_wpct"] = _ratio(self.home["wins"], self.home["decided"])
        tables["home_decided_games"] = self.home["decided"]
        woba = {k: woba_from_tokens(v)[0] for k, v in self.platoon.items()}
        metrics["platoon_gap_woba_lhb"] = _diff(woba.get("LR"), woba.get("LL"))
        metrics["platoon_gap_woba_rhb"] = _diff(woba.get("RL"), woba.get("RR"))
        ra9 = {
            hand: (27.0 * c["r"] / c["outs"]) if c["outs"] else None
            for hand, c in self.hand_ra.items()
        }
        metrics["lhp_minus_rhp_ra9"] = _diff(ra9.get("L"), ra9.get("R"))
        tables["ra9_by_hand"] = ra9
        metrics["ibb_per_pa"] = _ratio(self.totals["ibb"], self.totals["pa"])
        metrics["hbp_per_pa"] = _ratio(self.totals["hbp"], self.totals["pa"])
        backups = self._backup_catcher_starts(gpt)
        tables["backup_c_starts_per_162"] = backups
        metrics["backup_c_starts_mean_per_162"] = (
            statistics.fmean(backups.values()) if backups else None
        )
        metrics["backup_c_starts_min_per_162"] = min(backups.values()) if backups else None
        wpcts, games = [], []
        for c in self.team_wl.values():
            g = c["w"] + c["l"]
            if g:
                wpcts.append(c["w"] / g)
                games.append(g)
        if len(wpcts) >= 2:
            obs = statistics.pstdev(wpcts)
            noise = statistics.fmean(0.25 / g for g in games)
            metrics["team_wpct_sd"] = obs
            # Single-seed estimate; M17 asks for a multi-seed pooled value.
            metrics["team_true_wpct_sd"] = math.sqrt(max(0.0, obs * obs - noise))
        else:
            metrics["team_wpct_sd"] = metrics["team_true_wpct_sd"] = None

        coverage = {
            "games": self.games,
            "base_out_logged_games": self.logged_games,
            "base_out_logging": (
                "full" if self.games and self.logged_games == self.games
                else "partial" if self.logged_games else "absent"
            ),
        }
        self._bench_metrics(metrics, tables, gpt)
        return {"metrics": metrics, "tables": tables, "coverage": coverage}

    def _situational(
        self,
        metrics: dict[str, Any],
        tables: dict[str, Any],
        reference: dict[str, dict[str, Any]],
    ) -> None:
        hc, hr_ = self.half_count, self.half_runs
        n18 = hc["1-8"]
        mean18 = hr_["1-8"] / n18 if n18 else None
        for runs, key in ((0, "p0"), (1, "p1"), (2, "p2"), (3, "p3plus")):
            metrics[f"inning_runs_{key}"] = _ratio(self.half_dist[runs], n18)
        metrics["runs_per_half_inning_1_8"] = mean18
        metrics["first_inning_runs_ratio"] = (
            (hr_["1"] / hc["1"]) / mean18 if hc["1"] and mean18 else None
        )
        metrics["late_inning_runs_ratio_7_9"] = (
            (hr_["7-9"] / hc["7-9"]) / mean18 if hc["7-9"] and mean18 else None
        )
        metrics["late_inning_runs_ratio_7_9_vs_3_6"] = (
            (hr_["7-9"] / hc["7-9"]) / (hr_["3-6"] / hc["3-6"])
            if hc["7-9"] and hc["3-6"] and hr_["3-6"]
            else None
        )
        ex = self.extra_halves
        metrics["extra_half_runs"] = _ratio(ex["runs"], ex["n"])
        metrics["extra_half_p_score"] = _ratio(ex["scored"], ex["n"])
        metrics["extra_inning_game_share"] = _ratio(self.extra_games, self.games)

        if not self.logged_games:
            for key in (
                "late_close_ops_delta", "risp_ops_delta", "men_on_ops_delta",
                "runs_on_inning_ending_plays", "re24_max_abs_pct_err",
                "re24_cells_over_8pct",
            ):
                metrics[key] = None
            for mask, name in BASE_NAMES.items():
                for outs in range(3):
                    metrics[f"re24_{name}_{outs}"] = None
                    metrics[f"runprob_{name}_{outs}"] = None
            return
        overall = ops_from_tokens(self.situ["all"])
        metrics["late_close_ops_delta"] = _diff(ops_from_tokens(self.situ["late_close"]), overall)
        metrics["risp_ops_delta"] = _diff(ops_from_tokens(self.situ["risp"]), overall)
        metrics["men_on_ops_delta"] = _diff(
            ops_from_tokens(self.situ["men_on"]), ops_from_tokens(self.situ["empty"])
        )
        tables["late_close_pa"] = sum(self.situ["late_close"].values())
        # Rule 5.08(a): no run scores on a third out made by the batter before
        # he reaches first or by a force (L15). Must be 0.
        metrics["runs_on_inning_ending_plays"] = self.ending["runs"]
        tables["inning_ending_plays"] = dict(self.ending)
        tables["inning_ending_examples"] = list(self.ending_examples)
        re24 = {}
        for mask, name in BASE_NAMES.items():
            for outs in range(3):
                n, runs, scored = self.re24.get((mask, outs), (0, 0.0, 0))
                key = f"{name}_{outs}"
                metrics[f"re24_{key}"] = (runs / n) if n else None
                metrics[f"runprob_{key}"] = (scored / n) if n else None
                re24[key] = {"n": n, "re": metrics[f"re24_{key}"]}
        tables["re24"] = re24
        # L18's proposed gate: every cell with n >= 1000 within +/-8% of the
        # 2010-15 table (a ~4.24 R/G environment; scale it for hotter leagues).
        errors = []
        for key, cell in re24.items():
            ref = reference.get(f"re24_{key}")
            if ref and ref["value"] and cell["n"] >= 1000 and cell["re"] is not None:
                errors.append(abs(cell["re"] / ref["value"] - 1.0))
        metrics["re24_max_abs_pct_err"] = max(errors) if errors else None
        metrics["re24_cells_over_8pct"] = sum(e > 0.08 for e in errors) if errors else None
        tables["re24_cells_compared"] = len(errors)

    def _range_table(self, gpt: int) -> dict[str, dict[str, Any]]:
        """Per-position plays per 150 games per fa SD among regulars (M22).

        A proxy for OAA per fa SD: outfield putouts and middle/left-side
        infield assists are the plays range decides. It has no expected-outs
        baseline and inherits the engine's credit attribution (M4), so read
        it as a slope, not a run value. 1B and C are left out (their plays
        are mostly receiving throws and strikeouts).
        """
        min_gs = max(5, round(0.5 * gpt))
        rows: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for (pid, pos), c in self.fielders.items():
            if c["gs"] < min_gs or pid not in self.fa:
                continue
            if pos in OUTFIELD_RANGE_POSITIONS:
                plays = c["po"]
            elif pos in INFIELD_RANGE_POSITIONS:
                plays = c["a"]
            else:
                continue
            rows[pos].append((self.fa[pid], plays * 150.0 / c["gs"]))
        table = {}
        for pos in INFIELD_RANGE_POSITIONS + OUTFIELD_RANGE_POSITIONS:
            pts = rows.get(pos, [])
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            slope = _slope(xs, ys) if len(pts) >= 5 else None
            sd = statistics.pstdev(xs) if len(xs) >= 2 else None
            table[pos] = {
                "n": len(pts),
                "fa_sd": sd,
                "plays_per_150g_per_fa_point": slope,
                "plays_per_150g_per_fa_sd": (slope * sd) if (slope is not None and sd) else None,
                "r": _pearson(xs, ys) if len(pts) >= 5 else None,
            }
        return table

    def _backup_catcher_starts(self, gpt: int) -> dict[str, float]:
        by_team: dict[str, list[int]] = defaultdict(list)
        for pid, c in self.batters.items():
            team = self.batter_team.get(pid)
            if team and self.primary_pos.get(pid) == "C":
                by_team[team].append(c["gs"])
        out = {}
        for team in self.team_wl.keys() | set(self.batter_team.values()):
            starts = sorted(by_team.get(team, []), reverse=True)
            out[team] = (starts[1] if len(starts) > 1 else 0) * 162.0 / gpt
        return out


    # -- Release 3 item F (audit M16): bench, rest days, batter fatigue.
    # Reads the engine's per-side "bench_usage" metadata (pre-game rest
    # tallies) plus the batting lines already accumulated above.
    def _add_bench(self, meta: dict[str, Any], teams: dict[str, str]) -> None:
        tally = getattr(self, "bench_tally", None)
        if tally is None:
            tally = self.bench_tally = Counter()
            self.bench_logged_games = 0
        usage = meta.get("bench_usage")
        if not isinstance(usage, dict):
            return
        self.bench_logged_games += 1
        for side in teams:
            for key, value in (usage.get(side) or {}).items():
                tally[key] += _int(value)

    def _bench_metrics(
        self, metrics: dict[str, Any], tables: dict[str, Any], gpt: int
    ) -> None:
        tally = getattr(self, "bench_tally", Counter())
        logged = getattr(self, "bench_logged_games", 0)
        teams = {t for t in self.batter_team.values() if t}
        n_teams = len(teams)
        per_team = (162.0 / gpt / n_teams) if (n_teams and gpt) else None

        def season(key: str) -> float | None:
            return tally[key] * per_team if (logged and per_team) else None

        metrics["bench_rests_per_team_season"] = season("rests")
        metrics["bench_chain_subs_per_team_season"] = season("chain")
        metrics["bench_similar_subs_per_team_season"] = season("similar")
        # League totals per 162-game season (the V4 targets: < 500 / < 50).
        scale = 162.0 / gpt if gpt else 1.0
        metrics["bench_rests_blocked_field_per_162"] = (
            (tally["blocked"] - tally["blocked_c"]) * scale if logged else None
        )
        metrics["bench_rests_blocked_c_per_162"] = tally["blocked_c"] * scale if logged else None
        metrics["fatigue_tired_starter_share"] = (
            _ratio(tally["starters_tired"], tally["starters"]) if logged else None
        )
        everyday = sum(1 for c in self.batters.values() if c["gs"] >= gpt)
        metrics["hitters_starting_every_game"] = everyday if self.games else None
        c_starts: dict[str, list[int]] = defaultdict(list)
        for pid, c in self.batters.items():
            team = self.batter_team.get(pid)
            if team and self.primary_pos.get(pid) == "C":
                c_starts[team].append(c["gs"])
        tops = [max(v) for v in c_starts.values() if v]
        metrics["starting_c_max_starts_per_162"] = (
            max(tops) * 162.0 / gpt if (tops and gpt) else None
        )
        tables["bench_usage_totals"] = dict(tally)


def _diff(a: float | None, b: float | None) -> float | None:
    return (a - b) if (a is not None and b is not None) else None


def _fatigue_bucket(pitches_before: int) -> str | None:
    if FATIGUE_EARLY[0] <= pitches_before <= FATIGUE_EARLY[1]:
        return "early"
    if FATIGUE_LATE[0] <= pitches_before <= FATIGUE_LATE[1]:
        return "late"
    return None


def _within_delta(
    acc: dict[str, dict[Any, list[float]]], base: Any, other: Any
) -> tuple[float | None, int]:
    """Within-pitcher mean difference (other - base), weighted by each
    pitcher's PA in ``other``. Removes the composition effect that pooled
    splits carry: only better pitchers reach pass 3 or 91+ pitches."""
    num = 0.0
    weight = 0
    for buckets in acc.values():
        a, b = buckets.get(base), buckets.get(other)
        if not a or not b or not a[1] or not b[1]:
            continue
        num += b[1] * (b[0] / b[1] - a[0] / a[1])
        weight += b[1]
    return ((num / weight) if weight else None), weight


def _load_lineup_positions(lineup_dir: Path) -> dict[tuple[str, str], str]:
    """(team, player) -> fielding position from the team's lineup files, when
    both lineups agree; DH and conflicting entries are left out."""
    found: dict[tuple[str, str], set[str]] = defaultdict(set)
    if not lineup_dir or not Path(lineup_dir).is_dir():
        return {}
    for path in Path(lineup_dir).glob("*_vs_*.csv"):
        team = path.name.split("_vs_")[0]
        try:
            with path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    pid = str(row.get("player_id") or "")
                    pos = str(row.get("position") or "").strip().upper()
                    if pid and pos and pos != "DH":
                        found[(team, pid)].add(pos)
        except OSError:
            continue
    return {key: next(iter(v)) for key, v in found.items() if len(v) == 1}


# ------------------------------------------------------------ MLB reference
def load_reference(path: Path = DEFAULT_REFERENCE_PATH) -> dict[str, dict[str, Any]]:
    """metric_key -> {value, approximate, source}. Missing file -> {}."""
    ref: dict[str, dict[str, Any]] = {}
    path = Path(path)
    if not path.exists():
        return ref
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("metric_key") or "").strip()
            try:
                value = float(row.get("value") or "")
            except ValueError:
                continue
            ref[key] = {
                "value": value,
                "approximate": str(row.get("approximate") or "").strip() == "1",
                "source": row.get("source_note") or "",
            }
    return ref


def attach_reference(report: dict[str, Any], reference: dict[str, dict[str, Any]]) -> None:
    """Add ``reference`` and ``deltas`` blocks (value minus MLB) in place."""
    metrics = report.get("metrics", {})
    report["reference"] = {k: reference[k] for k in metrics if k in reference}
    report["deltas"] = {
        k: metrics[k] - reference[k]["value"]
        for k in metrics
        if k in reference and isinstance(metrics[k], (int, float))
    }


def format_report(report: dict[str, Any]) -> str:
    metrics = report.get("metrics", {})
    reference = report.get("reference", {})
    lines = [
        "Report-only KPIs (audit Release 2; --strict gates only the"
        " promoted keys)"
    ]
    coverage = report.get("coverage") or {}
    if coverage:
        lines.append(
            "  base-out logging: {base_out_logging} "
            "({base_out_logged_games}/{games} games)".format(**coverage)
        )
    if report.get("runtime_s") is not None:
        lines.append(f"  extra runtime: {report['runtime_s']:.1f}s")
    if report.get("error"):
        lines.append(f"  ERROR: {report['error']}")
    lines.append(f"  {'metric':<38} {'engine':>10} {'MLB':>10}")
    for key in sorted(metrics):
        value = metrics[key]
        if isinstance(value, (dict, list)):
            continue
        ref = reference.get(key)
        ref_txt = ""
        if ref:
            ref_txt = f"{ref['value']:.4g}" + ("~" if ref["approximate"] else "")
        val_txt = "n/a" if value is None else f"{value:.4g}"
        lines.append(f"  {key:<38} {val_txt:>10} {ref_txt:>10}")
    lines.append("  (~ = approximate reference)")
    return "\n".join(lines)


# ---------------------------------------------------------- matchup grids
def _population_levels(players_path: Path) -> tuple[list[float], list[float]]:
    """Hitter PH and pitcher (control+movement)/2 values from the fixture."""
    ph: list[float] = []
    comp: list[float] = []
    with Path(players_path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                if str(row.get("is_pitcher", "")).strip() in {"1", "True", "true"}:
                    comp.append((float(row["control"]) + float(row["movement"])) / 2.0)
                else:
                    ph.append(float(row["ph"]))
            except (KeyError, TypeError, ValueError):
                continue
    return ph, comp


def _pct(values: list[float], q: float) -> float:
    vals = sorted(values)
    idx = min(len(vals) - 1, max(0, round(q * (len(vals) - 1))))
    return vals[idx]


def _p5_50_p95(values: list[float]) -> list[float]:
    """Grid levels spanning the population's p5-p95, with 50 as the anchor."""
    if not values:
        return [50.0]
    return sorted({float(round(_pct(values, q))) for q in (0.05, 0.95)} | {50.0})


# A log5 cell needs this many events in each of its four inputs; with fewer,
# a zero count clamps to logit(1e-6) and swamps the max residual. Raise
# --matchup-grid-pa if cells are skipped.
GRID_MIN_EVENTS = 20


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _simulate_cell(
    *, contact: float, power: float, pitcher_level: float, n: int, seed: int,
    tuning: Any, park: Any,
) -> Counter:
    from physics_sim.engine import _batter_context
    from physics_sim.models import BatterRatings, PitcherRatings
    from physics_sim.physics import resolve_batted_ball, simulate_pitch

    batter = BatterRatings(
        player_id="grid_b", bats="R", primary_position="CF", other_positions=[],
        contact=contact, power=power, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=50.0, speed=50.0, eye=50.0,
        height=73.0, durability=50.0,
    )
    pitcher = PitcherRatings(
        player_id="grid_p", bats="R", throws="R", role="SP", preferred_role="SP",
        velocity=50.0, control=pitcher_level, movement=pitcher_level,
        gb_tendency=50.0, vs_left=50.0, hold_runner=50.0, endurance=50.0,
        durability=50.0, fielding=50.0, arm=50.0,
        repertoire={"fb": 55.0, "sl": 55.0, "cu": 55.0, "cb": 55.0},
    )
    ctx_b = _batter_context(batter, pitcher, tuning, tto=1)
    # Mirrors the engine's per-PA pitcher context (fresh pitcher).
    ctx_p = {
        "repertoire": pitcher.repertoire, "velocity": 83.0 + pitcher.arm * 0.2,
        "control": pitcher.control, "movement": pitcher.movement,
        "fatigue_factor": 1.0, "hand": pitcher.throws, "vs_left": pitcher.vs_left,
    }
    context = {
        "inning": 1, "outs": 0, "score_diff": 0,
        "bases": {"first": False, "second": False, "third": False},
        "catcher_fielding": 50.0, "batter_pitches_seen": 0,
        "batter_swing_rate": None, "batter_chase_rate": None,
        "last_pitch_type": None, "last_pitch_repeat": 0,
        "foul_territory_scale": 1.0,
    }
    # simulate_pitch draws from the module-level random stream; common random
    # numbers (same seed per cell) keep the log5 residuals low-noise.
    random.seed(seed)
    out: Counter = Counter()
    for _ in range(n):
        out["pa"] += 1
        balls = strikes = 0
        while True:
            res = simulate_pitch(
                batter=ctx_b, pitcher=ctx_p, tuning=tuning,
                count=(balls, strikes), context=context,
            )
            o = res.outcome
            if o == "ball":
                balls += 1
                if balls >= 4:
                    out["bb"] += 1
                    break
            elif o in ("hbp", "interference"):
                break
            elif o in ("strike", "swinging_strike"):
                strikes += 1
                if strikes >= 3:
                    out["k"] += 1
                    break
            elif o == "foul":
                strikes = min(2, strikes + 1)
            elif o == "in_play":
                _dist, is_hr, _bt, _ht = resolve_batted_ball(
                    exit_velo=res.exit_velo or 90.0,
                    launch_angle=res.launch_angle or 12.0,
                    spray_angle=res.spray_angle or 0.0,
                    park=park, tuning=tuning, batter_speed=batter.speed,
                    batter_contact=batter.contact, batter_power=batter.power,
                )
                out["hr"] += bool(is_hr)
                break
            else:
                break
    return out


def _log5_grid(
    cells: dict[tuple[float, float], Counter], levels_b: list[float],
    levels_p: list[float], anchor: float, key: str,
) -> dict[str, Any]:
    """Compare each cell with log5 from the anchor row/column (M20/M21)."""
    rows = []
    max_pp = max_logit = 0.0
    for b in levels_b:
        for p in levels_p:
            inputs = (cells[(b, p)], cells[(b, anchor)], cells[(anchor, p)],
                      cells[(anchor, anchor)])
            if min(c[key] for c in inputs) < GRID_MIN_EVENTS:
                rows.append({"batter": b, "pitcher": p, "skipped": "thin cell"})
                continue
            obs = cells[(b, p)][key] / cells[(b, p)]["pa"]
            bm = cells[(b, anchor)][key] / cells[(b, anchor)]["pa"]
            pm = cells[(anchor, p)][key] / cells[(anchor, p)]["pa"]
            lg = cells[(anchor, anchor)][key] / cells[(anchor, anchor)]["pa"]
            pred = 1.0 / (1.0 + math.exp(-(_logit(bm) + _logit(pm) - _logit(lg))))
            res_pp = obs - pred
            res_logit = _logit(obs) - _logit(pred)
            max_pp = max(max_pp, abs(res_pp))
            max_logit = max(max_logit, abs(res_logit))
            rows.append({
                "batter": b, "pitcher": p, "observed": obs, "log5": pred,
                "residual": res_pp, "residual_logit": res_logit,
            })
    return {"cells": rows, "max_abs_residual": max_pp, "max_abs_residual_logit": max_logit}


def matchup_grid_metrics(
    *,
    pa_per_cell: int,
    players_path: Path,
    tuning_overrides: dict[str, float] | None = None,
    seed: int = 20261006,
) -> dict[str, Any]:
    """CH x pitcher K grid and PH x pitcher HR grid, log5 residuals (M20, M21).

    A PA-level Monte Carlo on the real per-pitch code, as the audit ran it:
    one batter rating varies, the other is 50; the pitcher's control and
    movement both equal the level (repertoire 55); generic park. The CH grid
    spans 35-80 (the M20 gate range); the PH grid spans the fixture's own
    p5-p95 of hitter PH and pitcher composite (the M21 gate range), with 50 as
    the log5 anchor. Saves and restores the global random state.
    """
    from physics_sim.config import load_tuning
    from physics_sim.park import load_park

    tuning = load_tuning(tuning_overrides)
    park = load_park(None)
    ph_pop, comp_pop = _population_levels(players_path)
    state = random.getstate()
    try:
        ch_levels = [35.0, 50.0, 65.0, 80.0]
        ch_cells = {
            (b, p): _simulate_cell(
                contact=b, power=50.0, pitcher_level=p, n=pa_per_cell, seed=seed,
                tuning=tuning, park=park,
            )
            for b in ch_levels for p in ch_levels
        }
        k_grid = _log5_grid(ch_cells, ch_levels, ch_levels, 50.0, "k")
        ph_levels = _p5_50_p95(ph_pop)
        p_levels = _p5_50_p95(comp_pop)
        ph_cells = {
            (b, p): _simulate_cell(
                contact=50.0, power=b, pitcher_level=p, n=pa_per_cell, seed=seed,
                tuning=tuning, park=park,
            )
            for b in ph_levels for p in p_levels
        }
        hr_grid = _log5_grid(ph_cells, ph_levels, p_levels, 50.0, "hr")
    finally:
        random.setstate(state)
    return {
        "metrics": {
            "matchup_k_log5_max_abs_resid": k_grid["max_abs_residual"],
            "matchup_hr_log5_max_abs_resid_logit": hr_grid["max_abs_residual_logit"],
        },
        "tables": {
            "matchup_k_grid": {"levels": ch_levels, "pa_per_cell": pa_per_cell, **k_grid},
            "matchup_hr_grid": {
                "ph_levels": ph_levels, "pitcher_levels": p_levels,
                "pa_per_cell": pa_per_cell, **hr_grid,
            },
        },
    }
