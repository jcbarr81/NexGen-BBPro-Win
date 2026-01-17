from __future__ import annotations

"""League rollover archival service."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import csv
import json
import shutil

from playbalance.awards_manager import AwardsManager
from playbalance.season_context import CAREER_DATA_DIR, SeasonContext
from services.transaction_log import TRANSACTION_COLUMNS, reset_player_cache as reset_transaction_cache
from services.standings_repository import save_standings
from utils.path_utils import get_base_dir
from utils.player_loader import load_players_from_csv
from utils.sim_date import get_current_sim_date
from utils.stats_persistence import load_stats, merge_daily_history, reset_stats

_DATA_DIR = get_base_dir() / "data"
_STATS_PATH = _DATA_DIR / "season_stats.json"
_STANDINGS_PATH = _DATA_DIR / "standings.json"
_SCHEDULE_PATH = _DATA_DIR / "schedule.csv"
_PROGRESS_PATH = _DATA_DIR / "season_progress.json"
_TRANSACTIONS_PATH = _DATA_DIR / "transactions.csv"
_SEASON_HISTORY_DIR = _DATA_DIR / "season_history"
_PLAYOFFS_GENERIC = _DATA_DIR / "playoffs.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def _copy_file(src: Path, dst: Path) -> Optional[Path]:
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return dst
    except FileNotFoundError:
        return None
    except OSError:
        return None


def _relative(path: Path) -> str:
    base = get_base_dir()
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _aggregate_numeric(dicts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    totals: Dict[str, Any] = {}
    for entry in dicts.values():
        for key, value in entry.items():
            if isinstance(value, (int, float)):
                if key not in totals:
                    totals[key] = 0 if isinstance(value, int) and not isinstance(value, bool) else 0.0
                totals[key] += value
    return totals


@dataclass
class RolloverResult:
    status: str
    season_id: str
    artifacts: Dict[str, str]
    metadata_path: Optional[str] = None
    next_season: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


class LeagueRolloverService:
    """Archive current season artifacts and reset state for the next season."""

    def __init__(self, context: SeasonContext | None = None) -> None:
        self.context = context or SeasonContext.load()
        self.base_dir = get_base_dir()
        self.context.ensure_current_season()

    # ------------------------------------------------------------------
    def archive_season(
        self,
        *,
        ended_on: str | None = None,
        next_league_year: int | None = None,
        force: bool = False,
    ) -> RolloverResult:
        current = self.context.ensure_current_season()
        season_id = current.get("season_id")
        if not season_id:
            raise RuntimeError("Season identifier unavailable; cannot archive season.")

        if current.get("rollover_complete") and not force:
            return RolloverResult(
                status="skipped",
                season_id=season_id,
                artifacts={},
                reason="Season already marked as rolled over.",
                next_season=self.context.current,
            )

        league_year = current.get("league_year")
        season_dir = CAREER_DATA_DIR / season_id
        season_dir.mkdir(parents=True, exist_ok=True)
        artifacts: Dict[str, str] = {}

        stats_payload = self._archive_stats(season_dir, artifacts)
        players_path = self._archive_file(_DATA_DIR / "players.csv", season_dir / "players.csv", artifacts, "players")
        standings_path = self._archive_file(_STANDINGS_PATH, season_dir / "standings.json", artifacts, "standings")
        schedule_path = self._archive_file(_SCHEDULE_PATH, season_dir / "schedule.csv", artifacts, "schedule")
        progress_path = self._archive_file(_PROGRESS_PATH, season_dir / "season_progress.json", artifacts, "progress")
        self._archive_history(season_dir, artifacts)
        playoffs_path = self._archive_playoffs(season_dir, artifacts, league_year)
        champions_path = self._archive_file(_DATA_DIR / "champions.csv", season_dir / "champions.csv", artifacts, "champions")
        transactions_path = self._archive_file(_TRANSACTIONS_PATH, season_dir / "transactions.csv", artifacts, "transactions")
        self._archive_file(_DATA_DIR / "special_events.json", season_dir / "special_events.json", artifacts, "special_events")
        self._archive_draft_assets(season_dir, artifacts, league_year)

        awards_path = self._archive_awards(season_dir, stats_payload, artifacts)

        ended_val = ended_on or get_current_sim_date() or datetime.utcnow().date().isoformat()
        metadata = {
            "season_id": season_id,
            "league_year": league_year,
            "sequence": current.get("sequence"),
            "archived_on": _now_iso(),
            "ended_on": ended_val,
            "artifacts": artifacts,
            "sources": {
                "stats": _relative(_STATS_PATH),
                "standings": _relative(_STANDINGS_PATH) if standings_path else None,
                "schedule": _relative(_SCHEDULE_PATH) if schedule_path else None,
                "season_progress": _relative(_PROGRESS_PATH) if progress_path else None,
                "playoffs": _relative(playoffs_path) if playoffs_path else None,
                "transactions": _relative(_TRANSACTIONS_PATH) if transactions_path else None,
                "champions": _relative(_DATA_DIR / "champions.csv") if champions_path else None,
                "players": _relative(_DATA_DIR / "players.csv") if players_path else None,
            },
        }
        metadata_path = season_dir / "metadata.json"
        _write_json(metadata_path, metadata)
        artifacts["metadata"] = _relative(metadata_path)

        self._update_career_ledgers(season_id, stats_payload)
        next_descriptor = self.context.archive_current_season(
            artifacts=artifacts,
            ended_on=ended_val,
            next_league_year=next_league_year,
        )

        self._reset_active_state(league_year)

        return RolloverResult(
            status="archived",
            season_id=season_id,
            artifacts=artifacts,
            metadata_path=_relative(metadata_path),
            next_season=next_descriptor,
        )

    # ------------------------------------------------------------------
    def _archive_stats(self, season_dir: Path, artifacts: Dict[str, str]) -> Dict[str, Any]:
        merge_daily_history()
        stats_payload = load_stats()
        out_path = season_dir / "stats.json"
        _write_json(out_path, stats_payload)
        artifacts["stats"] = _relative(out_path)
        return stats_payload

    def _archive_history(self, season_dir: Path, artifacts: Dict[str, str]) -> None:
        if not _SEASON_HISTORY_DIR.exists():
            return
        dest = season_dir / "history"
        dest.mkdir(parents=True, exist_ok=True)
        for shard in _SEASON_HISTORY_DIR.glob("*.json"):
            _copy_file(shard, dest / shard.name)
        artifacts["history"] = _relative(dest)

    def _archive_playoffs(
        self,
        season_dir: Path,
        artifacts: Dict[str, str],
        league_year: Optional[int],
    ) -> Optional[Path]:
        candidate_paths = []
        if league_year:
            candidate_paths.append(_DATA_DIR / f"playoffs_{league_year}.json")
        candidate_paths.append(_PLAYOFFS_GENERIC)
        for src in candidate_paths:
            if src.exists():
                dst = season_dir / src.name
                copied = _copy_file(src, dst)
                if copied:
                    artifacts["playoffs"] = _relative(copied)
                    return copied
        return None

    def _archive_draft_assets(
        self,
        season_dir: Path,
        artifacts: Dict[str, str],
        league_year: Optional[int],
    ) -> None:
        if not league_year:
            return
        draft_dir = season_dir / "draft"
        copied_any = False
        for suffix in ("csv", "json"):
            pool_src = _DATA_DIR / f"draft_pool_{league_year}.{suffix}"
            pool_dst = draft_dir / pool_src.name
            if _copy_file(pool_src, pool_dst):
                copied_any = True
        state_src = _DATA_DIR / f"draft_state_{league_year}.json"
        results_src = _DATA_DIR / f"draft_results_{league_year}.csv"
        for src in (state_src, results_src):
            dst = draft_dir / src.name
            if _copy_file(src, dst):
                copied_any = True
        if copied_any:
            artifacts["draft"] = _relative(draft_dir)

    def _archive_awards(
        self,
        season_dir: Path,
        stats_payload: Dict[str, Any],
        artifacts: Dict[str, str],
    ) -> Optional[Path]:
        try:
            players = load_players_from_csv("data/players.csv")
        except Exception:
            players = []
        player_stats: Dict[str, Dict[str, Any]] = stats_payload.get("players", {})
        if not players or not player_stats:
            return None
        team_stats: Dict[str, Dict[str, Any]] = stats_payload.get("teams", {})
        player_lookup = {p.player_id: p for p in players}
        batting = {
            pid: stats
            for pid, stats in player_stats.items()
            if pid in player_lookup and (stats.get("pa") or stats.get("ab"))
        }
        pitching = {
            pid: stats
            for pid, stats in player_stats.items()
            if pid in player_lookup and (stats.get("ip") or stats.get("era") is not None)
        }
        if not batting or not pitching:
            return None
        max_games = 0
        try:
            games_list = [
                int(v.get("g", v.get("games", 0)) or 0)
                for v in team_stats.values()
            ]
            max_games = max(games_list) if games_list else 0
        except Exception:
            max_games = 0
        min_pa = int(round(max_games * 3.1)) if max_games else 0
        min_ip = float(round(max_games * 1.0, 2)) if max_games else 0.0
        awards = {}
        try:
            manager = AwardsManager(
                player_lookup,
                batting,
                pitching,
                min_pa=min_pa,
                min_ip=min_ip,
            )
            winners = manager.select_award_winners()
            for name, winner in winners.items():
                player = winner.player
                awards[name] = {
                    "player_id": player.player_id,
                    "player_name": f"{player.first_name} {player.last_name}".strip(),
                    "metric": winner.metric,
                }
        except Exception:
            awards = {}
        payload = {"awards": awards, "generated_at": _now_iso()}
        awards_path = season_dir / "awards.json"
        _write_json(awards_path, payload)
        artifacts["awards"] = _relative(awards_path)
        return awards_path

    def _archive_file(
        self,
        src: Path,
        dst: Path,
        artifacts: Dict[str, str],
        label: str,
    ) -> Optional[Path]:
        copied = _copy_file(src, dst)
        if copied:
            artifacts[label] = _relative(copied)
        return copied

    # ------------------------------------------------------------------
    def _update_career_ledgers(self, season_id: str, stats_payload: Dict[str, Any]) -> None:
        CAREER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        players_doc = _read_json(CAREER_DATA_DIR / "career_players.json", {"version": 1, "players": {}})
        teams_doc = _read_json(CAREER_DATA_DIR / "career_teams.json", {"version": 1, "teams": {}})

        players_map: Dict[str, Dict[str, Any]] = players_doc.setdefault("players", {})
        teams_map: Dict[str, Dict[str, Any]] = teams_doc.setdefault("teams", {})

        for pid, stats in stats_payload.get("players", {}).items():
            player_entry = players_map.setdefault(pid, {"seasons": {}, "totals": {}})
            player_entry.setdefault("seasons", {})
            player_entry["seasons"][season_id] = stats
            player_entry["totals"] = _aggregate_numeric(player_entry["seasons"])

        for tid, stats in stats_payload.get("teams", {}).items():
            team_entry = teams_map.setdefault(tid, {"seasons": {}, "totals": {}})
            team_entry.setdefault("seasons", {})
            team_entry["seasons"][season_id] = stats
            team_entry["totals"] = _aggregate_numeric(team_entry["seasons"])

        players_doc["updated_at"] = _now_iso()
        teams_doc["updated_at"] = _now_iso()

        _write_json(CAREER_DATA_DIR / "career_players.json", players_doc)
        _write_json(CAREER_DATA_DIR / "career_teams.json", teams_doc)

        # Clear cached player loaders so subsequent calls pick up updated career stats.
        try:
            load_players_from_csv.cache_clear()
        except AttributeError:
            pass
        reset_transaction_cache()

    # ------------------------------------------------------------------
    def _reset_active_state(self, league_year: Optional[int]) -> None:
        try:
            reset_stats(_STATS_PATH)
        except Exception:
            _write_json(_STATS_PATH, {"players": {}, "teams": {}, "history": []})
        if _SEASON_HISTORY_DIR.exists():
            for shard in _SEASON_HISTORY_DIR.glob("*.json"):
                try:
                    shard.unlink()
                except OSError:
                    pass
        save_standings({}, base_path=_STANDINGS_PATH)

        if _SCHEDULE_PATH.exists():
            try:
                _SCHEDULE_PATH.unlink()
            except OSError:
                pass

        if league_year:
            playoff_path = _DATA_DIR / f"playoffs_{league_year}.json"
            for candidate in (playoff_path, playoff_path.with_suffix(playoff_path.suffix + ".bak")):
                if candidate.exists():
                    try:
                        candidate.unlink()
                    except OSError:
                        pass
        if _PLAYOFFS_GENERIC.exists():
            try:
                _PLAYOFFS_GENERIC.unlink()
            except OSError:
                pass

        pitcher_recovery_path = _DATA_DIR / "pitcher_recovery.json"
        if pitcher_recovery_path.exists():
            try:
                pitcher_recovery_path.unlink()
            except OSError:
                pass

        try:
            from services.special_events import reset_special_events

            reset_special_events()
        except Exception:
            events_path = _DATA_DIR / "special_events.json"
            if events_path.exists():
                try:
                    events_path.unlink()
                except OSError:
                    pass

        self._reset_transactions_file()
        self._reset_progress_file()
        self._unlock_rosters()

    def _reset_transactions_file(self) -> None:
        _TRANSACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _TRANSACTIONS_PATH.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=TRANSACTION_COLUMNS)
            writer.writeheader()

    def _reset_progress_file(self) -> None:
        payload = {
            "preseason_done": {"free_agency": False, "training_camp": False, "schedule": False},
            "sim_index": 0,
            "playoffs_done": False,
            "draft_completed_years": [],
        }
        _write_json(_PROGRESS_PATH, payload)

    def _unlock_rosters(self) -> None:
        roster_dir = _DATA_DIR / "rosters"
        if not roster_dir.exists():
            return
        for csv_file in roster_dir.glob("*.csv"):
            try:
                csv_file.chmod(0o644)
            except OSError:
                pass
