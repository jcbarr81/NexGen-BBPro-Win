from __future__ import annotations

import csv
import os
import random
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from models.pitcher import Pitcher
from models.team import Team
from playbalance.sim_config import load_tuned_playbalance_config
from playbalance.simulation import (
    GameSimulation,
    TeamState,
    generate_boxscore,
    render_boxscore_html,
)
from utils.lineup_loader import build_default_game_state, load_lineup
from utils.lineup_autofill import auto_fill_lineup_for_team
from utils.roster_loader import load_roster, save_roster
from utils.pitcher_recovery import PitcherRecoveryTracker
from utils.player_loader import load_players_from_csv
from utils.player_writer import save_players_to_csv
from utils.team_loader import load_teams
from services.injury_manager import place_on_injury_list
from services.injury_history import record_injury_event
from services.injury_settings import get_injury_tuning_overrides
from services.physics_tuning_settings import get_physics_tuning_overrides
from utils.news_logger import log_news_event
from utils.pitcher_role import get_role
from utils.path_utils import get_base_dir

LineupEntry = Tuple[str, str]

MAX_PITCHERS_ON_DL = int(os.getenv("PB_MAX_PITCHERS_ON_DL", "5") or 5)
DAY_TO_DAY_MAX_DAYS = int(os.getenv("PB_DAY_TO_DAY_MAX_DAYS", "5") or 5)
_PHYSICS_USAGE_STATE = None
_PHYSICS_USAGE_DAY_MAP: Dict[str, int] = {}
_PHYSICS_USAGE_YEAR: Optional[int] = None
_PHYSICS_USAGE_LAST_DATE: Optional[str] = None


def _physics_usage_context(
    date_token: str | None,
) -> tuple[object | None, int | None]:
    if not date_token:
        return None, None
    global _PHYSICS_USAGE_STATE, _PHYSICS_USAGE_DAY_MAP, _PHYSICS_USAGE_YEAR, _PHYSICS_USAGE_LAST_DATE
    try:
        year = int(str(date_token).split("-")[0])
    except Exception:
        year = None
    reset = _PHYSICS_USAGE_STATE is None
    if year is not None and _PHYSICS_USAGE_YEAR not in (None, year):
        reset = True
    if _PHYSICS_USAGE_LAST_DATE and date_token < _PHYSICS_USAGE_LAST_DATE:
        reset = True
    if reset:
        from physics_sim.usage import UsageState

        _PHYSICS_USAGE_STATE = UsageState()
        _PHYSICS_USAGE_DAY_MAP = {}
        _PHYSICS_USAGE_YEAR = year
    if date_token not in _PHYSICS_USAGE_DAY_MAP:
        _PHYSICS_USAGE_DAY_MAP[date_token] = len(_PHYSICS_USAGE_DAY_MAP)
    _PHYSICS_USAGE_LAST_DATE = date_token
    return _PHYSICS_USAGE_STATE, _PHYSICS_USAGE_DAY_MAP[date_token]


def _resolve_game_engine(engine: str | None) -> str:
    raw = engine or os.getenv("PB_GAME_ENGINE") or os.getenv("PB_SIM_ENGINE")
    token = str(raw or "").strip().lower()
    if token in {"legacy", "old", "pbini"}:
        from playbalance.legacy_guard import legacy_enabled, warn_legacy_disabled

        if legacy_enabled():
            return "legacy"
        warn_legacy_disabled("Legacy playbalance engine")
        return "physics"
    if token in {"physics", "phys", "new", "next"}:
        return "physics"
    return "physics"


def _env_flag(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def _teams_by_id() -> Mapping[str, Team]:
    """Return a cached mapping of team IDs to :class:`Team` objects."""

    return {team.team_id: team for team in load_teams()}


def _normalize_game_date(value: str | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _starter_hand(state: TeamState) -> str:
    """Return the throwing hand of the team's starting pitcher."""

    if not state.pitchers:
        return ""
    starter = state.pitchers[0]
    hand = getattr(starter, "throws", "") or getattr(starter, "bats", "")
    return str(hand or "").upper()[:1]


def _load_saved_lineup(
    team_id: str,
    vs: str,
    *,
    lineup_dir: str | Path,
) -> Sequence[LineupEntry] | None:
    try:
        return load_lineup(team_id, vs=vs, lineup_dir=lineup_dir)
    except FileNotFoundError:
        return None
    except ValueError:
        return None


def read_lineup_file(path: Path) -> List[LineupEntry]:
    """Return ``(player_id, position)`` tuples parsed from ``path``."""

    entries: List[LineupEntry] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            player_id = (row.get("player_id") or "").strip()
            position = (row.get("position") or "").strip()
            if not player_id:
                raise ValueError(f"Missing player_id in lineup file {path}")
            if not position:
                raise ValueError(
                    f"Missing position for {player_id} in lineup file {path}"
                )
            entries.append((player_id, position))
    if len(entries) != 9:
        raise ValueError(
            f"Lineup file {path} must contain exactly nine players; "
            f"found {len(entries)}"
        )
    return entries


def apply_lineup(state: TeamState, lineup: Sequence[LineupEntry]) -> None:
    """Reorder ``state.lineup`` using ``lineup`` and assign positions."""

    hitters = list(state.lineup) + list(state.bench)
    id_to_player = {p.player_id: p for p in hitters}
    new_lineup = []
    seen: set[str] = set()
    for player_id, position in lineup:
        player = id_to_player.get(player_id)
        if player is None:
            raise ValueError(
                f"Player {player_id} is not on the active roster"
            )
        if player_id in seen:
            raise ValueError(
                f"Player {player_id} appears multiple times in the lineup"
            )
        setattr(player, "position", position)
        new_lineup.append(player)
        seen.add(player_id)
    # Defensive programming: ensure we always field a complete batting order.
    # If a saved lineup is incomplete or malformed (e.g., fewer than nine
    # entries), fall back to the default lineup by signaling an error to the
    # caller. This prevents simulations from running with 1–2 hitters and
    # producing distorted stats.
    if len(new_lineup) != 9:
        raise ValueError(
            f"Lineup must list 9 unique players; found {len(new_lineup)}"
        )
    state.lineup = new_lineup
    state.bench = [p for p in hitters if p.player_id not in seen]


def _log_bullpen_status(team_id: str, state: TeamState, date_token: str | None) -> None:
    """Append bullpen availability diagnostics when PB_LOG_BULLPEN_STATUS is set."""

    if not os.getenv("PB_LOG_BULLPEN_STATUS"):
        return
    usage = getattr(state, "usage_status", {}) or {}
    if not usage:
        return
    lines: list[str] = []
    for pitcher in state.pitchers[1:]:
        pid = getattr(pitcher, "player_id", "")
        if not pid:
            continue
        info = usage.get(pid)
        if not info:
            continue
        role = str(getattr(pitcher, "assigned_pitching_role", "") or "")
        available = bool(info.get("available", True))
        apps3 = int(info.get("apps3", 0) or 0)
        apps7 = int(info.get("apps7", 0) or 0)
        consec = int(info.get("consecutive_days", 0) or 0)
        last_pitches = int(info.get("last_pitches", 0) or 0)
        pct = info.get("available_pct")
        pct_text = f"{float(pct) * 100:.0f}%" if pct is not None else "--"
        available_on = info.get("available_on")
        if hasattr(available_on, "isoformat"):
            available_on = available_on.isoformat()
        lines.append(
            f"  {pid:<6} role={role:<3} ready={'Y' if available else 'N'} "
            f"pct={pct_text:<4} apps3={apps3} apps7={apps7} consec={consec} last={last_pitches} "
            f"avail_on={available_on}"
        )
    if not lines:
        return
    path = get_base_dir() / "tmp" / "bullpen_status.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = f"{date_token or 'undated'} team={team_id}"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(header + "\n")
        handle.write("\n".join(lines) + "\n")


def _apply_bullpen_usage_order(
    state: TeamState,
    team_id: str,
    tracker: PitcherRecoveryTracker | None,
    date_token: str | None,
    seed: int | None,
    *,
    players_file: str,
    roster_dir: str,
) -> None:
    """Reorder bullpen arms so rested pitchers are prioritised and tired arms sink."""

    if tracker is None or not date_token or not state.pitchers or len(state.pitchers) <= 1:
        return
    status_map = tracker.bullpen_game_status(team_id, date_token, players_file, roster_dir)
    # Stash for in-game decision making (caps, b2b checks, etc.)
    try:
        state.usage_status = dict(status_map)
    except Exception:
        state.usage_status = {}
    for pitcher in state.pitchers:
        info = status_map.get(getattr(pitcher, "player_id", ""), {})
        if info:
            setattr(pitcher, "budget_available_pct", info.get("available_pct", 1.0))
    if not status_map:
        return

    starter = state.pitchers[0]
    bullpen = list(state.pitchers[1:])
    if not bullpen:
        return

    rng_seed = hash((team_id, date_token, seed or 0))
    ordering_rng = random.Random(rng_seed)
    tie_breakers = {p.player_id: ordering_rng.random() for p in bullpen}

    available: list[tuple[dict[str, object], Pitcher]] = []
    resting: list[tuple[dict[str, object], Pitcher]] = []
    for pitcher in bullpen:
        info = dict(status_map.get(pitcher.player_id, {}))
        if info.get("available", True):
            available.append((info, pitcher))
        else:
            resting.append((info, pitcher))

    def _available_key(item: tuple[dict[str, object], Pitcher]) -> tuple[float, float, float, float]:
        info, pitcher = item
        days_since = float(info.get("days_since_use", 9999))
        last_pitches = float(info.get("last_pitches", 0))
        return (
            1.0,
            days_since,
            -last_pitches,
            tie_breakers.get(pitcher.player_id, 0.0),
        )

    def _resting_key(item: tuple[dict[str, object], Pitcher]) -> tuple[float, float]:
        info, pitcher = item
        available_on = info.get("available_on")
        ordinal = available_on.toordinal() if hasattr(available_on, "toordinal") else float("inf")
        return (
            ordinal,
            tie_breakers.get(pitcher.player_id, 0.0),
        )

    available.sort(key=_available_key, reverse=True)
    resting.sort(key=_resting_key)

    state.pitchers = [starter] + [p for _, p in available] + [p for _, p in resting]


def reorder_pitchers(state: TeamState, starter_id: str | None) -> None:
    """Move ``starter_id`` to the front and set as current starter.

    TeamState initializes the current pitcher (and credits G/GS) in
    ``__post_init__`` using the first entry in ``state.pitchers``. When a
    starter is supplied later (e.g., by the recovery tracker), simply
    reordering the list is not sufficient — the already-created
    ``current_pitcher_state`` would still point at the previous first pitcher
    who already received a G/GS credit. This helper reorders the list and also
    transfers the game/GS credit and ``current_pitcher_state`` to the desired
    starter so starts are attributed correctly.
    """

    def _prioritize_bullpen() -> None:
        if len(state.pitchers) <= 1:
            return
        starter = state.pitchers[0]
        bullpen: list = []
        rotation_rest: list = []
        for pitcher in state.pitchers[1:]:
            role = str(getattr(pitcher, "assigned_pitching_role", "") or "")
            if role.upper().startswith("SP"):
                rotation_rest.append(pitcher)
            else:
                bullpen.append(pitcher)
        state.pitchers[:] = [starter] + bullpen + rotation_rest

    if not starter_id:
        _prioritize_bullpen()
        return
    # Find desired starter
    target_index = None
    for idx, p in enumerate(state.pitchers):
        if p.player_id == starter_id:
            target_index = idx
            break
    if target_index is None:
        raise ValueError(f"Pitcher {starter_id} not found on pitching staff")

    # If already first, ensure current_pitcher_state exists and points to him
    if target_index == 0:
        if state.current_pitcher_state is None or (
            state.current_pitcher_state.player.player_id != starter_id
        ):
            from playbalance.state import PitcherState  # local import to avoid cycle

            new_ps = state.pitcher_stats.get(starter_id)
            if new_ps is None:
                new_ps = PitcherState(state.pitchers[0])
                new_ps.g += 1
                new_ps.gs += 1
                state.pitcher_stats[starter_id] = new_ps
            state.current_pitcher_state = new_ps
        _prioritize_bullpen()
        return

    # Move target pitcher to front
    starter = state.pitchers.pop(target_index)
    state.pitchers.insert(0, starter)

    from playbalance.state import PitcherState  # local import to avoid cycle
    # Remove the credit from the prior assumed starter
    prev_ps = state.current_pitcher_state
    if prev_ps is not None:
        if getattr(prev_ps, "g", 0) > 0:
            prev_ps.g -= 1
        if getattr(prev_ps, "gs", 0) > 0:
            prev_ps.gs -= 1
    # Credit the selected starter and set current state
    ps = state.pitcher_stats.get(starter.player_id)
    if ps is None:
        ps = PitcherState(starter)
        state.pitcher_stats[starter.player_id] = ps
    ps.g += 1
    ps.gs += 1
    state.current_pitcher_state = ps
    _prioritize_bullpen()


def prepare_team_state(
    team_id: str,
    *,
    lineup: Sequence[LineupEntry] | None = None,
    starter_id: str | None = None,
    players_file: str = "data/players.csv",
    roster_dir: str = "data/rosters",
) -> TeamState:
    """Return a :class:`TeamState` populated for ``team_id``.

    Lineups or starting pitchers supplied via ``lineup`` or ``starter_id``
    override the defaults derived from roster data.  The returned state stores
    a reference to the :class:`Team` object so season statistics can be
    persisted after the game completes.
    """

    state = build_default_game_state(
        team_id, players_file=players_file, roster_dir=roster_dir
    )
    team_obj = _teams_by_id().get(team_id)
    state.team = team_obj
    if team_obj is not None and getattr(team_obj, "season_stats", None):
        state.team_stats = dict(team_obj.season_stats)
    if lineup:
        apply_lineup(state, lineup)
    reorder_pitchers(state, starter_id)
    return state


def _sanitize_lineup(
    team_id: str,
    desired: Sequence[LineupEntry],
    *,
    players_file: str = "data/players.csv",
    roster_dir: str = "data/rosters",
    lineup_dir: str | Path = "data/lineups",
) -> Sequence[LineupEntry]:
    """Return a valid 9-player lineup and persist it to disk.

    Ignores ``desired`` when regenerating to ensure the final lineup reflects
    the current active roster.
    """
    try:
        load_roster.cache_clear()
    except Exception:
        pass
    lineup = auto_fill_lineup_for_team(
        team_id,
        players_file=players_file,
        roster_dir=roster_dir,
        lineup_dir=lineup_dir,
    )
    # Provide as sequence of (pid, position)
    return list(lineup)


def _player_for_boxscore(
    player_id: str,
    players_lookup: Mapping[str, object],
) -> object:
    player = players_lookup.get(player_id)
    if player is None:
        return SimpleNamespace(
            player_id=player_id,
            first_name="Unknown",
            last_name=str(player_id),
            primary_position="",
            position="",
        )
    if not getattr(player, "position", None):
        try:
            setattr(player, "position", getattr(player, "primary_position", "") or "")
        except Exception:
            pass
    return player


def _hydrate_physics_boxscore(
    box: dict[str, object],
    players_lookup: Mapping[str, object],
) -> dict[str, object]:
    from playbalance.stats import (
        compute_batting_derived,
        compute_batting_rates,
        compute_fielding_derived,
        compute_fielding_rates,
        compute_pitching_derived,
        compute_pitching_rates,
    )

    def _int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    for side in ("home", "away"):
        side_data = box.get(side, {}) if isinstance(box.get(side), dict) else {}
        batting = side_data.get("batting", []) if isinstance(side_data.get("batting"), list) else []
        pitching = (
            side_data.get("pitching", [])
            if isinstance(side_data.get("pitching"), list)
            else []
        )
        fielding = (
            side_data.get("fielding", [])
            if isinstance(side_data.get("fielding"), list)
            else []
        )

        for entry in batting:
            if not isinstance(entry, dict):
                continue
            pid = str(entry.get("player_id") or "")
            entry["player"] = _player_for_boxscore(pid, players_lookup)
            state = SimpleNamespace(
                b1=_int(entry.get("1b", entry.get("b1", 0))),
                b2=_int(entry.get("2b", entry.get("b2", 0))),
                b3=_int(entry.get("3b", entry.get("b3", 0))),
                hr=_int(entry.get("hr", 0)),
                lob=_int(entry.get("lob", 0)),
                pitches=_int(entry.get("pitches", 0)),
                pa=_int(entry.get("pa", 0)),
                ab=_int(entry.get("ab", 0)),
                h=_int(entry.get("h", 0)),
                bb=_int(entry.get("bb", 0)),
                hbp=_int(entry.get("hbp", 0)),
                sf=_int(entry.get("sf", 0)),
                so=_int(entry.get("so", 0)),
                so_looking=_int(entry.get("so_looking", 0)),
                sb=_int(entry.get("sb", 0)),
                cs=_int(entry.get("cs", 0)),
                gb=_int(entry.get("gb", 0)),
                ld=_int(entry.get("ld", 0)),
                fb=_int(entry.get("fb", 0)),
            )
            entry.update(compute_batting_derived(state))
            entry.update(compute_batting_rates(state))
            entry["2b"] = _int(entry.get("2b", entry.get("b2", 0)))
            entry["3b"] = _int(entry.get("3b", entry.get("b3", 0)))

        for entry in pitching:
            if not isinstance(entry, dict):
                continue
            pid = str(entry.get("player_id") or "")
            entry["player"] = _player_for_boxscore(pid, players_lookup)
            state = SimpleNamespace(
                outs=_int(entry.get("outs", 0)),
                gs=_int(entry.get("gs", 0)),
                gf=_int(entry.get("gf", 0)),
                r=_int(entry.get("r", 0)),
                er=_int(entry.get("er", 0)),
                so=_int(entry.get("so", 0)),
                bb=_int(entry.get("bb", 0)),
                hbp=_int(entry.get("hbp", 0)),
                hr=_int(entry.get("hr", 0)),
                h=_int(entry.get("h", 0)),
                gb=_int(entry.get("gb", 0)),
                ld=_int(entry.get("ld", 0)),
                fb=_int(entry.get("fb", 0)),
                pitches_thrown=_int(entry.get("pitches", 0)),
                bf=_int(entry.get("bf", 0)),
                first_pitch_strikes=_int(entry.get("first_pitch_strikes", 0)),
                zone_pitches=_int(entry.get("zone_pitches", 0)),
                o_zone_pitches=_int(entry.get("o_zone_pitches", 0)),
                zone_swings=_int(entry.get("zone_swings", 0)),
                o_zone_swings=_int(entry.get("o_zone_swings", 0)),
                zone_contacts=_int(entry.get("zone_contacts", 0)),
                o_zone_contacts=_int(entry.get("o_zone_contacts", 0)),
                so_looking=_int(entry.get("so_looking", 0)),
            )
            entry.update(compute_pitching_derived(state))
            entry.update(compute_pitching_rates(state))

        for entry in fielding:
            if not isinstance(entry, dict):
                continue
            pid = str(entry.get("player_id") or "")
            player = _player_for_boxscore(pid, players_lookup)
            entry["player"] = player
            state = SimpleNamespace(
                player=player,
                g=_int(entry.get("g", 0)),
                po=_int(entry.get("po", 0)),
                a=_int(entry.get("a", 0)),
                e=_int(entry.get("e", 0)),
                dp=_int(entry.get("dp", 0)),
                tp=_int(entry.get("tp", 0)),
                pk=_int(entry.get("pk", 0)),
                pb=_int(entry.get("pb", 0)),
                ci=_int(entry.get("ci", 0)),
                cs=_int(entry.get("cs", 0)),
                sba=_int(entry.get("sba", 0)),
            )
            entry.update(compute_fielding_derived(state))
            entry.update(compute_fielding_rates(state))

    return box


def _persist_physics_stats(
    *,
    metadata: dict[str, Any],
    players_lookup: Mapping[str, object],
    home_team: Team | None,
    away_team: Team | None,
) -> None:
    from playbalance.stats import (
        compute_batting_derived,
        compute_batting_rates,
        compute_fielding_derived,
        compute_fielding_rates,
        compute_pitching_derived,
        compute_pitching_rates,
        compute_team_rates,
    )
    from utils.stats_persistence import save_stats

    def _int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    batting_lines = metadata.get("batting_lines", {}) or {}
    if not isinstance(batting_lines, dict):
        batting_lines = {}
    pitcher_lines = metadata.get("pitcher_lines", {}) or {}
    if not isinstance(pitcher_lines, dict):
        pitcher_lines = {}
    fielding_lines = metadata.get("fielding_lines", {}) or {}
    if not isinstance(fielding_lines, dict):
        fielding_lines = {}
    score = metadata.get("score", {}) or {}
    if not isinstance(score, dict):
        score = {}

    updated_players: dict[str, object] = {}

    def _player_and_season(pid: str) -> tuple[object, dict[str, Any]] | None:
        player = players_lookup.get(pid)
        if player is None:
            return None
        season = getattr(player, "season_stats", None)
        if not isinstance(season, dict):
            season = {}
        player.season_stats = season
        updated_players[pid] = player
        return player, season

    batting_fields = (
        "g",
        "gs",
        "pa",
        "ab",
        "r",
        "h",
        "b1",
        "b2",
        "b3",
        "hr",
        "rbi",
        "bb",
        "ibb",
        "hbp",
        "so",
        "so_looking",
        "so_swinging",
        "sh",
        "sf",
        "roe",
        "fc",
        "ci",
        "gidp",
        "sb",
        "cs",
        "po",
        "pocs",
        "pitches",
        "lob",
        "lead",
        "gb",
        "ld",
        "fb",
    )

    for side, lines in batting_lines.items():
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            pid = str(line.get("player_id") or "")
            payload = _player_and_season(pid)
            if payload is None:
                continue
            _, season = payload
            for key in batting_fields:
                season[key] = season.get(key, 0) + _int(line.get(key, 0))
            state = SimpleNamespace(
                b1=_int(season.get("b1", 0)),
                b2=_int(season.get("b2", 0)),
                b3=_int(season.get("b3", 0)),
                hr=_int(season.get("hr", 0)),
                lob=_int(season.get("lob", 0)),
                pitches=_int(season.get("pitches", 0)),
                pa=_int(season.get("pa", 0)),
                ab=_int(season.get("ab", 0)),
                h=_int(season.get("h", 0)),
                bb=_int(season.get("bb", 0)),
                hbp=_int(season.get("hbp", 0)),
                sf=_int(season.get("sf", 0)),
                so=_int(season.get("so", 0)),
                so_looking=_int(season.get("so_looking", 0)),
                sb=_int(season.get("sb", 0)),
                cs=_int(season.get("cs", 0)),
                gb=_int(season.get("gb", 0)),
                ld=_int(season.get("ld", 0)),
                fb=_int(season.get("fb", 0)),
            )
            season.update(compute_batting_derived(state))
            season.update(compute_batting_rates(state))
            season["2b"] = season.get("b2", 0)
            season["3b"] = season.get("b3", 0)

    pitching_field_map = {
        "g": "g",
        "gs": "gs",
        "w": "w",
        "l": "l",
        "gf": "gf",
        "sv": "sv",
        "svo": "svo",
        "hld": "hld",
        "bs": "bs",
        "ir": "ir",
        "irs": "irs",
        "bf": "bf",
        "outs": "outs",
        "r": "r",
        "er": "er",
        "h": "h",
        "1b": "b1",
        "2b": "b2",
        "3b": "b3",
        "hr": "hr",
        "bb": "bb",
        "ibb": "ibb",
        "so": "so",
        "so_looking": "so_looking",
        "so_swinging": "so_swinging",
        "hbp": "hbp",
        "wp": "wp",
        "bk": "bk",
        "pk": "pk",
        "pocs": "pocs",
        "pitches": "pitches_thrown",
        "balls": "balls_thrown",
        "strikes": "strikes_thrown",
        "first_pitch_strikes": "first_pitch_strikes",
        "zone_pitches": "zone_pitches",
        "o_zone_pitches": "o_zone_pitches",
        "zone_swings": "zone_swings",
        "o_zone_swings": "o_zone_swings",
        "zone_contacts": "zone_contacts",
        "o_zone_contacts": "o_zone_contacts",
        "gb": "gb",
        "ld": "ld",
        "fb": "fb",
    }

    for side, lines in pitcher_lines.items():
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            pid = str(line.get("player_id") or "")
            payload = _player_and_season(pid)
            if payload is None:
                continue
            _, season = payload
            for key, season_key in pitching_field_map.items():
                season[season_key] = season.get(season_key, 0) + _int(line.get(key, 0))
            state = SimpleNamespace(
                outs=_int(season.get("outs", 0)),
                gs=_int(season.get("gs", 0)),
                gf=_int(season.get("gf", 0)),
                r=_int(season.get("r", 0)),
                er=_int(season.get("er", 0)),
                so=_int(season.get("so", 0)),
                bb=_int(season.get("bb", 0)),
                hbp=_int(season.get("hbp", 0)),
                hr=_int(season.get("hr", 0)),
                h=_int(season.get("h", 0)),
                gb=_int(season.get("gb", 0)),
                ld=_int(season.get("ld", 0)),
                fb=_int(season.get("fb", 0)),
                pitches_thrown=_int(season.get("pitches_thrown", 0)),
                bf=_int(season.get("bf", 0)),
                first_pitch_strikes=_int(season.get("first_pitch_strikes", 0)),
                zone_pitches=_int(season.get("zone_pitches", 0)),
                o_zone_pitches=_int(season.get("o_zone_pitches", 0)),
                zone_swings=_int(season.get("zone_swings", 0)),
                o_zone_swings=_int(season.get("o_zone_swings", 0)),
                zone_contacts=_int(season.get("zone_contacts", 0)),
                o_zone_contacts=_int(season.get("o_zone_contacts", 0)),
                so_looking=_int(season.get("so_looking", 0)),
            )
            season.update(compute_pitching_derived(state))
            season.update(compute_pitching_rates(state))

    fielding_fields = (
        "g",
        "gs",
        "po",
        "a",
        "e",
        "dp",
        "tp",
        "pk",
        "pb",
        "ci",
        "cs",
        "sba",
    )

    for side, lines in fielding_lines.items():
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            pid = str(line.get("player_id") or "")
            payload = _player_and_season(pid)
            if payload is None:
                continue
            player, season = payload
            for key in fielding_fields:
                if key in {"g", "gs"}:
                    continue
                season[key] = season.get(key, 0) + _int(line.get(key, 0))
            state = SimpleNamespace(
                player=player,
                g=_int(season.get("g", 0)),
                po=_int(season.get("po", 0)),
                a=_int(season.get("a", 0)),
                e=_int(season.get("e", 0)),
                dp=_int(season.get("dp", 0)),
                tp=_int(season.get("tp", 0)),
                pk=_int(season.get("pk", 0)),
                pb=_int(season.get("pb", 0)),
                ci=_int(season.get("ci", 0)),
                cs=_int(season.get("cs", 0)),
                sba=_int(season.get("sba", 0)),
            )
            season.update(compute_fielding_derived(state))
            season.update(compute_fielding_rates(state))

    def _update_team(team: Team | None, runs: int, opp_runs: int, lob: int, opp_lines: list[dict]) -> None:
        if team is None:
            return
        season = dict(getattr(team, "season_stats", {}) or {})
        if runs > opp_runs:
            season["w"] = season.get("w", 0) + 1
        elif runs < opp_runs:
            season["l"] = season.get("l", 0) + 1
        season["g"] = season.get("g", 0) + 1
        season["r"] = season.get("r", 0) + runs
        season["ra"] = season.get("ra", 0) + opp_runs
        season["lob"] = season.get("lob", 0) + lob

        def _sum(field: str) -> int:
            return sum(_int(line.get(field, 0)) for line in opp_lines if isinstance(line, dict))

        season["opp_pa"] = season.get("opp_pa", 0) + _sum("pa")
        season["opp_h"] = season.get("opp_h", 0) + _sum("h")
        season["opp_bb"] = season.get("opp_bb", 0) + _sum("bb")
        season["opp_so"] = season.get("opp_so", 0) + _sum("so")
        season["opp_hbp"] = season.get("opp_hbp", 0) + _sum("hbp")
        season["opp_hr"] = season.get("opp_hr", 0) + _sum("hr")
        season["opp_roe"] = season.get("opp_roe", 0) + _sum("roe")
        season.update(compute_team_rates(season))
        team.season_stats = season

    home_runs = _int(score.get("home", 0))
    away_runs = _int(score.get("away", 0))
    home_batting = batting_lines.get("home", []) if isinstance(batting_lines, dict) else []
    away_batting = batting_lines.get("away", []) if isinstance(batting_lines, dict) else []

    def _lob(lines: list[dict]) -> int:
        return sum(_int(line.get("lob", 0)) for line in lines if isinstance(line, dict))

    _update_team(
        home_team,
        home_runs,
        away_runs,
        _lob(home_batting),
        away_batting,
    )
    _update_team(
        away_team,
        away_runs,
        home_runs,
        _lob(away_batting),
        home_batting,
    )

    teams = [team for team in (home_team, away_team) if team is not None]
    save_stats(updated_players.values(), teams)


def _run_physics_game(
    *,
    home_id: str,
    away_id: str,
    home_state: TeamState,
    away_state: TeamState,
    players_file: str,
    roster_dir: str | Path,
    seed: int | None,
    date_token: str | None,
    tracker: PitcherRecoveryTracker | None,
    players_lookup: Mapping[str, object],
    persist_stats: bool,
) -> tuple[TeamState, TeamState, dict[str, object], str, dict[str, object]]:
    from physics_sim.data_loader import load_players_by_id
    from physics_sim.engine import simulate_game
    from physics_sim.outputs import serialize_game_result

    base_dir = get_base_dir()
    players_path = Path(players_file)
    if not players_path.is_absolute():
        players_path = base_dir / players_path

    batters_by_id, pitchers_by_id = load_players_by_id(players_path)

    def _ratings_from_players(
        roster: Sequence[object],
        pool: Mapping[str, object],
    ) -> list[object]:
        items: list[object] = []
        for player in roster:
            pid = getattr(player, "player_id", None)
            if not pid:
                continue
            rating = pool.get(pid)
            if rating is not None:
                items.append(rating)
        return items

    def _positions_from_players(roster: Sequence[object]) -> dict[str, str]:
        positions: dict[str, str] = {}
        for player in roster:
            pid = getattr(player, "player_id", None)
            if not pid:
                continue
            pos = getattr(player, "position", None) or getattr(
                player, "primary_position", ""
            )
            if pos:
                positions[pid] = str(pos)
        return positions

    away_lineup = _ratings_from_players(away_state.lineup, batters_by_id)
    home_lineup = _ratings_from_players(home_state.lineup, batters_by_id)
    away_positions = _positions_from_players(away_state.lineup)
    home_positions = _positions_from_players(home_state.lineup)
    away_bench = _ratings_from_players(away_state.bench, batters_by_id)
    home_bench = _ratings_from_players(home_state.bench, batters_by_id)
    away_pitchers = _ratings_from_players(away_state.pitchers, pitchers_by_id)
    home_pitchers = _ratings_from_players(home_state.pitchers, pitchers_by_id)

    if len(away_lineup) != 9 or len(home_lineup) != 9:
        raise ValueError("Physics sim requires complete 9-player lineups")
    if not away_pitchers or not home_pitchers:
        raise ValueError("Physics sim requires pitching staffs for both teams")

    away_roles: dict[str, str] = {}
    for pitcher in away_state.pitchers:
        role = str(
            getattr(pitcher, "assigned_pitching_role", "")
            or getattr(pitcher, "role", "")
            or ""
        )
        away_roles[pitcher.player_id] = role
    home_roles: dict[str, str] = {}
    for pitcher in home_state.pitchers:
        role = str(
            getattr(pitcher, "assigned_pitching_role", "")
            or getattr(pitcher, "role", "")
            or ""
        )
        home_roles[pitcher.player_id] = role

    park_name = None
    if home_state.team is not None:
        park_name = getattr(home_state.team, "stadium", None)

    usage_state, game_day = _physics_usage_context(date_token)

    tuning_overrides: Dict[str, Any] = {}
    try:
        tuning_overrides.update(get_physics_tuning_overrides())
    except Exception:
        pass
    try:
        tuning_overrides.update(get_injury_tuning_overrides())
    except Exception:
        pass
    if not tuning_overrides:
        tuning_overrides = None

    result = simulate_game(
        away_lineup=away_lineup,
        home_lineup=home_lineup,
        away_lineup_positions=away_positions,
        home_lineup_positions=home_positions,
        away_bench=away_bench,
        home_bench=home_bench,
        away_pitchers=away_pitchers,
        home_pitchers=home_pitchers,
        away_pitcher_roles=away_roles,
        home_pitcher_roles=home_roles,
        park_name=park_name,
        seed=seed,
        tuning_overrides=tuning_overrides,
        usage_state=usage_state,
        game_day=game_day,
    )

    payload = serialize_game_result(result)
    metadata = (
        payload.get("metadata", {})
        if isinstance(payload.get("metadata"), dict)
        else {}
    )
    boxscore = (
        payload.get("boxscore", {})
        if isinstance(payload.get("boxscore"), dict)
        else {}
    )
    box = _hydrate_physics_boxscore(boxscore, players_lookup)

    score = (
        metadata.get("score", {}) if isinstance(metadata.get("score"), dict) else {}
    )
    home_runs = int(score.get("home", 0) or 0)
    away_runs = int(score.get("away", 0) or 0)
    home_state.runs = home_runs
    away_state.runs = away_runs
    inning_runs = metadata.get("inning_runs", {}) or {}
    if isinstance(inning_runs, dict):
        home_state.inning_runs = list(inning_runs.get("home", []) or [])
        away_state.inning_runs = list(inning_runs.get("away", []) or [])

    home_name = home_state.team.name if home_state.team else home_id
    away_name = away_state.team.name if away_state.team else away_id
    html = render_boxscore_html(
        box,
        home_name=home_name,
        away_name=away_name,
    )

    meta = {
        "home_innings": len(home_state.inning_runs),
        "away_innings": len(away_state.inning_runs),
        "extra_innings": max(len(home_state.inning_runs), len(away_state.inning_runs)) > 9,
        "home_starter_hand": _starter_hand(home_state),
        "away_starter_hand": _starter_hand(away_state),
        "engine": "physics",
    }

    injury_events = metadata.get("injury_events", []) if isinstance(metadata, dict) else []
    if not isinstance(injury_events, list):
        injury_events = []
    if injury_events:
        team_lookup = {"home": home_id, "away": away_id}
        for event in injury_events:
            if not isinstance(event, dict):
                continue
            if event.get("team_id"):
                continue
            team_token = event.get("team")
            if not team_token:
                continue
            team_token = str(team_token)
            event["team_id"] = team_lookup.get(team_token, team_token)
    _apply_injury_events(
        injury_events,
        players_file=str(players_file),
        roster_dir=str(roster_dir),
        game_date=date_token,
    )

    if persist_stats:
        _persist_physics_stats(
            metadata=metadata,
            players_lookup=players_lookup,
            home_team=home_state.team,
            away_team=away_state.team,
        )

    try:
        from services.special_events import record_game_special_events

        record_game_special_events(
            metadata=metadata,
            home_id=home_id,
            away_id=away_id,
            players_lookup=dict(players_lookup),
            game_date=date_token,
        )
    except Exception:
        pass

    if tracker and date_token:
        def _states_from_lines(lines: list[dict[str, Any]]) -> list[SimpleNamespace]:
            output: list[SimpleNamespace] = []
            for line in lines:
                if not isinstance(line, dict):
                    continue
                pid = str(line.get("player_id") or "")
                player = players_lookup.get(pid)
                if player is None:
                    continue
                pitches = int(line.get("pitches", 0) or 0)
                output.append(
                    SimpleNamespace(player=player, pitches_thrown=pitches, simulated_pitches=0)
                )
            return output

        pitcher_lines = metadata.get("pitcher_lines", {}) if isinstance(metadata, dict) else {}
        if isinstance(pitcher_lines, dict):
            home_lines = pitcher_lines.get("home", []) if isinstance(pitcher_lines.get("home"), list) else []
            away_lines = pitcher_lines.get("away", []) if isinstance(pitcher_lines.get("away"), list) else []
            tracker.record_game(
                home_id,
                date_token,
                _states_from_lines(home_lines),
                players_file,
                str(roster_dir),
            )
            tracker.record_game(
                away_id,
                date_token,
                _states_from_lines(away_lines),
                players_file,
                str(roster_dir),
            )

    return home_state, away_state, box, html, meta


def run_single_game(
    home_id: str,
    away_id: str,
    *,
    home_lineup: Sequence[LineupEntry] | None = None,
    away_lineup: Sequence[LineupEntry] | None = None,
    home_starter: str | None = None,
    away_starter: str | None = None,
    players_file: str = "data/players.csv",
    roster_dir: str = "data/rosters",
    lineup_dir: str | Path = "data/lineups",
    game_date: str | date | None = None,
    seed: int | None = None,
    engine: str | None = None,
) -> tuple[TeamState, TeamState, dict[str, object], str, dict[str, object]]:
    """Simulate a single game and return team states, box score, HTML and metadata."""

    engine_name = _resolve_game_engine(engine)
    date_token = _normalize_game_date(game_date)
    tracker = PitcherRecoveryTracker.instance() if date_token else None
    if tracker and date_token:
        if home_starter is None:
            assigned = tracker.assign_starter(
                home_id, date_token, players_file, roster_dir
            )
            if assigned:
                home_starter = assigned
        else:
            tracker.ensure_team(home_id, players_file, roster_dir)
        if away_starter is None:
            assigned = tracker.assign_starter(
                away_id, date_token, players_file, roster_dir
            )
            if assigned:
                away_starter = assigned
        else:
            tracker.ensure_team(away_id, players_file, roster_dir)

    player_source = str(players_file)
    players_lookup = {
        player.player_id: player
        for player in load_players_from_csv(player_source)
    }

    def _pitcher_matchup(starter_id: str | None) -> str:
        if not starter_id:
            return "rhp"
        pitcher = players_lookup.get(starter_id)
        hand = str(getattr(pitcher, "throws", "") or getattr(pitcher, "bats", "") or "").upper()
        return "lhp" if hand.startswith("L") else "rhp"

    def _select_saved_lineup(team_id: str, opponent_starter: str | None) -> Sequence[LineupEntry] | None:
        desired: list[str] = []
        primary = _pitcher_matchup(opponent_starter)
        desired.append(primary)
        for fallback in ("rhp", "lhp"):
            if fallback not in desired:
                desired.append(fallback)
        for variant in desired:
            lineup = _load_saved_lineup(team_id, vs=variant, lineup_dir=lineup_dir)
            if lineup and len(lineup) == 9:
                return lineup
        return None

    if home_lineup is None:
        home_lineup = _select_saved_lineup(home_id, away_starter)
    if away_lineup is None:
        away_lineup = _select_saved_lineup(away_id, home_starter)

    def _build_state(team_id: str, lineup: Sequence[LineupEntry] | None, starter_id: str | None) -> TeamState:
        try:
            return prepare_team_state(
                team_id,
                lineup=lineup,
                starter_id=starter_id,
                players_file=players_file,
                roster_dir=roster_dir,
            )
        except ValueError:
            if lineup:
                # Salvage by sanitizing against ACT and persist the fix so
                # subsequent games use the corrected lineup.
                safe = _sanitize_lineup(
                    team_id,
                    lineup,
                    players_file=players_file,
                    roster_dir=roster_dir,
                    lineup_dir=lineup_dir,
                )
                return prepare_team_state(
                    team_id,
                    lineup=safe,
                    starter_id=starter_id,
                    players_file=players_file,
                    roster_dir=roster_dir,
                )
            raise

    rng = random.Random(seed)
    home_state = _build_state(home_id, home_lineup, home_starter)
    away_state = _build_state(away_id, away_lineup, away_starter)
    _apply_bullpen_usage_order(
        home_state,
        home_id,
        tracker,
        date_token,
        seed,
        players_file=players_file,
        roster_dir=roster_dir,
    )
    _log_bullpen_status(home_id, home_state, date_token)
    _apply_bullpen_usage_order(
        away_state,
        away_id,
        tracker,
        date_token,
        seed,
        players_file=players_file,
        roster_dir=roster_dir,
    )
    _log_bullpen_status(away_id, away_state, date_token)

    persist_stats = _env_flag("PB_PERSIST_STATS", True)
    if engine_name == "physics":
        return _run_physics_game(
            home_id=home_id,
            away_id=away_id,
            home_state=home_state,
            away_state=away_state,
            players_file=players_file,
            roster_dir=roster_dir,
            seed=seed,
            date_token=date_token,
            tracker=tracker,
            players_lookup=players_lookup,
            persist_stats=persist_stats,
        )

    cfg, _ = load_tuned_playbalance_config()
    sim = GameSimulation(home_state, away_state, cfg, rng, game_date=date_token)

    # Allow heavy simulation runs to disable per-game persistence via env var.
    # PB_PERSIST_STATS: "1"/"true"/"yes" to persist; "0"/"false"/"no" to skip.
    sim.simulate_game(persist_stats=persist_stats)
    _apply_injury_events(
        getattr(sim, "injury_events", []),
        players_file=str(players_file),
        roster_dir=str(roster_dir),
        game_date=date_token,
    )

    box = generate_boxscore(home_state, away_state)
    home_name = home_state.team.name if home_state.team else home_id
    away_name = away_state.team.name if away_state.team else away_id
    html = render_boxscore_html(
        box,
        home_name=home_name,
        away_name=away_name,
    )
    meta = {
        "home_innings": len(home_state.inning_runs),
        "away_innings": len(away_state.inning_runs),
        "extra_innings": max(len(home_state.inning_runs), len(away_state.inning_runs)) > 9,
        "home_starter_hand": _starter_hand(home_state),
        "away_starter_hand": _starter_hand(away_state),
        "engine": "legacy",
    }
    if getattr(sim, "debug_log", None):
        meta["debug_log"] = list(sim.debug_log)
    try:
        field_positions = sim.defense.set_field_positions()
        if field_positions:
            meta["field_positions"] = field_positions
    except Exception:
        pass
    if tracker and date_token:
        tracker.record_game(
            home_id,
            date_token,
            home_state.pitcher_stats.values(),
            players_file,
            roster_dir,
        )
        tracker.record_game(
            away_id,
            date_token,
            away_state.pitcher_stats.values(),
            players_file,
            roster_dir,
        )
        # Apply warmup tax for relievers who were warmed but did not enter
        try:
            tracker.record_warmups(
                home_id,
                date_token,
                home_state.bullpen_warmups,
                players_file,
                roster_dir,
            )
            tracker.record_warmups(
                away_id,
                date_token,
                away_state.bullpen_warmups,
                players_file,
                roster_dir,
            )
            # Apply post-game penalties (e.g., emergency usage tax)
            tracker.apply_penalties(
                home_id,
                date_token,
                getattr(home_state, "postgame_recovery_penalties", {}),
                players_file,
                roster_dir,
            )
            tracker.apply_penalties(
                away_id,
                date_token,
                getattr(away_state, "postgame_recovery_penalties", {}),
                players_file,
                roster_dir,
            )
        except Exception:
            # Defensive: warmup tax is best-effort and should not break game flow
            pass
    return home_state, away_state, box, html, meta


def _parse_injury_date(token: str | None) -> date:
    if not token:
        return date.today()
    try:
        return date.fromisoformat(str(token))
    except ValueError:
        return date.today()


def _apply_injury_events(
    events: List[Dict[str, object]],
    *,
    players_file: str,
    roster_dir: str,
    game_date: str | None,
) -> None:
    if not events:
        return
    injury_date = _parse_injury_date(game_date)
    players = list(load_players_from_csv(players_file))
    player_map = {p.player_id: p for p in players}
    team_rosters: Dict[str, object] = {}
    pitcher_dl_counts: Dict[str, int] = {}
    changed_players = False

    def _is_pitcher(player) -> bool:
        if player is None:
            return False
        if getattr(player, "is_pitcher", False):
            return True
        return get_role(player) in {"SP", "RP"}

    def _pitchers_on_dl(roster, team_id: str) -> int:
        player_ids = getattr(roster, "dl", []) or []
        return sum(1 for pid in player_ids if _is_pitcher(player_map.get(pid)))

    for event in events:
        team_id = event.get("team_id")
        player_id = event.get("player_id")
        if not team_id or not player_id:
            continue
        player = player_map.get(str(player_id))
        if player is None:
            continue
        team_id_str = str(team_id)
        roster = team_rosters.get(team_id_str)
        if roster is None:
            roster = load_roster(team_id_str, roster_dir=roster_dir)
            team_rosters[team_id_str] = roster
            pitcher_dl_counts[team_id_str] = _pitchers_on_dl(roster, team_id_str)
        dl_tier = str(event.get("dl_tier") or "").lower()
        if dl_tier in {"dl45", "45", "45-day", "45 day"}:
            dl_tier = "ir"
        elif dl_tier in {"dl", "dl15", "15", "15-day", "15 day"}:
            dl_tier = "dl15"
        days = int(event.get("days") or 0)
        description = str(event.get("description") or "Injury")
        player.injured = True
        player.injury_description = description
        player.injury_list = dl_tier if dl_tier else None
        player.injury_start_date = injury_date.isoformat()
        player.injury_minimum_days = days
        eligible = injury_date + timedelta(days=max(days, 0))
        player.injury_eligible_date = eligible.isoformat()

        if (
            _is_pitcher(player)
            and dl_tier
            and dl_tier != "none"
            and MAX_PITCHERS_ON_DL > 0
        ):
            current = pitcher_dl_counts.get(team_id_str, 0)
            if current >= MAX_PITCHERS_ON_DL:
                # Convert to a short day-to-day injury when the DL is saturated.
                dl_tier = "none"
                event["dl_tier"] = "none"
                days = max(1, min(days or DAY_TO_DAY_MAX_DAYS, DAY_TO_DAY_MAX_DAYS))
                player.injury_minimum_days = days
                eligible = injury_date + timedelta(days=days)
                player.injury_eligible_date = eligible.isoformat()
                description = f"{description} (day-to-day)"
                event["description"] = description
                player.injury_description = description
                player.injury_list = None
                player.return_date = None
            else:
                pitcher_dl_counts[team_id_str] = current + 1

        if dl_tier and dl_tier != "none":
            place_on_injury_list(player, roster, list_name=dl_tier)
            if dl_tier == "dl15":
                player.return_date = eligible.isoformat()
        log_news_event(
            f"{getattr(player, 'first_name', '')} {getattr(player, 'last_name', '')} injured ({description})",
            category="injury",
            team_id=team_id_str,
        )
        record_injury_event(
            {
                "player_id": str(player_id),
                "team_id": team_id_str,
                "description": description,
                "days": days,
                "dl_tier": dl_tier,
                "trigger": event.get("trigger"),
                "severity": event.get("severity"),
                "date": injury_date.isoformat(),
            }
        )
        changed_players = True

    if not changed_players:
        return

    save_players_to_csv(players, players_file)
    try:
        load_players_from_csv.cache_clear()
    except Exception:
        pass

    for team_id, roster in team_rosters.items():
        save_roster(team_id, roster)
    try:
        load_roster.cache_clear()
    except Exception:
        pass


def simulate_game_scores(
    home_id: str,
    away_id: str,
    *,
    seed: int | None = None,
    players_file: str = "data/players.csv",
    roster_dir: str = "data/rosters",
    lineup_dir: str | Path = "data/lineups",
    game_date: str | date | None = None,
    engine: str | None = None,
) -> tuple[int, int, str, dict[str, object]]:
    """Return the final score, rendered HTML and metadata for a matchup."""

    home_state, away_state, _, html, meta = run_single_game(
        home_id,
        away_id,
        seed=seed,
        players_file=players_file,
        roster_dir=roster_dir,
        lineup_dir=lineup_dir,
        game_date=game_date,
        engine=engine,
    )
    return home_state.runs, away_state.runs, html, meta


__all__ = [
    "LineupEntry",
    "apply_lineup",
    "prepare_team_state",
    "read_lineup_file",
    "reorder_pitchers",
    "run_single_game",
    "simulate_game_scores",
]



