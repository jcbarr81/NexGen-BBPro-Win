"""Hall of Fame eligibility, scoring, and persistence helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from playbalance.season_context import SeasonContext, CAREER_DATA_DIR
from utils.news_logger import log_news_event
from utils.path_utils import ActivePath, get_data_dir, resolve_app_path

HALL_OF_FAME_PATH = ActivePath(lambda: get_data_dir() / "hall_of_fame.json")
HALL_OF_FAME_VERSION = 1
DEFAULT_MIN_YEARS_RETIRED = 5
DEFAULT_SCORE_THRESHOLD = 120.0

AWARD_WEIGHTS = {
    "MVP": 25.0,
    "CY_YOUNG": 25.0,
    "ROY": 12.0,
    "ROOKIE_OF_THE_YEAR": 12.0,
    "GOLD_GLOVE": 8.0,
    "SILVER_SLUGGER": 8.0,
}
DEFAULT_AWARD_WEIGHT = 6.0


@dataclass(frozen=True)
class HallOfFameCandidate:
    player_id: str
    player_name: str
    is_pitcher: bool
    position: str
    last_season_year: int
    eligible_year: int
    years_retired: int
    score: float
    eligible: bool
    awards: Dict[str, int]


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _default_payload() -> Dict[str, Any]:
    return {
        "version": HALL_OF_FAME_VERSION,
        "settings": {
            "min_years_retired": DEFAULT_MIN_YEARS_RETIRED,
            "score_threshold": DEFAULT_SCORE_THRESHOLD,
        },
        "inductees": [],
        "exclusions": {},
        "updated_at": _now_iso(),
    }


def load_hall_of_fame(path: Path | None = None) -> Dict[str, Any]:
    target = path or HALL_OF_FAME_PATH
    if not target.exists():
        return _default_payload()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_payload()
    if not isinstance(payload, dict):
        return _default_payload()
    defaults = _default_payload()
    merged = dict(defaults)
    merged.update(payload)
    settings = dict(defaults.get("settings", {}))
    settings.update(payload.get("settings", {}) if isinstance(payload.get("settings"), dict) else {})
    merged["settings"] = settings
    if not isinstance(merged.get("inductees"), list):
        merged["inductees"] = []
    if not isinstance(merged.get("exclusions"), dict):
        merged["exclusions"] = {}
    return merged


def save_hall_of_fame(payload: Dict[str, Any], path: Path | None = None) -> None:
    target = path or HALL_OF_FAME_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["version"] = HALL_OF_FAME_VERSION
    payload["updated_at"] = _now_iso()
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def list_inductees() -> List[Dict[str, Any]]:
    payload = load_hall_of_fame()
    inductees = [entry for entry in payload.get("inductees", []) if isinstance(entry, dict)]
    inductees.sort(key=lambda item: (item.get("inducted_year", 0), item.get("player_name", "")), reverse=True)
    return inductees


def list_candidates(*, current_year: Optional[int] = None) -> List[HallOfFameCandidate]:
    context = SeasonContext.load()
    year = _resolve_current_year(context, current_year)
    payload = load_hall_of_fame()
    settings = payload.get("settings", {})
    min_years = _safe_int(settings.get("min_years_retired"), DEFAULT_MIN_YEARS_RETIRED)
    snapshots = _load_archived_player_snapshots(context)
    if not snapshots:
        return []
    career_totals = _load_career_totals()
    active_ids = _load_active_player_ids()
    award_counts = _load_award_counts(context)
    candidates: List[HallOfFameCandidate] = []
    for player_id, snapshot in snapshots.items():
        if player_id in active_ids:
            continue
        last_year = snapshot["last_season_year"]
        years_retired = year - last_year if year else 0
        eligible_year = last_year + min_years
        eligible = bool(years_retired >= min_years)
        totals = career_totals.get(player_id, {})
        awards = award_counts.get(player_id, {})
        score = _score_player(totals, awards, snapshot["is_pitcher"])
        candidates.append(
            HallOfFameCandidate(
                player_id=player_id,
                player_name=snapshot["player_name"],
                is_pitcher=snapshot["is_pitcher"],
                position=snapshot["position"],
                last_season_year=last_year,
                eligible_year=eligible_year,
                years_retired=years_retired,
                score=score,
                eligible=eligible,
                awards=awards,
            )
        )
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates


def update_hall_of_fame(*, current_year: Optional[int] = None) -> Dict[str, Any]:
    payload = load_hall_of_fame()
    settings = payload.get("settings", {})
    min_years = _safe_int(settings.get("min_years_retired"), DEFAULT_MIN_YEARS_RETIRED)
    threshold = _safe_float(settings.get("score_threshold"), DEFAULT_SCORE_THRESHOLD)
    candidates = list_candidates(current_year=current_year)
    inducted_ids = {
        str(entry.get("player_id"))
        for entry in payload.get("inductees", [])
        if isinstance(entry, dict) and entry.get("player_id")
    }
    exclusions = payload.get("exclusions", {}) if isinstance(payload.get("exclusions"), dict) else {}
    additions: List[Dict[str, Any]] = []
    year = _resolve_current_year(SeasonContext.load(), current_year)
    for candidate in candidates:
        if candidate.player_id in inducted_ids:
            continue
        if candidate.player_id in exclusions:
            continue
        if not candidate.eligible or candidate.years_retired < min_years:
            continue
        if candidate.score < threshold:
            continue
        additions.append(
            _candidate_to_inductee(
                candidate,
                inducted_year=year,
                source="auto",
            )
        )
    if additions:
        payload.setdefault("inductees", [])
        payload["inductees"].extend(additions)
        save_hall_of_fame(payload)
        try:
            names = ", ".join([entry.get("player_name", "") for entry in additions if entry.get("player_name")])
            if names:
                log_news_event(f"Hall of Fame induction class: {names}")
        except Exception:
            pass
    else:
        save_hall_of_fame(payload)
    return {"added": additions, "total": len(payload.get("inductees", []))}


def add_manual_inductee(player_id: str, *, current_year: Optional[int] = None, note: str | None = None) -> Dict[str, Any]:
    if not player_id:
        raise ValueError("player_id is required")
    payload = load_hall_of_fame()
    inducted = payload.get("inductees", [])
    inducted_ids = {str(entry.get("player_id")) for entry in inducted if isinstance(entry, dict)}
    if player_id in inducted_ids:
        return {"status": "exists", "player_id": player_id}
    exclusions = payload.get("exclusions", {}) if isinstance(payload.get("exclusions"), dict) else {}
    exclusions.pop(player_id, None)
    payload["exclusions"] = exclusions
    candidate = _candidate_lookup(player_id, current_year=current_year)
    if candidate is None:
        raise ValueError("Player not found or not retired.")
    entry = _candidate_to_inductee(
        candidate,
        inducted_year=_resolve_current_year(SeasonContext.load(), current_year),
        source="manual",
        note=note,
    )
    inducted.append(entry)
    payload["inductees"] = inducted
    save_hall_of_fame(payload)
    return {"status": "added", "entry": entry}


def remove_inductee(player_id: str, *, reason: str | None = None) -> Dict[str, Any]:
    if not player_id:
        raise ValueError("player_id is required")
    payload = load_hall_of_fame()
    inducted = [entry for entry in payload.get("inductees", []) if isinstance(entry, dict)]
    remaining = [entry for entry in inducted if str(entry.get("player_id")) != player_id]
    removed = len(remaining) != len(inducted)
    payload["inductees"] = remaining
    exclusions = payload.get("exclusions", {}) if isinstance(payload.get("exclusions"), dict) else {}
    exclusions[player_id] = {
        "removed_on": _now_iso(),
        "reason": reason or "manual",
    }
    payload["exclusions"] = exclusions
    save_hall_of_fame(payload)
    return {"status": "removed" if removed else "missing", "player_id": player_id}


def _candidate_lookup(player_id: str, *, current_year: Optional[int]) -> Optional[HallOfFameCandidate]:
    for candidate in list_candidates(current_year=current_year):
        if candidate.player_id == player_id:
            return candidate
    return None


def _candidate_to_inductee(
    candidate: HallOfFameCandidate,
    *,
    inducted_year: Optional[int],
    source: str,
    note: str | None = None,
) -> Dict[str, Any]:
    entry = {
        "player_id": candidate.player_id,
        "player_name": candidate.player_name,
        "inducted_year": inducted_year or candidate.eligible_year,
        "last_season_year": candidate.last_season_year,
        "eligible_year": candidate.eligible_year,
        "score": round(candidate.score, 2),
        "position": candidate.position,
        "is_pitcher": candidate.is_pitcher,
        "source": source,
        "awards": candidate.awards,
    }
    if note:
        entry["note"] = note
    return entry


def _resolve_current_year(context: SeasonContext, provided: Optional[int]) -> int:
    if provided is not None:
        return int(provided)
    try:
        current = context.current if isinstance(context.current, dict) else {}
        raw = current.get("league_year")
        if raw is not None:
            return int(raw)
    except Exception:
        pass
    return date.today().year


def _load_active_player_ids() -> set[str]:
    path = get_data_dir() / "players.csv"
    if not path.exists():
        return set()
    ids: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                pid = str(row.get("player_id") or "").strip()
                if pid:
                    ids.add(pid)
    except Exception:
        return ids
    return ids


def _load_career_totals() -> Dict[str, Dict[str, Any]]:
    path = CAREER_DATA_DIR / "career_players.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    players = payload.get("players", {})
    if not isinstance(players, dict):
        return {}
    totals: Dict[str, Dict[str, Any]] = {}
    for pid, entry in players.items():
        if not isinstance(entry, dict):
            continue
        totals[pid] = entry.get("totals", {}) if isinstance(entry.get("totals"), dict) else {}
    return totals


def _load_archived_player_snapshots(context: SeasonContext) -> Dict[str, Dict[str, Any]]:
    snapshots: Dict[str, Dict[str, Any]] = {}
    seasons = list(context.seasons)
    for season in seasons:
        if not isinstance(season, dict):
            continue
        season_id = str(season.get("season_id") or "").strip()
        if not season_id:
            continue
        year = _season_year(season_id, season.get("league_year"))
        if year is None:
            continue
        players_path = _season_players_path(season, season_id)
        if players_path is None or not players_path.exists():
            continue
        try:
            with players_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    pid = str(row.get("player_id") or "").strip()
                    if not pid:
                        continue
                    prev = snapshots.get(pid)
                    if prev and year <= prev.get("last_season_year", 0):
                        continue
                    first = str(row.get("first_name") or "").strip()
                    last = str(row.get("last_name") or "").strip()
                    name = f"{first} {last}".strip() or pid
                    position = str(row.get("primary_position") or "").strip()
                    is_pitcher = _safe_bool(row.get("is_pitcher"))
                    snapshots[pid] = {
                        "player_id": pid,
                        "player_name": name,
                        "position": position,
                        "is_pitcher": is_pitcher,
                        "last_season_year": year,
                    }
        except Exception:
            continue
    return snapshots


def _load_award_counts(context: SeasonContext) -> Dict[str, Dict[str, int]]:
    counts: Dict[str, Dict[str, int]] = {}
    seasons = list(context.seasons)
    for season in seasons:
        if not isinstance(season, dict):
            continue
        season_id = str(season.get("season_id") or "").strip()
        if not season_id:
            continue
        awards_path = _season_awards_path(season, season_id)
        if awards_path is None or not awards_path.exists():
            continue
        try:
            payload = json.loads(awards_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        awards = payload.get("awards", {}) if isinstance(payload, dict) else {}
        if not isinstance(awards, dict):
            continue
        for award_key, info in awards.items():
            if not isinstance(info, dict):
                continue
            pid = str(info.get("player_id") or "").strip()
            if not pid:
                continue
            per_player = counts.setdefault(pid, {})
            key = str(award_key or "").strip()
            if not key:
                continue
            per_player[key] = int(per_player.get(key, 0)) + 1
    return counts


def _season_year(season_id: str, raw_year: Any) -> Optional[int]:
    try:
        if raw_year is not None:
            return int(raw_year)
    except Exception:
        pass
    try:
        token = str(season_id).split("-")[-1]
        return int(token)
    except Exception:
        return None


def _season_players_path(season: Dict[str, Any], season_id: str) -> Optional[Path]:
    artifacts = _season_artifacts(season, season_id)
    path_str = artifacts.get("players")
    if path_str:
        return _resolve_path(path_str)
    candidate = CAREER_DATA_DIR / season_id / "players.csv"
    return candidate if candidate.exists() else None


def _season_awards_path(season: Dict[str, Any], season_id: str) -> Optional[Path]:
    artifacts = _season_artifacts(season, season_id)
    path_str = artifacts.get("awards")
    if path_str:
        return _resolve_path(path_str)
    candidate = CAREER_DATA_DIR / season_id / "awards.json"
    return candidate if candidate.exists() else None


def _season_artifacts(season: Dict[str, Any], season_id: str) -> Dict[str, str]:
    artifacts = season.get("artifacts")
    if isinstance(artifacts, dict) and artifacts:
        return {str(key): str(value) for key, value in artifacts.items() if value}
    meta_path = get_data_dir() / "careers" / season_id / "metadata.json"
    if not meta_path.exists():
        return {}
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    meta_artifacts = payload.get("artifacts", {})
    if isinstance(meta_artifacts, dict) and meta_artifacts:
        return {str(key): str(value) for key, value in meta_artifacts.items() if value}
    return {}


def _resolve_path(path_str: str) -> Optional[Path]:
    if not path_str:
        return None
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = resolve_app_path(candidate)
    return candidate


def _score_player(stats: Dict[str, Any], awards: Dict[str, int], is_pitcher: bool) -> float:
    if is_pitcher:
        return _score_pitcher(stats, awards)
    return _score_hitter(stats, awards)


def _score_hitter(stats: Dict[str, Any], awards: Dict[str, int]) -> float:
    data = _normalize_player_stats(stats)
    hits = _safe_int(data.get("h"))
    hr = _safe_int(data.get("hr"))
    rbi = _safe_int(data.get("rbi"))
    bb = _safe_int(data.get("bb"))
    sb = _safe_int(data.get("sb"))
    runs = _safe_int(data.get("r"))
    games = _safe_int(data.get("g"))
    war = _safe_float(data.get("war"))
    score = 0.0
    score += hits * 0.02
    score += hr * 0.6
    score += rbi * 0.2
    score += bb * 0.05
    score += sb * 0.1
    score += runs * 0.1
    score += games * 0.01
    score += war * 8.0
    score += _awards_score(awards)
    return score


def _score_pitcher(stats: Dict[str, Any], awards: Dict[str, int]) -> float:
    data = _normalize_player_stats(stats)
    wins = _safe_int(data.get("w"))
    saves = _safe_int(data.get("sv"))
    strikeouts = _safe_int(data.get("so"))
    ip = _safe_float(data.get("ip"))
    if not ip:
        outs = _safe_float(data.get("outs"))
        ip = outs / 3.0 if outs else 0.0
    er = _safe_float(data.get("er"))
    era = (er * 9.0) / ip if ip else None
    war = _safe_float(data.get("war"))
    score = 0.0
    score += wins * 0.3
    score += saves * 0.4
    score += strikeouts * 0.015
    score += ip * 0.02
    score += war * 8.0
    if era is not None:
        score += max(0.0, 4.5 - era) * 8.0
    score += _awards_score(awards)
    return score


def _awards_score(awards: Dict[str, int]) -> float:
    score = 0.0
    for award, count in awards.items():
        weight = AWARD_WEIGHTS.get(str(award).upper(), DEFAULT_AWARD_WEIGHT)
        score += weight * int(count or 0)
    return score


def _normalize_player_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(stats or {})
    if "b2" in data and "2b" not in data:
        data["2b"] = data.get("b2", 0)
    if "b3" in data and "3b" not in data:
        data["3b"] = data.get("b3", 0)
    if "wins" in data and "w" not in data:
        data["w"] = data.get("wins", 0)
    if "losses" in data and "l" not in data:
        data["l"] = data.get("losses", 0)
    return data


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_bool(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


__all__ = [
    "load_hall_of_fame",
    "save_hall_of_fame",
    "list_inductees",
    "list_candidates",
    "update_hall_of_fame",
    "add_manual_inductee",
    "remove_inductee",
    "HallOfFameCandidate",
]
