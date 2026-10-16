"""Release 6b (engine generation 7, "the ball flies right"): ball flight.

Everything here is read only by the switches of the ball-flight step and
draws no random number; with every switch off (every generation up to 6)
nothing in this module is called.

Carry with drag (``carry_model`` 1, RELEASE6_PLAN section 3)
-------------------------------------------------------------
A batted ball is a point mass with drag and lift (backspin from its launch
angle, after Alan Nathan's trajectory calculator; topped balls carry
topspin), launched 3 ft above the plate. :func:`trajectory` integrates it;
the result is precomputed into a table of carry (ft to where it lands, or
first bounces), hang time (s) and descent angle (degrees below the
horizontal at landing) on a 2 mph x 1 degree grid, at sea-level air and at
Coors Field's air (``THIN_AIR_DENSITY``). The table is a file in the package
(``carry_table.json``, rebuilt by ``scripts/build_carry_table.py``), read
once, and looked up bilinearly (:func:`flight`); a park's air is a linear
blend of the two layers (:func:`park_density`).

The carry a game uses is the table's times ``bb6_carry_scale`` (the hang
time times its square root). ``hr_scale``, ``park_factor_scale``,
``altitude_ft_scale``, ``altitude_scale`` and ``park_size_scale`` are not
read under the model.

Fences
------
Five points (LF line, left-centre, centre, right-centre, RF line, at -45,
-22.5, 0, 22.5 and 45 degrees of the PHYSICAL spray angle, positive toward
right field) with their wall heights, read from ``data/parks/
ParkFences.csv`` (generation 7's own file, owner decision 20), else from
the park's ``ParkConfig.csv`` row (:func:`utils.park_utils
.park_fence_for_name`); straight lines between them. A ball leaves the
park when its carry passes the fence plus the wall's height over the
tangent of its descent angle (the ball is that high that far before it
lands). A club with no real park plays in the generic park, the mean of
the 30 home parks of 2026 (``GENERIC_FENCE``, recomputed from the file by
the tests). Each real park's two sides can be moved out or in
(``bb6_park_fence_shift_left_ft`` / ``_right_ft``): owner decisions 18 and
20, each park's home runs fitted BY BATTER SIDE to Baseball Savant's
factors (``data/parks/ParkHRTargets.csv``) by
``scripts/fit_park_hr_factors.py``. Singles, doubles and triples are left
to each park's real shape.
"""

from __future__ import annotations

import functools
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

__all__ = [
    "CARRY_TABLE_FILE",
    "CURRENT_PARK_IDS",
    "EV_GRID",
    "Fence",
    "GENERIC_FENCE",
    "LA_GRID",
    "THIN_AIR_DENSITY",
    "air_density_ratio",
    "build_carry_table",
    "carry",
    "carry_model_on",
    "fence_at",
    "flight",
    "home_run_fence",
    "park_density",
    "park_fence",
    "real_park_on_generation7",
    "trajectory",
]

CARRY_TABLE_FILE = Path(__file__).resolve().parent / "carry_table.json"
# The table's grid: exit velocity (mph) and launch angle (degrees).
EV_GRID: Tuple[float, float, float] = (30.0, 126.0, 2.0)
LA_GRID: Tuple[float, float, float] = (-10.0, 80.0, 1.0)
# Air density of the table's second layer, against sea level: the standard
# atmosphere at Coors Field (5,197 ft).
THIN_AIR_DENSITY = 0.857
# Drag constant at sea-level density (1/ft): 0.5 * rho * A / m for a
# baseball, in the trajectory's units.
_DRAG_K0 = 0.005379
_GRAVITY = 32.174
_MPH_TO_FPS = 1.4667
_BALL_RADIUS_FT = 1.45 / 12.0
_RELEASE_HEIGHT_FT = 3.0


def carry_model_on(tuning: Any) -> bool:
    """``carry_model`` 1: the drag table, the five-point fence."""
    return tuning.get("carry_model", 0.0) >= 0.5


# --- the trajectory ---------------------------------------------------------------


def trajectory(
    exit_velo: float,
    launch_angle: float,
    density: float = 1.0,
    *,
    release_height: float = _RELEASE_HEIGHT_FT,
    dt: float = 0.004,
) -> Tuple[float, float, float]:
    """``(carry ft, hang s, descent angle deg)`` of a batted ball.

    A point mass with drag and lift. Backspin grows with launch angle
    (``-763 + 120 * LA`` rpm, held to -1,500..3,200: a topped ball spins
    forward), the drag coefficient with spin, the lift coefficient with
    the spin factor. Euler steps of ``dt``; the landing point is
    interpolated to the ground. Draws nothing.
    """
    v = exit_velo * _MPH_TO_FPS
    theta = math.radians(launch_angle)
    vx, vy = v * math.cos(theta), v * math.sin(theta)
    x, y, t = 0.0, release_height, 0.0
    spin = max(-1500.0, min(3200.0, -763.0 + 120.0 * launch_angle))
    omega = spin * 2.0 * math.pi / 60.0
    k = _DRAG_K0 * density
    cd = 0.3008 + 0.0292 * abs(spin) / 1000.0
    while True:
        speed = math.hypot(vx, vy)
        s = abs(_BALL_RADIUS_FT * omega) / max(speed, 1.0)
        cl = 1.12 * s / (0.583 + 2.333 * s)
        if spin < 0:
            cl = -cl
        ax = -k * speed * (cd * vx + cl * vy)
        ay = -k * speed * (cd * vy - cl * vx) - _GRAVITY
        vx += ax * dt
        vy += ay * dt
        x_next, y_next = x + vx * dt, y + vy * dt
        t += dt
        if y_next <= 0.0:
            frac = y / (y - y_next) if y != y_next else 0.0
            return (
                x + (x_next - x) * frac,
                t - dt * (1.0 - frac),
                math.degrees(math.atan2(-vy, vx)),
            )
        x, y = x_next, y_next


def _grid(spec: Tuple[float, float, float]) -> list[float]:
    start, stop, step = spec
    count = int(round((stop - start) / step)) + 1
    return [start + i * step for i in range(count)]


def build_carry_table() -> dict:
    """The table file's content (``scripts/build_carry_table.py``): carry
    to 0.01 ft, hang time to 0.0001 s, descent angle to 0.01 degree, for
    each density layer, exit velocity and launch angle."""
    evs, las = _grid(EV_GRID), _grid(LA_GRID)
    layers = []
    for density in (1.0, THIN_AIR_DENSITY):
        carry_rows, hang_rows, descent_rows = [], [], []
        for ev in evs:
            row = [trajectory(ev, la, density) for la in las]
            carry_rows.append([round(c, 2) for c, _h, _d in row])
            hang_rows.append([round(h, 4) for _c, h, _d in row])
            descent_rows.append([round(d, 2) for _c, _h, d in row])
        layers.append(
            {"density": density, "carry": carry_rows, "hang": hang_rows,
             "descent": descent_rows}
        )
    return {
        "version": 1,
        "exit_velo": list(EV_GRID),
        "launch_angle": list(LA_GRID),
        "layers": layers,
    }


@functools.lru_cache(maxsize=1)
def _table() -> tuple:
    payload = json.loads(CARRY_TABLE_FILE.read_text(encoding="utf-8"))
    if list(payload.get("exit_velo", ())) != list(EV_GRID) or list(
        payload.get("launch_angle", ())
    ) != list(LA_GRID):
        raise ValueError(f"{CARRY_TABLE_FILE}: grid does not match the module's")
    layers = payload["layers"]
    if [layer["density"] for layer in layers] != [1.0, THIN_AIR_DENSITY]:
        raise ValueError(f"{CARRY_TABLE_FILE}: unexpected density layers")
    return tuple(
        (layer["carry"], layer["hang"], layer["descent"]) for layer in layers
    )


def _cell(value: float, spec: Tuple[float, float, float]) -> Tuple[int, float]:
    start, stop, step = spec
    if not math.isfinite(value):
        # A missing number reads as the grid's first cell (never int(nan)).
        value = start
    position = (min(max(value, start), stop - 1e-6) - start) / step
    index = int(position)
    return index, position - index


def flight(
    exit_velo: float, launch_angle: float, density: float = 1.0
) -> Tuple[float, float, float]:
    """``(carry, hang, descent)`` from the table: bilinear in exit velocity
    and launch angle (held to the grid's edges), linear in air density
    between the sea-level and thin-air layers (extrapolated outside them).
    Draws nothing."""
    i, a = _cell(exit_velo, EV_GRID)
    j, b = _cell(launch_angle, LA_GRID)
    out = []
    for layer in _table():
        values = []
        for grid in layer:
            r0, r1 = grid[i], grid[i + 1]
            values.append(
                (r0[j] * (1.0 - b) + r0[j + 1] * b) * (1.0 - a)
                + (r1[j] * (1.0 - b) + r1[j + 1] * b) * a
            )
        out.append(values)
    if density == 1.0:
        dist, hang, descent = out[0]
    else:
        w = (1.0 - density) / (1.0 - THIN_AIR_DENSITY)
        dist, hang, descent = (
            sea + (thin - sea) * w for sea, thin in zip(out[0], out[1])
        )
    # A ball hit almost straight up with backspin drifts back behind the
    # plate in the trajectory (a few cells at 79 degrees and 106 mph or
    # more): it comes down at the plate, not behind it.
    return max(0.0, dist), hang, descent


def air_density_ratio(altitude_ft: float) -> float:
    """Air density at ``altitude_ft`` against sea level (the standard
    atmosphere's troposphere)."""
    altitude = max(0.0, float(altitude_ft or 0.0))
    return max(0.5, 1.0 - 6.8756e-6 * altitude) ** 4.2559


def park_density(altitude_ft: float, tuning: Any) -> float:
    """The density a park's balls fly through: the physical drop at its
    altitude times ``bb6_altitude_strength`` (1.0 = the integrator's full
    effect)."""
    drop = 1.0 - air_density_ratio(altitude_ft)
    return 1.0 - drop * tuning.get("bb6_altitude_strength", 1.0)


def home_run_slider_factor(tuning: Any) -> float:
    """The commissioner's Home Run Rate slider (``hr_scale``) under the
    ball-flight model: carry times ``1 + (hr_scale - bb6_hr_slider_neutral)
    * bb6_hr_slider_carry_share``. Home runs move about 13 times as fast as
    carry, so generation 7's share (.08) makes +0.01 on the slider about +1%
    home runs. 1.0 (no effect) with the share at its default 0."""
    share = tuning.get("bb6_hr_slider_carry_share", 0.0)
    if not share:
        return 1.0
    return max(
        0.5,
        1.0 + (tuning.get("hr_scale", 1.0) - tuning.get("bb6_hr_slider_neutral", 1.0))
        * share,
    )


def carry(
    exit_velo: float, launch_angle: float, altitude_ft: float, tuning: Any
) -> Tuple[float, float, float]:
    """``(carry, hang, descent)`` a game uses: the table at the park's air,
    the carry times ``bb6_carry_scale`` and the hang time times its square
    root (a ball that carries further stays up longer)."""
    dist, hang, descent = flight(
        exit_velo, launch_angle, park_density(altitude_ft, tuning)
    )
    scale = tuning.get("bb6_carry_scale", 1.0) * home_run_slider_factor(tuning)
    return dist * scale, hang * math.sqrt(max(scale, 1e-9)), descent


# --- fences -------------------------------------------------------------------------

# The 30 major-league home parks of 2026 (the Athletics at Sutter Health
# Park, the Rays back at Tropicana Field): the generic park is their mean,
# and a park's home-run factor is read against their mean.
CURRENT_PARK_IDS: Tuple[str, ...] = (
    "ANA01", "ARL03", "ATL03", "BAL12", "BOS07", "CHI11", "CHI12", "CIN09",
    "CLE08", "DEN02", "DET05", "HOU03", "KAN06", "LOS03", "MIA02", "MIL06",
    "MIN04", "NYC20", "NYC21", "SAC01", "PHI13", "PHO01", "PIT08", "SAN02",
    "SEA03", "SFO03", "STL10", "STP01", "TOR02", "WAS11",
)
# Every park with a home-run target (data/parks/ParkHRTargets.csv): the
# current 30, the Athletics' and Rays' former or temporary homes and the
# one-off venues. Each has a fence shift per side in the tuning.
FITTED_PARK_IDS: Tuple[str, ...] = CURRENT_PARK_IDS + (
    "OAK01", "TAM02", "MEX02", "DYE01", "SEO01", "WIL02", "LON01", "BIR01",
)


@dataclass(frozen=True)
class Fence:
    """A park's fence: distances (ft) and wall heights (ft) at the LF line,
    left-centre, centre, right-centre and the RF line; ``park_id`` is
    empty for the generic park."""

    distances: Tuple[float, float, float, float, float]
    heights: Tuple[float, float, float, float, float]
    park_id: str = ""


# The mean of CURRENT_PARK_IDS' fences in data/parks/ParkFences.csv and
# their mirror images, to 0.1 ft (:func:`mean_fence`;
# tests/test_r7_carry.py recomputes it). Unmirrored the mean is 331.6 /
# 385.8 / 403.0 / 384.7 / 328.1 ft with walls 10.2 / 10.2 / 9.4 / 10.8 /
# 11.0 ft.
GENERIC_FENCE = Fence(
    distances=(329.9, 385.2, 403.0, 385.2, 329.9),
    heights=(10.6, 10.5, 9.4, 10.5, 10.6),
)


def fence_at(fence: Fence, spray_angle: float) -> Tuple[float, float]:
    """``(distance, wall height)`` of ``fence`` at the physical spray angle
    (positive toward right field), straight lines between the five points;
    beyond the foul lines the line's value."""
    position = (max(-45.0, min(45.0, float(spray_angle))) + 45.0) / 22.5
    index = min(3, int(position))
    frac = position - index
    d, h = fence.distances, fence.heights
    return (
        d[index] * (1.0 - frac) + d[index + 1] * frac,
        h[index] * (1.0 - frac) + h[index + 1] * frac,
    )


def home_run_fence(
    fence: Fence, spray_angle: float, descent: float
) -> Tuple[float, float]:
    """``(the carry a home run needs, the fence distance)`` at
    ``spray_angle``: the fence plus the wall's height over the tangent of
    the descent angle (at least 15 degrees)."""
    distance, height = fence_at(fence, spray_angle)
    slope = math.tan(math.radians(max(15.0, float(descent))))
    return distance + max(0.0, height) / max(0.3, slope), distance


class ParkFencesMissing(RuntimeError):
    """Generation 7's fences file (``ParkFences.csv``) is not where the park
    data is read from: a game must not be played on the ParkConfig.csv rows
    an earlier engine reads (docs/park_data_generation7_runbook.md)."""


def require_park_fences(tuning: Any) -> None:
    """Raise :class:`ParkFencesMissing` when the ball-flight model
    (``carry_model`` or ``fielding_play_model``) is on and
    ``ParkFences.csv`` cannot be read from the park data folder. Nothing to
    check with both off."""
    if not (carry_model_on(tuning) or fielding_play_model_on(tuning)):
        return
    from utils.park_utils import PARK_FENCES_FILE, _find_park_data_file, park_fences

    if not park_fences():
        raise ParkFencesMissing(
            "the ball-flight model is on but the park data has no "
            f"{PARK_FENCES_FILE} ({_find_park_data_file(PARK_FENCES_FILE)}); "
            "upload it with the other park files before a league plays "
            "engine generation 7 (docs/park_data_generation7_runbook.md)"
        )


@functools.lru_cache(maxsize=512)
def _real_fence(name: str) -> Optional[Fence]:
    from utils.park_utils import park_fence_for_name

    found = park_fence_for_name(name) if name else None
    if found is None:
        return None
    park_id, distances, heights = found
    return Fence(distances=tuple(distances), heights=tuple(heights), park_id=park_id)


def clear_fence_cache() -> None:
    """Forget the fences read from ``ParkConfig.csv`` (tests, a new file)."""
    _real_fence.cache_clear()


def _shift(tuning: Any, key: str, park_id: str) -> float:
    table = tuning.values.get(key) if hasattr(tuning, "values") else None
    if not isinstance(table, dict):
        return 0.0
    return optional_float(table.get(park_id, 0.0)) or 0.0


def shifted_fence(fence: Fence, left: float, right: float) -> Fence:
    """``fence`` with its left-field side (LF line and left-centre) moved
    ``left`` ft, its right-field side ``right`` ft and centre field the
    mean of the two."""
    if not left and not right:
        return fence
    moves = (left, left, (left + right) / 2.0, right, right)
    return Fence(
        distances=tuple(d + m for d, m in zip(fence.distances, moves)),  # type: ignore[arg-type]
        heights=fence.heights,
        park_id=fence.park_id,
    )


def real_park_on_generation7(park: Any) -> bool:
    """True when generation 7 plays ``park`` on a real park's own fences
    (its exact current name; ``utils.park_utils.park_fence_for_name``);
    False for the generic park."""
    return _real_fence(str(getattr(park, "name", "") or "")) is not None


def park_fence(park: Any, tuning: Any) -> Fence:
    """The fence of ``park`` (a ``physics_sim.park.Park``): its real
    park's five points (``data/parks/ParkFences.csv``, else its
    ``ParkConfig.csv`` row; the lookup ``utils.park_utils
    .stadium_from_name`` makes), the generic park otherwise. A real park's
    two sides are moved by its ``bb6_park_fence_shift_left_ft`` and
    ``bb6_park_fence_shift_right_ft`` (owner decisions 18 and 20: home runs
    fitted by batter side, a left-handed batter's mostly to the right-field
    side)."""
    fence = _real_fence(str(getattr(park, "name", "") or ""))
    if fence is None:
        # The average major-league park (round 5): the mirrored mean fence
        # moved by ``bb6_generic_fence_shift_ft`` and its walls raised by
        # ``bb6_generic_wall_add_ft``, so it plays to the 30 parks' mean --
        # a mean fence alone gives about 9% fewer home runs (convex in the
        # distance) and fewer hits off the wall (the real parks' tall walls).
        get = tuning.get if hasattr(tuning, "get") else (lambda _k, d=None: d)
        shift = optional_float(get("bb6_generic_fence_shift_ft", 0.0)) or 0.0
        wall = optional_float(get("bb6_generic_wall_add_ft", 0.0)) or 0.0
        if not shift and not wall:
            return GENERIC_FENCE
        moved = shifted_fence(GENERIC_FENCE, shift, shift)
        return Fence(
            distances=moved.distances,
            heights=tuple(h + wall for h in moved.heights),  # type: ignore[arg-type]
            park_id=moved.park_id,
        )
    return shifted_fence(
        fence,
        _shift(tuning, "bb6_park_fence_shift_left_ft", fence.park_id),
        _shift(tuning, "bb6_park_fence_shift_right_ft", fence.park_id),
    )


# --- the fielding play model (fielding_play_model 1) ------------------------------

# Where the fielders stand: (depth ft from the plate, physical angle deg,
# positive toward right field).
INFIELD_SPOTS = {
    "3B": (118.0, -31.0), "SS": (146.0, -12.0), "2B": (150.0, 11.0),
    "1B": (112.0, 33.0), "P": (57.0, 0.0),
}
OUTFIELD_SPOTS = {"LF": (296.0, -27.0), "CF": (320.0, 0.0), "RF": (296.0, 27.0)}
_FIRST_BASE_XY = (90.0 * math.sin(math.radians(45.0)), 90.0 * math.cos(math.radians(45.0)))


def _xy(radius: float, angle: float) -> Tuple[float, float]:
    a = math.radians(angle)
    return radius * math.sin(a), radius * math.cos(a)


_INFIELD_XY = {pos: _xy(*spot) for pos, spot in INFIELD_SPOTS.items()}
_INFIELD_XY["C"] = (0.0, -3.0)
_OUTFIELD_XY = {pos: _xy(*spot) for pos, spot in OUTFIELD_SPOTS.items()}
_SQRT2 = math.sqrt(2.0)


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


@dataclass
class BallInPlay:
    """One batted ball resolved by the ball-flight model (no random number).

    ``route`` is ``"ground"`` or ``"air"`` (what the mechanics key on, not
    the Statcast class); ``hit_type`` is what the ball is if nobody catches
    it; ``of_position`` is the outfielder nearest where it comes down (the
    one runners advance on). The play fields are filled by :func:`play`.
    """

    exit_velo: float
    launch_angle: float
    spray: float
    distance: float
    hang: float
    descent: float
    wall: float
    needed: float
    is_hr: bool
    route: str
    hit_type: str
    of_position: str
    of_gap: float
    out0: float = 0.0
    fielder: str = ""
    out_type: str = ""
    infield_play: bool = False
    infield_hit: float = 0.0


def resolve_ball(
    exit_velo: float,
    launch_angle: float,
    spray_angle: float,
    *,
    park: Any,
    tuning: Any,
    batter_speed: float = 50.0,
) -> BallInPlay:
    """Carry, the fence and the hit type of a ball in play
    (``fielding_play_model`` 1). ``batter_speed`` is league-relative (50
    = the league's average hitter). Draws nothing.

    Hit type: a ball that gets through on the ground is a single, or a
    double when it is hit at least ``bb6_gb_double_ev`` mph within
    ``45 - bb6_gb_double_line_deg`` degrees of a foul line. In the air,
    with ``r`` where it comes down (at most the fence) and ``gap`` its
    distance to the nearest outfielder: a triple when ``r`` reaches
    ``bb6_triple_wall_frac`` of the fence and ``gap`` is at least
    ``bb6_triple_gap_ft`` (each less ``bb6_triple_speed_ft`` per unit of
    speed above average), a double when ``r`` reaches
    ``bb6_double_wall_frac`` of the fence, or ``gap`` is at least
    ``bb6_double_gap_ft`` (less ``bb6_double_speed_ft`` per unit of speed)
    and ``r`` at least ``bb6_double_min_ft``; otherwise a single.
    """
    t = tuning.get
    phi = max(-45.0, min(45.0, float(spray_angle)))
    altitude = float(getattr(park, "altitude_ft", 0.0) or 0.0)
    dist, hang, descent = carry(exit_velo, launch_angle, altitude, tuning)
    fence = park_fence(park, tuning)
    needed, wall = home_run_fence(fence, phi, descent)
    is_hr = dist > needed
    route = (
        "ground"
        if dist < t("bb6_ground_carry_ft", 150.0) and launch_angle < t("bb6_ground_max_la", 15.0)
        else "air"
    )
    landing = min(dist, wall) if route == "air" else max(dist, 250.0)
    x, y = _xy(landing, phi)
    of_position, of_gap = "CF", 1e9
    for pos, (ox, oy) in _OUTFIELD_XY.items():
        gap = math.hypot(x - ox, y - oy)
        if gap < of_gap:
            of_position, of_gap = pos, gap
    speed = (float(batter_speed) - 50.0) / 50.0
    if is_hr:
        hit_type = "hr"
    elif route == "ground":
        hit_type = (
            "double"
            if abs(phi) >= t("bb6_gb_double_line_deg", 39.0)
            and exit_velo >= t("bb6_gb_double_ev", 88.0)
            else "single"
        )
    else:
        r = min(dist, wall)
        triple_credit = t("bb6_triple_speed_ft", 30.0) * speed
        double_credit = t("bb6_double_speed_ft", 0.0) * speed
        # A ball that hits a tall wall in the air caroms straight back to
        # the fielder (Fenway's Monster): a double at most.
        off_tall_wall = dist > wall and fence_at(fence, phi)[1] >= t(
            "bb6_tall_wall_ft", 1e9
        )
        if (
            not off_tall_wall
            and r >= wall * t("bb6_triple_wall_frac", 0.99) - triple_credit
            and of_gap >= t("bb6_triple_gap_ft", 98.0) - triple_credit
        ):
            hit_type = "triple"
        elif r >= wall * t("bb6_double_wall_frac", 0.92) or (
            of_gap >= t("bb6_double_gap_ft", 82.0) - double_credit
            and r >= t("bb6_double_min_ft", 265.0)
        ):
            hit_type = "double"
        else:
            hit_type = "single"
    return BallInPlay(
        exit_velo=exit_velo, launch_angle=launch_angle, spray=phi, distance=dist,
        hang=hang, descent=descent, wall=wall, needed=needed, is_hr=is_hr,
        route=route, hit_type=hit_type, of_position=of_position, of_gap=of_gap,
    )


def play(ball: BallInPlay, tuning: Any, *, batter_speed: float = 50.0) -> BallInPlay:
    """The neutral out chance of ``ball`` and who makes the play
    (``fielding_play_model`` 1; RELEASE6_PLAN section 3), filled into
    ``ball`` and returned. Every fielder is an average one: the fielders'
    own ratings move the chance afterwards (``range_model``, a log-odds
    shift by the responsible fielder's rating). ``batter_speed`` is
    league-relative. Draws nothing.

    Ground route: each infielder (and the pitcher) reaches laterally
    (``bb6_if_reach0`` ft plus ``bb6_if_speed`` ft/s after
    ``bb6_if_react`` s, until the ball passes him) against the ball's path,
    with a normal error of ``bb6_if_sigma`` ft; having it, he throws to
    first against the runner (``bb6_run_time`` s, less ``bb6_run_speed`` a
    point of speed above average), the race's margin read through a
    normal of ``bb6_throw_sigma`` s. The out chance is the best fielder's
    reach times his throw; the infield-hit chance is the chance the
    fielder likeliest to reach it does, less the out chance.

    Air route: an infield liner first (the ball between 0.3 ft and
    ``bb6_liner_max_h`` ft high when it passes an infielder, who reaches
    ``bb6_liner_reach0`` + ``bb6_liner_speed`` ft/s after
    ``bb6_liner_react`` s), then the landing-point race on hang time:
    each outfielder covers ``bb6_of_reach0`` + ``bb6_of_speed`` ft/s after
    ``bb6_of_react`` s (times ``bb6_of_back_scale`` going back), each
    infielder and the catcher ``bb6_ifa_speed`` ft/s after
    ``bb6_ifa_react`` s on a ball landing short of 260 ft; at most
    ``bb6_air_out_max``.
    """
    t = tuning.get
    la_rad = math.radians(ball.launch_angle)
    v0x = max(15.0, ball.exit_velo * _MPH_TO_FPS * math.cos(la_rad))
    speed_points = float(batter_speed) - 50.0
    if ball.route == "ground":
        roll = max(
            20.0,
            v0x * t("bb6_roll_speed", 0.95)
            * math.exp(-max(0.0, -ball.launch_angle - 5.0) / t("bb6_roll_topped_deg", 45.0)),
        )
        t_run = t("bb6_run_time", 4.35) - speed_points * t("bb6_run_speed", 0.02)
        react = t("bb6_if_react", 0.25)
        charge = t("bb6_charge_speed", 17.0)
        best_out, best_pos, reach_any, best_beaten = -1.0, "SS", 0.0, 0.0
        for pos, (depth, angle) in INFIELD_SPOTS.items():
            off = math.radians(ball.spray - angle)
            if abs(off) > 1.3:
                continue
            along, lateral = depth * math.cos(off), depth * abs(math.sin(off))
            pitcher = pos == "P"
            reach = (2.0 if pitcher else t("bb6_if_reach0", 3.0)) + (
                3.0 if pitcher else t("bb6_if_speed", 17.5)
            ) * max(0.0, along / roll - react)
            p_reach = _phi((reach - lateral) / max(1e-6, t("bb6_if_sigma", 3.5)))
            reach_any = max(reach_any, p_reach)
            if p_reach <= 0.001:
                continue
            t_field = (along + charge * react) / (roll + charge)
            spot = max(30.0, along - charge * max(0.0, t_field - react))
            fx, fy = _xy(spot, ball.spray)
            throw = math.hypot(fx - _FIRST_BASE_XY[0], fy - _FIRST_BASE_XY[1])
            if pos == "1B":
                throw *= 0.5
            t_play = (
                t_field + t("bb6_if_exchange", 0.90)
                + t("bb6_if_set_per_ft", 0.02) * lateral
                + throw / t("bb6_throw_speed", 120.0)
            )
            p_throw = 1.0 - _phi(-(t_run - t_play) / max(1e-6, t("bb6_throw_sigma", 0.35)))
            p_out = p_reach * p_throw
            if p_out > best_out:
                best_out, best_pos = p_out, pos
                best_beaten = p_reach * (1.0 - p_throw)
        ball.out0 = max(0.0, best_out)
        ball.fielder = best_pos
        ball.out_type = "groundout"
        ball.infield_play = True
        # An infield hit: the fielder who makes the play reaches it and loses
        # the race, plus bb6_infield_hit_other_share of the rest of the
        # chance that somebody reaches it without getting the runner (1.0:
        # all of it). Only how the runners move depends on it.
        others = max(0.0, reach_any - ball.out0 - best_beaten)
        ball.infield_hit = best_beaten + t("bb6_infield_hit_other_share", 1.0) * others
        return ball
    p_liner, liner_pos = 0.0, ""
    if ball.launch_angle < 24.0:
        for pos, (depth, angle) in INFIELD_SPOTS.items():
            if pos == "P":
                continue
            t_c = depth / v0x
            height = _RELEASE_HEIGHT_FT + depth * math.tan(la_rad) - 16.09 * t_c * t_c
            if height < 0.3 or height > t("bb6_liner_max_h", 9.5):
                continue
            lateral = depth * abs(math.sin(math.radians(ball.spray - angle)))
            reach = t("bb6_liner_reach0", 5.0) + t("bb6_liner_speed", 16.0) * max(
                0.0, t_c - t("bb6_liner_react", 0.45)
            )
            p = _phi((reach - lateral) / max(1e-6, t("bb6_liner_sigma", 2.5)))
            if p > p_liner:
                p_liner, liner_pos = p, pos
    r = min(ball.distance, ball.wall)
    x, y = _xy(r, ball.spray)
    p_air, air_pos = 0.0, ""
    # A ball still higher than a fielder can reach when it gets to the wall
    # hits the wall: nobody catches it (Fenway's wall-ball doubles).
    off_wall = ball.distance > ball.wall and (
        (ball.distance - ball.wall) * math.tan(math.radians(max(1.0, ball.descent)))
        > t("bb6_wall_catch_ft", 1e9)
    )
    for pos, (ox, oy) in _OUTFIELD_XY.items():
        if off_wall:
            break
        gap = math.hypot(x - ox, y - oy)
        reach = t("bb6_of_reach0", 5.0) + t("bb6_of_speed", 28.0) * max(
            0.0, ball.hang - t("bb6_of_react", 1.8)
        )
        if r > OUTFIELD_SPOTS[pos][0]:
            reach *= t("bb6_of_back_scale", 0.90)
        p = _phi((reach - gap) / max(1e-6, t("bb6_of_sigma", 9.0)))
        if p > p_air:
            p_air, air_pos = p, pos
    if r < 260.0:
        for pos, (ix, iy) in _INFIELD_XY.items():
            gap = math.hypot(x - ix, y - iy)
            reach = t("bb6_ifa_speed", 16.0) * max(0.0, ball.hang - t("bb6_ifa_react", 0.8))
            p = _phi((reach - gap) / max(1e-6, t("bb6_ifa_sigma", 7.0)))
            if p > p_air:
                p_air, air_pos = p, pos
    p_air = min(t("bb6_air_out_max", 0.992), p_air)
    ball.out0 = 1.0 - (1.0 - p_liner) * (1.0 - p_air)
    if liner_pos and p_liner >= p_air:
        ball.fielder, ball.out_type, ball.infield_play = liner_pos, "lineout", True
    else:
        ball.fielder = air_pos or ball.of_position
        ball.infield_play = ball.fielder not in OUTFIELD_SPOTS
        ball.out_type = "lineout" if ball.launch_angle < 20.0 else "flyout"
    ball.infield_hit = 0.0
    return ball


def fielding_play_model_on(tuning: Any) -> bool:
    """``fielding_play_model`` 1: :func:`resolve_ball` and :func:`play`."""
    return tuning.get("fielding_play_model", 0.0) >= 0.5


def mean_fence(rows: Sequence[Tuple[Sequence[float], Sequence[float]]]) -> Fence:
    """The generic park from real fences: the mean of each fence and its
    mirror image (so the generic park favours neither side), to 0.1 ft."""
    count = 2 * len(rows)

    def mean(part: int, k: int) -> float:
        total = sum(row[part][k] + row[part][4 - k] for row in rows)
        return round(total / count, 1)

    return Fence(
        distances=tuple(mean(0, k) for k in range(5)),  # type: ignore[arg-type]
        heights=tuple(mean(1, k) for k in range(5)),  # type: ignore[arg-type]
    )


def optional_float(value: object) -> Optional[float]:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
