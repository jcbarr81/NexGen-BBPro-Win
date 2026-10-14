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

Release 5a adds the plate-discipline, contact, platoon and situational rows
Release 5 tunes against (``ReportOnlyKpis._add_r5`` / ``_r5_metrics`` and the
extra matchup-grid tables). All of them read the pitch log and box lines the
engine already writes; none is a gate.

Release 6a adds the rows Release 6 is built against, in four groups
(``ReportOnlyKpis._add_r6`` / ``_r6_metrics``): pitching (what each pitcher
rating is worth, batted balls by pitch type, the tired-starter and
times-through-the-order deltas with the batters faced taken out), power
(home runs by Power, doubles by Power, Contact and ground-ball rating),
fielding (errors and plays by position, players off their position) and
the batted ball (Statcast launch-angle classes, home run distance, spray by
batting side). The fielding rows by position need two records the engine
hands this harness beside the game (``GameResult.play_records``, never in
the pitch log or the metadata) and are None without them: ``fld_pos`` (the
position each out or error in play is credited to, by pitch-log index) and
``starting_positions``. A fault in this block is recorded in
``tables["r6_kpi_error"]`` and leaves every other row as it was. The
matchup grid gains a composite pitcher axis (an option) and the
``power_hr600_p<level>`` table. None is a gate.
"""
from __future__ import annotations

import csv
import math
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

# Every players.csv parse here reads rows as the engine does, whatever
# rating scale the fixture is stored on (see physics_sim_season_kpis).
from utils.rating_scale import engine_rows

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
        # Release 4 (W1): pitcher control, for the wild-pitch response check.
        self.control = _load_pitcher_control(Path(players_path))
        # Release 5: the pitcher ratings the engine reads, for the
        # rating-adjusted LHP-minus-RHP run average.
        self.pitcher_ratings = _load_pitcher_ratings(Path(players_path))
        # Release 5a: hitter Contact and Eye, for the rating-response slopes.
        self.ch, self.eye = _load_hitter_contact_eye(Path(players_path))
        # Release 6a: hitter Power, ground-ball and pull ratings, pitcher
        # ground-ball rating and each player's listed second positions.
        self.r6_ratings = _load_r6_ratings(Path(players_path))
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
        # Release 4 (W2): hit advancement by runner speed and situation (from
        # the engine's ``hit_adv`` rows) and batted-ball results by batter
        # speed (triples, BABIP, ground-ball hits).
        self.hit_adv_sit: dict[str, Counter] = defaultdict(Counter)
        self.hit_adv_tier: dict[str, Counter] = defaultdict(Counter)
        self.speed_bat: dict[str, Counter] = defaultdict(Counter)

    # -- setup
    def _load_players(self, path: Path) -> None:
        if not path.exists():
            return
        with path.open(newline="", encoding="utf-8") as handle:
            for row in engine_rows(handle):
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
        self._add_hit_speed(pas)
        self._add_hit_play_rules(pas, meta)  # Release 4 F1
        if pas and pas[0].state is not None:
            self.logged_games += 1
            self._add_base_out(pas, inning_runs, s_away, s_home)
        self._add_bench(meta, teams)
        self._add_running_w1(totals, log, meta)  # Release 4 (W1)
        self._add_outs_in_play(log, pas, totals)
        self._add_r5(meta, log, pas, starters)  # Release 5a
        # Release 6a. Guarded: a fault here must not take the rows above
        # (some of them strict gates) down with it.
        if getattr(self, "r6_error", None) is None:
            try:
                records = getattr(result, "play_records", None)
                self._add_r6(meta, log, pas, starters, records or {}, teams)
            except Exception as exc:
                self.r6_error = f"{type(exc).__name__}: {exc}"

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
        adjusted = _hand_ra9_rating_adjusted(
            self.pitchers, self.throws, self.pitcher_ratings
        )
        metrics["lhp_minus_rhp_ra9_rating_adj"] = adjusted["gap"]
        tables["ra9_by_hand_rating_adj"] = adjusted
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
        self._running_w1_metrics(metrics, tables, gpt)  # Release 4 (W1)
        self._hit_speed_metrics(metrics, tables, gpt)
        self._hit_play_rule_metrics(metrics, tables)  # Release 4 F1
        self._outs_in_play_metrics(metrics, tables, team_games)
        self._r5_metrics(metrics, tables, gpt, min_pa)  # Release 5a
        # Release 6a, into its own dicts first: a fault leaves its rows None
        # and everything above untouched.
        r6_metrics: dict[str, Any] = {key: None for key in R6_METRIC_KEYS}
        r6_tables: dict[str, Any] = {}
        error = getattr(self, "r6_error", None)
        if error is None:
            try:
                self._r6_metrics(r6_metrics, r6_tables, gpt, team_games)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                r6_metrics = {key: None for key in R6_METRIC_KEYS}
                r6_tables = {}
        if error is not None:
            r6_tables["r6_kpi_error"] = error
        for key, value in r6_metrics.items():
            metrics.setdefault(key, value)
        for key, value in r6_tables.items():
            tables.setdefault(key, value)
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
        # he reaches first or by a force (L15). Must be 0. Release 4 F1 adds
        # hits and reaches on error whose play made the third out on the
        # bases (_add_hit_play_rules), including runs after a tag third out.
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

    # -- Release 4 (W1): steals, wild pitches, passed balls, dropped third
    # strikes (audit H2, M10). Report-only; Release 4 W4 promotes the gates.
    # The zero checks read the engine's per-entry ``event_bases`` /
    # ``event_outs`` (the bases and outs before the play); a log without them
    # leaves those checks None ("not logged").
    def _add_running_w1(
        self,
        totals: dict[str, Any],
        log: list[dict[str, Any]],
        meta: dict[str, Any],
    ) -> None:
        run = getattr(self, "running_w1", None)
        if run is None:
            run = self.running_w1 = Counter()
            self.steal_by_pid: dict[str, Counter] = defaultdict(Counter)
            self.wp_by_pitcher: dict[str, Counter] = defaultdict(Counter)
            self.pb_by_catcher: dict[str, Counter] = defaultdict(Counter)
        for key in ("sb", "cs", "po", "pocs", "k_reach", "balk"):
            run[key] += _int(totals.get(key))
        for entry in log:
            tokens = _event_tokens(entry)
            if not tokens:
                continue
            logged = "event_bases" in entry
            mask = _int(entry.get("event_bases")) & 7
            foul = entry.get("outcome") == "foul"
            steal = {t for t in tokens if t[:2] in ("sb", "cs")}
            missed = tokens & {"wp", "pb"}
            if steal:
                run["steal_entries"] += 1
                run["steal_logged"] += logged
                run["steal_on_foul"] += foul
                cs = sum(1 for t in steal if t.startswith("cs"))
                run["double_steal_plays"] += len(steal) >= 2 or "adv2" in tokens
                run["double_steal_two_out"] += cs >= 2
                run["steal_third_attempts"] += sum(1 for t in steal if t.endswith("3"))
                run["steal_attempt_events"] += len(steal)
                run["adv2"] += "adv2" in tokens
            if missed:
                run["wp_pb_entries"] += 1
                run["wp_pb_logged"] += logged
                run["wp_pb_on_foul"] += foul
                run["wp_pb_bases_empty"] += logged and mask == 0
            if tokens & {"k_wp", "k_pb"}:
                run["k_event_entries"] += 1
                run["k_event_logged"] += logged
                if entry.get("k_reached") and logged:
                    illegal = (mask & 1) and _int(entry.get("event_outs")) < 2
                    run["illegal_k_reach"] += bool(illegal)
        for side in ("away", "home"):
            for line in (meta.get("batting_lines") or {}).get(side, []) or []:
                pid = str(line.get("player_id", ""))
                c = self.steal_by_pid[pid]
                for key in ("sb", "cs", "b1", "bb", "hbp"):
                    c[key] += _int(line.get(key))
            for line in (meta.get("pitcher_lines") or {}).get(side, []) or []:
                pid = str(line.get("player_id", ""))
                c = self.wp_by_pitcher[pid]
                c["wp"] += _int(line.get("wp"))
                c["outs"] += _int(line.get("outs"))
            for line in (meta.get("fielding_lines") or {}).get(side, []) or []:
                pid = str(line.get("player_id", ""))
                if self.primary_pos.get(pid) != "C" or _int(line.get("gs")) < 1:
                    continue
                c = self.pb_by_catcher[pid]
                c["gs"] += 1
                c["pb"] += _int(line.get("pb"))

    def _running_w1_metrics(
        self, metrics: dict[str, Any], tables: dict[str, Any], gpt: int
    ) -> None:
        run = getattr(self, "running_w1", Counter())
        team_games = self.games * 2
        sba = run["sb"] + run["cs"]
        metrics["cs_per_team_game"] = _ratio(run["cs"], team_games)
        metrics["pickoffs_per_team_game"] = _ratio(run["po"], team_games)
        metrics["k_reach_per_team_game"] = _ratio(run["k_reach"], team_games)

        # Zero checks: None when the log carries no event_bases at all.
        def zero_check(key: str, entries: str, logged: str) -> int | None:
            if not self.games:
                return None
            if run[entries] and not run[logged]:
                return None
            return run[key]

        metrics["steal_events_on_foul"] = (
            run["steal_on_foul"] if self.games else None
        )
        metrics["wp_pb_on_foul"] = run["wp_pb_on_foul"] if self.games else None
        metrics["wp_pb_bases_empty"] = zero_check(
            "wp_pb_bases_empty", "wp_pb_entries", "wp_pb_logged"
        )
        metrics["double_steal_two_out_plays"] = (
            run["double_steal_two_out"] if self.games else None
        )
        metrics["illegal_k_reach"] = zero_check(
            "illegal_k_reach", "k_event_entries", "k_event_logged"
        )
        metrics["steal_third_share"] = _ratio(
            run["steal_third_attempts"], run["steal_attempt_events"]
        )
        tables["running_w1_counts"] = dict(run)

        # Per-player steal volume: attempts per time on first (1B+BB+HBP).
        rows = getattr(self, "steal_by_pid", {})
        tof_all = sum(c["b1"] + c["bb"] + c["hbp"] for c in rows.values())
        metrics["sba_per_tof"] = _ratio(sba, tof_all)
        tiers: dict[str, Counter] = defaultdict(Counter)
        xs: list[float] = []
        ys: list[float] = []
        min_tof = max(20, round(100 * gpt / 162))
        scale = 162.0 / gpt if gpt else 1.0
        sb_season: dict[str, float] = {}
        for pid, c in rows.items():
            sp = self.sp.get(pid)
            tof = c["b1"] + c["bb"] + c["hbp"]
            att = c["sb"] + c["cs"]
            if c["sb"]:
                sb_season[pid] = c["sb"] * scale
            if sp is None:
                continue
            t = tiers[_steal_speed_tier(sp)]
            t["tof"] += tof
            t["att"] += att
            t["sb"] += c["sb"]
            t["players"] += 1
            if tof >= min_tof:
                xs.append(sp)
                ys.append(att / tof)
        tier_table = {}
        for name in STEAL_SPEED_TIERS:
            t = tiers.get(name) or Counter()
            att_rate = _ratio(t["att"], t["tof"])
            sb_pct = _ratio(t["sb"], t["att"])
            key = name.replace("-", "_").replace("+", "plus").replace("<", "lt")
            metrics[f"sba_per_tof_sp_{key}"] = att_rate
            metrics[f"sb_pct_sp_{key}"] = sb_pct
            tier_table[name] = {
                "players": t["players"], "tof": t["tof"], "att": t["att"],
                "sb": t["sb"], "att_per_tof": att_rate, "sb_pct": sb_pct,
            }
        tables["steal_by_speed_tier"] = tier_table
        mid = tiers.get("47-53") or Counter()
        fast = tiers.get("68-77") or Counter()
        mid_rate = _ratio(mid["att"], mid["tof"])
        fast_rate = _ratio(fast["att"], fast["tof"])
        metrics["steal_tier_ratio"] = (
            fast_rate / mid_rate if (fast_rate is not None and mid_rate) else None
        )
        metrics["corr_speed_steal_att"] = _pearson(xs, ys) if len(xs) >= 10 else None
        metrics["sb40_count"] = (
            sum(1 for v in sb_season.values() if v >= 40.0) if self.games else None
        )
        metrics["sb_leader"] = max(sb_season.values()) if sb_season else None
        tables["sb_leaders_per_162"] = [
            {"player_id": pid, "sp": self.sp.get(pid), "sb": round(v, 1)}
            for pid, v in sorted(sb_season.items(), key=lambda kv: -kv[1])[:10]
        ]

        # Missed-pitch rating response (M10): pitcher control vs WP/9 and
        # catcher fielding vs PB per game, among regulars.
        control = getattr(self, "control", {})
        min_outs = 3 * max(10, round(60 * gpt / 162))
        px, py = [], []
        for pid, c in getattr(self, "wp_by_pitcher", {}).items():
            if c["outs"] >= min_outs and pid in control:
                px.append(control[pid])
                py.append(27.0 * c["wp"] / c["outs"])
        metrics["corr_control_wp9"] = _pearson(px, py) if len(px) >= 10 else None
        min_gs = max(5, round(40 * gpt / 162))
        cx, cy = [], []
        for pid, c in getattr(self, "pb_by_catcher", {}).items():
            if c["gs"] >= min_gs and pid in self.fa:
                cx.append(self.fa[pid])
                cy.append(c["pb"] / c["gs"])
        metrics["corr_catcher_fa_pb"] = _pearson(cx, cy) if len(cx) >= 5 else None

    # -- Release 4 (W2): balls that fall for hits
    def _add_hit_speed(self, pas: list[PlateAppearance]) -> None:
        """Per-batter batted-ball results and per-runner hit advances.

        Batted balls in play exclude home runs and bunts (BABIP over swung
        balls, as the M6 study measured it). Runner rows come from the
        engine's ``hit_adv`` log on the hit's entry, ``[runner id, start,
        end, error]`` with end 4 = scored and 0 = out; older logs have none
        and only feed the batter half. The 0-1 out / 2 out split reads the
        live out count the engine logs with the rows (``hit_outs``, Release 4
        F1: a steal or pickoff earlier in the PA can change it), falling back
        to the PA-start state for older logs.
        """
        for pa in pas:
            token = pa.token
            if not token:
                continue
            last = pa.last
            bat = self.speed_bat[pa.batter_id]
            bat["pa"] += 1
            bat["b3"] += token == "3b"
            bunt = last.get("outcome") == "bunt" or token == "sh"
            ball_type = last.get("ball_type")
            if ball_type and token != "hr" and not bunt:
                hit = token in ("1b", "2b", "3b")
                bat["bip"] += 1
                bat["h"] += hit
                if ball_type == "gb":
                    bat["gb"] += 1
                    bat["gb_h"] += hit
            if token == "1b":
                bat["b1"] += 1
                bat["infield_1b"] += bool(last.get("infield_hit"))
            rows = last.get("hit_adv")
            if rows and token in ("1b", "2b"):
                outs = last.get("hit_outs")
                if outs is None and pa.state is not None:
                    outs = pa.state[2]
                self._add_hit_adv_rows(token, rows, outs)

    def _add_hit_adv_rows(
        self, token: str, rows: list[Any], outs: int | None
    ) -> None:
        """One hit's runner rows into the situation and speed-tier tables.

        Opportunities are the engine's (``_tally_extra_bases_taken``, B-Ref
        XBT%): the runner from 2nd on a single, the runner from 1st on a
        double, and the runner from 1st on a single only when 3rd was open
        for him. A runner from 1st whose lead runner held at 3rd is BLOCKED:
        he is left out of the ``s_r1`` rows and of
        ``r1_first_to_third_on_single_pct`` as well as the tiers, so that
        rate is first-to-3rd per chance (the plan's .29 target). The forced
        rows (``s_r3``, ``d_r2``, ``d_r3``) are reported but are not XBT
        chances.
        """
        kind = "s" if token == "1b" else "d"
        blocked = any(
            _int(r[1]) == 2 and _int(r[2]) == 3 for r in rows if len(r) >= 4
        )
        for row in rows:
            if len(row) < 4:
                continue
            pid, start = str(row[0]), _int(row[1])
            end, error = _int(row[2]), _int(row[3])
            if start not in (1, 2, 3):
                continue
            if kind == "s" and start == 1 and blocked:
                continue
            # "Taken": the extra base on an XBT chance; a forced runner (3rd
            # on a single, 2nd/3rd on a double) "takes" it by scoring.
            taken = (end >= 3) if (kind == "s" and start == 1) else (end == 4)
            taken = taken and not error
            out = end == 0
            situation = f"{kind}_r{start}"
            split = f"{situation}|{'2' if outs == 2 else '01'}out"
            for key in (situation, split):
                c = self.hit_adv_sit[key]
                c["n"] += 1
                c["taken"] += taken
                c["out"] += out
                c["error"] += error
            if situation not in ("s_r1", "s_r2", "d_r1"):
                continue
            for key in (_speed_tier(self.sp.get(pid)), "all"):
                c = self.hit_adv_tier[key]
                c["opp"] += 1
                c["taken"] += taken
                c["out"] += out

    def _hit_speed_metrics(
        self, metrics: dict[str, Any], tables: dict[str, Any], gpt: int
    ) -> None:
        """XBT and thrown-out rates by runner speed and situation, triples,
        BABIP and ground-ball hits by batter speed (Release 4, W2). Report
        only; MLB rows from the Release 4 plan, sections C and D."""
        sit = self.hit_adv_sit
        logged = bool(self.hit_adv_tier.get("all", Counter())["opp"])

        def rate(key: str, field: str) -> float | None:
            c = sit.get(key)
            return _ratio(c[field], c["n"]) if c else None

        tables["hit_advance_by_situation"] = {
            key: {
                "n": c["n"],
                "taken": _ratio(c["taken"], c["n"]),
                "out": _ratio(c["out"], c["n"]),
                "error": _ratio(c["error"], c["n"]),
            }
            for key, c in sorted(sit.items())
        }
        tables["xbt_by_speed_tier"] = {
            tier: {
                "opp": c["opp"],
                "xbt": _ratio(c["taken"], c["opp"]),
                "out_per_opp": _ratio(c["out"], c["opp"]),
            }
            for tier, c in sorted(
                self.hit_adv_tier.items(), key=lambda kv: _tier_order(kv[0])
            )
        }
        allc = self.hit_adv_tier.get("all", Counter())
        # Same chances as the engine's extra_base_advance_rate (a cross-check).
        metrics["xbt_logged_rate"] = (
            _ratio(allc["taken"], allc["opp"]) if logged else None
        )
        metrics["xbt_thrown_out_per_opp"] = (
            _ratio(allc["out"], allc["opp"]) if logged else None
        )
        metrics["r1_first_to_third_on_single_pct"] = rate("s_r1", "taken")
        metrics["r2_scores_on_single_pct"] = rate("s_r2", "taken")
        metrics["r2_scores_on_single_01out_pct"] = rate("s_r2|01out", "taken")
        metrics["r2_scores_on_single_2out_pct"] = rate("s_r2|2out", "taken")
        metrics["r1_scores_on_double_pct"] = rate("d_r1", "taken")
        metrics["forced_r3_scores_on_single_pct"] = rate("s_r3", "taken")
        metrics["forced_r2_scores_on_double_pct"] = rate("d_r2", "taken")
        for tier, name in (
            ("<40", "lt40"), ("50-59", "50_59"), ("70-84", "70_84"), ("85+", "85plus"),
        ):
            c = self.hit_adv_tier.get(tier)
            metrics[f"xbt_rate_sp{name}"] = _ratio(c["taken"], c["opp"]) if c else None

        # Batter speed: triples, BABIP and ground-ball hits by tier.
        by_tier: dict[str, Counter] = defaultdict(Counter)
        rows: list[tuple[float, Counter]] = []
        for pid, c in self.speed_bat.items():
            sp = self.sp.get(pid)
            if sp is None:
                continue
            by_tier[_speed_tier(sp)].update(c)
            rows.append((sp, c))
        tables["batting_by_speed_tier"] = {
            tier: {
                "pa": c["pa"],
                "b3_per_600pa": _ratio(600.0 * c["b3"], c["pa"]),
                "babip": _ratio(c["h"], c["bip"]),
                "gb_hit_rate": _ratio(c["gb_h"], c["gb"]),
                "infield_1b_share": _ratio(c["infield_1b"], c["b1"]),
            }
            for tier, c in sorted(by_tier.items(), key=lambda kv: _tier_order(kv[0]))
        }
        mid = by_tier.get("50-59", Counter())
        mid_rate = _ratio(mid["b3"], mid["pa"])
        for tier, name in (("70-84", "70_84"), ("85+", "85plus")):
            c = by_tier.get(tier)
            rate_t = _ratio(c["b3"], c["pa"]) if c else None
            metrics[f"triple_rate_ratio_sp{name}_vs_50_59"] = (
                rate_t / mid_rate if (rate_t is not None and mid_rate) else None
            )
            metrics[f"triples_per_600pa_sp{name}"] = (
                _ratio(600.0 * c["b3"], c["pa"]) if c else None
            )
        total = Counter()
        for _sp, c in rows:
            total.update(c)
        metrics["gb_hit_rate"] = _ratio(total["gb_h"], total["gb"])
        metrics["infield_single_share"] = _ratio(total["infield_1b"], total["b1"])
        # BIP-weighted least-squares BABIP slope per 10 sp (players with 50+
        # balls in play): the calibration fixture's speed gate (plan D).
        sel = [(sp, c) for sp, c in rows if c["bip"] >= 50]
        weight = sum(c["bip"] for _sp, c in sel)
        if len(sel) >= 3 and weight:
            mx = sum(sp * c["bip"] for sp, c in sel) / weight
            my = sum(c["h"] for _sp, c in sel) / weight
            num = sum(c["bip"] * (sp - mx) * (c["h"] / c["bip"] - my) for sp, c in sel)
            den = sum(c["bip"] * (sp - mx) ** 2 for sp, c in sel)
            metrics["babip_speed_slope_per10"] = 10.0 * num / den if den else None
        else:
            metrics["babip_speed_slope_per10"] = None
        min_pa = max(50, round(300 * gpt / 162))
        regs = [(sp, c["h"] / c["bip"]) for sp, c in rows if c["pa"] >= min_pa and c["bip"]]
        metrics["r_sp_babip"] = _pearson([a for a, _ in regs], [b for _, b in regs])
        tables["r_sp_babip_min_pa"] = min_pa
        # PA-weighted speed quintiles: fastest minus slowest BABIP.
        srt = sorted(rows, key=lambda r: r[0])
        total_pa = sum(c["pa"] for _sp, c in srt)
        quint = [Counter() for _ in range(5)]
        acc = 0
        for sp, c in srt:
            if total_pa:
                quint[min(4, int(5 * (acc + c["pa"] / 2) / total_pa))].update(c)
            acc += c["pa"]
        q_babip = [_ratio(q["h"], q["bip"]) for q in quint]
        tables["babip_by_speed_quintile"] = q_babip
        metrics["babip_fast_minus_slow_quintile"] = _diff(q_babip[4], q_babip[0])

    # -- Release 4 F1: rule 5.08(a) on hits, and outs per half-inning
    def _add_hit_play_rules(
        self, pas: list[PlateAppearance], meta: dict[str, Any]
    ) -> None:
        """Hits (and reaches on error) whose play made the third out.

        Reads the engine's ``hit_adv`` rows and ``hit_outs`` (the live out
        count; older logs fall back to the PA-start state when nothing moved
        mid-PA). Runners are played lead first, so the k-th out of the play
        is the k-th out row in lead-first order. On a hit the engine throws
        out the runner from 1st on a single at 3rd and every other runner at
        the plate. That out is a FORCE when the runner was forced to that
        very base (every base behind him occupied); the runner from 3rd with
        the bases loaded is the only one on a hit. Rule 5.08(a):
          * third out on a force: no run on the play counts;
          * third out on a tag: runners trailing the out runner must not
            score (only lead runners who scored ahead of him count).
        Runs that break either rule go into ``runs_on_inning_ending_plays``
        (with the ground-out and strikeout plays). A play that records more
        than three outs is counted too. ``inning_outs`` metadata (outs per
        half-inning) feeds ``half_innings_over_three_outs``.
        """
        rule = getattr(self, "hit_rule", None)
        if rule is None:
            rule = self.hit_rule = Counter()
        inning_outs = meta.get("inning_outs")
        if isinstance(inning_outs, dict):
            rule["halves_logged"] += 1
            for side in ("away", "home"):
                for outs in inning_outs.get(side) or []:
                    rule["halves"] += 1
                    rule["halves_over_three"] += _int(outs) > 3
        for pa in pas:
            token = pa.token
            if token not in ("1b", "2b", "roe"):
                continue
            last = pa.last
            note = last.get("hit_rule")
            if isinstance(note, dict) and note:
                rule["rule_plays"] += 1
                rule["rule_cut_runners"] += _int(note.get("cut"))
                rule["rule_held_runners"] += _int(note.get("held"))
            rows = [r for r in (last.get("hit_adv") or []) if len(r) >= 4]
            if not rows:
                continue
            outs_before = last.get("hit_outs")
            if outs_before is None:
                if pa.state is None or pa.mid_event:
                    continue
                outs_before = pa.state[2]
            outs_before = _int(outs_before)
            if outs_before > 2:
                continue
            out_rows = sorted(
                (r for r in rows if _int(r[2]) == 0),
                key=lambda r: -_int(r[1]),
            )
            if outs_before + len(out_rows) < 3:
                continue
            rule["hit_plays"] += 1
            rule["hit_plays_over_three_outs"] += outs_before + len(out_rows) > 3
            third = out_rows[2 - outs_before]
            start = _int(third[1])
            out_base = 3 if (token != "2b" and start == 1) else 4
            occupied = {_int(r[1]) for r in rows}
            forced = out_base == start + 1 and all(
                b in occupied for b in range(1, start)
            )
            bad = sum(
                1 for r in rows
                if _int(r[2]) == 4 and (forced or _int(r[1]) < start)
            )
            rule["hit_force_third_outs"] += forced
            rule["hit_runs"] += bad
            self.ending["plays"] += 1
            self.ending["hit_plays"] += 1
            self.ending["runs"] += bad
            if bad > 0:
                self.ending["plays_with_runs"] += 1
                if len(self.ending_examples) < 5:
                    self.ending_examples.append(
                        {
                            "outs_before": outs_before,
                            "result": token,
                            "hit_adv": rows,
                            "force": forced,
                            "runs": bad,
                        }
                    )

    def _hit_play_rule_metrics(
        self, metrics: dict[str, Any], tables: dict[str, Any]
    ) -> None:
        """Zero check: no half-inning records more than three outs (report
        only; None when no game carried ``inning_outs``). Also the plays
        where the engine's rule 5.08(a) handling stopped a runner."""
        rule = getattr(self, "hit_rule", Counter())
        metrics["half_innings_over_three_outs"] = (
            rule["halves_over_three"] if rule["halves_logged"] else None
        )
        # Plays (hits and reaches on error) on which the rule stopped a
        # runner, over the whole run (one season in the harness).
        metrics["hit_rule_plays"] = rule["rule_plays"] if self.games else None
        tables["hit_play_rule_counts"] = dict(rule)

    # -- Release 4 (W3): outs in play (audit M6 DP half, M7, M8) ------------
    def _oip(self) -> "_OutsInPlay":
        state = getattr(self, "oip", None)
        if state is None:
            state = self.oip = _OutsInPlay()
        return state

    def _add_outs_in_play(
        self,
        log: list[dict[str, Any]],
        pas: list[PlateAppearance],
        totals: dict[str, Any],
    ) -> None:
        """Tag-ups, ground outs with a runner on 3rd and GIDP by batter speed.

        Reads the engine's play records (``tag3`` / ``tag2`` / ``go3`` on the
        play's pitch_log entry, Release 4) and the ``tag_dp`` token. A log
        without them (older engine) only feeds the GIDP-by-speed table.
        """
        oip = self._oip()
        oip.dp_air += _int(totals.get("dp_air"))
        for entry in log:
            tag3 = entry.get("tag3")
            if isinstance(tag3, dict):
                oip.logged = True
                sp = self.sp.get(str(tag3.get("runner", "")))
                oip.tag3.append(
                    (
                        sp,
                        float(tag3.get("arm") or 50.0),
                        str(tag3.get("result") or "hold"),
                        bool(tag3.get("infield")),
                        bool(tag3.get("short")),
                    )
                )
                if not tag3.get("infield"):
                    oip.tag3_short += bool(tag3.get("short"))
            tag2 = entry.get("tag2")
            if isinstance(tag2, dict) and not tag2.get("infield"):
                oip.tag2["opp"] += 1
                oip.tag2["adv"] += tag2.get("result") == "adv"
                if tag2.get("dist") is not None:
                    band = oip.tag2_by_dist[_carry_band(float(tag2["dist"]))]
                    band["opp"] += 1
                    band["adv"] += tag2.get("result") == "adv"
            go3 = entry.get("go3")
            if isinstance(go3, dict):
                oip.logged = True
                key = (_int(go3.get("bases")) & 7, _int(go3.get("outs")))
                cell = oip.go3[key]
                cell["n"] += 1
                cell["scored"] += bool(go3.get("scored"))
                cell["dp"] += bool(go3.get("dp"))
            if "tag_dp" in _event_tokens(entry):
                oip.tag_dp += 1
        for pa in pas:
            if not pa.token:
                continue
            row = oip.gidp_by_batter[pa.batter_id]
            row["pa"] += 1
            if pa.state is None:
                continue
            outs, mask = pa.state[2], pa.state[3]
            if outs < 2 and mask & 1:
                row["opp"] += 1
                tokens = _event_tokens(pa.last)
                if pa.token == "out" and ("dp" in tokens or "tp" in tokens):
                    row["gidp"] += 1

    def _outs_in_play_metrics(
        self, metrics: dict[str, Any], tables: dict[str, Any], team_games: int
    ) -> None:
        """Report-only W3 rows. Targets (plan section E): tag-up score rate
        .72-.78 on outfield flies, thrown out per send .02-.04, r(tag, arm)
        <= -.08, r(tag, sp) >= +.07, fastest / slowest GIDP per opportunity
        quintile ~.5 (.40-.60 on the tier fixture). The RE24 cells (3rd only,
        1st and 3rd) are the existing ``re24_*`` / ``runprob_*`` rows.

        The tag-up rows are final results: a runner thrown out whose out a
        throwing error reverses (``e_th``) counts as scoring, so
        ``tagup_out_per_send`` is outs that stood per send. The race itself
        is ``tagup_race_out_per_send``: every send the throw beat, before
        any error, per send (the engine's ``p_out``; the .02-.04 target is
        for the final row). ``tagup_short_share`` is the share of outfield
        chances on flies under ``tag_up_min_carry_ft`` (pop-ups: nobody tags
        under ``tag_up_model`` 1); ``r_tagup_score_arm`` / ``_sp`` leave
        those out. ``r2_tagup_adv_rate`` is R2 taking 3rd
        per chance (3rd open, inning alive after the tag-up race);
        ``tables["r2_tagup_by_carry"]`` splits it by engine carry."""
        oip = self._oip()
        metrics["dp_air"] = oip.dp_air if self.games else None
        metrics["dp_air_per_team_game"] = _ratio(oip.dp_air, team_games)
        metrics["tag_dp_events"] = oip.tag_dp if self.games else None
        of = [row for row in oip.tag3 if not row[3]]
        infield = [row for row in oip.tag3 if row[3]]
        counts = Counter(row[2] for row in of)
        sends = counts["score"] + counts["error"] + counts["out"]
        n_of = len(of)
        logged = oip.logged
        metrics["tagup_r3_opps"] = n_of if logged else None
        metrics["tagup_score_rate"] = (
            _ratio(counts["score"] + counts["error"], n_of) if logged else None
        )
        metrics["tagup_hold_rate"] = _ratio(counts["hold"], n_of) if logged else None
        metrics["tagup_out_rate"] = _ratio(counts["out"], n_of) if logged else None
        metrics["tagup_send_rate"] = _ratio(sends, n_of) if logged else None
        metrics["tagup_out_per_send"] = _ratio(counts["out"], sends) if logged else None
        metrics["tagup_race_out_per_send"] = (
            _ratio(counts["out"] + counts["error"], sends) if logged else None
        )
        metrics["tagup_short_share"] = (
            _ratio(oip.tag3_short, n_of) if logged else None
        )
        metrics["tagup_infield_share"] = (
            _ratio(len(infield), len(oip.tag3)) if logged else None
        )
        metrics["tagup_infield_score_rate"] = (
            _ratio(sum(r[2] in ("score", "error") for r in infield), len(infield))
            if logged else None
        )
        metrics["r2_tagup_adv_rate"] = (
            _ratio(oip.tag2["adv"], oip.tag2["opp"]) if logged else None
        )
        carry = {}
        for band in CARRY_BANDS:
            c = oip.tag2_by_dist.get(band)
            if c:
                carry[band] = {"n": c["opp"], "adv": _ratio(c["adv"], c["opp"])}
        tables["r2_tagup_by_carry"] = carry
        # The correlations use the chances where the race actually runs:
        # short pop-ups freeze every runner whatever his speed or the arm.
        raced = [r for r in of if not r[4]]
        scored = [1.0 if r[2] in ("score", "error") else 0.0 for r in raced]
        metrics["r_tagup_score_arm"] = _pearson([r[1] for r in raced], scored)
        with_sp = [(r[0], s) for r, s in zip(raced, scored) if r[0] is not None]
        metrics["r_tagup_score_sp"] = _pearson(
            [sp for sp, _ in with_sp], [s for _, s in with_sp]
        )

        def tier_table(rows, bucket):
            table: dict[str, Counter] = defaultdict(Counter)
            for row in rows:
                key = bucket(row)
                if key is not None:
                    table[key][row[2]] += 1
            out = {}
            for key, c in sorted(table.items()):
                n = sum(c.values())
                out[key] = {
                    "n": n,
                    "score": _ratio(c["score"] + c["error"], n),
                    "hold": _ratio(c["hold"], n),
                    "out": _ratio(c["out"], n),
                }
            return out

        def sp_tier(row):
            sp = row[0]
            if sp is None:
                return None
            return "<45" if sp < 45 else "45-59" if sp < 60 else "60-74" if sp < 75 else "75+"

        def arm_tier(row):
            arm = row[1]
            return "<45" if arm < 45 else "45-55" if arm < 55 else "55+"

        tables["tagup_by_speed_tier"] = tier_table(of, sp_tier)
        tables["tagup_by_arm_tier"] = tier_table(of, arm_tier)
        tables["tagup_counts"] = {"outfield": dict(counts), "infield": len(infield)}

        go3 = {}
        for (mask, outs), c in sorted(oip.go3.items()):
            name = BASE_NAMES.get(mask, str(mask))
            go3[f"{name}_{outs}"] = {
                "n": c["n"],
                "r3_scored": _ratio(c["scored"], c["n"]),
                "dp": _ratio(c["dp"], c["n"]),
            }
        tables["ground_out_r3"] = go3
        for mask in (4, 5, 6, 7):
            for outs in (0, 1):
                c = oip.go3.get((mask, outs))
                metrics[f"go_r3_scores_{BASE_NAMES[mask]}_{outs}"] = (
                    _ratio(c["scored"], c["n"]) if (logged and c) else None
                )

        # GIDP per opportunity by PA-weighted batter-speed quintile (M6).
        rows = sorted(
            (self.sp[pid], c)
            for pid, c in oip.gidp_by_batter.items()
            if pid in self.sp and c["pa"]
        )
        total_pa = sum(c["pa"] for _sp, c in rows)
        quint = [Counter() for _ in range(5)]
        acc = 0
        for sp, c in rows:
            q = min(4, int(5 * (acc + c["pa"] / 2) / total_pa))
            quint[q].update(c)
            quint[q]["sp_x_pa"] += sp * c["pa"]
            acc += c["pa"]
        table = []
        for q in quint:
            table.append(
                {
                    "mean_sp": _ratio(q["sp_x_pa"], q["pa"]),
                    "opp": q["opp"],
                    "gidp_per_opp": _ratio(q["gidp"], q["opp"]),
                }
            )
        tables["gidp_by_batter_speed_quintile"] = table
        for i, row in enumerate(table, start=1):
            metrics[f"gidp_per_opp_speed_q{i}"] = row["gidp_per_opp"]
        slow, fast = table[0]["gidp_per_opp"], table[4]["gidp_per_opp"]
        metrics["gidp_fast_slow_ratio"] = (fast / slow) if (slow and fast is not None) else None

    # -- Release 5a: plate discipline, contact, platoon and situations -------
    # Report-only rows for the Release 5 retune. Everything is read from the
    # pitch log and box lines the engine already writes.
    def _r5(self) -> "_R5Tallies":
        state = getattr(self, "r5", None)
        if state is None:
            state = self.r5 = _R5Tallies()
        return state

    def _add_r5(
        self,
        meta: dict[str, Any],
        log: list[dict[str, Any]],
        pas: list[PlateAppearance],
        starters: set[str],
    ) -> None:
        """One game's Release 5a tallies.

        Pitch level: swings in and out of the zone by count (``in_zone`` is
        the rule-book zone, as in the gated z/o-swing), fouls, takes by
        location and call, and hit batters. PA level: called third strikes,
        home and away results, PA with a runner on first only, each
        reliever's first six batters of the outing and the starters' PA by
        times through the order. Box lines: saves and save chances, and
        whether each lineup's hand was the opposing starter's.
        """
        r5 = self._r5()
        pitch = r5.pitch
        for entry in log:
            count = entry.get("count")
            if count is None or "pitch_type" not in entry:
                continue
            outcome = entry.get("outcome")
            swing = bool(entry.get("swing"))
            in_zone = bool(entry.get("in_zone"))
            where = "zone" if in_zone else "chase"
            r5.count_loc[(count, where)] += 1
            r5.count_loc_swings[(count, where)] += swing
            if str(count).endswith("-2"):
                pitch["two_strike"] += 1
                pitch["two_strike_foul"] += outcome == "foul"
            pitch["foul"] += outcome == "foul"
            pitch["in_play"] += outcome == "in_play"
            if outcome == "hbp":
                pitch["hbp"] += 1
                pitch["hbp_in_zone"] += in_zone
            elif not swing and outcome in ("ball", "strike"):
                pitch[f"take_{where}"] += 1
                pitch[f"take_{where}_strike"] += outcome == "strike"
            bat = r5.batter_pitches[str(entry.get("batter_id", ""))]
            bat[where] += 1
            bat[f"{where}_swing"] += swing
            pit = r5.pitcher_pitches[str(entry.get("pitcher_id", ""))]
            pit["pitches"] += 1
            pit["zone"] += in_zone

        faced: Counter = Counter()  # this game's batters faced, per pitcher
        for pa in pas:
            token = pa.token
            if not token:
                continue
            r5.pa["pa"] += 1
            if token == "so" and pa.last.get("strikeout_type") == "called":
                r5.pa["so_looking"] += 1
            faced[pa.pitcher_id] += 1
            if pa.pitcher_id in starters:
                tto = _int(pa.first.get("tto"))
                if tto >= 1:
                    r5.starter_tto[min(tto, 3)][token] += 1
            elif faced[pa.pitcher_id] <= RELIEF_FRESH_BF:
                r5.relief_fresh[token] += 1
            if pa.state is not None:
                r5.half[pa.state[1]][token] += 1
                if pa.state[3] == 1:
                    r5.r1_only[token] += 1

        pitcher_lines = meta.get("pitcher_lines") or {}
        for side in ("away", "home"):
            for line in pitcher_lines.get(side, []) or []:
                r5.saves["sv"] += _int(line.get("sv"))
                r5.saves["svo"] += _int(line.get("svo"))
            for line in (meta.get("batting_lines") or {}).get(side, []) or []:
                bl = r5.batter_lines[str(line.get("player_id", ""))]
                bl["ab"] += _int(line.get("ab"))
                bl["h"] += _int(line.get("h"))

        # The harness picks each lineup (vs LHP / vs RHP) before the game;
        # it must be the one for the starter the other club really used.
        hands = meta.get("lineup_hand")
        if isinstance(hands, dict):
            for side, other in (("away", "home"), ("home", "away")):
                hand = str(hands.get(side) or "").upper()
                starter = next(
                    (
                        str(line.get("player_id", ""))
                        for line in pitcher_lines.get(other, []) or []
                        if _int(line.get("gs")) >= 1
                    ),
                    "",
                )
                if hand not in ("L", "R") or not starter:
                    continue
                faced_hand = "L" if self.throws.get(starter, "R") == "L" else "R"
                r5.lineup_hand["n"] += 1
                r5.lineup_hand["match"] += hand == faced_hand

    def _r5_metrics(
        self, metrics: dict[str, Any], tables: dict[str, Any], gpt: int, min_pa: int
    ) -> None:
        """The Release 5a report-only rows (plan section 2.5); never gated.

        ``min_pa`` is the dispersion block's regular bar (400 PA or BF per
        162 games). Slopes are in percentage points of the rate per 10
        rating points, weighted by each player's PA (or BF). Rows that need
        the base-out state are None when no game logged it.
        """
        r5 = self._r5()
        pitch = r5.pitch

        # Fouls, called third strikes and swings by count and location (M1).
        metrics["foul_per_two_strike_pitch"] = _ratio(
            pitch["two_strike_foul"], pitch["two_strike"]
        )
        metrics["foul_share_of_contact"] = _ratio(
            pitch["foul"], pitch["foul"] + pitch["in_play"]
        )
        # Per engine PA: a catcher's-interference PA carries no result token
        # in the log, so the token count runs about one PA in 4,000 short.
        metrics["looking_k_per_pa"] = _ratio(
            r5.pa["so_looking"], self.totals["pa"] or r5.pa["pa"]
        )
        by_count = {}
        for count in COUNTS:
            row = {}
            for where in ("zone", "chase"):
                n = r5.count_loc[(count, where)]
                rate = _ratio(r5.count_loc_swings[(count, where)], n)
                metrics[f"{where}_swing_rate_{count.replace('-', '_')}"] = rate
                row[f"{where}_pitches"] = n
                row[f"{where}_swing_rate"] = rate
            by_count[count] = row
        tables["zone_chase_swing_by_count"] = by_count

        # Hit batters and the umpire: a pitch in the zone cannot be a hit
        # batter, and a take is called by where the pitch was.
        metrics["hbp_in_zone_share"] = _ratio(pitch["hbp_in_zone"], pitch["hbp"])
        metrics["oz_take_called_strike_rate"] = _ratio(
            pitch["take_chase_strike"], pitch["take_chase"]
        )
        metrics["iz_take_called_ball_rate"] = _ratio(
            pitch["take_zone"] - pitch["take_zone_strike"], pitch["take_zone"]
        )

        # Rating response (H4, M20): walks on Eye and on Control, strikeouts
        # on Contact. Unintentional walks; sacrifice bunts left out.
        hitters = []
        for pid, c in self.batters.items():
            den = c["pa"] - c["ibb"] - c["sh"]
            if den >= min_pa:
                hitters.append((pid, c["bb"] - c["ibb"], c["so"], den))
        pitchers = []
        for pid, c in self.pitchers.items():
            den = c["bf"] - c["ibb"]
            if den >= min_pa and pid in self.control:
                pitchers.append((self.control[pid], c["bb"] - c["ibb"], den))
        eye_rows = [(self.eye[p], bb, n) for p, bb, _so, n in hitters if p in self.eye]
        ch_rows = [(self.ch[p], so, n) for p, _bb, so, n in hitters if p in self.ch]
        metrics["bb_pct_per10_eye"] = _rate_slope_pp_per10(eye_rows)
        metrics["bb_pct_per10_control"] = _rate_slope_pp_per10(pitchers)
        metrics["k_pct_per10_contact"] = _rate_slope_pp_per10(ch_rows)
        tables["rating_slope_players"] = {
            "min_pa": min_pa,
            "bb_pct_per10_eye": len(eye_rows),
            "bb_pct_per10_control": len(pitchers),
            "k_pct_per10_contact": len(ch_rows),
        }

        # Do hitters who chase also swing in the zone? (one swing skill)
        regulars = {pid for pid, _bb, _so, _n in hitters}
        o_swing, z_swing = [], []
        for pid, c in r5.batter_pitches.items():
            if pid in regulars and c["zone"] and c["chase"]:
                o_swing.append(c["chase_swing"] / c["chase"])
                z_swing.append(c["zone_swing"] / c["zone"])
        metrics["hitter_o_z_swing_corr"] = (
            _pearson(o_swing, z_swing) if len(o_swing) >= 10 else None
        )

        # Dispersion: pitcher zone rate and hitter batting average.
        min_pitches = max(200, round(1500 * gpt / 162))
        zone_rows = [
            (c["zone"], c["pitches"])
            for c in r5.pitcher_pitches.values()
            if c["pitches"] >= min_pitches
        ]
        avg_rows = [
            (r5.batter_lines[pid]["h"], r5.batter_lines[pid]["ab"])
            for pid, c in self.batters.items()
            if c["pa"] >= min_pa and pid in r5.batter_lines
        ]
        disp = tables.setdefault("dispersion", {})
        for name, rows, bar in (
            ("pitcher_zone_pct", zone_rows, {"min_pitches": min_pitches}),
            ("hitter_avg", avg_rows, {"min_pa": min_pa}),
        ):
            sd, var, n = true_sd(rows)
            metrics[f"{name}_true_sd"] = sd
            disp[name] = {"true_sd": sd, "true_var": var, "n": n, **bar}

        # Contact and BABIP (decision 4): the speed rows' twins on Contact.
        ch_bat = [(self.ch[pid], c) for pid, c in self.speed_bat.items() if pid in self.ch]
        metrics["babip_contact_slope_per10"] = _babip_slope_per10(ch_bat)
        min_pa_babip = max(50, round(300 * gpt / 162))
        regs = [
            (ch, c["h"] / c["bip"])
            for ch, c in ch_bat
            if c["pa"] >= min_pa_babip and c["bip"]
        ]
        metrics["r_ch_babip"] = _pearson([a for a, _ in regs], [b for _, b in regs])

        # Platoon (H7): opposite-hand minus same-hand, switch hitters apart.
        def bucket(*keys: str) -> Counter:
            total: Counter = Counter()
            for key in keys:
                total.update(self.platoon.get(key) or {})
            return total

        same, opp = _token_rates(bucket("LL", "RR")), _token_rates(bucket("LR", "RL"))
        for name in ("k_pct", "bb_pct", "iso"):
            metrics[f"platoon_gap_{name}"] = _diff(opp[name], same[name])
        metrics["switch_woba_vs_lhp"] = woba_from_tokens(bucket("SL"))[0]
        metrics["switch_woba_vs_rhp"] = woba_from_tokens(bucket("SR"))[0]
        vs_lhp = {side: sum(bucket(f"{side}L").values()) for side in ("L", "R", "S")}
        metrics["rhb_share_of_pa_vs_lhp"] = _ratio(vs_lhp["R"], sum(vs_lhp.values()))
        tables["platoon_rates"] = {"same": same, "opposite": opp, "pa_vs_lhp": vs_lhp}

        # Hit batters by matchup hand, per batter faced (every PA result).
        # A switch hitter bats from the opposite side, so he counts there.
        # MLB hits the same-hand batter about twice as often.
        hbp_hand = {}
        for name, keys in (
            ("same", ("LL", "RR")), ("opposite", ("LR", "RL", "SL", "SR"))
        ):
            counts = bucket(*keys)
            faced = sum(counts.values())
            hbp_hand[name] = {
                "bf": faced, "hbp": counts["hbp"],
                "hbp_per_bf": _ratio(counts["hbp"], faced),
            }
        same_rate = hbp_hand["same"]["hbp_per_bf"]
        opp_rate = hbp_hand["opposite"]["hbp_per_bf"]
        metrics["hbp_same_over_opposite_hand"] = (
            same_rate / opp_rate if same_rate is not None and opp_rate else None
        )
        tables["hbp_by_matchup_hand"] = hbp_hand

        # Situations (M19, L5): walks late and close and with first base
        # occupied, intentional walks, the home side and the fresh reliever.
        logged = bool(self.logged_games)
        situ_all = self.situ.get("all") or Counter()
        late = self.situ.get("late_close") or Counter()
        empty = self.situ.get("empty") or Counter()
        metrics["late_close_ubb_pct_delta"] = (
            _diff(_token_rates(late)["bb_pct"], _token_rates(situ_all)["bb_pct"])
            if logged else None
        )
        metrics["bb_pct_empty_minus_r1"] = (
            _diff(_token_rates(empty)["bb_pct"], _token_rates(r5.r1_only)["bb_pct"])
            if logged else None
        )
        metrics["ibb_late_close_share"] = (
            _ratio(late["ibb"], situ_all["ibb"]) if logged else None
        )
        metrics["home_minus_away_woba"] = _diff(
            woba_from_tokens(r5.half["bottom"])[0], woba_from_tokens(r5.half["top"])[0]
        )
        pass1, pass3 = r5.starter_tto[1], r5.starter_tto[3]
        metrics["relief_bf1_6_minus_starter_pass1_woba"] = _diff(
            woba_from_tokens(r5.relief_fresh)[0], woba_from_tokens(pass1)[0]
        )
        # The strict tto_ops_gap over starting pitchers' PA only (pass 1 of
        # the league split is mostly relief PA). Same 500 pass-3 PA floor.
        metrics["tto_ops_gap_starters"] = (
            _diff(ops_from_tokens(pass3), ops_from_tokens(pass1))
            if sum(pass3.values()) >= 500 else None
        )
        metrics["save_conversion"] = _ratio(r5.saves["sv"], r5.saves["svo"])
        metrics["lineup_hand_match_rate"] = _ratio(
            r5.lineup_hand["match"], r5.lineup_hand["n"]
        )
        tables["r5_counts"] = {
            "pitch": dict(pitch),
            "pa": dict(r5.pa),
            "saves": dict(r5.saves),
            "lineup_hand": dict(r5.lineup_hand),
            "r1_only_pa": sum(r5.r1_only.values()),
            "relief_fresh_pa": sum(r5.relief_fresh.values()),
            "starter_pa_by_pass": {
                str(k): sum(r5.starter_tto[k].values()) for k in (1, 2, 3)
            },
            "home_pa": sum(r5.half["bottom"].values()),
            "away_pa": sum(r5.half["top"].values()),
        }

    # -- Release 6a: pitching, power, fielding and the batted ball ------------
    # Report-only rows for the Release 6 build (RELEASE6_PLAN.md section 4,
    # step 1). Read from the pitch log, the box lines and the two records
    # the engine hands this harness in ``GameResult.play_records``
    # (``fld_pos``, ``starting_positions``).
    def _r6(self) -> "_R6Tallies":
        state = getattr(self, "r6", None)
        if state is None:
            state = self.r6 = _R6Tallies()
        return state

    def _batting_side(self, batter_id: str, pitcher_id: str) -> str:
        """The side a batter hits from against this pitcher: a switch hitter
        bats opposite the pitcher's hand (``engine._effective_batter_side``)."""
        bats = self.bats.get(batter_id, "R")
        if bats == "S":
            return "L" if self.throws.get(pitcher_id, "R") == "R" else "R"
        return bats if bats in ("L", "R") else "R"

    def _add_r6(
        self,
        meta: dict[str, Any],
        log: list[dict[str, Any]],
        pas: list[PlateAppearance],
        starters: set[str],
        records: dict[str, Any],
        teams: dict[str, str] | None = None,
    ) -> None:
        """One game's Release 6a tallies.

        Pitch level: pitches by type. Ball in play (the ``in_play`` entry,
        which carries the PA's result): the engine's class and exit velocity
        by pitch type and by pitcher, the Statcast class by launch angle,
        home run distance, the spray angle by batting side and the position
        the engine credited the out or error to (``records["fld_pos"]``, by
        the entry's index in the log). PA level: every hitter's wOBA per PA
        (the batter adjustment) and, for starters, each PA's pitch-count
        bucket and time through the order. Box lines: runs and earned runs,
        hitter doubles and strikeouts, errors by the position each fielder
        started at (``records["starting_positions"]``). ``records`` is the
        game's ``play_records``; ``{}`` for a result without them. ``teams``
        maps the game's sides to its clubs (for the fielding records).
        """
        r6 = self._r6()
        fielded = records.get("fld_pos")
        if isinstance(fielded, dict):
            r6.fld_logged = True
        else:
            fielded = {}
        for index, entry in enumerate(log):
            pitch_type = entry.get("pitch_type")
            if pitch_type is None:
                continue
            pitch_type = str(pitch_type)
            r6.pitch_types[pitch_type] += 1
            if entry.get("outcome") != "in_play":
                continue
            ev, la = entry.get("exit_velo"), entry.get("launch_angle")
            if ev is None or la is None:
                continue
            ev, la = float(ev), float(la)
            token = str(entry.get("pa_result") or "")
            ball_type = str(entry.get("ball_type") or "")
            pitcher_id = str(entry.get("pitcher_id", ""))
            batter_id = str(entry.get("batter_id", ""))
            homer = token == "hr"
            by_type = r6.by_pitch_type[pitch_type]
            by_type["bip"] += 1
            by_type[ball_type] += 1
            by_type["ev"] += ev
            mound = r6.pitcher_bip[pitcher_id]
            mound["bip"] += 1
            mound["gb"] += ball_type == "gb"
            mound["ev"] += ev
            r6.engine_class[ball_type] += 1
            cls = r6.statcast[statcast_class(la)]
            cls["n"] += 1
            cls["ev"] += ev
            cls["hr"] += homer
            cls["hit"] += token in HIT_TOKENS
            distance = entry.get("distance")
            if homer and distance is not None:
                r6.hr["n"] += 1
                r6.hr["ft"] += float(distance)
                r6.hr["ft450"] += float(distance) >= HR_LONG_FT
                r6.hr_longest = max(r6.hr_longest, float(distance))
            spray = entry.get("spray_angle")
            if spray is not None:
                side = self._batting_side(batter_id, pitcher_id)
                pull = pull_angle(float(spray), side)
                third = (
                    "pull" if pull > SPRAY_THIRD_DEG
                    else "oppo" if pull < -SPRAY_THIRD_DEG
                    else "straight"
                )
                by_side = r6.spray[side]
                by_side["n"] += 1
                by_side[third] += 1
                by_side["hr"] += homer
                by_side["hr_pull"] += homer and third == "pull"
                own = r6.spray_by_batter[(batter_id, side)]
                own[0] += 1
                own[1] += pull
            if index in fielded:
                pos = str(fielded[index] or "?").upper()
                if ball_type == "gb":
                    r6.gb_plays[pos] += 1
                elif not entry.get("reached_on_error"):
                    r6.air_outs[pos] += 1

        for pa in pas:
            token = pa.token
            if not token or pa.pitches == 0 or token in ("ibb", "sh"):
                continue  # the PA the wOBA deltas above leave out as well
            weight = WOBA_WEIGHTS.get(token, 0.0)
            season = r6.batter_woba[pa.batter_id]
            season[0] += weight
            season[1] += 1
            if pa.pitcher_id not in starters:
                continue
            bucket = _fatigue_bucket(_int(pa.first.get("pitch_count")) - 1)
            tto = min(_int(pa.first.get("tto")), 3)
            r6.starter_pa.append((pa.pitcher_id, pa.batter_id, bucket, tto, weight))
            if bucket is None:
                continue
            acc = r6.fatigue[pa.pitcher_id][bucket]
            acc["pa"] += 1
            acc["so"] += token == "so"
            acc["bb"] += token == "bb"
            last = pa.last
            if last.get("outcome") == "in_play" and last.get("exit_velo") is not None:
                acc["bip"] += 1
                acc["ev"] += float(last["exit_velo"])

        starting = records.get("starting_positions")
        for side in ("away", "home"):
            arms = set()
            for line in (meta.get("pitcher_lines") or {}).get(side, []) or []:
                pid = str(line.get("player_id", ""))
                arms.add(pid)
                r6.runs["r"] += _int(line.get("r"))
                r6.runs["er"] += _int(line.get("er"))
                r6.pitcher_er[pid] += _int(line.get("er"))
            for line in (meta.get("batting_lines") or {}).get(side, []) or []:
                bc = r6.batters[str(line.get("player_id", ""))]
                for key in ("pa", "ab", "h", "b2", "b3", "hr", "so"):
                    bc[key] += _int(line.get(key))
            positions = starting.get(side) if isinstance(starting, dict) else None
            if not isinstance(positions, dict) or not positions:
                continue
            r6.positions_logged = True
            for pid, pos in positions.items():
                pos = str(pos or "").strip().upper()
                if not pos or pos in ("DH", "P"):
                    continue
                r6.slots["n"] += 1
                r6.slots[self._slot_status(str(pid), pos)] += 1
            for line in (meta.get("fielding_lines") or {}).get(side, []) or []:
                errors = _int(line.get("e"))
                if not errors:
                    continue
                pid = str(line.get("player_id", ""))
                pos = str(positions.get(pid) or "").strip().upper()
                if not pos or pos == "DH":
                    # A pitcher is not in the lineup's positions; anyone
                    # else who did not start in the field came off the bench.
                    pos = "P" if pid in arms else "SUB"
                r6.errors_by_pos[pos] += errors

        self._add_r6_chances(records, teams or {}, log)

    def _add_r6_chances(
        self,
        records: dict[str, Any],
        teams: dict[str, str],
        log: list[dict[str, Any]],
    ) -> None:
        """One game's fielding records (Release 6a, fielding).

        ``errors``: every error the engine charged, with its source; a
        batter safe on a ball the pitcher fielded is a ``comebacker``.
        ``bip_chances`` / ``error_chances`` (a game played with
        ``fielding_chance_log``): for each ball in play the out chance used
        and a league-average fielder's, credited to the responsible fielder
        (shared when two are); for each error roll the same pair. Outs are
        counted in hits saved: an out chance times ``babip_scale``.
        """
        r6 = self._r6()
        charged = records.get("errors")
        if isinstance(charged, list):
            r6.errors_logged = True
            for row in charged:
                source, pos = str(row[1]), str(row[2] or "?").upper()
                if source == "roe" and pos == "P":
                    source = "comebacker"
                r6.error_sources[source] += 1
                r6.errors_charged[f"{source}|{pos}"] += 1
        chances = records.get("bip_chances")
        if not isinstance(chances, list):
            return
        r6.chance_logged = True
        scale = float(records.get("babip_scale") or 1.0)
        game = self.games
        for row in chances:
            side, positions, fielders = row[1], row[3], row[4]
            out_used, out_avg, hit_prob = float(row[5]), float(row[6]), float(row[7])
            gained = scale * (out_used - out_avg)
            r6.level["n"] += 1
            r6.level["shift"] += out_used - out_avg
            r6.level["neutral"] += out_avg
            team = r6.team_chance[teams.get(side, side)]
            team["bip"] += 1
            team["out"] += 1.0 - hit_prob
            team["range"] += gained
            for pos, pid in zip(positions, fielders):
                if pid is None:
                    continue
                key = (str(pid), str(pos))
                r6.fielder_chance[key]["range"] += gained / len(positions)
                r6.fielder_chance[key]["balls"] += 1
                r6.fielder_games[key].add(game)
            # What scripts/fit_fielding_slopes.py reads: by responsible
            # position (a shared ball split), balls and the sum of
            # out0 * (1 - out0), line drives apart; and where the ground
            # balls go (0.5 degree bins toward the left-field side).
            ball_type = str(row[2])
            entry = log[row[0]] if 0 <= row[0] < len(log) else {}
            # How the ball came out (1b / 2b / 3b / out / roe), for what an
            # out at each position is worth in runs.
            result = str(entry.get("pa_result") or "")
            spread = out_avg * (1.0 - out_avg) / max(1, len(positions))
            for pos in positions:
                sums = r6.chance_sums[str(pos)]
                sums[f"balls_{ball_type}"] += 1.0 / len(positions)
                sums["spread_ld" if ball_type == "ld" else "spread"] += spread
                if result:
                    sums[f"result_{result}"] += 1.0 / len(positions)
            if ball_type == "gb":
                spray = entry.get("spray_angle")
                if spray is not None:
                    bucket = math.floor(-float(spray) * 2.0) / 2.0
                    r6.grounder_direction[bucket] += 1
        for row in records.get("error_chances") or []:
            side, pos, pid = row[1], row[2], row[3]
            used, average = float(row[4]), float(row[5])
            team = r6.team_chance[teams.get(side, side)]
            team["err"] += used
            team["err_saved"] += average - used
            if pos is not None and 0 <= row[0] < len(log):
                grounder = log[row[0]].get("out_type") == "groundout"
                r6.chance_sums[str(pos)]["rolls_gb" if grounder else "rolls_air"] += 1
            if pid is None or pos is None:
                continue
            key = (str(pid), str(pos))
            r6.fielder_chance[key]["err"] += average - used
            r6.fielder_chance[key]["rolls"] += 1
            r6.fielder_games[key].add(game)

    def _slot_status(self, player_id: str, position: str) -> str:
        """How a starter is listed for the position he started at:
        ``primary``, ``secondary`` (a listed second position) or
        ``unlisted`` (the engine's three fielding multipliers)."""
        if position == self.primary_pos.get(player_id, ""):
            return "primary"
        if position in self.r6_ratings["other_pos"].get(player_id, ()):
            return "secondary"
        return "unlisted"

    def _r6_metrics(
        self,
        metrics: dict[str, Any],
        tables: dict[str, Any],
        gpt: int,
        team_games: int,
    ) -> None:
        """The Release 6a report-only rows; never gated."""
        self._r6_pitching(metrics, tables, gpt)
        self._r6_power(metrics, tables, gpt)
        self._r6_fielding(metrics, tables, team_games)
        self._r6_batted_ball(metrics, tables, gpt)

    def _r6_pitching(
        self, metrics: dict[str, Any], tables: dict[str, Any], gpt: int
    ) -> None:
        r6 = self._r6()
        gf = self.r6_ratings["pitcher_gf"]

        # What +10 of each pitcher rating is worth, the four taken together
        # (plan 2.1: the arm must lower FIP, the pitch grade must carry the
        # strikeouts). Least squares over the pitchers with 40+ innings,
        # weighted by batters faced; FIP without its constant (runs per 9),
        # the rates in percentage points per batter faced.
        min_outs = 3 * max(10, round(40 * gpt / 162))
        regulars = []
        for pid, c in self.pitchers.items():
            ratings = self.pitcher_ratings.get(pid)
            bf = c["bf"] - c["ibb"]
            if ratings is None or c["outs"] < min_outs or bf <= 0:
                continue
            mound = r6.pitcher_bip.get(pid) or Counter()
            regulars.append({
                "pid": pid,
                "x": [ratings[key] for key in R6_PITCHER_RATINGS.values()],
                "bf": float(bf),
                "fip": _fip(c),
                "k": c["so"] / bf,
                "bb": (c["bb"] - c["ibb"]) / bf,
                "hr": c["hr"] / bf,
                "era": 27.0 * r6.pitcher_er[pid] / c["outs"],
                "gb": _ratio(mound["gb"], mound["bip"]),
                "ev": _ratio(mound["ev"], mound["bip"]),
            })
        slopes: dict[str, Any] = {"pitchers": len(regulars), "min_outs": min_outs}
        names = list(R6_PITCHER_RATINGS)
        if len(regulars) >= R6_MIN_REGRESSION_ROWS:
            xs = [row["x"] for row in regulars]
            weights = [row["bf"] for row in regulars]
            for outcome, scale in (
                ("fip", 10.0), ("k", 1000.0), ("bb", 1000.0), ("hr", 1000.0),
                ("era", 10.0), ("ev", 10.0),
            ):
                rows = [
                    (x, row[outcome], w)
                    for x, row, w in zip(xs, regulars, weights)
                    if row[outcome] is not None
                ]
                beta = _least_squares(
                    [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows]
                )
                slopes[outcome] = {
                    name: (scale * b if b is not None else None)
                    for name, b in zip(names, beta)
                }
            # The same strikeout regression on standardised ratings and a
            # standardised rate, unweighted: how many sd of K one sd of the
            # rating moves (target for the mean pitch grade: >= .35).
            slopes["k_std_beta"] = dict(zip(names, _standardised_betas(
                xs, [row["k"] for row in regulars]
            )))
        fip_slopes = slopes.get("fip") or {}
        k_slopes = slopes.get("k") or {}
        for name in names:
            metrics[f"pitcher_fip_per10_{name}"] = fip_slopes.get(name)
            metrics[f"pitcher_k_pct_per10_{name}"] = k_slopes.get(name)
        metrics["pitcher_k_std_beta_grade"] = (
            slopes.get("k_std_beta") or {}
        ).get("grade")
        tables["pitcher_rating_slopes"] = slopes

        # Ground balls and exit velocity by the pitch thrown (the engine's
        # own ground-ball class), and the fastball + sinker share of pitches.
        by_type = {}
        for pitch_type, c in sorted(r6.by_pitch_type.items()):
            by_type[pitch_type] = {
                "pitches": r6.pitch_types[pitch_type],
                "bip": c["bip"],
                "gb_pct": _ratio(c["gb"], c["bip"]),
                "ev": _ratio(c["ev"], c["bip"]),
            }
        tables["batted_ball_by_pitch_type"] = by_type
        for pitch_type in R6_PITCH_TYPES:
            row = by_type.get(pitch_type) or {}
            metrics[f"gb_pct_pitch_{pitch_type}"] = row.get("gb_pct")
            metrics[f"ev_pitch_{pitch_type}"] = row.get("ev")
        pitches = sum(r6.pitch_types.values())
        metrics["fb_si_pitch_share"] = _ratio(
            r6.pitch_types["fb"] + r6.pitch_types["si"], pitches
        )

        # Spread among ERA-qualified pitchers (observed sd): FIP, and the
        # mean exit velocity they allow.
        min_outs_q = 3 * max(1, round(gpt * 1.0))
        qual_fip, qual_ev = [], []
        for pid, c in self.pitchers.items():
            if c["outs"] < min_outs_q:
                continue
            qual_fip.append(_fip(c))
            mound = r6.pitcher_bip.get(pid)
            if mound and mound["bip"]:
                qual_ev.append(mound["ev"] / mound["bip"])
        metrics["qualified_fip_sd"] = (
            statistics.pstdev(qual_fip) if len(qual_fip) >= 10 else None
        )
        metrics["qualified_ev_against_sd"] = (
            statistics.pstdev(qual_ev) if len(qual_ev) >= 10 else None
        )

        # Do pitchers own a ground-ball rate? True sd of GB% over pitchers
        # with 250+ balls in play, and r(ground-ball rating, GB%) over the
        # 40+ inning pitchers (the engine does not read a pitcher's gf yet).
        min_bip = max(50, round(250 * gpt / 162))
        sd, var, n = true_sd(
            (c["gb"], c["bip"]) for c in r6.pitcher_bip.values() if c["bip"] >= min_bip
        )
        metrics["pitcher_gb_pct_true_sd"] = sd
        tables["pitcher_gb_pct_dispersion"] = {
            "true_sd": sd, "true_var": var, "n": n, "min_bip": min_bip,
        }
        pairs = [
            (gf[row["pid"]], row["gb"])
            for row in regulars
            if row["pid"] in gf and row["gb"] is not None
        ]
        metrics["r_pitcher_gf_gb_pct"] = (
            _pearson([a for a, _ in pairs], [b for _, b in pairs])
            if len(pairs) >= 10 else None
        )

        # The same starter at pitches 91-105 against pitches 1-25 of the
        # outing: strikeouts and walks per PA (fractions) and exit velocity
        # (mph), weighted by his late PA (late balls in play for EV).
        for key, events, trials in (
            ("k_pct", "so", "pa"), ("bb_pct", "bb", "pa"), ("ev", "ev", "bip"),
        ):
            metrics[f"starter_{key}_delta_91_105"] = _bucket_delta(
                r6.fatigue, events, trials
            )

        # The wOBA deltas with the batters faced taken out: each PA counts
        # as its wOBA value minus that hitter's season mean. The raw rows
        # carry who bats when: pitches 91-105 fall on the bottom of the
        # order (the raw delta reads low) and the third time through on the
        # top (it reads high). Starters only, within pitcher, weighted by
        # the later group's PA.
        means = {pid: acc[0] / acc[1] for pid, acc in r6.batter_woba.items() if acc[1]}
        adjusted = {}
        for name, index, base, other in (
            ("starter_woba_delta_91_105", 2, "early", "late"),
            ("tto_pass2_woba_delta", 3, 1, 2),
            ("tto_pass3_woba_delta", 3, 1, 3),
        ):
            raw, adj, n = _starter_pa_delta(r6.starter_pa, means, index, base, other)
            metrics[f"{name}_batter_adj"] = adj
            adjusted[name] = {"starters_raw": raw, "batter_adjusted": adj, "pa": n}
        tables["batter_adjusted_deltas"] = adjusted

    def _r6_power(
        self, metrics: dict[str, Any], tables: dict[str, Any], gpt: int
    ) -> None:
        r6 = self._r6()
        power = self.r6_ratings["power"]
        gf = self.r6_ratings["hitter_gf"]
        min_pa = max(1, round(gpt * 3.1))  # the batting-title bar, as gated
        rows = []
        for pid, c in sorted(r6.batters.items()):
            if c["pa"] < min_pa or c["ab"] <= 0:
                continue
            if pid not in power or pid not in self.ch:
                continue
            rows.append({
                "pid": pid, "ph": power[pid], "ch": self.ch[pid],
                "gf": gf.get(pid, 50.0), "pa": c["pa"], "hr": c["hr"],
                "b2": c["b2"],
                "hr600": 600.0 * c["hr"] / c["pa"],
                "d_rate": c["b2"] / c["pa"],
                "k_rate": c["so"] / c["pa"],
                "iso": (c["b2"] + 2 * c["b3"] + 3 * c["hr"]) / c["ab"],
            })
        n = len(rows)
        enough = n >= R6_MIN_REGRESSION_ROWS
        tables["qualified_hitters"] = {"n": n, "min_pa": min_pa}

        # Home runs per 600 PA by Power fifth (each hitter counted once), and
        # the weakest fifth over the middle one (decision 4: .75 or less).
        # Ratings are whole numbers, so a fifth's edge falls inside a group
        # of hitters with the same Power: they share the group's mean
        # (``_tie_averaged``), or the order within the tie would decide the
        # answer (sorting ties by home runs reads the ratio .04 to .06 low).
        fifths: list[list[dict[str, Any]]] = [[] for _ in range(5)]
        if enough:
            by_power = _tie_averaged(rows, "ph", ("hr600",))
            q = n // 5
            fifths = [
                by_power[:q], by_power[q:2 * q], by_power[2 * q:n - 2 * q],
                by_power[n - 2 * q:n - q], by_power[n - q:],
            ]
        quintiles = []
        for i, group in enumerate(fifths, start=1):
            value = statistics.fmean(r["hr600"] for r in group) if group else None
            metrics[f"hr600_power_q{i}"] = value
            quintiles.append({
                "n": len(group),
                "mean_power": statistics.fmean(r["ph"] for r in group) if group else None,
                "hr600": value,
            })
        tables["hr600_by_power_quintile"] = quintiles
        low, mid = metrics["hr600_power_q1"], metrics["hr600_power_q3"]
        metrics["hr_power_bottom_quintile_ratio"] = (
            (low / mid) if (mid and low is not None) else None
        )
        bands = {}
        for lo, hi in R6_POWER_BANDS:
            group = [r for r in rows if lo <= r["ph"] < hi]
            if group:
                bands[f"{lo}-{hi}"] = {
                    "n": len(group),
                    "hr600": _ratio(
                        600.0 * sum(r["hr"] for r in group),
                        sum(r["pa"] for r in group),
                    ),
                }
        tables["hr600_by_power_band"] = bands

        # The spread of the home run totals themselves: mean HR per 600 PA
        # of the lowest and highest fifth of qualified hitters and the
        # median, and the share of them with 30 (per 162 games).
        by_hr = sorted(r["hr600"] for r in rows)
        q = n // 5
        metrics["qualified_hr600_q1"] = statistics.fmean(by_hr[:q]) if enough else None
        metrics["qualified_hr600_median"] = statistics.median(by_hr) if enough else None
        metrics["qualified_hr600_q5"] = statistics.fmean(by_hr[-q:]) if enough else None
        metrics["hr30_share_of_qualified"] = (
            sum(1 for r in rows if r["hr"] >= 30.0 * gpt / 162.0) / n if enough else None
        )

        # Who hits the doubles: doubles per 600 PA per +10 Power and per +10
        # Contact (the two taken together), and whether doubles and
        # strikeouts go with power (r of 2B rate with HR rate, of K% with ISO).
        beta = (
            _least_squares(
                [[r["ph"], r["ch"]] for r in rows], [r["d_rate"] for r in rows]
            )
            if enough else [None, None]
        )
        for name, slope in zip(("power", "contact"), beta):
            metrics[f"doubles_per10_{name}"] = (
                6000.0 * slope if slope is not None else None
            )
        metrics["corr_2b_hr"] = (
            _pearson([r["d_rate"] for r in rows], [r["hr600"] for r in rows])
            if enough else None
        )
        metrics["corr_k_iso"] = (
            _pearson([r["k_rate"] for r in rows], [r["iso"] for r in rows])
            if enough else None
        )

        # Doubles per 600 PA by ground-ball rating third, t1 the lowest gf
        # (the owner's rule: line-drive hitters lead in doubles). Hitters
        # with the same gf share their group's doubles and PA, as above.
        thirds: list[list[dict[str, Any]]] = [[], [], []]
        if enough:
            by_gf = _tie_averaged(rows, "gf", ("b2", "pa"))
            t = n // 3
            thirds = [by_gf[:t], by_gf[t:n - t], by_gf[n - t:]]
        terciles = []
        for i, group in enumerate(thirds, start=1):
            pa = sum(r["pa"] for r in group)
            value = _ratio(600.0 * sum(r["b2"] for r in group), pa)
            metrics[f"doubles600_gf_t{i}"] = value
            terciles.append({
                "n": len(group),
                "mean_gf": statistics.fmean(r["gf"] for r in group) if group else None,
                "doubles600": value,
            })
        tables["doubles600_by_gf_tercile"] = terciles

    def _r6_fielding(
        self, metrics: dict[str, Any], tables: dict[str, Any], team_games: int
    ) -> None:
        r6 = self._r6()

        # Errors per team-game by the position the fielder started at (a
        # pitcher is P; a fielder who came off the bench is in the table as
        # SUB). MLB is about .53 in all; the engine charges none to
        # catchers or pitchers today.
        placed = r6.positions_logged and team_games
        for pos in R6_FIELD_POSITIONS:
            metrics[f"e_per_team_game_{pos.lower()}"] = (
                r6.errors_by_pos[pos] / team_games if placed else None
            )
        tables["errors_by_position"] = dict(r6.errors_by_pos)

        # Who the engine gives the ground balls to: the share of ground-ball
        # outs and errors credited to each infield position; and the share
        # of outfield putouts on air balls by outfielder.
        grounders = sum(r6.gb_plays.values())
        for pos in INFIELD_POSITIONS:
            metrics[f"gb_play_share_{pos.lower()}"] = (
                _ratio(r6.gb_plays[pos], grounders) if r6.fld_logged else None
            )
        putouts = sum(r6.air_outs[pos] for pos in OUTFIELD_RANGE_POSITIONS)
        for pos in OUTFIELD_RANGE_POSITIONS:
            metrics[f"of_putout_share_{pos.lower()}"] = (
                _ratio(r6.air_outs[pos], putouts) if r6.fld_logged else None
            )
        tables["plays_by_position"] = {
            "ground_ball": dict(r6.gb_plays), "air_out": dict(r6.air_outs),
        }

        # Starters away from their primary position, per fielder-slot (one
        # per position per club per game; DH and pitcher left out): all of
        # them, and the ones at a listed second position.
        slots = r6.slots
        logged = r6.positions_logged
        metrics["off_primary_slot_share"] = (
            _ratio(slots["secondary"] + slots["unlisted"], slots["n"]) if logged else None
        )
        metrics["secondary_slot_share"] = (
            _ratio(slots["secondary"], slots["n"]) if logged else None
        )
        tables["fielder_slots"] = dict(slots)

        # Runs that were not earned (the pitching lines' R minus ER; the
        # extra-inning automatic runner's run is unearned too).
        metrics["unearned_run_share"] = _ratio(
            r6.runs["r"] - r6.runs["er"], r6.runs["r"]
        )
        self._r6_fielding_records(metrics, tables, team_games)

    def _r6_fielding_records(
        self, metrics: dict[str, Any], tables: dict[str, Any], team_games: int
    ) -> None:
        """The rows read from the engine's fielding records (Release 6a,
        fielding): errors by source, and from the chance log what a fielding
        rating is worth by position, the league level and the spread of
        team defence with the luck taken out."""
        r6 = self._r6()
        gpt = self.games_per_team

        # Errors per team-game by where they came from: a batter safe on a
        # batted ball (roe; comebacker when the pitcher fielded it), a throw
        # on a runner taking a base (advance) or tagging up (tag_up) and,
        # under error_model 2, the catcher's throw on a steal, a pickoff
        # throw, an outfielder letting a hit through and the relay on a
        # force play. By the position charged in the table.
        logged = r6.errors_logged and team_games
        for source in R6_ERROR_SOURCES:
            metrics[f"e_per_team_game_src_{source}"] = (
                r6.error_sources[source] / team_games if logged else None
            )
        charged: dict[str, dict[str, int]] = defaultdict(dict)
        by_position: Counter = Counter()
        for key, count in sorted(r6.errors_charged.items()):
            source, pos = key.split("|", 1)
            charged[source][pos] = count
            by_position[pos] += count
        tables["errors_by_source"] = {
            "by_source": dict(charged),
            "by_position_charged": dict(by_position),
            "per_team_game_by_position_charged": {
                pos: count / team_games for pos, count in sorted(by_position.items())
            } if team_games else {},
        }
        grounders = sum(r6.gb_plays.values())
        metrics["gb_play_share_p"] = (
            _ratio(r6.gb_plays["P"], grounders) if r6.fld_logged else None
        )

        for pos in R6_RANGE_POSITIONS:
            metrics[f"oaa_per_fa_sd_{pos.lower()}"] = None
            metrics[f"oaa_per_8pt_{pos.lower()}"] = None
        metrics["team_der_true_sd"] = None
        metrics["range_level_shift"] = None
        metrics["neutral_out_prob_mean"] = None
        if not r6.chance_logged:
            return

        # League level: the mean out chance less the mean of what average
        # fielders would have made of the same balls (0 = the ratings as a
        # whole neither add nor take outs), and that neutral mean.
        metrics["range_level_shift"] = _ratio(r6.level["shift"], r6.level["n"])
        metrics["neutral_out_prob_mean"] = _ratio(r6.level["neutral"], r6.level["n"])
        # The sums the slope re-fit reads (scripts/fit_fielding_slopes.py).
        tables["fielding_chance_sums"] = {
            "team_games": team_games,
            "by_position": {
                pos: dict(sums) for pos, sums in sorted(r6.chance_sums.items())
            },
            "grounder_direction": {
                f"{bucket:g}": count
                for bucket, count in sorted(r6.grounder_direction.items())
            },
        }

        # Outs above an average fielder per 150 games, range plus errors,
        # against the fa rating: per rating SD of the regulars at the
        # position and per 8 points. Expected outs from the logged chances,
        # so there is no luck in them (a season's realised outs carry 9 to
        # 12 outs of it). A regular has a chance in half the club's games.
        min_games = max(10, round(81 * gpt / 162))
        value_table = {}
        for pos in R6_RANGE_POSITIONS:
            rows = []
            for (pid, where), c in r6.fielder_chance.items():
                games = len(r6.fielder_games[(pid, where)])
                if where != pos or games < min_games or pid not in self.fa:
                    continue
                per150 = 150.0 / games
                rows.append((self.fa[pid], c["range"] * per150, c["err"] * per150))
            row: dict[str, Any] = {"fielders": len(rows)}
            if len(rows) >= R6_MIN_FIELDERS:
                xs = [r[0] for r in rows]
                sd = statistics.pstdev(xs)
                range_slope = _slope(xs, [r[1] for r in rows])
                error_slope = _slope(xs, [r[2] for r in rows])
                row["fa_sd"] = sd
                row["range_outs_per_point"] = range_slope
                row["error_outs_per_point"] = error_slope
                if range_slope is not None and error_slope is not None:
                    slope = range_slope + error_slope
                    metrics[f"oaa_per_fa_sd_{pos.lower()}"] = slope * sd
                    metrics[f"oaa_per_8pt_{pos.lower()}"] = slope * 8.0
                    row["range_outs_per_fa_sd"] = range_slope * sd
                    row["error_outs_per_fa_sd"] = error_slope * sd
            value_table[pos] = row
        tables["fielding_value_by_position"] = value_table

        # Team defence with the luck taken out: each club's expected DER
        # from the chances its balls in play were given (outs before errors
        # less expected errors, per ball), and the SD of it across clubs.
        # Split in the table into what the fielders' range adds, what their
        # error rates add and what is left (the balls their pitchers and
        # opponents gave them).
        ders, ranges, errors, rest = [], [], [], []
        for team, c in r6.team_chance.items():
            if c["bip"] <= 0:
                continue
            ders.append((c["out"] - c["err"]) / c["bip"])
            ranges.append(c["range"] / c["bip"])
            errors.append(c["err_saved"] / c["bip"])
            rest.append((c["out"] - c["err"] - c["range"] - c["err_saved"]) / c["bip"])
        if len(ders) >= 2:
            metrics["team_der_true_sd"] = statistics.pstdev(ders)
            mean_bip = sum(c["bip"] for c in r6.team_chance.values()) / len(ders)
            mean_der = statistics.fmean(ders)
            tables["team_der_true"] = {
                "teams": len(ders),
                "mean": mean_der,
                "sd": statistics.pstdev(ders),
                "range_sd": statistics.pstdev(ranges),
                "error_sd": statistics.pstdev(errors),
                "pitchers_and_opponents_sd": statistics.pstdev(rest),
                "binomial_noise_sd": math.sqrt(
                    max(0.0, mean_der * (1.0 - mean_der)) / mean_bip
                ),
            }

    def _r6_batted_ball(
        self, metrics: dict[str, Any], tables: dict[str, Any], gpt: int
    ) -> None:
        r6 = self._r6()
        pull_rating = self.r6_ratings["hitter_pull"]

        # Statcast classes by launch angle (ground ball under 10 degrees,
        # line drive 10-25, fly ball 25-50, pop-up above 50): share of balls
        # in play, mean exit velocity and the hit rate of the balls that
        # stayed in the park. The gated bip_*_pct rows use the engine's own
        # cut-offs (9.0 / 15.7); both are in tables["batted_ball_classes"].
        balls = sum(c["n"] for c in r6.statcast.values())
        classes = {}
        for name in STATCAST_CLASSES:
            c = r6.statcast[name]
            share = _ratio(c["n"], balls)
            ev = _ratio(c["ev"], c["n"])
            hit_rate = _ratio(c["hit"] - c["hr"], c["n"] - c["hr"])
            metrics[f"statcast_{name}_pct"] = share
            metrics[f"statcast_{name}_ev"] = ev
            metrics[f"statcast_{name}_hit_rate"] = hit_rate
            classes[name] = {
                "n": c["n"], "share": share, "ev": ev,
                "non_hr_hit_rate": hit_rate, "hr": c["hr"],
            }
        engine_balls = sum(r6.engine_class.values())
        tables["batted_ball_classes"] = {
            "statcast": classes,
            "engine": {
                name: _ratio(count, engine_balls)
                for name, count in sorted(r6.engine_class.items())
            },
        }

        # Home runs per fly ball with the pop-ups in the denominator
        # (Statcast fly balls + pop-ups); hr_per_fb_pct in the gated metrics
        # divides by the engine's fly-ball class alone.
        homers = sum(c["hr"] for c in r6.statcast.values())
        metrics["hr_per_fb_pu"] = _ratio(
            homers, r6.statcast["fb"]["n"] + r6.statcast["pu"]["n"]
        )

        # How far the home runs go (engine carry): the mean in feet and the
        # share of 450 ft or more.
        metrics["hr_distance_mean_ft"] = _ratio(r6.hr["ft"], r6.hr["n"])
        metrics["hr_450plus_share"] = _ratio(r6.hr["ft450"], r6.hr["n"])
        tables["hr_distance"] = {
            "n": r6.hr["n"], "longest_ft": r6.hr_longest if r6.hr["n"] else None,
        }

        # Spray: the stored angle read as a physical one (positive = the
        # right-field side), so a left-handed batter pulls to positive and a
        # right-handed one to negative. Pull / centre / opposite field are
        # thirds of 15 degrees either side of centre; by batting side and
        # together. r(pull rating, mean pull angle) is over the hitters with
        # 150+ balls in play from that side: it should be positive for both.
        total = Counter()
        spray_table = {}
        min_balls = max(30, round(150 * gpt / 162))
        for side, name in (("R", "rhb"), ("L", "lhb")):
            c = r6.spray.get(side) or Counter()
            total.update(c)
            for third in SPRAY_THIRDS:
                metrics[f"{third}_pct_{name}"] = _ratio(c[third], c["n"])
            pairs = [
                (pull_rating[pid], acc[1] / acc[0])
                for (pid, hand), acc in r6.spray_by_batter.items()
                if hand == side and acc[0] >= min_balls and pid in pull_rating
            ]
            metrics[f"r_pull_rating_pull_angle_{name}"] = (
                _pearson([a for a, _ in pairs], [b for _, b in pairs])
                if len(pairs) >= 10 else None
            )
            spray_table[name] = {
                "n": c["n"], "hitters": len(pairs),
                "hr_pulled_share": _ratio(c["hr_pull"], c["hr"]),
            }
        for third in SPRAY_THIRDS:
            metrics[f"{third}_pct"] = _ratio(total[third], total["n"])
        spray_table["all"] = {
            "n": total["n"], "hr_pulled_share": _ratio(total["hr_pull"], total["hr"]),
        }
        spray_table["min_balls_in_play"] = min_balls
        tables["spray_by_batting_side"] = spray_table


# Release 4 (W1): raw-speed tiers for the steal tables (the plan's tiers;
# 47-53 is the "50", 68-77 the "fast 70", 78-89 the "burner 85").
STEAL_SPEED_TIERS = (
    "<40", "40-46", "47-53", "54-61", "62-67", "68-77", "78-89", "90+"
)


def _steal_speed_tier(sp: float) -> str:
    for upper, name in (
        (40, "<40"), (47, "40-46"), (54, "47-53"), (62, "54-61"),
        (68, "62-67"), (78, "68-77"), (90, "78-89"),
    ):
        if sp < upper:
            return name
    return "90+"


def _load_pitcher_control(path: Path) -> dict[str, float]:
    control: dict[str, float] = {}
    if not path.exists():
        return control
    with path.open(newline="", encoding="utf-8") as handle:
        for row in engine_rows(handle):
            pid = str(row.get("player_id") or "")
            if not pid or str(row.get("is_pitcher", "")).strip() not in {"1", "True", "true"}:
                continue
            try:
                control[pid] = float(row.get("control") or "")
            except ValueError:
                pass
    return control


# The pitcher ratings the engine's pitch model reads, as regressors of the
# rating-adjusted LHP-minus-RHP run average (centred on 50).
HAND_RA9_RATINGS = ("control", "movement", "arm", "endurance", "pitch_grade")
HAND_RA9_MIN_OUTS = 60
HAND_RA9_MIN_PITCHERS = 5


def _load_pitcher_ratings(path: Path) -> dict[str, dict[str, float]]:
    """pid -> the ``HAND_RA9_RATINGS`` of each pitcher (blank rating = 50;
    ``pitch_grade`` is his mean grade over the pitches he throws)."""
    from physics_sim.models import PITCH_KEYS

    ratings: dict[str, dict[str, float]] = {}
    if not path.exists():
        return ratings
    with path.open(newline="", encoding="utf-8") as handle:
        for row in engine_rows(handle):
            pid = str(row.get("player_id") or "")
            if not pid or str(row.get("is_pitcher", "")).strip() not in {"1", "True", "true"}:
                continue
            values: dict[str, float] = {}
            for key in HAND_RA9_RATINGS[:-1]:
                try:
                    values[key] = float(row.get(key) or 50.0)
                except ValueError:
                    values[key] = 50.0
            grades = []
            for key in PITCH_KEYS:
                try:
                    grade = float(row.get(key) or 0.0)
                except ValueError:
                    continue
                if grade > 0.0:
                    grades.append(grade)
            values["pitch_grade"] = (sum(grades) / len(grades)) if grades else 50.0
            ratings[pid] = values
    return ratings


def _solve_linear(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when singular."""
    n = len(rhs)
    rows = [list(matrix[i]) + [rhs[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-9:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(col + 1, n):
            factor = rows[r][col] / rows[col][col]
            for c in range(col, n + 1):
                rows[r][c] -= factor * rows[col][c]
    solution = [0.0] * n
    for i in range(n - 1, -1, -1):
        tail = sum(rows[i][j] * solution[j] for j in range(i + 1, n))
        solution[i] = (rows[i][n] - tail) / rows[i][i]
    return solution


def _hand_ra9_rating_adjusted(
    pitchers: dict[str, Counter],
    throws: dict[str, str],
    ratings: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """LHP minus RHP run average at equal ratings (decision 7).

    Outs-weighted least squares of each pitcher's RA9 on his
    ``HAND_RA9_RATINGS`` and a left-hander flag, over the pitchers with
    ``HAND_RA9_MIN_OUTS`` or more outs; ``gap`` is the flag's coefficient,
    in runs per nine. The raw ``lhp_minus_rhp_ra9`` also moves when one
    hand's pitchers are simply better; this does not. ``gap`` is None with
    fewer than ``HAND_RA9_MIN_PITCHERS`` of either hand or ratings that do
    not vary.
    """
    rows = []
    for pid, c in pitchers.items():
        if c["outs"] < HAND_RA9_MIN_OUTS or pid not in ratings:
            continue
        left = 1.0 if throws.get(pid, "R") == "L" else 0.0
        x = [1.0, left] + [ratings[pid][key] - 50.0 for key in HAND_RA9_RATINGS]
        rows.append((x, 27.0 * c["r"] / c["outs"], float(c["outs"])))
    lefties = sum(1 for x, _y, _w in rows if x[1])
    out: dict[str, Any] = {
        "gap": None, "pitchers": len(rows), "lhp": lefties,
        "min_outs": HAND_RA9_MIN_OUTS, "per10": {},
    }
    if min(lefties, len(rows) - lefties) < HAND_RA9_MIN_PITCHERS:
        return out
    size = len(rows[0][0])
    normal = [[0.0] * size for _ in range(size)]
    target = [0.0] * size
    for x, y, w in rows:
        for i in range(size):
            target[i] += w * x[i] * y
            for j in range(size):
                normal[i][j] += w * x[i] * x[j]
    beta = _solve_linear(normal, target)
    if beta is None:
        return out
    out["gap"] = beta[1]
    out["per10"] = {
        key: 10.0 * beta[2 + i] for i, key in enumerate(HAND_RA9_RATINGS)
    }
    return out


SPEED_TIERS = ("<40", "40-49", "50-59", "60-69", "70-84", "85+")


def _speed_tier(sp: float | None) -> str:
    """Release 4 runner/batter speed tier (the plan's per-tier tables)."""
    if sp is None:
        return "unknown"
    if sp < 40:
        return "<40"
    if sp < 50:
        return "40-49"
    if sp < 60:
        return "50-59"
    if sp < 70:
        return "60-69"
    if sp < 85:
        return "70-84"
    return "85+"


def _tier_order(tier: str) -> int:
    return SPEED_TIERS.index(tier) if tier in SPEED_TIERS else len(SPEED_TIERS)


# Engine-carry bands (ft) for the R2 tag-up table.
CARRY_BANDS = ("<150", "150-199", "200-249", "250-299", "300+")


def _carry_band(dist: float) -> str:
    for upper, name in zip((150, 200, 250, 300), CARRY_BANDS):
        if dist < upper:
            return name
    return CARRY_BANDS[-1]


class _OutsInPlay:
    """Release 4 (W3) accumulator for ``ReportOnlyKpis._add_outs_in_play``."""

    def __init__(self) -> None:
        self.logged = False
        self.dp_air = 0
        self.tag_dp = 0
        # (runner sp or None, thrower arm, result, infield) per R3 chance.
        self.tag3: list[tuple[float | None, float, str, bool]] = []
        self.tag2: Counter = Counter()
        # R2 chances (opp / adv) by engine-carry band (``_carry_band``).
        self.tag2_by_dist: dict[str, Counter] = defaultdict(Counter)
        self.tag3_short = 0
        self.go3: dict[tuple[int, int], Counter] = defaultdict(Counter)
        self.gidp_by_batter: dict[str, Counter] = defaultdict(Counter)


class _R5Tallies:
    """Release 5a accumulator for ``ReportOnlyKpis._add_r5``."""

    def __init__(self) -> None:
        # (count, "zone" | "chase") -> pitches / swings.
        self.count_loc: Counter = Counter()
        self.count_loc_swings: Counter = Counter()
        self.pitch: Counter = Counter()
        self.pa: Counter = Counter()
        # Per player: zone / chase pitches and swings seen; pitches thrown.
        self.batter_pitches: dict[str, Counter] = defaultdict(Counter)
        self.pitcher_pitches: dict[str, Counter] = defaultdict(Counter)
        self.batter_lines: dict[str, Counter] = defaultdict(Counter)
        # PA result tokens: by half ("top" = the away side bats), with a
        # runner on first only, a reliever's first batters of an outing and
        # the starters' PA by times through the order (1, 2, 3+).
        self.half: dict[str, Counter] = defaultdict(Counter)
        self.r1_only: Counter = Counter()
        self.relief_fresh: Counter = Counter()
        self.starter_tto: dict[int, Counter] = defaultdict(Counter)
        self.saves: Counter = Counter()
        self.lineup_hand: Counter = Counter()


# A reliever's "fresh" batters: the first six he faces in an outing.
RELIEF_FRESH_BF = 6


def _token_rates(counts: Counter) -> dict[str, float | None]:
    """K%, unintentional BB% and ISO over PA result tokens. Intentional
    walks and sacrifice bunts are left out of the PA."""
    pa = sum(counts.values()) - counts["ibb"] - counts["sh"]
    ab = sum(counts[t] for t in AB_TOKENS)
    extra = counts["2b"] + 2 * counts["3b"] + 3 * counts["hr"]
    return {
        "pa": pa,
        "k_pct": _ratio(counts["so"], pa),
        "bb_pct": _ratio(counts["bb"], pa),
        "iso": _ratio(extra, ab),
    }


def _rate_slope_pp_per10(rows: list[tuple[float, int, int]]) -> float | None:
    """Trials-weighted least-squares slope of a rate on a rating.

    ``rows`` are (rating, events, trials) per player. Percentage points of
    the rate per 10 rating points; None with fewer than 10 players or no
    spread in the rating.
    """
    rows = [(x, k, n) for x, k, n in rows if n > 0]
    weight = sum(n for _x, _k, n in rows)
    if len(rows) < 10 or not weight:
        return None
    mx = sum(x * n for x, _k, n in rows) / weight
    my = sum(k for _x, k, _n in rows) / weight
    num = sum(n * (x - mx) * (k / n - my) for x, k, n in rows)
    den = sum(n * (x - mx) ** 2 for x, _k, n in rows)
    return 1000.0 * num / den if den else None


def _babip_slope_per10(rows: list[tuple[float, Counter]]) -> float | None:
    """BIP-weighted least-squares BABIP slope per 10 rating points over the
    players with 50+ balls in play (``babip_speed_slope_per10``'s rule)."""
    sel = [(x, c) for x, c in rows if c["bip"] >= 50]
    weight = sum(c["bip"] for _x, c in sel)
    if len(sel) < 3 or not weight:
        return None
    mx = sum(x * c["bip"] for x, c in sel) / weight
    my = sum(c["h"] for _x, c in sel) / weight
    num = sum(c["bip"] * (x - mx) * (c["h"] / c["bip"] - my) for x, c in sel)
    den = sum(c["bip"] * (x - mx) ** 2 for x, c in sel)
    return 10.0 * num / den if den else None


def _load_hitter_contact_eye(path: Path) -> tuple[dict[str, float], dict[str, float]]:
    """Hitter Contact (``ch``) and Eye by player id. A blank Eye reads as
    the Contact rating, as ``BatterRatings.from_row`` reads it."""
    contact: dict[str, float] = {}
    eye: dict[str, float] = {}
    if not path.exists():
        return contact, eye
    with path.open(newline="", encoding="utf-8") as handle:
        for row in engine_rows(handle):
            pid = str(row.get("player_id") or "")
            if not pid or str(row.get("is_pitcher", "")).strip() in {"1", "True", "true"}:
                continue
            try:
                contact[pid] = float(row.get("ch") or "")
            except ValueError:
                continue
            try:
                eye[pid] = float(row.get("eye") or "")
            except ValueError:
                eye[pid] = contact[pid]
    return contact, eye


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


# ------------------------------------------------------------- Release 6a
# Statcast batted-ball classes by launch angle, in degrees: a ground ball
# under 10, a line drive from 10 to under 25, a fly ball from 25 to 50 and a
# pop-up above 50.
STATCAST_CLASSES = ("gb", "ld", "fb", "pu")
STATCAST_LD_MIN_DEG = 10.0
STATCAST_FB_MIN_DEG = 25.0
STATCAST_PU_MIN_DEG = 50.0
# A long home run, and the half-width of the centre third of the field.
HR_LONG_FT = 450.0
SPRAY_THIRD_DEG = 15.0
# Pulled, up the middle and opposite field, named as the benchmark file
# names them (pull_pct / straight_pct / oppo_pct).
SPRAY_THIRDS = ("pull", "straight", "oppo")
# metric name -> key in ``_load_pitcher_ratings`` of the four pitcher
# ratings the rating-value regressions take together.
R6_PITCHER_RATINGS = {
    "arm": "arm", "control": "control", "movement": "movement",
    "grade": "pitch_grade",
}
# The pitch types with a metric row (every type thrown is in the table).
R6_PITCH_TYPES = ("fb", "si", "sl", "cu", "cb")
R6_FIELD_POSITIONS = ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
INFIELD_POSITIONS = ("1B", "2B", "3B", "SS")
# Raw Power bands of ``tables["hr600_by_power_band"]`` (low inclusive).
R6_POWER_BANDS = (
    (0, 42), (42, 46), (46, 49), (49, 52), (52, 55), (55, 58), (58, 62), (62, 101),
)
# Fewer players than this and a regression, a fifth or a third is None.
R6_MIN_REGRESSION_ROWS = 30
# Release 6a (fielding). The seven positions a fielder's range is read at;
# the error sources of ``play_records["errors"]`` (``comebacker`` is a
# batter safe on a ball the pitcher fielded; the last four exist only under
# ``error_model`` 2); and the fewest fielders at a position for its
# outs-per-rating regression.
R6_RANGE_POSITIONS = ("1B", "2B", "3B", "SS", "LF", "CF", "RF")
R6_ERROR_SOURCES = (
    "roe", "comebacker", "advance", "tag_up", "steal", "pickoff", "of_hit",
    "relay",
)
R6_MIN_FIELDERS = 8
# The rows that come from the engine's fielding records (None without them).
R6_FIELDING_LOG_KEYS: tuple[str, ...] = tuple(
    [f"oaa_per_fa_sd_{pos.lower()}" for pos in R6_RANGE_POSITIONS]
    + [f"oaa_per_8pt_{pos.lower()}" for pos in R6_RANGE_POSITIONS]
    + ["team_der_true_sd", "range_level_shift", "neutral_out_prob_mean"]
    + [f"e_per_team_game_src_{source}" for source in R6_ERROR_SOURCES]
    + ["gb_play_share_p"]
)
# Every metric the Release 6a block reports (None when it has no data).
R6_METRIC_KEYS: tuple[str, ...] = tuple(
    [f"pitcher_fip_per10_{name}" for name in R6_PITCHER_RATINGS]
    + [f"pitcher_k_pct_per10_{name}" for name in R6_PITCHER_RATINGS]
    + ["pitcher_k_std_beta_grade"]
    + [f"gb_pct_pitch_{pitch}" for pitch in R6_PITCH_TYPES]
    + [f"ev_pitch_{pitch}" for pitch in R6_PITCH_TYPES]
    + [
        "fb_si_pitch_share", "qualified_fip_sd", "qualified_ev_against_sd",
        "pitcher_gb_pct_true_sd", "r_pitcher_gf_gb_pct",
        "starter_k_pct_delta_91_105", "starter_bb_pct_delta_91_105",
        "starter_ev_delta_91_105", "starter_woba_delta_91_105_batter_adj",
        "tto_pass2_woba_delta_batter_adj", "tto_pass3_woba_delta_batter_adj",
    ]
    + [f"hr600_power_q{i}" for i in range(1, 6)]
    + [
        "hr_power_bottom_quintile_ratio", "qualified_hr600_q1",
        "qualified_hr600_median", "qualified_hr600_q5",
        "hr30_share_of_qualified", "doubles_per10_power",
        "doubles_per10_contact", "corr_2b_hr", "corr_k_iso",
    ]
    + [f"doubles600_gf_t{i}" for i in range(1, 4)]
    + [f"e_per_team_game_{pos.lower()}" for pos in R6_FIELD_POSITIONS]
    + [f"gb_play_share_{pos.lower()}" for pos in INFIELD_POSITIONS]
    + [f"of_putout_share_{pos.lower()}" for pos in OUTFIELD_RANGE_POSITIONS]
    + ["off_primary_slot_share", "secondary_slot_share", "unearned_run_share"]
    + [
        f"statcast_{name}_{stat}"
        for name in STATCAST_CLASSES for stat in ("pct", "ev", "hit_rate")
    ]
    + ["hr_per_fb_pu", "hr_distance_mean_ft", "hr_450plus_share"]
    + [
        f"{third}_pct_{side}"
        for side in ("rhb", "lhb") for third in SPRAY_THIRDS
    ]
    + ["r_pull_rating_pull_angle_rhb", "r_pull_rating_pull_angle_lhb"]
    + [f"{third}_pct" for third in SPRAY_THIRDS]
    + list(R6_FIELDING_LOG_KEYS)
)


def statcast_class(launch_angle: float) -> str:
    """The Statcast batted-ball class of a launch angle (degrees)."""
    if launch_angle < STATCAST_LD_MIN_DEG:
        return "gb"
    if launch_angle < STATCAST_FB_MIN_DEG:
        return "ld"
    if launch_angle <= STATCAST_PU_MIN_DEG:
        return "fb"
    return "pu"


def pull_angle(spray_angle: float, batting_side: str) -> float:
    """A spray angle as degrees toward the batter's pull side.

    ``spray_angle`` is read as a physical angle, positive toward right
    field: a left-handed batter pulls to positive, a right-handed one to
    negative. (The engine draws it hand-blind today, so a right-handed
    batter's pull rating reads backwards; the Release 6 spray fix stores it
    this way.)
    """
    return spray_angle if batting_side == "L" else -spray_angle


class _R6Tallies:
    """Release 6a accumulator for ``ReportOnlyKpis._add_r6``."""

    def __init__(self) -> None:
        # Pitches by type; balls in play by pitch type and by pitcher
        # (``bip``, the engine's class counts and the exit-velocity sum).
        self.pitch_types: Counter = Counter()
        self.by_pitch_type: dict[str, Counter] = defaultdict(Counter)
        self.pitcher_bip: dict[str, Counter] = defaultdict(Counter)
        # Balls in play by the engine's class and by Statcast class (``n``,
        # exit-velocity sum ``ev``, ``hit`` and ``hr``).
        self.engine_class: Counter = Counter()
        self.statcast: dict[str, Counter] = {
            name: Counter() for name in STATCAST_CLASSES
        }
        # Home runs: ``n``, feet ``ft`` and the ones of HR_LONG_FT or more.
        self.hr: Counter = Counter()
        self.hr_longest = 0.0
        # Batting side -> thirds of the field; (batter, side) -> [balls,
        # pull-angle sum].
        self.spray: dict[str, Counter] = defaultdict(Counter)
        self.spray_by_batter: dict[tuple[str, str], list[float]] = defaultdict(
            lambda: [0, 0.0]
        )
        # The position the engine credited a play to (``fld_pos``): ground
        # balls (outs and errors) and outs in the air.
        self.fld_logged = False
        self.gb_plays: Counter = Counter()
        self.air_outs: Counter = Counter()
        # Hitter -> [wOBA value sum, PA]; one row per starter PA: (pitcher,
        # batter, pitch-count bucket or None, time through the order, wOBA
        # value); starter -> bucket -> PA, strikeouts, walks, balls in play
        # and their exit-velocity sum.
        self.batter_woba: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
        self.starter_pa: list[tuple[str, str, str | None, int, float]] = []
        self.fatigue: dict[str, dict[str, Counter]] = defaultdict(
            lambda: defaultdict(Counter)
        )
        # Box lines: runs and earned runs, earned runs by pitcher, hitter
        # counting lines.
        self.runs: Counter = Counter()
        self.pitcher_er: Counter = Counter()
        self.batters: dict[str, Counter] = defaultdict(Counter)
        # Starting positions (``starting_positions``): fielder-slots by how
        # the starter is listed there, and errors by starting position.
        self.positions_logged = False
        self.slots: Counter = Counter()
        self.errors_by_pos: Counter = Counter()
        # Every error the engine charged (``errors``): by source, and by
        # (source, position charged).
        self.errors_logged = False
        self.error_sources: Counter = Counter()
        self.errors_charged: Counter = Counter()
        # The chance log (``bip_chances`` / ``error_chances``, only from a
        # game played with ``fielding_chance_log``). League: balls ``n``,
        # the out chance used minus an average fielder's (``shift``) and the
        # average fielder's (``neutral``). Team: balls ``bip``, expected outs
        # ``out`` (before errors), the fielders' share of them ``range``,
        # expected errors ``err`` and errors saved against average fielders
        # ``err_saved``. (fielder, position): outs above average on range
        # ``range`` and on errors ``err``, and the games he had a chance in.
        self.chance_logged = False
        self.level: Counter = Counter()
        self.team_chance: dict[str, Counter] = defaultdict(Counter)
        self.fielder_chance: dict[tuple[str, str], Counter] = defaultdict(Counter)
        self.fielder_games: dict[tuple[str, str], set[int]] = defaultdict(set)
        # For the slope re-fit: position -> balls by class, the sum of
        # out0 * (1 - out0) (``spread``; line drives in ``spread_ld``) and
        # error rolls on ground outs and in the air, and the balls by how
        # they came out (``result_1b``, ``result_out``, ...); and ground
        # balls by direction (degrees toward the left-field side, 0.5
        # degree bins).
        self.chance_sums: dict[str, Counter] = defaultdict(Counter)
        self.grounder_direction: Counter = Counter()


def _load_r6_ratings(path: Path) -> dict[str, dict[str, Any]]:
    """The ratings the Release 6a rows read, each by player id.

    ``power`` (``ph``), ``hitter_gf`` and ``hitter_pull`` (``gf`` / ``pl``)
    for hitters, ``pitcher_gf`` for pitchers and ``other_pos`` (the listed
    second positions, split as ``BatterRatings.from_row`` splits them) for
    everyone. A blank ``gf`` or ``pl`` is 50, as the engine reads it; a
    hitter with no ``ph`` is left out of ``power``.
    """
    ratings: dict[str, dict[str, Any]] = {
        "power": {}, "hitter_gf": {}, "hitter_pull": {}, "pitcher_gf": {},
        "other_pos": {},
    }
    if not path.exists():
        return ratings

    def number(row: dict[str, Any], key: str) -> float:
        try:
            return float(row.get(key) or 50.0)
        except ValueError:
            return 50.0

    with path.open(newline="", encoding="utf-8") as handle:
        for row in engine_rows(handle):
            pid = str(row.get("player_id") or "")
            if not pid:
                continue
            raw = str(row.get("other_positions") or "").strip()
            raw = raw.strip("[]").replace("'", "").replace('"', "")
            ratings["other_pos"][pid] = frozenset(
                p.strip().upper() for p in raw.replace("|", ",").split(",") if p.strip()
            )
            if str(row.get("is_pitcher", "")).strip() in {"1", "True", "true"}:
                ratings["pitcher_gf"][pid] = number(row, "gf")
                continue
            ratings["hitter_gf"][pid] = number(row, "gf")
            ratings["hitter_pull"][pid] = number(row, "pl")
            try:
                ratings["power"][pid] = float(row.get("ph") or "")
            except ValueError:
                pass
    return ratings


def _tie_averaged(
    rows: list[dict[str, Any]], key: str, fields: tuple[str, ...]
) -> list[dict[str, Any]]:
    """``rows`` sorted by ``key``, each of ``fields`` replaced by its mean
    over the rows that share the same ``key`` value.

    For cutting a population into fifths or thirds by a whole-number
    rating: a cut that falls inside a group of equal ratings then gives
    both sides the group's mean, whatever order the tied rows are in.
    """
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    out = []
    for value in sorted(groups):
        group = groups[value]
        shared = {
            name: statistics.fmean(row[name] for row in group) for name in fields
        }
        out.extend({**row, **shared} for row in group)
    return out


def _fip(c: Counter) -> float:
    """Fielding-independent pitching without its league constant: (13 HR +
    3 (unintentional BB + HBP) - 2 K) per inning."""
    walks = c["bb"] - c["ibb"] + c["hbp"]
    return (13.0 * c["hr"] + 3.0 * walks - 2.0 * c["so"]) / (c["outs"] / 3.0)


def _least_squares(
    xs: list[list[float]], ys: list[float], ws: list[float] | None = None
) -> list[float | None]:
    """Slopes of ``ys`` on the columns of ``xs`` taken together.

    Least squares with an intercept (fitted, not returned), each row
    weighted by ``ws`` (1 without it). A column that does not vary is left
    out of the fit and its slope is None; every slope is None with fewer
    rows than columns + 2 or a system that cannot be solved.
    """
    if not xs:
        return []
    cols = len(xs[0])
    none: list[float | None] = [None] * cols
    weights = [1.0] * len(xs) if ws is None else [float(w) for w in ws]
    total = sum(weights)
    if len(xs) < cols + 2 or total <= 0.0:
        return none
    means = [
        sum(w * x[j] for x, w in zip(xs, weights)) / total for j in range(cols)
    ]
    keep = [
        j for j in range(cols)
        if sum(w * (x[j] - means[j]) ** 2 for x, w in zip(xs, weights)) > 1e-9 * total
    ]
    if not keep:
        return none
    mean_y = sum(w * y for y, w in zip(ys, weights)) / total
    size = len(keep)
    normal = [[0.0] * size for _ in range(size)]
    target = [0.0] * size
    for x, y, w in zip(xs, ys, weights):
        centred = [x[j] - means[j] for j in keep]
        for a in range(size):
            target[a] += w * centred[a] * (y - mean_y)
            for b in range(size):
                normal[a][b] += w * centred[a] * centred[b]
    solved = _solve_linear(normal, target)
    if solved is None:
        return none
    slopes = list(none)
    for j, slope in zip(keep, solved):
        slopes[j] = slope
    return slopes


def _standardised_betas(xs: list[list[float]], ys: list[float]) -> list[float | None]:
    """Unweighted least-squares slopes in standard deviations: how many sd
    of ``ys`` one sd of each column of ``xs`` moves, the columns taken
    together. None for a column (or an outcome) that does not vary."""
    slopes = _least_squares(xs, ys)
    sd_y = statistics.pstdev(ys) if len(ys) >= 2 else 0.0
    out: list[float | None] = []
    for j, slope in enumerate(slopes):
        if slope is None or not sd_y:
            out.append(None)
        else:
            out.append(slope * statistics.pstdev([x[j] for x in xs]) / sd_y)
    return out


def _bucket_delta(
    acc: dict[str, dict[str, Counter]], events: str, trials: str
) -> float | None:
    """Within-starter change in ``events`` per ``trials`` from the early
    pitch-count bucket to the late one, weighted by his late trials."""
    num = 0.0
    weight = 0.0
    for buckets in acc.values():
        early, late = buckets.get("early"), buckets.get("late")
        if not early or not late or not early[trials] or not late[trials]:
            continue
        num += late[trials] * (
            late[events] / late[trials] - early[events] / early[trials]
        )
        weight += late[trials]
    return (num / weight) if weight else None


def _starter_pa_delta(
    rows: list[tuple[str, str, str | None, int, float]],
    batter_means: dict[str, float],
    index: int,
    base: Any,
    other: Any,
) -> tuple[float | None, float | None, int]:
    """(raw, batter-adjusted, PA) within-pitcher wOBA change, ``other``
    minus ``base``.

    ``rows`` are starter PA: (pitcher, batter, pitch-count bucket, time
    through the order, wOBA value); ``index`` picks the grouping column (2
    or 3). The adjusted value of a PA is its wOBA value minus the batter's
    own season mean (``batter_means``), so a group that faces better
    hitters is not charged for them. Both are the mean over pitchers with
    PA in both groups of (other - base), weighted by the PA in ``other``.
    """
    acc: dict[str, dict[Any, list[float]]] = {}
    for row in rows:
        group = row[index]
        if group != base and group != other:
            continue
        cells = acc.setdefault(row[0], {base: [0.0, 0.0, 0], other: [0.0, 0.0, 0]})
        cell = cells[group]
        cell[0] += row[4]
        cell[1] += row[4] - batter_means.get(row[1], 0.0)
        cell[2] += 1
    raw = adjusted = 0.0
    weight = 0
    for cells in acc.values():
        a, b = cells[base], cells[other]
        if not a[2] or not b[2]:
            continue
        raw += b[2] * (b[0] / b[2] - a[0] / a[2])
        adjusted += b[2] * (b[1] / b[2] - a[1] / a[2])
        weight += b[2]
    if not weight:
        return None, None, 0
    return raw / weight, adjusted / weight, weight


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
        for row in engine_rows(handle):
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

# The grid is its own league: the anchor cell (a 50 hitter against a pitcher
# with control and movement 50 throwing GRID_PITCH_GRADE pitches to a
# GRID_CATCHER_FIELDING catcher) is the league-average hitter, pitcher and
# catcher. The Release 5 models read ratings against the league's centres
# (contact_model: Contact and the pitch-quality mix; swing_model: Eye;
# command_model: control; umpire_model: catcher fielding), so the grid pins
# every centre to its own anchor. A fixture's centres would put the anchor
# hitter and pitcher off average (calibration: Contact 48.8, pitch quality
# 52.7), and so would a centre pinned in the profile. With the models off
# nothing in a cell reads a centre that is not already 50. The K and HR
# cells are right-handed batter against right-handed pitcher, so the
# anchor strikes out a little more than the league (the same-hand penalty).
# With centred_ratings on the engine shifts each rating by 50 minus its
# centre before the pitch (a cell goes through the engine's own
# _batter_context and _pitcher_context), so the centres it shifts by are
# pinned too: Power at the grid's 50 and the pitcher's workload-weighted
# centres (pitcher_*_usage_center) at the same anchor as the plain ones.
# The grid's pitches then read as the league-average 50 pitch.
GRID_PITCH_GRADE = 55.0
GRID_CATCHER_FIELDING = 50.0
GRID_RATING_CENTERS = {
    "hitter_contact_center": 50.0,
    "hitter_eye_center": 50.0,
    "hitter_power_center": 50.0,
    "hitter_speed_center": 50.0,
    "pitcher_control_center": 50.0,
    "pitcher_movement_center": 50.0,
    "pitcher_arm_center": 50.0,
    "pitcher_grade_center": GRID_PITCH_GRADE,
    "pitcher_control_usage_center": 50.0,
    "pitcher_movement_usage_center": 50.0,
    "pitcher_arm_usage_center": 50.0,
    "pitcher_grade_usage_center": GRID_PITCH_GRADE,
    "catcher_fa_center": GRID_CATCHER_FIELDING,
    # Release 6a: the grid hitter and pitcher carry a ground-ball rating of
    # 50 and the hitter a pull rating of 50, so these centres are the
    # grid's own as well (nothing reads them yet).
    "hitter_gf_center": 50.0,
    "hitter_pull_center": 50.0,
    "pitcher_gf_usage_center": 50.0,
}
# Release 6a: the composite pitcher axis (``composite_pitcher``). Generation
# 6 weights the pitch grade at .55 of pitch quality, so a grid that moves
# only control and movement understates the pitcher. On the composite axis
# every pitch grade moves with the level, point for point, around the
# grid's average grade: the anchor cell is the same pitcher on both axes.
GRID_AXIS_CONTROL_MOVEMENT = "control_movement"
GRID_AXIS_COMPOSITE = "composite"
# The Power x pitcher home-run box the composite grid adds (plan section 5:
# the HR log5 residual over the whole 35-80 box).
HR_BOX_LEVELS = (35.0, 50.0, 65.0, 80.0)
# The K grid's inner cells: batter and pitcher no higher than this.
K_GRID_INNER_MAX = 65.0
# League-relative Power levels of the ``power_hr600_p<level>`` table.
POWER_TABLE_LEVELS = tuple(float(level) for level in range(30, 85, 5))


def _grid_pitch_grade(pitcher_level: float, composite: bool) -> float:
    """The grade of every pitch a grid pitcher throws: the grid's average
    grade, moved with his level on the composite axis."""
    if not composite:
        return GRID_PITCH_GRADE
    return GRID_PITCH_GRADE + (pitcher_level - 50.0)


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _simulate_cell(
    *, contact: float, power: float, pitcher_level: float, n: int, seed: int,
    tuning: Any, park: Any, bats: str = "R", throws: str = "R",
    pitch_grade: float = GRID_PITCH_GRADE,
) -> Counter:
    """One grid cell: ``n`` PA of one batter against one pitcher.

    Counts ``pa``, ``bb``, ``k`` (split into ``k_looking`` and
    ``k_swinging``, Release 5a) and ``hr``. ``bats`` / ``throws`` set the
    hands for the platoon cells; both vs-left ratings are 50.
    ``pitch_grade`` is the grade of each of his four pitches (Release 6a:
    it moves with ``pitcher_level`` on the composite axis).
    """
    from physics_sim.engine import (
        _batter_context,
        _league_relative,
        _pitcher_context,
    )
    from physics_sim.models import BatterRatings, PitcherRatings
    from physics_sim.physics import resolve_batted_ball, simulate_pitch

    batter = BatterRatings(
        player_id="grid_b", bats=bats, primary_position="CF", other_positions=[],
        contact=contact, power=power, gb_tendency=50.0, pull_tendency=50.0,
        vs_left=50.0, fielding=50.0, arm=50.0, speed=50.0, eye=50.0,
        height=73.0, durability=50.0,
    )
    pitcher = PitcherRatings(
        player_id="grid_p", bats=throws, throws=throws, role="SP", preferred_role="SP",
        velocity=50.0, control=pitcher_level, movement=pitcher_level,
        gb_tendency=50.0, vs_left=50.0, hold_runner=50.0, endurance=50.0,
        durability=50.0, fielding=50.0, arm=50.0,
        repertoire={pitch: pitch_grade for pitch in ("fb", "sl", "cu", "cb")},
    )
    ctx_b = _batter_context(batter, pitcher, tuning, tto=1)
    # The engine's own per-PA pitcher context (a fresh pitcher).
    ctx_p = _pitcher_context(pitcher, tuning)
    context = {
        "inning": 1, "outs": 0, "score_diff": 0,
        "bases": {"first": False, "second": False, "third": False},
        "catcher_fielding": GRID_CATCHER_FIELDING, "batter_pitches_seen": 0,
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
                    out["k_looking" if o == "strike" else "k_swinging"] += 1
                    break
            elif o == "foul":
                strikes = min(2, strikes + 1)
            elif o == "in_play":
                _dist, is_hr, _bt, _ht = resolve_batted_ball(
                    exit_velo=res.exit_velo or 90.0,
                    launch_angle=res.launch_angle or 12.0,
                    spray_angle=res.spray_angle or 0.0,
                    park=park, tuning=tuning, batter_speed=batter.speed,
                    batter_contact=_league_relative(
                        batter.contact, "hitter_contact_center", tuning
                    ),
                    batter_power=_league_relative(
                        batter.power, "hitter_power_center", tuning
                    ),
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
    tuning_overrides: dict[str, Any] | None = None,
    seed: int = 20261006,
    composite_pitcher: bool = False,
    fixture_dir: Path | None = None,
    fixture_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """CH x pitcher K grid and PH x pitcher HR grid, log5 residuals (M20, M21).

    A PA-level Monte Carlo on the real per-pitch code, as the audit ran it:
    one batter rating varies, the other is 50; the pitcher's control and
    movement both equal the level (repertoire 55); generic park. The CH grid
    spans 35-80 (the M20 gate range); the PH grid spans the fixture's own
    p5-p95 of hitter PH and pitcher composite (the M21 gate range), with 50 as
    the log5 anchor. Saves and restores the global random state.

    Release 5a adds, from the same Monte Carlo: the CH grid's strikeouts
    split into swinging and looking (``_k_split_grid``) and a platoon grid,
    the HR rate against the opposite hand over the same hand by Power for
    each batting side (``_platoon_hr_grid``; 20 more cells).

    Release 5: the rating centres are the grid's own (``GRID_RATING_CENTERS``),
    whatever the overrides hold, so a 50 is the league-average rating under
    the models that read ratings against a centre.

    Release 6a: ``composite_pitcher`` makes the pitcher axis of every grid
    a composite -- control, movement and every pitch grade move together
    (``_grid_pitch_grade``) -- instead of control and movement alone, and
    adds a Power x pitcher HR box over 35-80
    (``matchup_hr_log5_box_max_abs_resid_logit``; 12 more cells). The
    metric names are the same on both axes and ``tables
    ["matchup_grid_pitcher_axis"]`` says which one was run; the default is
    the control-and-movement axis, cell for cell what it was. The inner K
    residual (``matchup_k_log5_inner_max_abs_resid``, batter and pitcher at
    65 or below) is read off the K grid on either axis. With
    ``fixture_dir`` the Power table is run as well
    (``power_hr600_p<level>``, :func:`power_hr600_table`; 11 more cells),
    on ``fixture_overrides``: the run's tuning with the FIXTURE's centres,
    not the grid's.
    """
    from physics_sim.config import load_tuning
    from physics_sim.park import load_park

    tuning = load_tuning({**(tuning_overrides or {}), **GRID_RATING_CENTERS})
    park = load_park(None)
    ph_pop, comp_pop = _population_levels(players_path)

    def cell(*, pitcher_level: float, **kwargs: Any) -> Counter:
        return _simulate_cell(
            pitcher_level=pitcher_level, n=pa_per_cell, seed=seed, tuning=tuning,
            park=park,
            pitch_grade=_grid_pitch_grade(pitcher_level, composite_pitcher),
            **kwargs,
        )

    hr_box = None
    power_table = None
    state = random.getstate()
    try:
        ch_levels = [35.0, 50.0, 65.0, 80.0]
        ch_cells = {
            (b, p): cell(contact=b, power=50.0, pitcher_level=p)
            for b in ch_levels for p in ch_levels
        }
        k_grid = _log5_grid(ch_cells, ch_levels, ch_levels, 50.0, "k")
        ph_levels = _p5_50_p95(ph_pop)
        p_levels = _p5_50_p95(comp_pop)
        ph_cells = {
            (b, p): cell(contact=50.0, power=b, pitcher_level=p)
            for b in ph_levels for p in p_levels
        }
        hr_grid = _log5_grid(ph_cells, ph_levels, p_levels, 50.0, "hr")
        # Release 5a: the same hitter from each side against each hand
        # (pitcher level 50). Every cell reseeds, so the cells above are
        # unchanged by these.
        platoon_cells = {
            (side, level, hand): cell(
                contact=50.0, power=level, pitcher_level=50.0, bats=side,
                throws=hand,
            )
            for side in ("L", "R") for level in PLATOON_GRID_POWER
            for hand in ("L", "R")
        }
        if composite_pitcher:
            box = list(HR_BOX_LEVELS)
            # The Power 50 row is the K grid's Contact 50 row (the same
            # hitter, pitchers and seed), so it is not simulated twice.
            box_cells = {
                (b, p): ch_cells[(50.0, p)] if b == 50.0
                else cell(contact=50.0, power=b, pitcher_level=p)
                for b in box for p in box
            }
            hr_box = _log5_grid(box_cells, box, box, 50.0, "hr")
        if fixture_dir is not None:
            power_table = power_hr600_table(
                pa_per_cell=pa_per_cell, fixture_dir=fixture_dir,
                players_path=players_path, tuning_overrides=fixture_overrides,
                seed=seed,
            )
    finally:
        random.setstate(state)
    k_split = _k_split_grid(ch_cells, ch_levels)
    platoon = _platoon_hr_grid(platoon_cells)
    inner = [
        abs(row["residual"]) for row in k_grid["cells"]
        if "residual" in row
        and max(row["batter"], row["pitcher"]) <= K_GRID_INNER_MAX
    ]
    metrics = {
        "matchup_k_log5_max_abs_resid": k_grid["max_abs_residual"],
        "matchup_hr_log5_max_abs_resid_logit": hr_grid["max_abs_residual_logit"],
        **k_split["metrics"],
        **platoon["metrics"],
        # Release 6a: the K residual away from the 80 row and column.
        "matchup_k_log5_inner_max_abs_resid": max(inner) if inner else None,
    }
    tables = {
        "matchup_k_grid": {"levels": ch_levels, "pa_per_cell": pa_per_cell, **k_grid},
        "matchup_hr_grid": {
            "ph_levels": ph_levels, "pitcher_levels": p_levels,
            "pa_per_cell": pa_per_cell, **hr_grid,
        },
        "matchup_k_split_grid": {
            "levels": ch_levels, "pa_per_cell": pa_per_cell,
            "cells": k_split["cells"],
        },
        "matchup_platoon_hr_grid": {
            "power_levels": list(PLATOON_GRID_POWER),
            "pa_per_cell": pa_per_cell, "cells": platoon["cells"],
        },
        "matchup_grid_pitcher_axis": (
            GRID_AXIS_COMPOSITE if composite_pitcher else GRID_AXIS_CONTROL_MOVEMENT
        ),
    }
    if hr_box is not None:
        thin = sum(1 for row in hr_box["cells"] if "skipped" in row)
        # A thin cell (too few home runs for log5) is left out of the
        # maximum; raise --matchup-grid-pa until none is skipped.
        metrics["matchup_hr_log5_box_max_abs_resid_logit"] = (
            hr_box["max_abs_residual_logit"] if thin < len(hr_box["cells"]) else None
        )
        metrics["matchup_hr_log5_box_thin_cells"] = thin
        tables["matchup_hr_box_grid"] = {
            "levels": list(HR_BOX_LEVELS), "pa_per_cell": pa_per_cell,
            "hr_per_pa": [
                {
                    "batter": b, "pitcher": p,
                    "hr_per_pa": _ratio(box_cells[(b, p)]["hr"], box_cells[(b, p)]["pa"]),
                    "k_per_pa": _ratio(box_cells[(b, p)]["k"], box_cells[(b, p)]["pa"]),
                }
                for b in HR_BOX_LEVELS for p in HR_BOX_LEVELS
            ],
            **hr_box,
        }
    if power_table is not None:
        metrics.update(power_table["metrics"])
        tables["power_hr600_table"] = power_table["table"]
    return {"metrics": metrics, "tables": tables}


def power_hr600_table(
    *,
    pa_per_cell: int,
    fixture_dir: Path,
    players_path: Path,
    tuning_overrides: dict[str, Any] | None = None,
    seed: int = 20261006,
) -> dict[str, Any]:
    """Home runs per 600 PA by league-relative Power (``power_hr600_p<level>``).

    Release 6a (decision 4: a Power 30-40 hitter at about 5 to 10). A
    fixture's regulars stop near Power 35 at the bottom and 65 at the top,
    so the ends of the Power curve can only be read by Monte Carlo: one
    hitter per level in ``POWER_TABLE_LEVELS``, the league's average in
    everything else -- Contact, Eye, speed, ground-ball and pull rating and
    the vs-left rating of his batting side at the fixture's centres, Power
    the level's distance from the Power centre -- batting from each side
    in the league's proportion (a switch hitter counts half each) against
    the fixture's ACT pitchers drawn by expected workload
    (``services.league_rating_centers.active_pitcher_workloads``), with a
    league-average catcher, in the generic park. ``tuning_overrides`` are
    the run's overrides WITH the fixture's rating centres (the harness's
    ``with_rating_centers``), so every pitcher is read as a game reads him.

    Every cell uses the same seed (common random numbers: the same pitchers
    in the same order). The caller saves and restores the global random
    state. Metrics are None when the fixture has no ACT pitcher.
    """
    from physics_sim.config import load_tuning
    from physics_sim.models import PitcherRatings
    from physics_sim.park import load_park
    from services.league_rating_centers import active_pitcher_workloads

    tuning = load_tuning(tuning_overrides or {})
    park = load_park(None)
    staff = [
        (PitcherRatings.from_row(row), weight)
        for row, weight in active_pitcher_workloads(
            Path(fixture_dir), players_path=players_path
        )
    ]
    metrics: dict[str, float | None] = {}
    cells = []
    for level in POWER_TABLE_LEVELS:
        key = f"power_hr600_p{int(level)}"
        if not staff:
            metrics[key] = None
            continue
        c = _simulate_staff_cell(
            power=level, n=pa_per_cell, seed=seed, tuning=tuning, staff=staff,
            park=park,
        )
        metrics[key] = _ratio(600.0 * c["hr"], c["pa"])
        cells.append({
            "power": level, "pa": c["pa"], "hr": c["hr"],
            "hr600": metrics[key],
            "k_per_pa": _ratio(c["k"], c["pa"]),
            "bb_per_pa": _ratio(c["bb"], c["pa"]),
        })
    return {
        "metrics": metrics,
        "table": {
            "levels": list(POWER_TABLE_LEVELS), "pa_per_cell": pa_per_cell,
            "pitchers": len(staff), "cells": cells,
        },
    }


def _simulate_staff_cell(
    *, power: float, n: int, seed: int, tuning: Any, staff: list[tuple[Any, float]],
    park: Any,
) -> Counter:
    """One Power-table cell: ``n`` PA of the league's average hitter at
    league-relative Power ``power`` against ``staff`` ((pitcher, workload)
    pairs). Counts ``pa``, ``bb``, ``k`` and ``hr``. See
    :func:`power_hr600_table`."""
    from physics_sim.engine import (
        _batter_context,
        _league_relative,
        _pitcher_context,
    )
    from physics_sim.models import BatterRatings
    from physics_sim.physics import resolve_batted_ball, simulate_pitch

    def centre(key: str) -> float:
        return tuning.get(key, 50.0)

    batters = {
        side: BatterRatings(
            player_id="table_b", bats=side, primary_position="CF",
            other_positions=[], contact=centre("hitter_contact_center"),
            power=power - 50.0 + centre("hitter_power_center"),
            gb_tendency=centre("hitter_gf_center"),
            pull_tendency=centre("hitter_pull_center"),
            vs_left=centre(f"hitter_vl_center_{side.lower()}"), fielding=50.0,
            arm=50.0, speed=centre("hitter_speed_center"),
            eye=centre("hitter_eye_center"), height=73.0, durability=50.0,
        )
        for side in ("L", "R")
    }
    share_l = tuning.get("hitter_bats_share_l", 0.0)
    share_r = tuning.get("hitter_bats_share_r", 0.0)
    share_s = tuning.get("hitter_bats_share_s", 0.0)
    known = share_l + share_r + share_s
    # Unknown shares (0 / 0 / 0): MLB's rough split.
    left = (share_l + 0.5 * share_s) / known if known > 0.0 else 0.45
    context = {
        "inning": 1, "outs": 0, "score_diff": 0,
        "bases": {"first": False, "second": False, "third": False},
        "catcher_fielding": centre("catcher_fa_center"), "batter_pitches_seen": 0,
        "batter_swing_rate": None, "batter_chase_rate": None,
        "last_pitch_type": None, "last_pitch_repeat": 0,
        "foul_territory_scale": 1.0,
    }
    # Who pitches and which side the hitter bats from come from a private
    # stream; the pitches themselves from the module-level one, reseeded
    # per cell as the grid cells are.
    rng = random.Random(seed * 7919 + 13)
    picks = rng.choices(range(len(staff)), weights=[w for _p, w in staff], k=n)
    mound: dict[int, Any] = {}
    random.seed(seed)
    out: Counter = Counter()
    for pick in picks:
        batter = batters["L" if rng.random() < left else "R"]
        pitcher = staff[pick][0]
        ctx_p = mound.get(pick)
        if ctx_p is None:
            ctx_p = mound[pick] = _pitcher_context(pitcher, tuning)
        ctx_b = _batter_context(batter, pitcher, tuning, tto=1)
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
                    batter_contact=_league_relative(
                        batter.contact, "hitter_contact_center", tuning
                    ),
                    batter_power=_league_relative(
                        batter.power, "hitter_power_center", tuning
                    ),
                )
                out["hr"] += bool(is_hr)
                break
            else:  # hit batter, catcher's interference
                break
    return out


# Power levels of the platoon HR-ratio grid. Dense around 50: the platoon
# power bonus is added before the bat-speed knee there, so the ratio steps
# between a hitter just below it and one just above (audit H7).
PLATOON_GRID_POWER = (40.0, 50.0, 55.0, 65.0, 80.0)


def _k_split_grid(
    cells: dict[tuple[float, float], Counter], levels: list[float]
) -> dict[str, Any]:
    """Swinging and looking strikeouts per cell of the CH x pitcher grid.

    Release 5a: Contact should lower the called third strike as well as the
    swinging one. The per-Contact rows pool the pitcher levels:
    ``matchup_looking_k_share_ch<level>`` (looking K per strikeout) and
    ``matchup_looking_k_per_pa_ch<level>``.
    """
    rows = []
    metrics: dict[str, float | None] = {}
    for b in levels:
        pooled: Counter = Counter()
        for p in levels:
            c = cells[(b, p)]
            pooled.update(c)
            rows.append({
                "batter": b, "pitcher": p,
                "k_swinging_per_pa": _ratio(c["k_swinging"], c["pa"]),
                "k_looking_per_pa": _ratio(c["k_looking"], c["pa"]),
                "looking_share": _ratio(c["k_looking"], c["k"]),
            })
        metrics[f"matchup_looking_k_share_ch{int(b)}"] = _ratio(
            pooled["k_looking"], pooled["k"]
        )
        metrics[f"matchup_looking_k_per_pa_ch{int(b)}"] = _ratio(
            pooled["k_looking"], pooled["pa"]
        )
    return {"metrics": metrics, "cells": rows}


def _platoon_hr_grid(
    cells: dict[tuple[str, float, str], Counter]
) -> dict[str, Any]:
    """HR rate against the opposite hand over the same hand, by Power.

    One ratio per batting side and Power level
    (``matchup_platoon_hr_ratio_<lhb|rhb>_ph<level>``); None when either
    cell has fewer than GRID_MIN_EVENTS home runs.
    """
    rows = []
    metrics: dict[str, float | None] = {}
    for side in ("L", "R"):
        other = "R" if side == "L" else "L"
        for level in PLATOON_GRID_POWER:
            same, opp = cells[(side, level, side)], cells[(side, level, other)]
            ratio = None
            if same["hr"] and min(same["hr"], opp["hr"]) >= GRID_MIN_EVENTS:
                ratio = (opp["hr"] / opp["pa"]) / (same["hr"] / same["pa"])
            name = "lhb" if side == "L" else "rhb"
            metrics[f"matchup_platoon_hr_ratio_{name}_ph{int(level)}"] = ratio
            rows.append({
                "bats": side, "power": level,
                "hr_per_pa_same": _ratio(same["hr"], same["pa"]),
                "hr_per_pa_opposite": _ratio(opp["hr"], opp["pa"]),
                "ratio": ratio,
            })
    return {"metrics": metrics, "cells": rows}
