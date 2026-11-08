"""Turn a stored game replay into timed plays for the game viewer
(backlog #74 step 2; ``docs/replay/REPLAY_DATA_SPEC.md`` section 4).

The stored record (``nexgen.replay/1``, :mod:`services.game_replay`) is what
the engine logged: every pitch, every batted ball, who was on base before and
after each play and who scored. This module turns each entry into a *play*:
a few seconds of timed movement -- the ball, the runners, the fielders who
move -- plus cues (catch, throw, tag, out, safe, score), a line of text and
the scoreboard after it. The 2D viewer (and the 3D one after it) only draws
what a play says.

The rule is the spec's: **the engine decides, the viewer only shows.** Who is
out, who is safe, where every runner ends up and who scores come from the
stored record; the timing is filled in from the ball-flight model and a few
animation speeds, and bent where it has to be so an out's throw always beats
the runner and a safe runner always beats the throw. :func:`check_plays`
verifies exactly that, and that the plays add up to the engine's outs and
score.

Plays are derived, never stored: a better converter re-renders every old
game. Building plays draws no random number.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from physics_sim import ballflight

SCHEMA = "nexgen.plays/1"

# --- the field (ballflight's frame: feet, home plate at the origin, +y to
# centre field through second base, +x toward first base / right field) ----

_B = 90.0 / math.sqrt(2.0)
BASE_XY: Dict[int, Tuple[float, float]] = {
    0: (0.0, 0.0), 1: (_B, _B), 2: (0.0, 2.0 * _B), 3: (-_B, _B), 4: (0.0, 0.0),
}
RUBBER_XY = (0.0, 60.5)
POSITIONS = ("P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF")
SCORING_NUMBER = {pos: str(n) for n, pos in enumerate(POSITIONS, start=1)}
POSITION_NAME = {
    "P": "pitcher", "C": "catcher", "1B": "first base", "2B": "second base",
    "3B": "third base", "SS": "shortstop", "LF": "left field",
    "CF": "center field", "RF": "right field",
}
FIELD_SIDE = {"LF": "left", "CF": "center", "RF": "right"}


def _xy(radius: float, angle: float) -> Tuple[float, float]:
    a = math.radians(angle)
    return radius * math.sin(a), radius * math.cos(a)


def standing_spots() -> Dict[str, Tuple[float, float]]:
    """Where each fielder stands before the pitch (the fielding play
    model's spots; the catcher behind the plate)."""
    spots = {pos: _xy(*spot) for pos, spot in ballflight.INFIELD_SPOTS.items()}
    spots.update({pos: _xy(*spot) for pos, spot in ballflight.OUTFIELD_SPOTS.items()})
    spots["C"] = (0.0, -4.0)
    return {pos: spots[pos] for pos in POSITIONS}


SPOTS = standing_spots()

# --- animation speeds (feet and seconds; what the viewer shows, not what
# the engine decided) ------------------------------------------------------

_MPH_FPS = 1.4667
RELEASE_Y = 54.0            # the ball leaves the hand about 6.5 ft in front of the rubber
RELEASE_Z = 5.8
RUNNER_FPS = 27.0           # a runner between bases (90 ft in 3.3 s)
TROT_FPS = 26.0             # a home-run trot (brisk: the viewer is not a broadcast)
WALK_FPS = 22.0             # a walk or a hit batter to first
HOME_TO_FIRST = 4.3         # the batter's run, contact to the bag
BATTER_START = 0.25         # out of the box after contact
IF_THROW_FPS = 120.0
OF_THROW_FPS = 105.0
IF_RUN_FPS = 21.0
OF_RUN_FPS = 26.0
REACT = 0.3
EXCHANGE = 0.55             # glove to throw
PIVOT = 0.45                # a double-play pivot
STEAL_LEAD = 0.25           # a base stealer goes this long before the release
MARGIN = 0.15               # what an out's throw / a safe runner wins by
GAP = 0.6                   # the play holds this long after its last move


class _Builder:
    """One play's timeline while it is being built."""

    def __init__(self) -> None:
        self.ball: List[List[float]] = []
        self.fielders: Dict[str, List[List[float]]] = {}
        self.runners: List[Dict[str, Any]] = []
        self.cues: List[Dict[str, Any]] = []
        self.throws: List[Dict[str, Any]] = []

    # ball ---------------------------------------------------------------
    def ball_at(self, t: float, x: float, y: float, z: float) -> None:
        point = [round(t, 3), round(x, 2), round(y, 2), round(max(0.0, z), 2)]
        if self.ball and point[0] < self.ball[-1][0]:
            point[0] = self.ball[-1][0]
        self.ball.append(point)

    def ball_end(self) -> Tuple[float, float, float, float]:
        t, x, y, z = self.ball[-1]
        return t, x, y, z

    # fielders -----------------------------------------------------------
    def fielder_at(self, pos: str) -> Tuple[float, float, float]:
        path = self.fielders.get(pos)
        if path:
            t, x, y = path[-1]
            return t, x, y
        x, y = SPOTS[pos]
        return 0.0, x, y

    def fielder_to(
        self, pos: str, x: float, y: float, *, arrive: Optional[float] = None,
        start: Optional[float] = None, speed: float = IF_RUN_FPS,
    ) -> float:
        """Move ``pos`` to ``(x, y)``; returns the arrival time. With
        ``arrive`` he gets there exactly then (leaving late enough, or
        hurrying); otherwise at ``speed`` from ``start``."""
        t0, x0, y0 = self.fielder_at(pos)
        path = self.fielders.setdefault(pos, [[0.0, round(x0, 2), round(y0, 2)]])
        dist = math.hypot(x - x0, y - y0)
        begin = max(t0, start if start is not None else t0)
        if arrive is None:
            arrive = begin + dist / speed
        else:
            begin = max(t0, min(begin, arrive - dist / speed))
            if begin > arrive:
                begin = arrive
        if begin > path[-1][0]:
            path.append([round(begin, 3), round(x0, 2), round(y0, 2)])
        path.append([round(max(arrive, path[-1][0]), 3), round(x, 2), round(y, 2)])
        return max(arrive, path[-1][0])

    # throws -------------------------------------------------------------
    def throw(
        self, frm: str, to: str, base: Optional[int], *, release: float,
        x: Optional[float] = None, y: Optional[float] = None,
        not_before: float = 0.0, speed: float = IF_THROW_FPS,
    ) -> float:
        """A throw from fielder ``frm`` to fielder ``to`` (at ``base`` when
        given, else at ``(x, y)``); the catcher of it is moved there in
        time. Returns when it is caught (never before ``not_before``)."""
        _t, fx, fy = self.fielder_at(frm)
        tx, ty = (BASE_XY[base] if base is not None else (x or 0.0, y or 0.0))
        if base is not None and to != frm:
            tx, ty = _bag_spot(base, to)
        dist = math.hypot(tx - fx, ty - fy)
        catch = max(release + dist / speed, not_before)
        release = catch - dist / speed
        if to == frm:
            catch = self.fielder_to(frm, tx, ty, start=release)
        else:
            self.fielder_to(to, tx, ty, arrive=min(catch - 0.1, max(release, 0.0) + 2.5),
                            start=0.0)
            self.ball_at(release, fx, fy, 5.5)
            self.ball_at(catch, tx, ty, 5.0)
            self.cues.append({"t": round(release, 3), "type": "throw", "by": frm,
                              "to": to, "base": base})
            self.cues.append({"t": round(catch, 3), "type": "catch", "by": to})
        self.throws.append({"t": round(catch, 3), "base": base, "by": to})
        return catch

    # runners ------------------------------------------------------------
    def run(
        self, who: str, role: str, start_base: int, end_base: int, *,
        start: float, speed: float = RUNNER_FPS, out_at: Optional[int] = None,
        arrive: Optional[float] = None, short: float = 0.0,
    ) -> Dict[str, Any]:
        """A runner from ``start_base`` to ``end_base`` (4 = home) leaving at
        ``start``; ``out_at`` marks the base he is put out at. ``arrive`` pins
        when he reaches the last bag (slower, never faster, than ``speed``
        unless the play demands it); ``short`` stops him that many feet
        before it (a tag out between bases)."""
        stops = list(range(start_base, end_base + 1)) if end_base >= start_base else [start_base]
        points = [BASE_XY[b] for b in stops]
        if short and len(points) >= 2:
            (ax, ay), (bx, by) = points[-2], points[-1]
            seg = math.hypot(bx - ax, by - ay)
            f = max(0.0, (seg - short) / seg)
            points[-1] = (ax + (bx - ax) * f, ay + (by - ay) * f)
        legs = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])]
        total = sum(legs)
        natural = start + total / speed
        end = natural if arrive is None else max(arrive, start + total / (speed * 1.6))
        path = [[round(start, 3), round(points[0][0], 2), round(points[0][1], 2)]]
        t = start
        for leg, (px, py) in zip(legs, points[1:]):
            t += (end - start) * (leg / total) if total else 0.0
            path.append([round(t, 3), round(px, 2), round(py, 2)])
        record = {"who": who, "role": role, "from": start_base,
                  "to": 0 if out_at is not None else end_base, "path": path}
        if out_at is not None:
            record["out_at"] = out_at
        self.runners.append(record)
        return record

    def stay(self, who: str, base: int) -> None:
        x, y = BASE_XY[base]
        self.runners.append({"who": who, "role": "runner", "from": base, "to": base,
                             "path": [[0.0, round(x, 2), round(y, 2)]]})

    def cue(self, t: float, cue_type: str, **extra: Any) -> None:
        self.cues.append({"t": round(t, 3), "type": cue_type, **extra})

    def duration(self) -> float:
        ends = [self.ball[-1][0]] if self.ball else [0.0]
        ends += [path[-1][0] for path in self.fielders.values()]
        ends += [r["path"][-1][0] for r in self.runners]
        ends += [c["t"] for c in self.cues]
        return round(max(ends) + GAP, 2)


def _bag_spot(base: int, pos: str) -> Tuple[float, float]:
    """Where a fielder stands to take a throw at ``base`` (a step off the
    bag toward the infield, so the runner and the fielder don't overlap)."""
    x, y = BASE_XY[base]
    if base == 4 or base == 0:
        return 0.0, -2.0
    cx, cy = 0.0, _B
    d = math.hypot(cx - x, cy - y)
    return x + (cx - x) / d * 3.0, y + (cy - y) / d * 3.0


def _coverer(base: int, fielder: str, spray: float = 0.0) -> str:
    """Who takes a throw at ``base`` when ``fielder`` made the play."""
    if base == 1:
        return "P" if fielder == "1B" else "1B"
    if base == 2:
        if fielder in ("SS", "3B"):
            return "2B"
        if fielder in ("1B", "2B"):
            return "SS"
        return "SS" if spray <= 0 else "2B"
    if base == 3:
        return "SS" if fielder == "3B" else "3B"
    return "P" if fielder == "C" else "C"


# --- reading the stored record -------------------------------------------


def _tokens(entry: Dict[str, Any]) -> List[str]:
    return [t for t in str(entry.get("runner_event") or "").split("+") if t]


def _name(players: Dict[str, Any], pid: Optional[str]) -> str:
    if not pid:
        return ""
    info = players.get(pid) or {}
    return str(info.get("name") or pid)


def _last(players: Dict[str, Any], pid: Optional[str]) -> str:
    name = _name(players, pid)
    return name.split()[-1] if name else ""


def _count_after(count: str, entry: Dict[str, Any]) -> str:
    try:
        balls, strikes = (int(v) for v in str(count or "0-0").split("-"))
    except ValueError:
        balls, strikes = 0, 0
    outcome = entry.get("outcome")
    if outcome == "ball":
        balls += 1
    elif outcome in ("strike", "swinging_strike"):
        strikes += 1
    elif outcome == "foul" and strikes < 2:
        strikes += 1
    return f"{min(balls, 4)}-{min(strikes, 3)}"


class _Defense:
    """Who plays where for each side, through the game's substitutions
    (applied by inning: the record has no finer timing)."""

    def __init__(self, replay: Dict[str, Any]) -> None:
        self.base: Dict[str, Dict[str, str]] = {}
        for side in ("away", "home"):
            self.base[side] = {
                str(pid): str(pos) for pid, pos in (replay.get("lineups") or {}).get(side, [])
            }
        subs = replay.get("substitutions") or {}
        self.subs: Dict[str, List[Dict[str, Any]]] = {
            side: list(subs.get(side, []) if isinstance(subs, dict) else [])
            for side in ("away", "home")
        }

    def position_of(self, side: str, pid: Optional[str], inning: int) -> Optional[str]:
        if not pid:
            return None
        where = dict(self.base.get(side, {}))
        for sub in self.subs.get(side, []):
            if int(sub.get("inning") or 0) <= inning:
                where.pop(str(sub.get("out")), None)
                if sub.get("position"):
                    where[str(sub.get("in"))] = str(sub.get("position"))
        pos = where.get(str(pid))
        return pos if pos in SCORING_NUMBER else None


# --- the converter --------------------------------------------------------


def build_plays(replay: Dict[str, Any]) -> Dict[str, Any]:
    """The viewer's document for a stored replay: the game, its field and
    one play per stored entry. Draws nothing; never raises on an entry it
    cannot animate (that play keeps its text and scoreboard, without
    movement)."""
    game = dict(replay.get("game") or {})
    players = dict(replay.get("players") or {})
    entries: List[Dict[str, Any]] = list(replay.get("pitches") or [])
    bases_trace: Dict[str, Dict[str, Any]] = dict(replay.get("bases") or {})
    fielded: Dict[str, str] = dict(replay.get("fielded") or {})
    errors = {int(e.get("i", -1)): e for e in (replay.get("errors") or []) if isinstance(e, dict)}
    defense = _Defense(replay)
    altitude = float(game.get("park_altitude_ft") or 0.0)
    density = ballflight.air_density_ratio(altitude)

    plays: List[Dict[str, Any]] = []
    inning, half, outs = 1, "top", 0
    score = {"away": 0, "home": 0}
    count = "0-0"
    for index, entry in enumerate(entries):
        if entry.get("pa_start"):
            inning = int(entry.get("inning") or inning)
            half = str(entry.get("half") or half)
            outs = int(entry.get("outs_before") or 0)
            count = "0-0"
        batting = "away" if half == "top" else "home"
        fielding = "home" if batting == "away" else "away"
        trace = bases_trace.get(str(index)) or {}
        before = list(trace.get("before") or [None, None, None])
        after = list(trace.get("after") or before)
        scored = list(trace.get("scored") or [])
        batter_id = entry.get("batter_id")
        # A plate appearance ends with a result, or with the batter on base
        # without one (catcher's interference).
        pa_end = bool(entry.get("pa_result")) or bool(
            batter_id and (batter_id in after or batter_id in scored))
        participants = [pid for pid in before if pid]
        if pa_end:
            participants.append(entry.get("batter_id"))
        play_outs = max(0, len(participants) - len([p for p in after if p]) - len(scored))
        outs_after = min(3, outs + play_outs)
        score_after = dict(score)
        score_after[batting] += len(scored)
        count_shown = str(entry.get("count") or count)
        context = {
            "index": index, "entry": entry, "before": before, "after": after,
            "scored": scored, "pa_end": pa_end, "players": players,
            "fielded": fielded.get(str(index)), "error": errors.get(index),
            "density": density, "inning": inning, "fielding": fielding,
            "defense": defense, "outs": outs, "play_outs": play_outs,
        }
        builder = _Builder()
        try:
            text = _animate(builder, context)
        except Exception:  # pragma: no cover - a play it can't draw keeps its text
            builder = _Builder()
            text = _describe_fallback(context)
        injury = entry.get("injury")
        if isinstance(injury, dict) and injury.get("player_id"):
            hurt = _name(players, injury.get("player_id"))
            text += f". {hurt} is hurt ({injury.get('description') or 'injury'})"
            if injury.get("replacement_id"):
                text += f"; {_name(players, injury.get('replacement_id'))} replaces him"
        # A runner replaced on his base finishes the play as his replacement.
        for rec in builder.runners:
            if rec["to"] in (1, 2, 3) and after[rec["to"] - 1] and rec["who"] != after[rec["to"] - 1]:
                rec["replaced"] = rec["who"]
                rec["who"] = after[rec["to"] - 1]
        moved = before != after or bool(scored) or play_outs > 0
        play = {
            "i": index, "inning": inning, "half": half, "batting": batting,
            "outs": outs, "outs_after": outs_after, "count": count_shown,
            "count_after": "0-0" if pa_end else _count_after(count_shown, entry),
            "batter": entry.get("batter_id"), "pitcher": entry.get("pitcher_id"),
            "bases_before": before, "bases_after": after, "scored": scored,
            "score": score_after, "pa_end": pa_end, "key": pa_end or moved,
            "result": entry.get("pa_result") or entry.get("outcome"),
            "text": text, "dur": builder.duration(), "ball": builder.ball,
            "fielders": builder.fielders, "runners": builder.runners,
            "cues": sorted(builder.cues, key=lambda c: c["t"]),
            "throws": builder.throws,
        }
        pitch = _pitch_summary(entry)
        if pitch:
            play["pitch"] = pitch
        plays.append(play)
        outs = outs_after
        score = score_after
        count = play["count_after"]
    fence = _field_fence(game)
    return {
        "schema": SCHEMA,
        "source": replay.get("schema"),
        "game": game,
        "players": players,
        "lineups": replay.get("lineups") or {},
        "final": replay.get("final") or {},
        "field": {
            "fence": {"distances": list(fence.distances), "heights": list(fence.heights),
                      "angles": [-45.0, -22.5, 0.0, 22.5, 45.0]},
            "bases": {str(b): list(BASE_XY[b]) for b in (0, 1, 2, 3)},
            "rubber": list(RUBBER_XY),
            "positions": {pos: [round(x, 2), round(y, 2)] for pos, (x, y) in SPOTS.items()},
        },
        "plays": plays,
    }


def _field_fence(game: Dict[str, Any]) -> ballflight.Fence:
    try:
        found = ballflight._real_fence(str(game.get("park") or ""))
    except Exception:
        found = None
    return found or ballflight.GENERIC_FENCE


def _pitch_summary(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not entry.get("pitch_type"):
        return None
    loc = entry.get("location") or [0.0, 2.5]
    return {
        "type": entry.get("pitch_type"), "mph": entry.get("velocity"),
        "x": loc[0], "z": loc[1], "call": entry.get("outcome"),
        "swing": bool(entry.get("swing")), "in_zone": bool(entry.get("in_zone")),
    }


# --- animating one entry --------------------------------------------------


def _animate(b: _Builder, c: Dict[str, Any]) -> str:
    entry = c["entry"]
    tokens = _tokens(entry)
    outcome = entry.get("outcome")
    t0 = 0.0
    if any(t.startswith("po") for t in tokens):
        t0 = _pickoff(b, c, tokens)
    if outcome == "ibb":
        return _walk(b, c, t0, text=f"{_batter_name(c)} is walked intentionally")
    if outcome == "bunt":
        return _bunt(b, c, tokens, t0)
    t_plate = _pitch(b, entry, t0)
    stole = False
    if any(t[:2] in ("sb", "cs") for t in tokens) and not entry.get("in_play") and not entry.get(
            "strikeout"):
        _steal(b, c, tokens, t0, t_plate)
        stole = True
    if entry.get("in_play"):
        return _in_play(b, c, tokens, t_plate)
    _ball_past_or_caught(b, entry, tokens, t_plate)
    if outcome == "foul":
        return _foul(b, c, t_plate)
    if outcome == "interference" and c["pa_end"]:
        return _walk(b, c, t_plate + 0.3,
                     text=f"{_batter_name(c)} reaches on catcher's interference")
    if outcome == "hbp":
        return _walk(b, c, t_plate, text=f"{_batter_name(c)} is hit by the pitch",
                     start=t_plate + 0.4)
    if entry.get("strikeout"):
        return _strikeout(b, c, tokens, t_plate)
    if c["pa_end"] and entry.get("pa_result") == "bb" and not stole:
        return _walk(b, c, t_plate + 0.3, text=f"{_batter_name(c)} walks")
    if not stole:
        _between_pitch_runners(b, c, tokens, t_plate)
    return _pitch_text(c, tokens)


def _batter_name(c: Dict[str, Any]) -> str:
    return _name(c["players"], c["entry"].get("batter_id")) or "The batter"


def _pitch(b: _Builder, entry: Dict[str, Any], t0: float) -> float:
    loc = entry.get("location") or [0.0, 2.5]
    mph = float(entry.get("velocity") or 88.0)
    flight = RELEASE_Y / (mph * _MPH_FPS)
    b.ball_at(t0, 1.2, RELEASE_Y, RELEASE_Z)
    b.ball_at(t0 + flight, float(loc[0]), 0.5, float(loc[1]))
    b.cue(t0, "pitch", by="P")
    if entry.get("swing"):
        b.cue(t0 + flight - 0.05, "swing")
    return t0 + flight


def _ball_past_or_caught(b: _Builder, entry: Dict[str, Any], tokens: List[str], t: float) -> None:
    if entry.get("outcome") == "foul":
        return
    _t, x, _y, z = b.ball_end()
    if any(tok in ("wp", "pb", "k_wp", "k_pb") for tok in tokens):
        b.ball_at(t + 0.1, x * 0.5, -6.0, 0.5)
        b.ball_at(t + 1.4, x * 2.0, -45.0, 0.0)
        b.fielder_to("C", x * 2.0, -42.0, arrive=t + 2.2, start=t + 0.2)
        b.cue(t + 0.1, "past", by="C", kind="wild pitch" if "wp" in "".join(tokens) else "passed ball")
        return
    if entry.get("outcome") == "hbp":
        return
    b.ball_at(t + 0.05, x * 0.8, -3.5, max(0.5, z * 0.9))
    b.cue(t + 0.05, "catch", by="C")


def _foul(b: _Builder, c: Dict[str, Any], t: float) -> str:
    entry = c["entry"]
    ev = float(entry.get("exit_velo") or 70.0)
    la = float(entry.get("launch_angle") or 20.0)
    spray = float(entry.get("spray_angle") or 60.0)
    dist, hang, _d = ballflight.flight(ev, la, c["density"])
    dist = max(15.0, min(dist, 330.0))
    hang = max(0.4, min(hang, 3.0))
    if abs(spray) <= 45.0:
        spray = 180.0 + spray if la > 40 else (50.0 if spray >= 0 else -50.0)
    _arc(b, t, dist, spray, la, ev, hang, stop=1.0 if la < 10 else 0.8)
    b.cue(t, "contact", foul=True)
    return f"Foul ball, {_count_after(entry.get('count') or '0-0', entry)}"


def _arc(
    b: _Builder, t0: float, dist: float, spray: float, la: float, ev: float,
    hang: float, *, stop: float = 1.0, start_z: float = 3.0, end_z: float = 0.0,
) -> Tuple[float, float, float]:
    """A batted ball in the air from the plate: sampled every ~0.1 s, the
    horizontal speed bleeding off with drag, a parabola of the right apex.
    Ends at ``stop`` of the flight; returns (t, x, y) of the end."""
    v = max(20.0, ev * _MPH_FPS)
    apex = (v * math.sin(math.radians(max(1.0, la)))) ** 2 / (2 * 32.17) * 0.62
    apex = max(2.0, min(apex, 180.0))
    steps = max(2, int(hang * stop / 0.1))
    k = 1.1
    norm = 1.0 - math.exp(-k)
    t = x = y = 0.0
    for i in range(steps + 1):
        f = stop * i / steps
        s = dist * (1.0 - math.exp(-k * f)) / norm
        z = start_z * (1.0 - f) + end_z * f + 4.0 * apex * f * (1.0 - f)
        x, y = _xy(s, spray)
        t = t0 + hang * f
        b.ball_at(t, x, y, z)
    return t, x, y


def _walk(b: _Builder, c: Dict[str, Any], t: float, *, text: str,
          start: Optional[float] = None) -> str:
    entry = c["entry"]
    begin = t if start is None else start
    _move_runners_simply(b, c, begin, speed=WALK_FPS, batter_speed=WALK_FPS)
    scored = c["scored"]
    if scored:
        text += f"; {_names(c, scored)} {'scores' if len(scored) == 1 else 'score'}"
    del entry
    return text


def _move_runners_simply(
    b: _Builder, c: Dict[str, Any], start: float, *, speed: float = RUNNER_FPS,
    batter_speed: float = RUNNER_FPS, outs_at: Optional[Dict[str, Tuple[int, float]]] = None,
) -> None:
    """Every runner from where the trace had him to where it has him after:
    the bases' own record, so the play always ends where the engine did.
    ``outs_at`` gives an out runner's base and the time he is put out."""
    outs_at = outs_at or {}
    for start_base, pid in _participants(c):
        end = _end_base(c, pid)
        role = "batter" if start_base == 0 else "runner"
        go = start + (BATTER_START if role == "batter" and speed == RUNNER_FPS else 0.0)
        if end is None:
            base, when = outs_at.get(pid, (min(start_base + 1, 4), start + 2.0))
            b.run(pid, role, start_base, base, start=go, out_at=base, arrive=when + MARGIN,
                  speed=speed if role == "runner" else batter_speed)
            b.cue(when, "out", who=pid, base=base)
        elif end == start_base:
            b.stay(pid, start_base)
        else:
            rec = b.run(pid, role, start_base, end, start=go,
                        speed=speed if role == "runner" else batter_speed)
            if end == 4:
                b.cue(rec["path"][-1][0], "score", who=pid)


def _participants(c: Dict[str, Any]) -> List[Tuple[int, str]]:
    out = [(base + 1, pid) for base, pid in enumerate(c["before"]) if pid]
    if c["pa_end"] and c["entry"].get("batter_id"):
        out.append((0, c["entry"]["batter_id"]))
    return out


def _end_base(c: Dict[str, Any], pid: str) -> Optional[int]:
    """Where ``pid`` ends the play: 1-3, 4 (scored), or None (out). A
    pinch runner who took his base counts as the runner he replaced."""
    if pid in c["scored"]:
        return 4
    for base, who in enumerate(c["after"]):
        if who == pid:
            return base + 1
    # Replaced on the bases (a pinch runner, or a hurt batter's
    # replacement): someone new on a base. He stands in for the runner who
    # was on that base, else for the batter.
    injury = c["entry"].get("injury")
    if isinstance(injury, dict) and injury.get("player_id") == pid:
        for base, who in enumerate(c["after"]):
            if who and who == injury.get("replacement_id"):
                return base + 1
    known = {p for p in c["before"] if p} | {c["entry"].get("batter_id")}
    strangers = [base for base, who in enumerate(c["after"]) if who and who not in known]
    for base in strangers:
        if c["before"][base] == pid:
            return base + 1
    if c["pa_end"] and pid == c["entry"].get("batter_id"):
        moved_on = set(c["after"]) | set(c["scored"])
        for base in strangers:
            # A base that was empty, or whose runner went on (he is
            # elsewhere now), is the batter's.
            if not c["before"][base] or c["before"][base] in moved_on:
                return base + 1
    return None


def _names(c: Dict[str, Any], pids: Iterable[str]) -> str:
    names = [_name(c["players"], p) for p in pids]
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _pitch_text(c: Dict[str, Any], tokens: List[str]) -> str:
    entry = c["entry"]
    outcome = entry.get("outcome")
    words = {
        "ball": "Ball", "strike": "Called strike", "swinging_strike": "Swinging strike",
        "interference": "Catcher's interference",
    }
    text = words.get(str(outcome), str(outcome or "Pitch").replace("_", " ").capitalize())
    extra = _runner_text(c, tokens)
    count = _count_after(entry.get("count") or "0-0", entry)
    return f"{text}, {count}" + (f". {extra}" if extra else "")


def _runner_text(c: Dict[str, Any], tokens: List[str]) -> str:
    parts = []
    for tok in tokens:
        if tok.startswith("sb"):
            parts.append(f"stolen base ({_base_word(tok[2:])})")
        elif tok.startswith("cs"):
            parts.append(f"caught stealing ({_base_word(tok[2:])})")
        elif tok.startswith("poa"):
            parts.append("pickoff throw")
        elif tok.startswith("po") and tok != "pocs":
            parts.append(f"picked off {_base_word(tok[2:])}")
        elif tok in ("wp", "k_wp"):
            parts.append("wild pitch")
        elif tok in ("pb", "k_pb"):
            parts.append("passed ball")
        elif tok == "balk":
            parts.append("balk")
        elif tok.startswith("pr"):
            parts.append("pinch runner")
    text = "; ".join(parts)
    if c["scored"]:
        text += ("; " if text else "") + f"{_names(c, c['scored'])} scores"
    return text[:1].upper() + text[1:] if text else ""


def _base_word(code: str) -> str:
    return {"1": "first", "2": "second", "3": "third", "h": "home", "H": "home"}.get(code, code)


def _base_num(code: str) -> int:
    return {"1": 1, "2": 2, "3": 3, "h": 4, "H": 4}.get(code, 2)


def _pickoff(b: _Builder, c: Dict[str, Any], tokens: List[str]) -> float:
    """A pickoff throw before the pitch: the pitcher to the bag, the
    runner diving back (or tagged out). Returns when the pitch can start."""
    tok = next(t for t in tokens if t.startswith("po"))
    base = _base_num(tok[-1]) if tok[-1] in "123hH" else 1
    base = min(base, 3)
    cover = {1: "1B", 2: "SS", 3: "3B"}[base]
    b.fielder_to(cover, *_bag_spot(base, cover), arrive=0.5, start=0.0)
    b.ball_at(0.6, *RUBBER_XY, 5.5)
    catch = 0.6 + math.dist(RUBBER_XY, BASE_XY[base]) / 90.0
    b.ball_at(catch, *_bag_spot(base, cover), 2.0)
    b.cue(0.6, "throw", by="P", to=cover, base=base)
    b.cue(catch + 0.1, "tag", by=cover, base=base)
    if tok.startswith("poa") or tok == "pocs":
        b.ball_at(catch + 0.9, *RUBBER_XY, 5.5)
        b.fielder_to(cover, *SPOTS[cover], start=catch + 0.8)
        return catch + 1.6
    return catch + 0.4


def _steal(b: _Builder, c: Dict[str, Any], tokens: List[str], t0: float, t_plate: float) -> None:
    """The stealers run with the pitch; the catcher throws to the bag. An
    out's throw beats the runner by MARGIN, a safe runner beats it."""
    entry = c["entry"]
    outs_at: Dict[str, Tuple[int, float]] = {}
    throw_base = None
    caught = False
    for tok in tokens:
        if tok[:2] in ("sb", "cs") and len(tok) == 3:
            throw_base = _base_num(tok[2])
            caught = tok.startswith("cs")
    if throw_base is None:
        _between_pitch_runners(b, c, tokens, t_plate)
        return
    stealer = c["before"][throw_base - 2] if 2 <= throw_base <= 4 else None
    run_time = 90.0 / RUNNER_FPS + STEAL_LEAD
    safe_arrive = t0 - STEAL_LEAD + run_time
    release = t_plate + 0.1 + 0.6
    cover = "C" if throw_base == 4 else ("SS" if throw_base == 2 else "3B")
    if throw_base == 4:
        cover = "C"
    if caught:
        catch = b.throw("C", cover if cover != "C" else "P", throw_base if throw_base < 4 else 4,
                        release=release, speed=125.0)
        if stealer:
            outs_at[stealer] = (throw_base, catch + 0.05)
        b.cue(catch + 0.05, "tag", by=cover, base=throw_base)
    else:
        catch = b.throw("C", cover if cover != "C" else "P", throw_base if throw_base < 4 else 4,
                        release=release, speed=125.0, not_before=safe_arrive + MARGIN)
        b.cue(catch, "safe", who=stealer, base=throw_base)
    del entry
    _move_runners_simply(b, c, t0 - STEAL_LEAD, outs_at=outs_at)


def _between_pitch_runners(b: _Builder, c: Dict[str, Any], tokens: List[str], t: float) -> None:
    """Runners who move on a wild pitch, passed ball or balk (or anything
    else between pitches): they go when the ball gets away."""
    if c["before"] == c["after"] and not c["scored"]:
        for base, pid in enumerate(c["before"]):
            if pid:
                b.stay(pid, base + 1)
        return
    if "balk" in tokens:
        b.cue(t - 0.3, "balk")
    _move_runners_simply(b, c, t + 0.2)


def _strikeout(b: _Builder, c: Dict[str, Any], tokens: List[str], t: float) -> str:
    entry = c["entry"]
    kind = entry.get("strikeout_type") or ("swinging" if entry.get("swing") else "called")
    name = _name(c["players"], entry.get("batter_id"))
    b.cue(t + 0.1, "strikeout", kind=kind)
    verb = "is called out on strikes" if kind == "called" else "strikes out swinging"
    if entry.get("k_reached") or any(tok in ("k_wp", "k_pb") for tok in tokens):
        _move_runners_simply(b, c, t + 0.3)
        return f"{name} strikes out but reaches on a dropped third strike"
    outs_at: Dict[str, Tuple[int, float]] = {}
    batter = entry.get("batter_id")
    if batter:
        outs_at[batter] = (0, t + 0.1)
    for tok in tokens:
        if tok.startswith("cs") and len(tok) == 3:
            base = _base_num(tok[2])
            cover = "SS" if base == 2 else ("3B" if base == 3 else "P")
            catch = b.throw("C", cover, base, release=t + 0.6, speed=125.0)
            stealer = c["before"][base - 2] if 2 <= base <= 4 else None
            if stealer:
                outs_at[stealer] = (base, catch + 0.05)
    for start_base, pid in _participants(c):
        if pid == batter:
            b.cue(t + 0.1, "out", who=pid, base=0)
            continue
        end = _end_base(c, pid)
        if end is None:
            base, when = outs_at.get(pid, (start_base + 1, t + 2.0))
            b.run(pid, "runner", start_base, base, start=t - STEAL_LEAD - 0.4,
                  out_at=base, arrive=when + MARGIN)
            b.cue(when, "out", who=pid, base=base)
        elif end == start_base:
            b.stay(pid, start_base)
        else:
            b.run(pid, "runner", start_base, end, start=t - STEAL_LEAD - 0.4)
    extra = _runner_text(c, [tok for tok in tokens if tok.startswith(("sb", "cs"))])
    return f"{name} {verb}" + (f". {extra}" if extra else "")


def _bunt(b: _Builder, c: Dict[str, Any], tokens: List[str], t0: float) -> str:
    """A bunt (stored without a pitch): a soft roller up the line, the
    pitcher or a corner fielder throws to first unless it is a hit."""
    entry = c["entry"]
    t_plate = _pitch(b, {"velocity": 88.0, "location": [0.0, 2.6], "swing": True}, t0)
    spray = -22.0 if c["before"][1] else 18.0
    spot = _xy(42.0, spray)
    b.ball_at(t_plate + 0.15, *_xy(8.0, spray), 0.5)
    b.ball_at(t_plate + 1.6, spot[0], spot[1], 0.0)
    fielder = "3B" if spray < 0 else "1B"
    if "bunt_hit" not in tokens:
        fielder = "P"
    t_field = b.fielder_to(fielder, spot[0], spot[1] + 1.5, arrive=t_plate + 1.7, start=t_plate)
    b.cue(t_field, "field", by=fielder)
    name = _name(c["players"], entry.get("batter_id"))
    batter = entry.get("batter_id")
    outs_at: Dict[str, Tuple[int, float]] = {}
    if "bunt_hit" in tokens:
        text = f"{name} bunts for a hit"
    else:
        cover = "2B" if fielder == "1B" else "1B"
        catch = b.throw(fielder, cover, 1, release=t_field + EXCHANGE)
        if batter and _end_base(c, batter) is None:
            outs_at[batter] = (1, catch)
        text = f"{name} sacrifice bunt" if "sac" in tokens else f"{name} bunts out"
        lead = [pid for base, pid in _participants(c) if base and _end_base(c, pid) is None]
        if lead:
            text = f"{name} bunts; {_names(c, lead)} out"
    _move_runners_simply(b, c, t_plate, outs_at=outs_at)
    if c["scored"]:
        text += f"; {_names(c, c['scored'])} scores"
    return text


# --- balls in play --------------------------------------------------------


def _in_play(b: _Builder, c: Dict[str, Any], tokens: List[str], t: float) -> str:
    entry = c["entry"]
    b.cue(t, "contact")
    ev = float(entry.get("exit_velo") or 80.0)
    la = float(entry.get("launch_angle") or 10.0)
    spray = max(-45.0, min(45.0, float(entry.get("spray_angle") or 0.0)))
    dist = float(entry.get("distance") or 0.0)
    result = entry.get("pa_result")
    ground = entry.get("ball_type") == "gb" or (la < 10.0 and dist < 120.0)
    if result == "hr":
        return _home_run(b, c, t, ev, la, spray, dist)
    if ground:
        return _ground_ball(b, c, tokens, t, ev, la, spray, dist)
    return _air_ball(b, c, tokens, t, ev, la, spray, dist)


def _hang(ev: float, la: float, dist: float, density: float) -> float:
    carry, hang, _descent = ballflight.flight(ev, la, density)
    scale = dist / carry if carry > 1.0 else 1.0
    return max(0.35, min(7.5, hang * math.sqrt(max(scale, 0.05))))


def _home_run(b: _Builder, c: Dict[str, Any], t: float, ev: float, la: float,
              spray: float, dist: float) -> str:
    hang = _hang(ev, la, dist, c["density"])
    land_t, x, y = _arc(b, t, max(dist, 340.0), spray, la, ev, hang)
    of = min(("LF", "CF", "RF"), key=lambda p: math.dist(SPOTS[p], (x, y)))
    wall = _xy(min(math.hypot(x, y), 395.0) * 0.93, spray)
    b.fielder_to(of, *wall, start=t + REACT, speed=OF_RUN_FPS)
    b.cue(land_t, "home_run")
    for start_base, pid in _participants(c):
        b.run(pid, "batter" if start_base == 0 else "runner", start_base, 4,
              start=t + (0.8 if start_base == 0 else 0.5), speed=TROT_FPS)
        b.cue(b.runners[-1]["path"][-1][0], "score", who=pid)
    name = _name(c["players"], c["entry"].get("batter_id"))
    runs = len(c["scored"])
    kind = {1: "solo home run", 2: "two-run home run", 3: "three-run home run",
            4: "grand slam"}.get(runs, "home run")
    side = _side_word(spray)
    return f"{name} hits a {kind} to {side} ({int(round(dist))} ft)"


def _side_word(spray: float) -> str:
    if spray <= -30:
        return "left"
    if spray <= -12:
        return "left-center" if spray > -22 else "left"
    if spray < 12:
        return "center"
    if spray < 30:
        return "right-center" if spray < 22 else "right"
    return "right"


def _infield_spot(pos: str) -> Tuple[float, float]:
    depth, angle = ballflight.INFIELD_SPOTS.get(pos, (120.0, 0.0))
    return depth, angle


def _out_runners(c: Dict[str, Any]) -> List[Tuple[int, str]]:
    """Runners (and the batter) put out on this play, lead runner first."""
    outs = [(base, pid) for base, pid in _participants(c) if _end_base(c, pid) is None]
    return sorted(outs, key=lambda item: -item[0])


def _ground_ball(b: _Builder, c: Dict[str, Any], tokens: List[str], t: float,
                 ev: float, la: float, spray: float, dist: float) -> str:
    entry = c["entry"]
    v0x = max(15.0, ev * _MPH_FPS * math.cos(math.radians(la)))
    roll = max(20.0, v0x * 0.95 * math.exp(-max(0.0, -la - 5.0) / 45.0))
    bounce = max(4.0, min(dist, 60.0))
    t_bounce = t + bounce / v0x
    b.ball_at(t_bounce, *_xy(bounce, spray), 0.0)
    result = entry.get("pa_result")
    fielder = c["fielded"] if c["fielded"] in SCORING_NUMBER else None
    out_runners = _out_runners(c)
    name = _name(c["players"], entry.get("batter_id"))
    batter = entry.get("batter_id")
    hit = result in ("1b", "2b", "3b")
    if hit and not entry.get("infield_hit"):
        return _ball_through(b, c, t, t_bounce, bounce, roll, spray, ev, result)
    if fielder is None or fielder in ("LF", "CF", "RF"):
        fielder = _nearest_infielder(spray)
    depth, angle = _infield_spot(fielder)
    off = math.radians(spray - angle)
    along = max(bounce + 5.0, depth * math.cos(off))
    charge = 17.0
    t_field_rel = (along + charge * REACT) / (roll + charge)
    spot_r = max(30.0, along - charge * max(0.0, t_field_rel - REACT))
    if fielder == "P":
        spot_r = max(bounce + 2.0, min(spot_r, 58.0))
    if fielder == "C":
        spot_r = max(5.0, min(spot_r, 25.0))
    spot = _xy(spot_r, spray)
    t_field = max(t_bounce + 0.05, t + (spot_r - bounce) / roll + bounce / v0x)
    b.ball_at(t_field, spot[0], spot[1], 0.3)
    b.fielder_to(fielder, spot[0], spot[1], arrive=t_field, start=t + REACT)
    b.cue(t_field, "field", by=fielder)
    error = c["error"]
    outs_at: Dict[str, Tuple[int, float]] = {}
    chain: List[str] = [fielder]
    holder, release = fielder, t_field + EXCHANGE
    batter_natural = t + BATTER_START + HOME_TO_FIRST
    for base_from, pid in out_runners:
        base = 1 if base_from == 0 else min(4, base_from + 1)
        cover = _coverer(base, holder, spray)
        if cover == holder or (holder == "1B" and base == 1 and spot_r < 140 and spray > 15):
            cover = holder
        catch = b.throw(holder, cover, base, release=release)
        outs_at[pid] = (base, catch)
        if cover != holder:
            chain.append(cover)
        b.cue(catch, "out", who=pid, base=base)
        holder, release = cover, catch + PIVOT
    batter_safe = batter and _end_base(c, batter) == 1 and c["pa_end"]
    if batter_safe and (entry.get("infield_hit") or "fc" in tokens or "fc_home" in tokens
                        or entry.get("reached_on_error")):
        if not out_runners:
            cover = _coverer(1, holder, spray)
            b.throw(holder, cover, 1, release=release,
                    not_before=batter_natural + MARGIN + (0.25 if entry.get("reached_on_error") else 0.0))
            b.cue(batter_natural, "safe", who=batter, base=1)
    if error:
        b.cue(t_field + 0.2, "error", by=error.get("pos") or fielder)
    _place_runners(b, c, t, outs_at, out_cues=False)
    return _ground_text(c, tokens, name, fielder, chain, out_runners, result)


def _nearest_infielder(spray: float) -> str:
    return min(("3B", "SS", "2B", "1B"),
               key=lambda p: abs(ballflight.INFIELD_SPOTS[p][1] - spray))


def _ball_through(b: _Builder, c: Dict[str, Any], t: float, t_bounce: float,
                  bounce: float, roll: float, spray: float, ev: float, result: str) -> str:
    """A ground ball through the infield: it rolls to the outfield, the
    nearest outfielder picks it up and throws it in after the runners."""
    reach = 300.0 if result != "1b" and abs(spray) > 35 else 225.0
    pick = _xy(reach, spray)
    of = min(("LF", "CF", "RF"), key=lambda p: math.dist(SPOTS[p], pick))
    avg_roll = max(40.0, roll * 0.65)
    t_pick = t_bounce + (reach - bounce) / avg_roll
    b.ball_at(t_pick, pick[0], pick[1], 0.0)
    b.fielder_to(of, pick[0], pick[1], arrive=t_pick, start=t + REACT, speed=OF_RUN_FPS)
    b.cue(t_pick, "field", by=of)
    ends = _place_runners(b, c, t, {}, out_cues=True)
    _throw_in(b, c, of, t_pick + EXCHANGE, ends, spray)
    name = _name(c["players"], c["entry"].get("batter_id"))
    word = {"1b": "singles", "2b": "doubles", "3b": "triples"}.get(result, "hits")
    text = f"{name} {word} on a ground ball to {POSITION_NAME[of]}"
    return text + _scored_text(c)


def _air_ball(b: _Builder, c: Dict[str, Any], tokens: List[str], t: float,
              ev: float, la: float, spray: float, dist: float) -> str:
    entry = c["entry"]
    result = entry.get("pa_result")
    hang = _hang(ev, la, dist, c["density"])
    land = _xy(dist, spray)
    fielder = c["fielded"] if c["fielded"] in SCORING_NUMBER else None
    batter = entry.get("batter_id")
    name = _name(c["players"], batter)
    caught = batter is not None and c["pa_end"] and _end_base(c, batter) is None and result in (
        "out", "sf", "sh")
    if entry.get("foul_out_fielder"):
        fielder = c["defense"].position_of(c["fielding"], entry.get("foul_out_fielder"),
                                           c["inning"]) or fielder
    if caught:
        if fielder is None:
            fielder = min(SPOTS, key=lambda p: math.dist(SPOTS[p], land) if p != "P" else 1e9)
        liner = entry.get("out_type") == "lineout" and fielder in ("1B", "2B", "3B", "SS", "P")
        if liner:
            depth, _angle = _infield_spot(fielder)
            catch_r = min(dist, depth)
            frac = catch_r / max(dist, 1.0)
            catch_t, x, y = _arc(b, t, dist, spray, la, ev, hang, stop=max(0.08, frac ** 1.1),
                                 end_z=0.0)
        else:
            catch_t, x, y = _arc(b, t, dist, spray, la, ev, hang, stop=0.97)
        speed = OF_RUN_FPS if fielder in ("LF", "CF", "RF") else IF_RUN_FPS
        b.fielder_to(fielder, x, y, arrive=catch_t, start=t + REACT, speed=speed)
        b.cue(catch_t, "catch", by=fielder)
        b.cue(catch_t, "out", who=batter, base=0)
        outs_at: Dict[str, Tuple[int, float]] = {batter: (0, catch_t)}
        _tag_ups(b, c, tokens, fielder, catch_t, outs_at)
        kind = {"lineout": "lines out", "flyout": "flies out"}.get(
            str(entry.get("out_type")), "pops out" if entry.get("ball_type") == "pu" else "flies out")
        if entry.get("ball_type") == "pu" and fielder not in ("LF", "CF", "RF"):
            kind = "pops out"
        if entry.get("foul_out_fielder"):
            kind = "fouls out"
        text = f"{name} {kind} to {POSITION_NAME.get(fielder, fielder)}"
        if result == "sf":
            text = f"{name} hits a sacrifice fly to {POSITION_NAME.get(fielder, fielder)}"
        doubled = [pid for base, pid in _participants(c) if base and _end_base(c, pid) is None]
        if doubled:
            text += f"; {_names(c, doubled)} doubled off"
        return text + _scored_text(c)
    # A hit (or an error) in the air: it lands, an outfielder chases it down.
    land_t, x, y = _arc(b, t, dist, spray, la, ev, hang)
    roll = 18.0 if dist < 300 else 8.0
    rx, ry = _xy(dist + roll, spray)
    b.ball_at(land_t + 0.7, rx, ry, 0.0)
    of = min(("LF", "CF", "RF"), key=lambda p: math.dist(SPOTS[p], (x, y)))
    if dist < 200 and fielder in ("1B", "2B", "3B", "SS"):
        of = fielder
    t_pick = max(land_t + 0.7, t + REACT + math.dist(SPOTS[of], (rx, ry)) / OF_RUN_FPS)
    b.ball_at(t_pick, rx, ry, 0.0)
    b.fielder_to(of, rx, ry, arrive=t_pick, start=t + REACT, speed=OF_RUN_FPS)
    b.cue(t_pick, "field", by=of)
    if c["error"]:
        b.cue(land_t, "error", by=c["error"].get("pos") or of)
    ends = _place_runners(b, c, t, {}, out_cues=True)
    _throw_in(b, c, of, t_pick + EXCHANGE, ends, spray)
    word = {"1b": "singles", "2b": "doubles", "3b": "triples"}.get(str(result), "reaches")
    if entry.get("reached_on_error") or (result == "out" and batter and _end_base(c, batter)):
        text = f"{name} reaches on an error by the {POSITION_NAME.get(of, of)}"
    else:
        text = f"{name} {word} to {_side_word(spray)} field"
    return text + _scored_text(c)


def _tag_ups(b: _Builder, c: Dict[str, Any], tokens: List[str], fielder: str,
             catch_t: float, outs_at: Dict[str, Tuple[int, float]]) -> None:
    """Runners after a catch: they tag and go (scoring, advancing or thrown
    out), hold, or are doubled off their base."""
    entry = c["entry"]
    batter = entry.get("batter_id")
    holder = fielder
    for start_base, pid in sorted(_participants(c), key=lambda item: -item[0]):
        if pid == batter:
            continue
        end = _end_base(c, pid)
        if end == start_base:
            b.stay(pid, start_base)
            continue
        if end is None:
            tag = entry.get("tag3") or entry.get("tag2") or {}
            tagging_out = isinstance(tag, dict) and tag.get("runner") == pid and tag.get(
                "result") == "out"
            if tagging_out:
                base = min(4, start_base + 1)
                cover = _coverer(base, holder)
                catch = b.throw(holder, cover, base, release=catch_t + EXCHANGE,
                                speed=OF_THROW_FPS)
                b.run(pid, "runner", start_base, base, start=catch_t, out_at=base,
                      arrive=catch + MARGIN)
                b.cue(catch, "out", who=pid, base=base)
            else:
                # Doubled off: he went on contact and can't get back.
                cover = {1: "1B", 2: "SS", 3: "3B"}.get(start_base, "1B")
                catch = b.throw(holder, cover, start_base, release=catch_t + EXCHANGE,
                                speed=OF_THROW_FPS if holder in FIELD_SIDE else IF_THROW_FPS)
                rec = b.run(pid, "runner", start_base, start_base, start=0.0)
                rec["to"], rec["out_at"] = 0, start_base
                x0, y0 = BASE_XY[start_base]
                nx, ny = BASE_XY[min(4, start_base + 1)]
                mid = (x0 + (nx - x0) * 0.3, y0 + (ny - y0) * 0.3)
                rec["path"] = [[0.0, round(x0, 2), round(y0, 2)],
                               [round(catch_t, 3), round(mid[0], 2), round(mid[1], 2)],
                               [round(catch + MARGIN, 3), round(x0 + (mid[0] - x0) * 0.2, 2),
                                round(y0 + (mid[1] - y0) * 0.2, 2)]]
                b.cue(catch, "out", who=pid, base=start_base)
            holder = cover
            continue
        # Tags and advances: leaves on the catch, beats any throw.
        rec = b.run(pid, "runner", start_base, end, start=catch_t)
        arrive = rec["path"][-1][0]
        if end == 4:
            b.cue(arrive, "score", who=pid)
        if fielder in FIELD_SIDE and end >= 3:
            cover = _coverer(end, fielder)
            b.throw(fielder, cover, end, release=catch_t + EXCHANGE, speed=OF_THROW_FPS,
                    not_before=arrive + MARGIN)
            b.cue(arrive, "safe", who=pid, base=end)
    del outs_at


def _place_runners(b: _Builder, c: Dict[str, Any], t: float,
                   outs_at: Dict[str, Tuple[int, float]], *, out_cues: bool) -> Dict[str, Tuple[int, float]]:
    """Every runner and the batter from the bases trace, leaving on contact.
    Returns ``{pid: (end base, arrival time)}``; outs put out at their
    ``outs_at`` time (or, on a hit, thrown out at the next base)."""
    ends: Dict[str, Tuple[int, float]] = {}
    for start_base, pid in _participants(c):
        end = _end_base(c, pid)
        role = "batter" if start_base == 0 else "runner"
        go = t + (BATTER_START if role == "batter" else 0.05)
        speed = 90.0 / HOME_TO_FIRST if role == "batter" else RUNNER_FPS
        if end is None:
            base, when = outs_at.get(pid, (None, None))  # type: ignore[assignment]
            if base is None:
                base = _out_base_on_hit(c, pid, start_base)
                when = go + 90.0 * max(1, base - start_base) / speed
                ends[pid] = (-base, when)
                b.run(pid, role, start_base, base, start=go, out_at=base, short=4.0,
                      speed=speed)
                if out_cues:
                    b.cue(when, "out", who=pid, base=base)
                continue
            b.run(pid, role, start_base, base, start=go, out_at=base,
                  arrive=when + MARGIN, speed=speed)
            ends[pid] = (-base, when)
            continue
        if end == start_base:
            b.stay(pid, start_base)
            ends[pid] = (end, 0.0)
            continue
        rec = b.run(pid, role, start_base, end, start=go, speed=speed)
        arrive = rec["path"][-1][0]
        ends[pid] = (end, arrive)
        if end == 4:
            b.cue(arrive, "score", who=pid)
    return ends


def _out_base_on_hit(c: Dict[str, Any], pid: str, start_base: int) -> int:
    tokens = _tokens(c["entry"])
    if "oobH" in tokens and start_base >= 1:
        return 4
    if "oob3" in tokens and start_base in (1, 2):
        return 3
    if start_base == 0:
        return 2
    return min(4, start_base + 2) if start_base == 1 else min(4, start_base + 1)


def _throw_in(b: _Builder, c: Dict[str, Any], of: str, release: float,
              ends: Dict[str, Tuple[int, float]], spray: float) -> None:
    """The outfielder's throw: at a runner he puts out (beating him), else
    to the base the lead runner stopped at, after everyone is in."""
    outs = [(pid, -base, when) for pid, (base, when) in ends.items() if base < 0]
    if outs:
        holder = of
        for pid, base, when in sorted(outs, key=lambda item: item[2]):
            cover = _coverer(base, holder, spray)
            catch = b.throw(holder, cover, base, release=release, speed=OF_THROW_FPS)
            # The runner is put out when the ball gets there: retime him.
            for rec in b.runners:
                if rec["who"] == pid and rec.get("out_at") == base:
                    _retime_end(rec, catch + MARGIN)
            b.cue(catch, "tag", by=cover, base=base)
            for cue in b.cues:
                if cue.get("type") == "out" and cue.get("who") == pid:
                    cue["t"] = round(catch, 3)
            holder, release = cover, catch + PIVOT
        return
    standing = [(base, when) for base, when in ends.values() if 1 <= base <= 3]
    if not standing:
        target, last = 2, max([w for _b, w in ends.values()] or [release])
    else:
        target = max(base for base, _w in standing)
        last = max(when for _b, when in ends.values())
    cover = _coverer(target, of, spray)
    b.throw(of, cover, target, release=release, speed=OF_THROW_FPS,
            not_before=last + MARGIN)


def _retime_end(rec: Dict[str, Any], end: float) -> None:
    """Stretch (or squeeze) a runner's path so its last point is ``end``."""
    path = rec["path"]
    start = path[0][0]
    old = path[-1][0]
    if old <= start:
        path[-1][0] = round(end, 3)
        return
    for point in path[1:]:
        point[0] = round(start + (point[0] - start) * (end - start) / (old - start), 3)


def _scored_text(c: Dict[str, Any]) -> str:
    if not c["scored"]:
        return ""
    verb = "scores" if len(c["scored"]) == 1 else "score"
    return f"; {_names(c, c['scored'])} {verb}"


def _ground_text(c: Dict[str, Any], tokens: List[str], name: str, fielder: str,
                 chain: Sequence[str], out_runners: Sequence[Tuple[int, str]],
                 result: Optional[str]) -> str:
    entry = c["entry"]
    numbers = "-".join(SCORING_NUMBER.get(p, p) for p in chain)
    if result in ("1b", "2b") and entry.get("infield_hit"):
        return f"{name} beats it out for an infield single to {POSITION_NAME[fielder]}" + _scored_text(c)
    if entry.get("reached_on_error") or c["error"]:
        err = c["error"] or {}
        pos = err.get("pos") or fielder
        return f"{name} reaches on an error by the {POSITION_NAME.get(pos, pos)}" + _scored_text(c)
    if "tp" in tokens:
        return f"{name} hits into a triple play, {numbers}" + _scored_text(c)
    if len(out_runners) >= 2 or any(t.startswith("dp") for t in tokens):
        return f"{name} grounds into a double play, {numbers}" + _scored_text(c)
    batter = entry.get("batter_id")
    if out_runners and all(pid != batter for _b, pid in out_runners):
        lead = _names(c, [pid for _b, pid in out_runners])
        return f"{name} reaches on a fielder's choice; {lead} out, {numbers}" + _scored_text(c)
    if len(chain) == 1:
        return f"{name} grounds out to {POSITION_NAME[fielder]} unassisted" + _scored_text(c)
    return f"{name} grounds out, {numbers}" + _scored_text(c)


def _describe_fallback(c: Dict[str, Any]) -> str:
    entry = c["entry"]
    name = _name(c["players"], entry.get("batter_id"))
    result = entry.get("pa_result") or entry.get("outcome") or "pitch"
    return f"{name}: {str(result).replace('_', ' ')}"


# --- the checker ------------------------------------------------------------


def _position_at(path: Sequence[Sequence[float]], t: float) -> Tuple[float, float]:
    if t <= path[0][0]:
        return path[0][1], path[0][2]
    for (t0, x0, y0), (t1, x1, y1) in zip(path, path[1:]):
        if t <= t1:
            f = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
    return path[-1][1], path[-1][2]


def check_plays(doc: Dict[str, Any]) -> List[str]:
    """Problems with a plays document (empty when it is sound):

    - every runner ends where the engine put him (bases after, scored,
      out), and the plays' outs and runs add up to each half-inning's and
      the final score;
    - every out made by a throw: the ball is there before the runner;
    - every safe runner: he is there before any throw to that base;
    - every path's times run forward.
    """
    problems: List[str] = []
    plays = doc.get("plays") or []
    for play in plays:
        i = play["i"]
        ended: Dict[int, str] = {}
        scored = []
        for rec in play["runners"]:
            times = [p[0] for p in rec["path"]]
            if times != sorted(times):
                problems.append(f"{i}: {rec['who']}'s path runs backward in time")
            if rec["to"] == 4:
                scored.append(rec["who"])
            elif rec["to"] in (1, 2, 3):
                ended[rec["to"]] = rec["who"]
        after = {b + 1: pid for b, pid in enumerate(play["bases_after"]) if pid}
        if play["runners"] and ended != after:
            problems.append(f"{i}: runners end at {ended}, the engine has {after}")
        if play["runners"] and sorted(scored) != sorted(play["scored"]):
            problems.append(f"{i}: scored {scored}, the engine has {play['scored']}")
        for pos, path in play["fielders"].items():
            times = [p[0] for p in path]
            if times != sorted(times):
                problems.append(f"{i}: the {pos}'s path runs backward in time")
        times = [p[0] for p in play["ball"]]
        if times != sorted(times):
            problems.append(f"{i}: the ball's path runs backward in time")
        outs_cued = {c.get("who") for c in play["cues"] if c["type"] == "out"}
        for rec in play["runners"]:
            if rec["to"] == 0 and rec["who"] not in outs_cued:
                problems.append(f"{i}: {rec['who']} is out without an out cue")
        for cue in play["cues"]:
            if cue["type"] != "out" or not cue.get("base"):
                continue
            rec = next((r for r in play["runners"] if r["who"] == cue.get("who")), None)
            if rec is None or rec.get("out_at") is None:
                continue
            if rec["path"][-1][0] + 1e-6 < cue["t"]:
                problems.append(
                    f"{i}: {rec['who']} reaches base {cue['base']} at {rec['path'][-1][0]} "
                    f"before the out at {cue['t']}")
        for rec in play["runners"]:
            if rec["to"] not in (1, 2, 3, 4) or rec["to"] == rec["from"]:
                continue
            arrive = rec["path"][-1][0]
            for throw in play.get("throws", []):
                if throw.get("base") == rec["to"] and arrive - MARGIN / 2 < throw["t"] < arrive + MARGIN / 2:
                    problems.append(f"{i}: {rec['who']} (safe at {rec['to']}) and the throw "
                                    f"there tie at {arrive}")
                if (throw.get("base") == rec["to"] and throw["t"] < arrive - MARGIN / 2
                        and not _throw_for_other_out(play, throw)):
                    problems.append(f"{i}: the throw beats {rec['who']} to base {rec['to']} "
                                    f"({throw['t']} < {arrive}) but he is safe")
    problems.extend(_check_totals(doc))
    return problems


def _throw_for_other_out(play: Dict[str, Any], throw: Dict[str, Any]) -> bool:
    """True when ``throw`` put somebody out (a force or tag at its base at
    its time), so a later runner reaching that base is not beaten by it."""
    for cue in play["cues"]:
        if cue["type"] == "out" and cue.get("base") == throw.get("base") and abs(
                cue["t"] - throw["t"]) < 0.3:
            return True
    return False


def _check_totals(doc: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    plays = doc.get("plays") or []
    final = (doc.get("final") or {}).get("score")
    if plays and final:
        last = plays[-1]["score"]
        if {k: int(v) for k, v in last.items()} != {k: int(final[k]) for k in ("away", "home")}:
            problems.append(f"final score {last} != the engine's {final}")
    for prev, nxt in zip(plays, plays[1:]):
        same_half = prev["inning"] == nxt["inning"] and prev["half"] == nxt["half"]
        if same_half and prev["outs_after"] != nxt["outs"]:
            problems.append(f"{nxt['i']}: starts with {nxt['outs']} outs, the plays made "
                            f"{prev['outs_after']}")
        if not same_half and prev["outs_after"] != 3:
            problems.append(f"{prev['i']}: the half ends with {prev['outs_after']} outs")
    return problems
