"""League season-history aggregation (server-safe).

Ported verbatim from the retired ``ui.league_history_window`` PyQt module
(removed in v6.14.52 "retire PyQt UI") so the ``GET /league/history`` API
endpoint no longer depends on a desktop-only module. Pure logic: walks the
``SeasonContext`` archive and resolves each season's champion / runner-up /
series-result / MVP / Cy Young from the committed artifacts, with a playoff
bracket fallback. No Qt, no UI imports.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from playbalance.season_context import SeasonContext
from utils.path_utils import get_data_dir, resolve_app_path

__all__ = ["SeasonHistoryEntry", "load_history_entries"]


@dataclass
class SeasonHistoryEntry:
    season_id: str
    league_year: str
    ended_on: str
    archived_on: str
    champion: str
    runner_up: str
    series_result: str
    mvp: str
    cy_young: str
    artifacts: Dict[str, str]


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def _resolve_path(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    candidate = Path(path_str)
    if not candidate.is_absolute():
        candidate = resolve_app_path(candidate)
    return candidate


def _display(value: object, default: str = "-") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _load_awards(path: Path | None) -> Dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = _read_json(path, {})
    awards = payload.get("awards", {})
    if isinstance(awards, dict):
        return awards
    return {}


def _award_name(awards: Dict[str, Any], key: str) -> str:
    entry = awards.get(key, {})
    if not isinstance(entry, dict):
        return "-"
    name = str(entry.get("player_name") or "").strip()
    if not name:
        name = str(entry.get("player_id") or "").strip()
    return name or "-"


def _load_champion(path: Path | None, league_year: str) -> tuple[str, str, str]:
    if not league_year:
        return "", "", ""
    if path is None or not path.exists():
        return "", "", ""
    target = league_year.strip()
    selected = None
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if not row:
                    continue
                if target and str(row.get("year", "")).strip() != target:
                    continue
                selected = row
    except OSError:
        return "", "", ""
    if not selected:
        return "", "", ""
    return (
        str(selected.get("champion", "") or "").strip(),
        str(selected.get("runner_up", "") or "").strip(),
        str(selected.get("series_result", "") or "").strip(),
    )


def _final_round_from_bracket(bracket: object) -> object | None:
    try:
        rounds = list(getattr(bracket, "rounds", []) or [])
    except Exception:
        rounds = []
    if not rounds:
        return None

    def _is_final(name: str) -> bool:
        tokens = [
            t.lower()
            for t in str(name or "").replace("-", " ").replace("_", " ").split()
            if t
        ]
        finals = {"ws", "world", "worlds", "final", "finals", "championship"}
        return any(t in finals for t in tokens)

    finals = [r for r in rounds if _is_final(getattr(r, "name", ""))]
    if finals:
        return finals[-1]
    return rounds[-1]


def _series_result_from_bracket(bracket: object) -> str:
    try:
        champ = getattr(bracket, "champion", None)
        if not champ:
            return ""
        final_round = _final_round_from_bracket(bracket)
        if final_round is None:
            return ""
        matchups = list(getattr(final_round, "matchups", []) or [])
        if not matchups:
            return ""
        matchup = matchups[0]
        wins_c = 0
        wins_o = 0
        for game in list(getattr(matchup, "games", []) or []):
            res = str(getattr(game, "result", "") or "")
            if "-" not in res:
                continue
            try:
                home_score, away_score = map(int, res.split("-", 1))
            except Exception:
                continue
            if home_score > away_score:
                winner = getattr(game, "home", "")
            elif away_score > home_score:
                winner = getattr(game, "away", "")
            else:
                continue
            if winner == champ:
                wins_c += 1
            else:
                wins_o += 1
        return f"{wins_c}-{wins_o}" if (wins_c or wins_o) else ""
    except Exception:
        return ""


def _load_champion_from_bracket(path: Path | None, league_year: str) -> tuple[str, str, str]:
    if not league_year or path is None or not path.exists():
        return "", "", ""
    try:
        from playbalance.playoffs import load_bracket
    except Exception:
        return "", "", ""
    try:
        bracket = load_bracket(path=path)
    except Exception:
        bracket = None
    if bracket is None:
        return "", "", ""
    try:
        bracket_year = int(getattr(bracket, "year", 0) or 0)
    except Exception:
        bracket_year = 0
    if bracket_year and str(bracket_year) != league_year.strip():
        return "", "", ""

    champion = str(getattr(bracket, "champion", "") or "").strip()
    runner_up = str(getattr(bracket, "runner_up", "") or "").strip()
    series_result = _series_result_from_bracket(bracket)

    if champion and not runner_up:
        try:
            final_round = _final_round_from_bracket(bracket)
            matchups = list(getattr(final_round, "matchups", []) or []) if final_round else []
            if matchups:
                matchup = matchups[0]
                high = getattr(matchup, "high", None)
                low = getattr(matchup, "low", None)
                high_id = getattr(high, "team_id", None) if high else None
                low_id = getattr(low, "team_id", None) if low else None
                if high_id and low_id:
                    runner_up = low_id if champion == high_id else high_id
        except Exception:
            pass

    return champion, runner_up, series_result


def _season_artifacts(season: Dict[str, Any], season_id: str) -> Dict[str, str]:
    artifacts = season.get("artifacts")
    if isinstance(artifacts, dict) and artifacts:
        return {
            str(key): str(value)
            for key, value in artifacts.items()
            if value
        }
    meta_path = get_data_dir() / "careers" / season_id / "metadata.json"
    payload = _read_json(meta_path, {})
    meta_artifacts = payload.get("artifacts", {})
    if isinstance(meta_artifacts, dict) and meta_artifacts:
        return {
            str(key): str(value)
            for key, value in meta_artifacts.items()
            if value
        }
    return {}


def load_history_entries() -> List[SeasonHistoryEntry]:
    """Return one :class:`SeasonHistoryEntry` per archived season, newest first."""

    context = SeasonContext.load()
    entries: List[SeasonHistoryEntry] = []
    seasons = list(context.seasons)
    for season in reversed(seasons):
        if not isinstance(season, dict):
            continue
        season_id = str(season.get("season_id", "") or "").strip()
        if not season_id:
            continue
        league_year = _display(season.get("league_year"), "")
        ended_on = _display(season.get("ended_on"), "")
        archived_on = _display(season.get("archived_on"), "")
        artifacts = _season_artifacts(season, season_id)
        awards = _load_awards(_resolve_path(artifacts.get("awards")))
        champions_path = _resolve_path(artifacts.get("champions"))
        champion, runner_up, series_result = _load_champion(champions_path, league_year)
        if not (champion and runner_up and series_result):
            playoffs_path = _resolve_path(artifacts.get("playoffs"))
            b_champ, b_runner, b_series = _load_champion_from_bracket(playoffs_path, league_year)
            if not champion and b_champ:
                champion = b_champ
            if not runner_up and b_runner:
                runner_up = b_runner
            if not series_result and b_series:
                series_result = b_series
        entries.append(
            SeasonHistoryEntry(
                season_id=season_id,
                league_year=league_year,
                ended_on=ended_on,
                archived_on=archived_on,
                champion=champion,
                runner_up=runner_up,
                series_result=series_result,
                mvp=_award_name(awards, "MVP"),
                cy_young=_award_name(awards, "CY_YOUNG"),
                artifacts=artifacts,
            )
        )
    return entries
