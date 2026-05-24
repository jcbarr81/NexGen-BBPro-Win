"""View-model helpers for the additive Player Profile V2 preview."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
import csv
import json
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from playbalance.season_context import SeasonContext
from services.contracts_service import get_contract
from services.finance_budget_effects import (
    ScoutingDisplayProfile,
    scouting_display_profile_for_team,
    scouting_display_value,
)
from services.injury_history import load_player_injury_history
from services.injury_manager import disabled_list_days_remaining, disabled_list_label
from services.training_history import load_player_training_history
from services.training_settings import HITTER_TRACKS, PITCHER_TRACKS, load_training_settings
from utils.star_rating import star_text
from utils.path_utils import get_data_dir
from utils.rating_display import rating_display_value
from utils.stats_persistence import load_stats

_BATTING_STATS: List[str] = [
    "age",
    "team",
    "g",
    "ab",
    "r",
    "h",
    "2b",
    "3b",
    "hr",
    "rbi",
    "bb",
    "ibb",
    "k",
    "sb",
    "cs",
    "sh",
    "hbp",
    "gidp",
    "avg",
    "obp",
    "slg",
    "ops",
]

_PITCHING_STATS: List[str] = [
    "age",
    "team",
    "g",
    "gs",
    "w",
    "l",
    "pct",
    "era",
    "ip",
    "r",
    "er",
    "h",
    "hr",
    "bb",
    "k",
    "oba",
    "hbp",
    "wp",
    "cg",
    "sho",
    "sv",
    "bs",
    "dera",
]

_HITTER_RATINGS: Tuple[Tuple[str, str], ...] = (
    ("Contact", "ch"),
    ("Power", "ph"),
    ("Speed", "sp"),
    ("Fielding", "fa"),
    ("Arm", "arm"),
    ("Eye", "eye"),
    ("Plate Lab", "pl"),
    ("Vision", "vl"),
    ("Scouting", "sc"),
    ("GB/FB", "gf"),
)

_PITCHER_RATINGS: Tuple[Tuple[str, str], ...] = (
    ("Control", "control"),
    ("Movement", "movement"),
    ("Endurance", "endurance"),
    ("Hold", "hold_runner"),
    ("Fielding", "fa"),
    ("Arm", "arm"),
    ("Fastball", "fb"),
    ("Slider", "sl"),
    ("Curve", "cu"),
    ("Splitter", "si"),
    ("Knuckle", "kn"),
)

_STAT_ROUNDING: Dict[str, int] = {
    "avg": 3,
    "obp": 3,
    "slg": 3,
    "ops": 3,
    "pct": 3,
    "oba": 3,
    "era": 2,
    "whip": 2,
    "ip": 2,
    "dera": 2,
}


@dataclass(frozen=True)
class ProfileNote:
    title: str
    detail: str = ""


@dataclass(frozen=True)
class TrainingFocusSummary:
    source_text: str
    hitters_text: str
    pitchers_text: str


@dataclass(frozen=True)
class PlayerProfileViewModel:
    player_id: str
    full_name: str
    initials: str
    team_id: str
    is_pitcher: bool
    positions_text: str
    age_text: str
    height_text: str
    weight_text: str
    bats_text: str
    throws_text: str
    role_text: str
    overall_display: Optional[float]
    overall_stars_text: str
    scouting_summary: str
    scouting_confidence_text: str
    health_status: str
    header_metrics: Tuple[Tuple[str, str], ...]
    defense_ratings: Tuple[Tuple[str, str], ...]
    overview_ratings: Tuple[Tuple[str, str], ...]
    training_focus: Optional[TrainingFocusSummary]
    recent_training_entries: Tuple[ProfileNote, ...]
    injury_history: Tuple[ProfileNote, ...]
    stats_rows: Tuple[Tuple[str, Dict[str, Any]], ...]
    stats_columns: Tuple[str, ...]
    overall_details: Tuple[Tuple[str, str], ...] = ()
    contract_details: Tuple[Tuple[str, str], ...] = ()
    # Rolling metric chart: parallel lists — ``dates`` is a list of date-ish
    # labels (snapshot stems) and ``series`` maps metric label -> list of
    # values. Hitters: AVG/OPS. Pitchers: ERA/WHIP. Same shape PyQt's
    # RollingStatsWidget consumed.
    rolling_stats: Dict[str, Any] = None  # type: ignore[assignment]
    # Career ledger tabs ported from ``ui/player_profile_dialog.py``.
    ratings_history: Tuple[Dict[str, Any], ...] = ()
    awards_history: Tuple[Dict[str, str], ...] = ()
    transactions_log: Tuple[Dict[str, str], ...] = ()
    trade_log: Tuple[Dict[str, str], ...] = ()


def build_player_profile_view_model(player: Any) -> PlayerProfileViewModel:
    """Return a V2-friendly view model for ``player``."""

    _refresh_season_stats(player)
    team_id = _resolve_team_id(player)
    is_pitcher = _is_pitcher(player)
    # Route through ``api.routers._rating_presentation.compute_overall``
    # so the profile's headline OVR matches what the list views show
    # (top-N + position-weighted blend of the *displayed* ratings).
    # Fall back to the legacy raw average if compute_overall isn't
    # importable (keeps the PyQt-only path working in isolation).
    overall_raw: Optional[int] = None
    displayed_overall: Optional[float] = None
    try:
        from api.routers._rating_presentation import compute_overall as _compute

        result = _compute(
            lambda key: getattr(player, key, None),
            is_pitcher=is_pitcher,
            position=getattr(player, "primary_position", None),
        )
        overall_raw = result.get("overall_raw")
        if result.get("overall_display") is not None:
            displayed_overall = float(result["overall_display"])
    except Exception:
        overall_raw = None
    if overall_raw is None:
        overall_raw = getattr(player, "overall", None)
        if not isinstance(overall_raw, (int, float)):
            overall_raw = _estimate_overall_rating(player, is_pitcher=is_pitcher)
    if displayed_overall is None:
        displayed_overall = _display_overall_base(overall_raw, player)
    overall_display = _apply_scouting_adjustment(displayed_overall, player)
    if overall_display is None:
        overall_display = displayed_overall
    star_source = overall_display if overall_display is not None else overall_raw
    stars_text = star_text(star_source, min_rating=35.0, max_rating=99.0) or "--"
    training_focus = _build_training_focus_summary(
        player_id=str(getattr(player, "player_id", "") or ""),
        team_id=team_id,
    )
    overall_details = _build_overall_details(
        raw_value=overall_raw,
        displayed_value=displayed_overall,
        scouted_value=overall_display,
        stars_text=stars_text,
    )
    contract_details = _build_contract_details(str(getattr(player, "player_id", "") or ""))
    stats_rows = _collect_stats_rows(player, team_id=team_id, is_pitcher=is_pitcher)
    stats_columns = tuple(_PITCHING_STATS if is_pitcher else _BATTING_STATS)
    return PlayerProfileViewModel(
        player_id=str(getattr(player, "player_id", "") or ""),
        full_name=_full_name(player),
        initials=_initials(player),
        team_id=team_id,
        is_pitcher=is_pitcher,
        positions_text=_positions_text(player),
        age_text=str(_calculate_age(getattr(player, "birthdate", "")) or "--"),
        height_text=_format_height(getattr(player, "height", None)),
        weight_text=_stringify_value(getattr(player, "weight", None), suffix=" lb"),
        bats_text=str(getattr(player, "bats", "?") or "?"),
        throws_text=str(getattr(player, "throws", "?") or "?"),
        role_text=str(getattr(player, "role", "") or ""),
        overall_display=overall_display,
        overall_stars_text=stars_text,
        scouting_summary=str(getattr(player, "summary", "") or "No scouting report available."),
        scouting_confidence_text=_scouting_profile(team_id).confidence_label,
        health_status=_build_injury_status(player),
        header_metrics=tuple(_header_metrics(player, team_id=team_id)),
        defense_ratings=tuple(_defense_ratings(player)),
        overview_ratings=tuple(_overview_ratings(player, is_pitcher=is_pitcher)),
        training_focus=training_focus,
        recent_training_entries=tuple(_recent_training_notes(player)),
        injury_history=tuple(_injury_notes(player)),
        stats_rows=tuple(stats_rows),
        stats_columns=stats_columns,
        overall_details=overall_details,
        contract_details=contract_details,
        rolling_stats=_compute_rolling_stats(
            str(getattr(player, "player_id", "") or ""),
            is_pitcher=is_pitcher,
        ),
        ratings_history=tuple(
            _collect_ratings_history_entries(player, is_pitcher=is_pitcher)
        ),
        awards_history=tuple(_collect_awards_history(player)),
        transactions_log=tuple(
            _collect_transactions_entries(player, trade_only=False)
        ),
        trade_log=tuple(
            _collect_transactions_entries(player, trade_only=True)
        ),
    )


def _full_name(player: Any) -> str:
    first_name = str(getattr(player, "first_name", "") or "").strip()
    last_name = str(getattr(player, "last_name", "") or "").strip()
    name = f"{first_name} {last_name}".strip()
    return name or str(getattr(player, "player_id", "Player") or "Player")


def _initials(player: Any) -> str:
    parts = [part for part in _full_name(player).split() if part]
    if not parts:
        return "PP"
    return "".join(part[0] for part in parts[:2]).upper()


def _resolve_team_id(player: Any) -> str:
    player_id = str(getattr(player, "player_id", "") or "").strip()
    if player_id:
        looked_up = _lookup_player_team(player_id)
        if looked_up:
            return looked_up
    for key in ("team_id", "team", "team_abbr"):
        value = str(getattr(player, key, "") or "").strip().upper()
        if value:
            return value
    return ""


def _lookup_player_team(player_id: str) -> str:
    roster_dir = get_data_dir() / "rosters"
    if not roster_dir.exists():
        return ""
    for path in sorted(roster_dir.glob("*.csv")):
        stem = path.stem
        if not stem or "_" in stem:
            continue
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    if row and str(row[0]).strip() == player_id:
                        return stem.upper()
        except OSError:
            continue
    return ""


def _is_pitcher(player: Any) -> bool:
    return bool(
        getattr(player, "is_pitcher", False)
        or str(getattr(player, "primary_position", "") or "").upper() == "P"
    )


def _positions_text(player: Any) -> str:
    primary = str(getattr(player, "primary_position", "") or "").strip()
    others = [str(value).strip() for value in getattr(player, "other_positions", []) or []]
    positions = [value for value in [primary, *others] if value and value.lower() != "none"]
    return ", ".join(positions) if positions else "?"


def _format_height(height: Any) -> str:
    if height in ("", None):
        return "?"
    try:
        inches = int(float(height))
    except (TypeError, ValueError):
        text = str(height).strip()
        return text or "?"
    feet, rem_inches = divmod(max(0, inches), 12)
    return f"{feet}'{rem_inches}\""


def _calculate_age(birthdate_str: str) -> Optional[int]:
    try:
        birthdate = datetime.strptime(str(birthdate_str), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    today = date.today()
    age = today.year - birthdate.year
    if (today.month, today.day) < (birthdate.month, birthdate.day):
        age -= 1
    return max(age, 0)


def _stringify_value(value: Any, *, suffix: str = "") -> str:
    if value in ("", None):
        return "?"
    return f"{value}{suffix}"


def _format_numeric_text(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(numeric):
        return "--"
    return str(int(round(numeric)))


def _format_currency(value: Any) -> str:
    try:
        numeric = int(round(float(value)))
    except (TypeError, ValueError):
        return "--"
    if numeric <= 0:
        return "--"
    return f"${numeric:,}"


def _format_days_text(value: Any) -> str:
    try:
        numeric = int(round(float(value)))
    except (TypeError, ValueError):
        return "--"
    if numeric < 0:
        return "--"
    return f"{numeric:,} days"


def _format_yes_no(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value in (None, ""):
        return "--"
    return "Yes" if bool(value) else "No"


def _format_count_text(value: Any, *, singular: str) -> str:
    if isinstance(value, (list, tuple, set, frozenset)):
        numeric = len(value)
    else:
        try:
            numeric = int(round(float(value)))
        except (TypeError, ValueError):
            return "--"
    if numeric <= 0:
        return "0"
    label = singular if numeric == 1 else f"{singular}s"
    return f"{numeric} {label}"


def _scouting_profile(team_id: str) -> ScoutingDisplayProfile:
    try:
        return scouting_display_profile_for_team(team_id or None)
    except Exception:
        return ScoutingDisplayProfile(
            team_id=team_id,
            scouting_multiplier=1.0,
            confidence_score=100,
            confidence_label="Exact",
            max_rating_error=0,
        )


def _display_overall_base(value: Any, player: Any) -> Optional[float]:
    if not isinstance(value, (int, float)):
        return None
    display_val = rating_display_value(
        value,
        key="OVR",
        position=getattr(player, "primary_position", None),
        is_pitcher=_is_pitcher(player),
        mode="scale_99",
    )
    try:
        numeric_display = float(display_val)
    except (TypeError, ValueError):
        return None
    return numeric_display


def _apply_scouting_adjustment(value: Any, player: Any) -> Optional[float]:
    if not isinstance(value, (int, float)):
        return None
    adjusted = scouting_display_value(
        value,
        player_id=str(getattr(player, "player_id", "") or ""),
        metric_key="OVR",
        team_id=_resolve_team_id(player) or None,
        minimum=35,
        maximum=99,
    )
    try:
        return float(adjusted)
    except (TypeError, ValueError):
        return float(value)


def _display_overall(value: Any, player: Any) -> Optional[float]:
    display_val = _display_overall_base(value, player)
    if display_val is None:
        return None
    adjusted = _apply_scouting_adjustment(display_val, player)
    return adjusted if adjusted is not None else display_val


def _display_rating(
    player: Any,
    key: str,
    *,
    label_key: Optional[str] = None,
    minimum: int = 35,
    maximum: int = 99,
) -> str:
    raw = getattr(player, key, None)
    if raw in ("", None):
        return "--"
    display_val = rating_display_value(
        raw,
        key=(label_key or key).upper(),
        position=getattr(player, "primary_position", None),
        is_pitcher=_is_pitcher(player),
        mode="scale_99",
    )
    adjusted = scouting_display_value(
        display_val,
        player_id=str(getattr(player, "player_id", "") or ""),
        metric_key=(label_key or key).upper(),
        team_id=_resolve_team_id(player) or None,
        minimum=minimum,
        maximum=maximum,
    )
    try:
        return str(int(round(float(adjusted))))
    except (TypeError, ValueError):
        return str(adjusted)


def _header_metrics(player: Any, *, team_id: str) -> List[Tuple[str, str]]:
    age_text = str(_calculate_age(getattr(player, "birthdate", "")) or "--")
    bats = str(getattr(player, "bats", "?") or "?")
    throws = str(getattr(player, "throws", "?") or "?")
    metrics = [
        ("Age", age_text),
        ("B/T", f"{bats}/{throws}"),
        ("Height", _format_height(getattr(player, "height", None))),
        ("Weight", _stringify_value(getattr(player, "weight", None), suffix=" lb")),
        ("Team", team_id or "--"),
        ("Pos", _positions_text(player)),
    ]
    role = str(getattr(player, "role", "") or "").strip()
    if role:
        metrics.append(("Role", role))
    return metrics


def _defense_ratings(player: Any) -> List[Tuple[str, str]]:
    return [
        ("Fielding", _display_rating(player, "fa", label_key="FA")),
        ("Arm", _display_rating(player, "arm", label_key="AS")),
        ("Speed", _display_rating(player, "sp", label_key="SP")),
    ]


def _overview_ratings(player: Any, *, is_pitcher: bool) -> List[Tuple[str, str]]:
    items = _PITCHER_RATINGS if is_pitcher else _HITTER_RATINGS
    rows: List[Tuple[str, str]] = []
    for label, key in items:
        raw = getattr(player, key, None)
        if raw in ("", None):
            continue
        if key in {"fb", "sl", "cu", "si", "kn"}:
            try:
                if float(raw) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
        rows.append((label, _display_rating(player, key)))
    return rows


def _build_training_focus_summary(
    *,
    player_id: str,
    team_id: str,
) -> Optional[TrainingFocusSummary]:
    if not player_id:
        return None
    try:
        settings = load_training_settings()
    except Exception:
        return None
    weights = settings.for_player(player_id, team_id or None)
    source = "League default"
    if player_id in settings.player_overrides:
        source = "Player override"
    elif team_id and team_id in settings.team_overrides:
        source = f"Team override ({team_id})"
    hitters_text = " | ".join(
        f"{track.title()} {int(round(weights.hitter_weight(track)))}%"
        for track in HITTER_TRACKS
    )
    pitchers_text = " | ".join(
        f"{track.replace('_', ' ').title()} {int(round(weights.pitcher_weight(track)))}%"
        for track in PITCHER_TRACKS
    )
    return TrainingFocusSummary(
        source_text=source,
        hitters_text=hitters_text,
        pitchers_text=pitchers_text,
    )


def _build_overall_details(
    *,
    raw_value: Any,
    displayed_value: Any,
    scouted_value: Any,
    stars_text: str,
) -> Tuple[Tuple[str, str], ...]:
    return (
        ("Raw", _format_numeric_text(raw_value)),
        ("Displayed", _format_numeric_text(displayed_value)),
        ("Scouted", _format_numeric_text(scouted_value)),
        ("Stars", stars_text or "--"),
    )


def _build_contract_details(player_id: str) -> Tuple[Tuple[str, str], ...]:
    if not player_id:
        return ()
    try:
        contract = get_contract(player_id)
    except Exception:
        return ()
    if not isinstance(contract, Mapping):
        return ()
    salary = _format_currency(contract.get("annual_salary"))
    years_left = _format_numeric_text(contract.get("years_left"))
    fa_year = _format_numeric_text(contract.get("fa_year"))
    service_time = _format_days_text(contract.get("service_time_days"))
    status_parts = [
        f"Arb: {_format_yes_no(contract.get('arb_eligible'))}",
        f"Guaranteed: {_format_yes_no(contract.get('guaranteed'))}",
    ]
    terms_parts = [
        f"Options: {_format_count_text(contract.get('options', []), singular='option')}",
        f"Incentives: {_format_count_text(contract.get('incentives', []), singular='incentive')}",
        f"Buyout: {_format_currency(contract.get('buyout_guarantee'))}",
    ]
    return (
        ("Annual Salary", salary),
        ("Years Left", years_left),
        ("FA Year", fa_year),
        ("Service Time", service_time),
        ("Status", " | ".join(status_parts)),
        ("Terms", " | ".join(terms_parts)),
    )


def _recent_training_notes(player: Any) -> List[ProfileNote]:
    player_id = str(getattr(player, "player_id", "") or "")
    if not player_id:
        return []
    notes: List[ProfileNote] = []
    for entry in load_player_training_history(player_id, limit=3):
        season = str(entry.get("season_id", "") or "").strip()
        focus = str(entry.get("focus", "") or "Training Focus").strip()
        run_at = str(entry.get("run_at", "") or "").strip()
        if "T" in run_at:
            run_at = run_at.split("T", 1)[0]
        changes = entry.get("changes") or {}
        detail_bits: List[str] = []
        if isinstance(changes, Mapping):
            for key, value in changes.items():
                if isinstance(value, (int, float)) and value:
                    sign = "+" if value >= 0 else ""
                    detail_bits.append(f"{str(key).upper()} {sign}{int(value)}")
        title = f"{run_at}: {season} - {focus}" if run_at else f"{season} - {focus}"
        detail = ", ".join(detail_bits)
        notes.append(ProfileNote(title=title.strip(" -"), detail=detail))
    return notes


def _build_injury_status(player: Any) -> str:
    injured = bool(getattr(player, "injured", False))
    injury_list = str(getattr(player, "injury_list", "") or "").strip()
    description = str(getattr(player, "injury_description", "") or "").strip()
    return_date = str(getattr(player, "return_date", "") or "").strip()
    ready = getattr(player, "ready", None)
    if injury_list:
        label = disabled_list_label(injury_list) or injury_list.upper()
        remaining = None
        try:
            remaining = disabled_list_days_remaining(player)
        except Exception:
            remaining = None
        if isinstance(remaining, int):
            return f"{label} ({remaining} days remaining)"
        if description:
            return f"{label}: {description}"
        return label
    if injured and description:
        return description
    if return_date:
        return f"Estimated return: {return_date}"
    if ready is False:
        return "Not yet game-ready"
    return "Available"


def _injury_notes(player: Any) -> List[ProfileNote]:
    player_id = str(getattr(player, "player_id", "") or "")
    if not player_id:
        return []
    notes: List[ProfileNote] = []
    for entry in load_player_injury_history(player_id, limit=8):
        date_token = str(entry.get("date", "") or "").strip()
        if "T" in date_token:
            date_token = date_token.split("T", 1)[0]
        season = str(entry.get("season_id", "") or "").strip()
        description = str(entry.get("description", "") or "Injury").strip()
        title = f"{date_token} - {description}" if date_token else f"{season} - {description}"
        detail = str(entry.get("severity", "") or "").strip()
        notes.append(ProfileNote(title=title.strip(" -"), detail=detail))
    return notes


def _collect_stats_rows(
    player: Any,
    *,
    team_id: str,
    is_pitcher: bool,
) -> List[Tuple[str, Dict[str, Any]]]:
    rows: List[Tuple[str, Dict[str, Any]]] = []
    current_year = _current_season_year()
    season = _stats_to_dict(getattr(player, "season_stats", {}), is_pitcher)
    if season:
        season.setdefault("age", _calculate_age(getattr(player, "birthdate", "")))
        season.setdefault("team", team_id)
        _clamp_games_to_team_max(season)
        rows.append((f"{current_year:04d}", season))

    history_rows: List[Tuple[Tuple[int, str], str, Dict[str, Any]]] = []
    history_map = getattr(player, "career_history", {}) or {}
    if isinstance(history_map, Mapping):
        for season_id, raw_stats in history_map.items():
            data = _stats_to_dict(raw_stats, is_pitcher)
            if not data:
                continue
            data.setdefault("team", team_id)
            history_rows.append((_season_sort_key(str(season_id)), _format_season_label(str(season_id)), data))
    history_rows.sort(key=lambda item: item[0], reverse=True)
    rows.extend((label, data) for _, label, data in history_rows)

    career_components: List[Dict[str, Any]] = []
    if season:
        career_components.append(season)
    for _, label, data in history_rows:
        if season and _year_from_token(label) == current_year:
            continue
        career_components.append(data)
    career = _sum_stat_rows(career_components, is_pitcher=is_pitcher)
    if career:
        career.setdefault("team", team_id)
        rows.append(("Career", career))
    if rows:
        return rows

    history_entries = list((_load_stats_snapshot().get("history", []) or []))
    aggregated = _aggregate_history_rows(player, history_entries, is_pitcher=is_pitcher)
    for label, data in aggregated:
        data.setdefault("team", team_id)
    return aggregated


def _current_season_year() -> int:
    try:
        ctx = SeasonContext.load()
        season_id = str(ctx.current_season_id or "")
        year = _year_from_token(season_id)
        if year is not None:
            return year
    except Exception:
        pass
    return datetime.now().year


def _season_sort_key(season_id: str) -> Tuple[int, str]:
    return (_year_from_token(season_id) or -1, str(season_id))


def _format_season_label(season_id: str) -> str:
    parts = str(season_id).rsplit("-", 1)
    if len(parts) != 2:
        return str(season_id)
    league_token, year_token = parts
    try:
        year_int = int(year_token)
    except ValueError:
        return str(season_id)
    league_token = league_token.strip().upper()
    if league_token and league_token not in {"LEAGUE"}:
        return f"{year_int:04d} ({league_token})"
    return f"{year_int:04d}"


def _stats_to_dict(stats: Any, is_pitcher: bool) -> Dict[str, Any]:
    if isinstance(stats, dict):
        data = dict(stats)
    elif is_dataclass(stats):
        data = asdict(stats)
    else:
        return {}
    if is_pitcher:
        data = _normalize_pitching_stats(data)
    else:
        if "b2" in data and "2b" not in data:
            data["2b"] = data.get("b2", 0)
        if "b3" in data and "3b" not in data:
            data["3b"] = data.get("b3", 0)
    _round_stat_values(data)
    return data


def _normalize_pitching_stats(data: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(data)
    outs = result.get("outs")
    if outs is not None and "ip" not in result:
        result["ip"] = float(outs) / 3.0
    ip = result.get("ip", 0)
    try:
        ip_value = float(ip or 0)
    except (TypeError, ValueError):
        ip_value = 0.0
    if ip_value:
        er = _safe_float(result.get("er"))
        result.setdefault("era", (er * 9.0) / ip_value if ip_value else 0.0)
    result.setdefault("w", result.get("wins", result.get("w", 0)))
    result.setdefault("l", result.get("losses", result.get("l", 0)))
    return result


def _aggregate_history_rows(
    player: Any,
    entries: Iterable[Dict[str, Any]],
    *,
    is_pitcher: bool,
) -> List[Tuple[str, Dict[str, Any]]]:
    aggregated: Dict[str, Tuple[int, str, Dict[str, Any]]] = {}
    player_id = str(getattr(player, "player_id", "") or "")
    unknown_counter = 0
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        players_block = entry.get("players", {})
        if not isinstance(players_block, Mapping):
            continue
        player_data = players_block.get(player_id)
        if not player_data:
            continue
        snapshot = player_data.get("stats", player_data) if isinstance(player_data, Mapping) else player_data
        data = _stats_to_dict(snapshot, is_pitcher)
        if not data:
            continue
        year_val, date_token = _year_from_entry(entry)
        if year_val is None:
            unknown_counter += 1
            label = f"Year {unknown_counter}"
            order_key = -unknown_counter
        else:
            label = f"{year_val:04d}"
            order_key = year_val
        stored = aggregated.get(label)
        if stored is None or (date_token and date_token > stored[1]):
            aggregated[label] = (order_key, date_token, data)
    ordered = sorted(aggregated.items(), key=lambda item: (item[1][0], item[1][1]), reverse=True)
    return [(label, payload[2]) for label, payload in ordered]


def _year_from_entry(entry: Mapping[str, Any]) -> Tuple[Optional[int], str]:
    date_token = str(entry.get("date", "") or "").strip()
    year_val = _year_from_token(entry.get("year") or entry.get("season_id"))
    if year_val is None and date_token:
        try:
            year_val = int(date_token.split("-", 1)[0])
        except (TypeError, ValueError):
            year_val = None
    return year_val, date_token


def _year_from_token(token: Any) -> Optional[int]:
    if token in ("", None):
        return None
    text = str(token).strip()
    try:
        return int(text.rsplit("-", 1)[-1])
    except (TypeError, ValueError):
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 4:
            try:
                return int(digits[-4:])
            except ValueError:
                return None
    return None


def _sum_stat_rows(
    rows: Iterable[Dict[str, Any]],
    *,
    is_pitcher: bool,
) -> Dict[str, Any]:
    totals: Dict[str, Any] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for key, value in row.items():
            if key in {"avg", "obp", "slg", "ops", "era", "whip", "pct", "oba", "dera"}:
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0) + value
    if is_pitcher:
        ip = _safe_float(totals.get("ip"))
        if not ip:
            outs = _safe_float(totals.get("outs"))
            ip = outs / 3.0 if outs else 0.0
            if ip:
                totals["ip"] = ip
        if ip:
            er = _safe_float(totals.get("er"))
            totals["era"] = (er * 9.0) / ip
    else:
        ab = _safe_float(totals.get("ab"))
        hits = _safe_float(totals.get("h"))
        doubles = _safe_float(totals.get("2b", totals.get("b2", 0)))
        triples = _safe_float(totals.get("3b", totals.get("b3", 0)))
        homers = _safe_float(totals.get("hr"))
        walks = _safe_float(totals.get("bb"))
        hbp = _safe_float(totals.get("hbp"))
        sf = _safe_float(totals.get("sf"))
        if ab:
            singles = hits - doubles - triples - homers
            total_bases = singles + (2 * doubles) + (3 * triples) + (4 * homers)
            totals["avg"] = hits / ab
            totals["slg"] = total_bases / ab
        denom = ab + walks + hbp + sf
        if denom:
            totals["obp"] = (hits + walks + hbp) / denom
        if "obp" in totals and "slg" in totals:
            totals["ops"] = totals["obp"] + totals["slg"]
    _round_stat_values(totals)
    return totals


def _round_stat_values(data: Dict[str, Any]) -> None:
    for key, decimals in _STAT_ROUNDING.items():
        value = data.get(key)
        if isinstance(value, (int, float)):
            data[key] = round(float(value), decimals)


def _load_stats_snapshot() -> Dict[str, Any]:
    try:
        data = load_stats()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _refresh_season_stats(player: Any) -> None:
    player_id = str(getattr(player, "player_id", "") or "")
    if not player_id:
        return
    snapshot = _load_stats_snapshot()
    current = snapshot.get("players", {}).get(player_id)
    if isinstance(current, dict) and current:
        try:
            player.season_stats = current
        except Exception:
            pass


def _clamp_games_to_team_max(season: Dict[str, Any]) -> None:
    snapshot = _load_stats_snapshot()
    team_stats = snapshot.get("teams", {})
    if not isinstance(team_stats, Mapping):
        return
    games: List[int] = []
    for value in team_stats.values():
        if not isinstance(value, Mapping):
            continue
        try:
            games.append(int(value.get("g", value.get("games", 0)) or 0))
        except (TypeError, ValueError):
            continue
    if not games:
        return
    max_games = max(games)
    try:
        season_games = int(season.get("g", 0) or 0)
    except (TypeError, ValueError):
        return
    if max_games:
        season["g"] = min(season_games, max_games)


def _estimate_overall_rating(player: Any, *, is_pitcher: bool) -> Optional[int]:
    keys = (
        ("endurance", "control", "movement", "hold_runner", "arm", "fa", "fb", "cu", "cb", "sl", "si", "scb", "kn")
        if is_pitcher
        else ("ch", "ph", "sp", "pl", "vl", "sc", "fa", "arm", "gf")
    )
    values: List[float] = []
    for key in keys:
        raw = getattr(player, key, None)
        try:
            numeric = float(raw)
        except (TypeError, ValueError):
            continue
        if key in {"fb", "cu", "cb", "sl", "si", "scb", "kn"} and numeric <= 0:
            continue
        values.append(numeric)
    if not values:
        return None
    return max(35, min(99, int(round(sum(values) / len(values)))))


def _safe_float(value: Any) -> float:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return numeric if math.isfinite(numeric) else 0.0


# ---------------------------------------------------------------------------
# Rolling stats chart data (hitter AVG/OPS or pitcher ERA/WHIP across the
# last ~12 season_history snapshots). Ports ``_compute_rolling_stats`` from
# ``ui/player_profile_dialog.py`` so the React chart consumes exactly the
# same payload the PyQt widget did.


def _calc_obp(stats: Mapping[str, Any]) -> float:
    ab = _safe_float(stats.get("ab"))
    hits = _safe_float(stats.get("h"))
    bb = _safe_float(stats.get("bb"))
    hbp = _safe_float(stats.get("hbp"))
    sf = _safe_float(stats.get("sf"))
    denom = ab + bb + hbp + sf
    if denom <= 0:
        return 0.0
    return (hits + bb + hbp) / denom


def _calc_slg(stats: Mapping[str, Any]) -> float:
    ab = _safe_float(stats.get("ab"))
    if ab <= 0:
        return 0.0
    doubles = _safe_float(stats.get("2b", stats.get("b2", 0)))
    triples = _safe_float(stats.get("3b", stats.get("b3", 0)))
    homers = _safe_float(stats.get("hr"))
    hits = _safe_float(stats.get("h"))
    singles = max(0.0, hits - doubles - triples - homers)
    return (singles + 2 * doubles + 3 * triples + 4 * homers) / ab


def _compute_rolling_stats(player_id: str, *, is_pitcher: bool) -> Dict[str, Any]:
    if not player_id:
        return {"dates": [], "series": {}}
    history_dir = get_data_dir() / "season_history"
    if not history_dir.exists():
        return {"dates": [], "series": {}}

    dates: List[str] = []
    if is_pitcher:
        metric_specs = [("ERA", "era"), ("WHIP", "whip")]
    else:
        metric_specs = [("AVG", "avg"), ("OPS", "ops")]
    series: Dict[str, List[float]] = {label: [] for label, _ in metric_specs}

    snapshots = sorted(history_dir.glob("*.json"))
    for path in snapshots[-12:]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        stats = (payload.get("players") or {}).get(player_id)
        if not stats:
            continue
        dates.append(path.stem)
        for label, metric_id in metric_specs:
            if metric_id == "avg":
                ab = _safe_float(stats.get("ab"))
                hits = _safe_float(stats.get("h"))
                value = hits / ab if ab else 0.0
            elif metric_id == "ops":
                value = _calc_obp(stats) + _calc_slg(stats)
            elif metric_id == "era":
                outs = _safe_float(stats.get("outs"))
                ip = outs / 3 if outs else 0.0
                er = _safe_float(stats.get("er"))
                value = (er * 9) / ip if ip else 0.0
            elif metric_id == "whip":
                outs = _safe_float(stats.get("outs"))
                ip = outs / 3 if outs else 0.0
                walks = _safe_float(stats.get("bb"))
                hits_allowed = _safe_float(stats.get("h"))
                value = (walks + hits_allowed) / ip if ip else 0.0
            else:
                value = 0.0
            series[label].append(round(value, 3))
    return {"dates": dates, "series": series}


# ---------------------------------------------------------------------------
# Career ledger: ratings history + awards + transactions/trades. Ports the
# matching collectors in ``ui/player_profile_dialog.py``.


_HITTER_RATING_HISTORY = ("ch", "ph", "sp", "eye", "fa", "arm")
_PITCHER_RATING_HISTORY = ("endurance", "control", "movement", "arm", "fa")


def _collect_ratings_history_entries(
    player: Any,
    *,
    is_pitcher: bool,
) -> List[Dict[str, Any]]:
    """Per-season rating snapshot list. Each entry is
    ``{label, ratings: {key: value}}``. Walks SeasonContext history + the
    live player to avoid duplicating the current year."""

    player_id = str(getattr(player, "player_id", "") or "").strip()
    if not player_id:
        return []
    entries: List[Dict[str, Any]] = []
    seen_years: set[int] = set()

    try:
        ctx = SeasonContext.load()
        seasons = list(ctx.seasons)
    except Exception:
        seasons = []

    keys = _PITCHER_RATING_HISTORY if is_pitcher else _HITTER_RATING_HISTORY

    for season in seasons:
        if not isinstance(season, dict):
            continue
        season_id = str(season.get("season_id") or "").strip()
        if not season_id:
            continue
        league_year = season.get("league_year")
        try:
            year_val = int(league_year) if league_year is not None else 0
        except (TypeError, ValueError):
            year_val = 0
        path = get_data_dir() / "careers" / season_id / "players.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            row_match: Optional[Mapping[str, Any]] = None
            for row in reader:
                if str(row.get("player_id", "")).strip() == player_id:
                    row_match = row
                    break
        if not row_match:
            continue
        ratings: Dict[str, Any] = {}
        for k in keys:
            raw = row_match.get(k)
            try:
                ratings[k] = int(raw) if raw not in ("", None) else None
            except (TypeError, ValueError):
                ratings[k] = None
        label = f"{year_val:04d}" if year_val else season_id
        entries.append({"label": label, "ratings": ratings})
        if year_val:
            seen_years.add(year_val)

    # Append current season so the table trails off at "now".
    current_year = date.today().year
    if current_year not in seen_years:
        current_ratings: Dict[str, Any] = {}
        for k in keys:
            try:
                raw = getattr(player, k, None)
                current_ratings[k] = int(raw) if raw not in ("", None) else None
            except (TypeError, ValueError):
                current_ratings[k] = None
        if any(v is not None for v in current_ratings.values()):
            entries.append(
                {"label": f"{current_year:04d}", "ratings": current_ratings}
            )

    def _year(entry: Dict[str, Any]) -> int:
        try:
            return int(entry["label"])
        except (TypeError, ValueError):
            return -1

    entries.sort(key=_year)
    return entries


def _collect_awards_history(player: Any) -> List[Dict[str, str]]:
    """Best-effort award list. Awards live in ``career_players.json`` and
    ``season_history/*.json`` depending on the sim version; read both and
    dedupe. Each entry is ``{year, award, description}``."""

    player_id = str(getattr(player, "player_id", "") or "").strip()
    if not player_id:
        return []

    entries: List[Dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    # career_players.json — per-season "awards" list.
    career_path = (
        get_data_dir() / "career_players.json"
    )  # path mirror; see playbalance.season_context.CAREER_DATA_DIR
    try:
        from playbalance.season_context import CAREER_DATA_DIR

        career_path = CAREER_DATA_DIR / "career_players.json"
    except Exception:
        pass
    try:
        if career_path.exists():
            payload = json.loads(career_path.read_text(encoding="utf-8"))
            players = payload.get("players") if isinstance(payload, dict) else None
            entry = (players or {}).get(player_id) if isinstance(players, dict) else None
            seasons = (entry or {}).get("seasons") if isinstance(entry, dict) else None
            if isinstance(seasons, dict):
                for season_id, data in seasons.items():
                    awards = data.get("awards") if isinstance(data, dict) else None
                    if not awards:
                        continue
                    year_label = str(data.get("year") or season_id)
                    for award in awards:
                        if isinstance(award, dict):
                            name = str(award.get("name", "")).strip()
                            desc = str(award.get("description", "")).strip()
                        else:
                            name = str(award).strip()
                            desc = ""
                        if not name:
                            continue
                        key = (year_label, name)
                        if key in seen:
                            continue
                        seen.add(key)
                        entries.append(
                            {
                                "year": year_label,
                                "award": name,
                                "description": desc,
                            }
                        )
    except Exception:
        pass

    entries.sort(key=lambda e: (e.get("year") or "", e.get("award") or ""))
    return entries


def _collect_transactions_entries(
    player: Any,
    *,
    trade_only: bool,
) -> List[Dict[str, str]]:
    """Transaction log rows from ``financial_transactions.csv`` filtered to
    this player. When ``trade_only`` is True, restrict to trade-type rows.
    Each entry is ``{date, description, from_team, to_team}``."""

    player_id = str(getattr(player, "player_id", "") or "").strip()
    if not player_id:
        return []
    path = get_data_dir() / "financial_transactions.csv"
    if not path.exists():
        return []
    entries: List[Dict[str, str]] = []
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                pid = str(row.get("player_id", "")).strip()
                if pid != player_id:
                    continue
                kind = str(row.get("type") or row.get("transaction_type") or "").strip()
                if trade_only and "trade" not in kind.lower():
                    continue
                entries.append(
                    {
                        "date": str(row.get("date") or row.get("season_day") or ""),
                        "description": str(
                            row.get("description") or row.get("note") or kind or ""
                        ),
                        "from_team": str(
                            row.get("from_team") or row.get("from") or ""
                        ),
                        "to_team": str(row.get("to_team") or row.get("to") or ""),
                    }
                )
    except OSError:
        return []
    entries.sort(key=lambda e: e.get("date") or "")
    return entries


__all__ = [
    "ProfileNote",
    "TrainingFocusSummary",
    "PlayerProfileViewModel",
    "build_player_profile_view_model",
]
