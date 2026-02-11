import csv
import json
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable

from models.player import Player
from models.pitcher import Pitcher
from playbalance.season_context import CAREER_DATA_DIR
from utils.path_utils import get_base_dir as _get_base_dir, get_data_dir as _get_data_dir
from utils.stats_persistence import load_stats
from services.unified_data_service import get_unified_data_service

# Backwards compatibility: tests patch these attributes directly.
get_base_dir = _get_base_dir
get_data_dir = _get_data_dir


def _required_int(row, key):
    value = row.get(key)
    if value is None or value == "":
        raise ValueError(f"Missing required field: {key}")
    return int(value)


def _optional_int(row, key, default=0):
    value = row.get(key)
    if value is None or value == "":
        return default
    return int(value)


def _optional_bool(row, key, default=False):
    value = row.get(key)
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _optional_int_or_none(row, key):
    value = row.get(key)
    if value is None or value == "":
        return None
    return int(value)


_CACHE_LOCK = RLock()
_STATS_CACHE: Dict[str, Any] | None = None
_STATS_TOKEN: tuple[int, int] | None = None
_CAREER_CACHE: Dict[str, Any] | None = None
_CAREER_TOKEN: tuple[int, int] | None = None


def _load_career_players() -> dict[str, dict]:
    path = CAREER_DATA_DIR / "career_players.json"
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    players = data.get("players", {})
    if isinstance(players, dict):
        return players
    return {}


def _file_token(path: Path) -> tuple[int, int] | None:
    try:
        stat_result = path.stat()
    except OSError:
        return None
    mtime_ns = getattr(stat_result, "st_mtime_ns", None)
    if mtime_ns is None:
        mtime_ns = int(stat_result.st_mtime * 1_000_000_000)
    return mtime_ns, stat_result.st_size


def _stats_payload() -> Dict[str, Any]:
    global _STATS_CACHE, _STATS_TOKEN
    stats_path = get_data_dir() / "season_stats.json"
    token = _file_token(stats_path)
    with _CACHE_LOCK:
        if _STATS_CACHE is None or token != _STATS_TOKEN:
            _STATS_CACHE = load_stats(stats_path)
            _STATS_TOKEN = token
        return _STATS_CACHE


def _career_payload() -> Dict[str, dict]:
    global _CAREER_CACHE, _CAREER_TOKEN
    path = CAREER_DATA_DIR / "career_players.json"
    token = _file_token(path)
    with _CACHE_LOCK:
        if _CAREER_CACHE is None or token != _CAREER_TOKEN:
            _CAREER_CACHE = _load_career_players()
            _CAREER_TOKEN = token
        return _CAREER_CACHE


def _apply_dynamic_player_data(players: Iterable[Player]) -> None:
    """Attach season/career stats based on the latest on-disk payloads."""

    stats_data = _stats_payload()
    stats_map: Dict[str, Any] = stats_data.get("players", {}) if isinstance(stats_data, dict) else {}
    career_map = _career_payload()

    for player in players:
        season = stats_map.get(player.player_id)
        if season:
            player.season_stats = season
        elif hasattr(player, "season_stats"):
            try:
                delattr(player, "season_stats")
            except AttributeError:
                pass

        career_entry = career_map.get(player.player_id) if isinstance(career_map, dict) else None
        if career_entry:
            totals = career_entry.get("totals", {})
            if isinstance(totals, dict):
                player.career_stats = dict(totals)
            seasons = career_entry.get("seasons", {})
            if isinstance(seasons, dict):
                player.career_history = {
                    sid: dict(data) if isinstance(data, dict) else data
                    for sid, data in seasons.items()
                }
        else:
            if hasattr(player, "career_stats"):
                try:
                    delattr(player, "career_stats")
                except AttributeError:
                    pass
            if hasattr(player, "career_history"):
                try:
                    delattr(player, "career_history")
                except AttributeError:
                    pass


def _resolve_players_path(resolved: Path, raw: Path) -> Path:
    """Mirror legacy lookup semantics for locating player CSV files."""

    if resolved.exists():
        return resolved
    if raw.is_absolute() and raw.exists():
        return raw
    repo_root = Path(__file__).resolve().parent.parent
    alt_path = repo_root / raw
    if alt_path.exists():
        return alt_path
    return resolved


def _read_players_from_csv(csv_path: Path):
    """Load player objects from a CSV file.

    Parameters
    ----------
    file_path : str or Path
        Path to the CSV file. Relative paths are resolved with respect to the
        project root so that callers can load data regardless of the current
        working directory.
    """

    players = []
    with csv_path.open(mode="r", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            is_pitcher_value = row.get("is_pitcher", "").strip().lower()
            is_pitcher = is_pitcher_value in {"true", "1", "yes"}

            height = _required_int(row, "height")
            weight = _required_int(row, "weight")
            gf = _required_int(row, "gf")

            common_kwargs = {
                "player_id": row["player_id"],
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "birthdate": row["birthdate"],
                "height": height,
                "weight": weight,
                "ethnicity": row.get("ethnicity", ""),
                "skin_tone": row.get("skin_tone", ""),
                "hair_color": row.get("hair_color", ""),
                "facial_hair": row.get("facial_hair", ""),
                "bats": row["bats"],
                "primary_position": row["primary_position"],
                "other_positions": row.get("other_positions", "").split("|") if row.get("other_positions") else [],
                "gf": gf,
                "injured": (row.get("injured") or "false").strip().lower() == "true",
                "injury_description": row.get("injury_description") or None,
                "return_date": row.get("return_date") or None,
                "injury_list": (row.get("injury_list") or "").strip().lower() or None,
                "injury_start_date": row.get("injury_start_date") or None,
                "injury_minimum_days": _optional_int_or_none(row, "injury_minimum_days"),
                "injury_eligible_date": row.get("injury_eligible_date") or None,
                "injury_rehab_assignment": row.get("injury_rehab_assignment") or None,
                "injury_rehab_days": _optional_int(row, "injury_rehab_days", 0),
                "durability": _optional_int(row, "durability", 50),
                "ready": _optional_bool(row, "ready", False),
            }

            if is_pitcher:
                endurance = _required_int(row, "endurance")
                control = _required_int(row, "control")
                movement = _required_int(row, "movement")
                hold_runner = _required_int(row, "hold_runner")
                role = row.get("role", "")
                preferred_role = row.get("preferred_pitching_role", "")
                fb = _required_int(row, "fb")
                cu = _required_int(row, "cu")
                cb = _required_int(row, "cb")
                sl = _required_int(row, "sl")
                si = _required_int(row, "si")
                scb = _required_int(row, "scb")
                kn = _required_int(row, "kn")
                arm = _optional_int(row, "arm")
                if arm == 0:
                    arm = fb
                fa = _optional_int(row, "fa")
                player = Pitcher(
                    **common_kwargs,
                    endurance=endurance,
                    control=control,
                    movement=movement,
                    hold_runner=hold_runner,
                    fb=fb,
                    cu=cu,
                    cb=cb,
                    sl=sl,
                    si=si,
                    scb=scb,
                    kn=kn,
                    role=role,
                    preferred_pitching_role=preferred_role,
                    pitcher_archetype=row.get("pitcher_archetype", ""),
                    arm=arm,
                    fa=fa,
                    potential={
                        "gf": _optional_int(row, "pot_gf", gf),
                        "fb": _optional_int(row, "pot_fb", fb),
                        "cu": _optional_int(row, "pot_cu", cu),
                        "cb": _optional_int(row, "pot_cb", cb),
                        "sl": _optional_int(row, "pot_sl", sl),
                        "si": _optional_int(row, "pot_si", si),
                        "scb": _optional_int(row, "pot_scb", scb),
                        "kn": _optional_int(row, "pot_kn", kn),
                        "control": _optional_int(row, "pot_control", control),
                        "movement": _optional_int(row, "pot_movement", movement),
                        "endurance": _optional_int(row, "pot_endurance", endurance),
                        "hold_runner": _optional_int(row, "pot_hold_runner", hold_runner),
                        "arm": _optional_int(row, "pot_arm", arm),
                        "fa": _optional_int(row, "pot_fa", fa),
                    },
                )
                player.is_pitcher = True
            else:
                ch = _required_int(row, "ch")
                ph = _required_int(row, "ph")
                sp = _required_int(row, "sp")
                eye = _optional_int(row, "eye", ch)
                pl = _required_int(row, "pl")
                vl = _required_int(row, "vl")
                sc = _required_int(row, "sc")
                fa = _required_int(row, "fa")
                arm = _required_int(row, "arm")
                player = Player(
                    **common_kwargs,
                    ch=ch,
                    ph=ph,
                    sp=sp,
                    eye=eye,
                    hitter_archetype=row.get("hitter_archetype", ""),
                    pl=pl,
                    vl=vl,
                    sc=sc,
                    fa=fa,
                    arm=arm,
                    potential={
                        "ch": _optional_int(row, "pot_ch", ch),
                        "ph": _optional_int(row, "pot_ph", ph),
                        "sp": _optional_int(row, "pot_sp", sp),
                        "eye": _optional_int(row, "pot_eye", eye),
                        "gf": _optional_int(row, "pot_gf", gf),
                        "pl": _optional_int(row, "pot_pl", pl),
                        "vl": _optional_int(row, "pot_vl", vl),
                        "sc": _optional_int(row, "pot_sc", sc),
                        "fa": _optional_int(row, "pot_fa", fa),
                        "arm": _optional_int(row, "pot_arm", arm),
                    },
                )
                player.is_pitcher = False

            players.append(player)
    return players


def load_players_from_csv(file_path):
    """Return players loaded from ``file_path`` using the shared data service."""

    service = get_unified_data_service()
    raw_path = Path(str(file_path))

    def _loader(resolved: Path):
        csv_path = _resolve_players_path(resolved, raw_path)
        return _read_players_from_csv(csv_path)

    players = service.get_players(raw_path, _loader)
    _apply_dynamic_player_data(players)
    return players


def _players_cache_clear(file_path=None):
    service = get_unified_data_service()
    service.invalidate_players(file_path)


load_players_from_csv.cache_clear = _players_cache_clear  # type: ignore[attr-defined]
