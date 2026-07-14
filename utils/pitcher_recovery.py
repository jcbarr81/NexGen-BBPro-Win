from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import csv
from datetime import date, datetime, timedelta
import functools
import json
from pathlib import Path
from typing import Dict, Iterable, Optional

from utils.path_utils import get_base_dir, resolve_app_path
from utils.pitcher_role import get_role
from utils.player_loader import load_players_from_csv
from utils.roster_loader import load_roster

_DATE_FORMAT = "%Y-%m-%d"
_EPOCH = date(1970, 1, 1)


def _resolve_path(path: str | Path) -> Path:
    return resolve_app_path(path)


def _parse_date(value: str | None) -> date:
    if not value:
        return _EPOCH
    try:
        return datetime.strptime(value, _DATE_FORMAT).date()
    except ValueError:
        return _EPOCH


def _format_date(value: date) -> str:
    return value.strftime(_DATE_FORMAT)


@functools.lru_cache(maxsize=512)
def _rest_days(pitches: int) -> int:
    """Return rest days required after throwing ``pitches``.

    When ``enableUsageModelV2`` is active in the PlayBalance config, apply
    configurable pitch-count thresholds. Otherwise, fall back to the legacy
    step function.

    Pure function of ``pitches`` + the static bundled PBINI.txt tuning (which
    only changes on deploy → fresh process), so it's safe to memoize. This
    removes the repeated per-game PBINI.txt parse the profiler flagged in the
    pitcher-recovery path.
    """

    if pitches <= 0:
        return 0

    # Lazy import to avoid module-level dependency and potential cycles
    try:
        from playbalance.playbalance_config import PlayBalanceConfig  # type: ignore
    except Exception:
        PlayBalanceConfig = None  # type: ignore

    cfg = None
    if PlayBalanceConfig is not None:
        try:
            base = get_base_dir()
            cfg = PlayBalanceConfig.from_file(base / "playbalance" / "PBINI.txt")
        except Exception:
            cfg = None

    # Usage Model V2 thresholds: ≤Lvl0→0d, ≤Lvl1→1d, …, >Lvl5→6d
    if cfg is not None and int(cfg.get("enableUsageModelV2", 0)):
        lvl0 = int(cfg.get("restDaysPitchesLvl0", 10))
        lvl1 = int(cfg.get("restDaysPitchesLvl1", 20))
        lvl2 = int(cfg.get("restDaysPitchesLvl2", 35))
        lvl3 = int(cfg.get("restDaysPitchesLvl3", 50))
        lvl4 = int(cfg.get("restDaysPitchesLvl4", 70))
        lvl5 = int(cfg.get("restDaysPitchesLvl5", 95))
        if pitches <= lvl0:
            return 0
        if pitches <= lvl1:
            return 1
        if pitches <= lvl2:
            return 2
        if pitches <= lvl3:
            return 3
        if pitches <= lvl4:
            return 4
        if pitches <= lvl5:
            return 5
        return 6

    # Legacy curve (pre-V2):
    if pitches <= 10:
        return 1
    if pitches <= 25:
        return 2
    if pitches <= 45:
        return 3
    if pitches <= 70:
        return 4
    if pitches <= 95:
        return 5
    return 6


@dataclass
class _PitcherStatus:
    available_on: str | None = None
    last_used: str | None = None
    last_pitches: int = 0
    # Rolling history of recent usage entries: {date, pitches, appeared, warmed_only}
    recent: list[dict] = field(default_factory=list)
    # Last role seen (e.g., SP, LR, MR, SU, CL)
    last_role: str | None = None
    max_pitches: float = 0.0
    available_pitches: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "available_on": self.available_on,
            "last_used": self.last_used,
            "last_pitches": self.last_pitches,
            "recent": list(self.recent),
            "last_role": self.last_role,
            "max_pitches": self.max_pitches,
            "available_pitches": self.available_pitches,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "_PitcherStatus":
        def _sanitize_recent(value: object) -> list[dict]:
            cleaned: list[dict] = []
            if not isinstance(value, list):
                return cleaned
            for item in value:
                if not isinstance(item, dict):
                    continue
                cleaned.append(
                    {
                        "date": str(item.get("date")) if item.get("date") else None,
                        "pitches": int(item.get("pitches", 0) or 0),
                        "appeared": bool(item.get("appeared", False)),
                        "warmed_only": bool(item.get("warmed_only", False)),
                        "available_pitches": float(item.get("available_pitches", 0.0) or 0.0),
                    }
                )
            return cleaned

        return cls(
            available_on=str(data.get("available_on"))
            if data.get("available_on")
            else None,
            last_used=str(data.get("last_used")) if data.get("last_used") else None,
            last_pitches=int(data.get("last_pitches", 0)),
            recent=_sanitize_recent(data.get("recent")),
            last_role=str(data.get("last_role")) if data.get("last_role") else None,
            max_pitches=float(data.get("max_pitches", 0.0) or 0.0),
            available_pitches=float(data.get("available_pitches", 0.0) or 0.0),
        )


class PitcherRecoveryTracker:
    """Track pitcher rest and rotation assignments across the season."""

    _instance: "PitcherRecoveryTracker" | None = None

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = _resolve_path(path or "data/pitcher_recovery.json")
        self.data: Dict[str, Dict[str, object]] = {"teams": {}}
        self._assignments: Dict[str, str] = {}
        self._load()
        self._config_cache = None
        # S1-02 (deep_review_plan.md): the tracker used to rebuild each team
        # from CSVs ~6× per game and rewrite the whole JSON file ~4× per game.
        # ``_ensured`` memoizes _ensure_team for the current sim day, and
        # ``deferred_saves()`` batches the file writes to one flush per day.
        self._ensured: Dict[tuple[str, str, str], Dict[str, object]] = {}
        self._defer_saves = False
        self._dirty = False
        self._current_date: str | None = None

    # ------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        """Persist now, or remember to at the end of the deferral window."""
        if self._defer_saves:
            self._dirty = True
        else:
            self.save()

    @contextmanager
    def deferred_saves(self):
        """Batch tracker writes: one save() at exit instead of one per call.

        Reentrant-safe (inner contexts are no-ops). Used by the season
        simulator to flush once per simulated day.
        """
        if self._defer_saves:
            yield
            return
        self._defer_saves = True
        try:
            yield
        finally:
            self._defer_saves = False
            if self._dirty:
                self._dirty = False
                self.save()

    # ------------------------------------------------------------------
    @staticmethod
    def _assigned_role_for(pitcher: object) -> str:
        role = str(getattr(pitcher, "assigned_pitching_role", "") or "").upper()
        if role:
            return role
        role = str(getattr(pitcher, "role", "") or "").upper()
        if role:
            return role
        derived = get_role(pitcher)
        return str(derived or "").upper()

    @staticmethod
    def _trim_recent(status: _PitcherStatus, *, keep_days: int = 14, ref: date | None = None) -> None:
        """Keep only recent entries within ``keep_days`` prior to ``ref`` (default: today)."""
        if not status.recent:
            return
        try:
            today = ref or datetime.utcnow().date()
        except Exception:
            today = _EPOCH
        cutoff = today - timedelta(days=max(keep_days, 1))
        new_recent: list[dict] = []
        for entry in status.recent:
            d = _parse_date(str(entry.get("date"))) if entry else _EPOCH
            if d >= cutoff:
                new_recent.append(dict(entry))
        status.recent = new_recent

    # ------------------------------------------------------------------
    @classmethod
    def instance(cls) -> "PitcherRecoveryTracker":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    def _config(self):
        if self._config_cache is None:
            from playbalance.playbalance_config import PlayBalanceConfig

            self._config_cache = PlayBalanceConfig.from_file(
                get_base_dir() / "playbalance" / "PBINI.txt"
            )
        return self._config_cache

    def refresh_config(self) -> None:
        self._config_cache = None

    def _role_key(self, role: str | None) -> str:
        token = (role or "").upper()
        if token.startswith("SP"):
            return "SP"
        if token in {"CL", "SU", "MR", "LR"}:
            return token
        return "MR"

    def _role_multiplier(self, role: str) -> float:
        cfg = self._config()
        default = float(cfg.get("pitchBudgetMultiplier_MR", 1.8) or 1.8)
        return float(cfg.get(f"pitchBudgetMultiplier_{role}", default) or default)

    def _recovery_pct(self, role: str) -> float:
        cfg = self._config()
        default = float(cfg.get("pitchBudgetRecoveryPct_MR", 0.35) or 0.35)
        return float(cfg.get(f"pitchBudgetRecoveryPct_{role}", default) or default)

    def _availability_threshold(self, role: str) -> float:
        cfg = self._config()
        default = float(cfg.get("pitchBudgetAvailThresh_MR", 0.6) or 0.6)
        return float(cfg.get(f"pitchBudgetAvailThresh_{role}", default) or default)

    def _warmup_base(self, role: str) -> float:
        cfg = self._config()
        default = float(cfg.get("warmupPitchBase_MR", 12) or 12)
        return float(cfg.get(f"warmupPitchBase_{role}", default) or default)

    def _warmup_exponent(self) -> float:
        cfg = self._config()
        return float(cfg.get("warmupAvailabilityExponent", 1.0) or 1.0)

    def _warmup_floor(self) -> float:
        cfg = self._config()
        return float(cfg.get("warmupAvailabilityFloor", 0.25) or 0.25)

    def _exhaustion_penalty_scale(self) -> float:
        cfg = self._config()
        return float(cfg.get("pitchBudgetExhaustionPenaltyScale", 0.0) or 0.0)

    def _max_pitches_for(self, role: str, endurance: float) -> float:
        multiplier = self._role_multiplier(role)
        return max(0.0, float(endurance or 0.0) * multiplier)

    def _fallback_endurance(self, role: str) -> float:
        cfg = self._config()
        role_key = (role or "MR").upper()
        default = float(cfg.get("pitchBudgetFallbackEndurance_MR", 45) or 45)
        return float(
            cfg.get(f"pitchBudgetFallbackEndurance_{role_key}", default) or default
        )

    def _apply_daily_recovery(self, status: _PitcherStatus, role: str) -> None:
        if status.max_pitches <= 0:
            return
        pct = self._recovery_pct(role)
        recovered = status.max_pitches * pct
        status.available_pitches = min(
            status.max_pitches, status.available_pitches + recovered
        )

    def _apply_budget_penalty(
        self, status: _PitcherStatus, role: str, amount: float
    ) -> None:
        if amount <= 0 or status.max_pitches <= 0:
            return
        status.available_pitches = max(0.0, status.available_pitches - amount)

    def _ensure_budget_initialized(
        self, status: _PitcherStatus, pitcher: object | None, role: str
    ) -> None:
        if status.max_pitches > 0:
            status.available_pitches = min(status.available_pitches, status.max_pitches)
            return
        endurance = 0.0
        if pitcher is not None:
            endurance = float(getattr(pitcher, "endurance", 0) or 0)
        if endurance <= 0:
            endurance = self._fallback_endurance(role)
        status.max_pitches = self._max_pitches_for(role, endurance)
        status.available_pitches = status.max_pitches

    def _load(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except (OSError, json.JSONDecodeError):
            loaded = {}
        teams = loaded.get("teams") if isinstance(loaded, dict) else None
        if isinstance(teams, dict):
            self.data["teams"] = teams
        else:
            self.data["teams"] = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw_teams = self.data.get("teams", {}) or {}
        teams: Dict[str, Dict[str, object]] = {}
        for team_id, entry in raw_teams.items():
            new_entry: Dict[str, object] = {}
            try:
                new_entry["rotation"] = list(entry.get("rotation", []))
            except Exception:
                new_entry["rotation"] = []
            new_entry["next_index"] = int(entry.get("next_index", 0) or 0)
            pitchers = entry.get("pitchers", {}) or {}
            clean_pitchers: Dict[str, dict] = {}
            for pid, pdata in pitchers.items():
                status = _PitcherStatus.from_dict(pdata)
                clean_pitchers[pid] = status.to_dict()
            new_entry["pitchers"] = clean_pitchers
            teams[team_id] = new_entry
        payload = {"teams": teams}
        try:
            with self.path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, check_circular=False)
        except ValueError:
            teams = payload.get("teams", {})
            for team_id, entry in teams.items():
                try:
                    json.dumps({team_id: entry})
                except ValueError:
                    print(f"JSON serialization error for team {team_id}")
                    raise
            raise

    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Clear all saved recovery data and persist an empty tracker state."""

        self.data = {"teams": {}}
        self._assignments.clear()
        self._ensured.clear()
        self._current_date = None
        self.save()

    # ------------------------------------------------------------------
    def start_day(self, date_str: str) -> None:
        """Reset per-game assignments for *date_str*."""

        self._assignments.clear()
        self._ensured.clear()  # rosters may have changed overnight (injuries)
        teams = self.data.get("teams", {}) or {}
        updated = False
        for entry in teams.values():
            pitchers = entry.get("pitchers", {}) or {}
            for pid, payload in list(pitchers.items()):
                status = _PitcherStatus.from_dict(payload)
                role = self._role_key(status.last_role)
                self._apply_daily_recovery(status, role)
                status.available_pitches = min(status.available_pitches, status.max_pitches)
                pitchers[pid] = status.to_dict()
                updated = True
        if updated:
            self.save()
        self._current_date = date_str

    # ------------------------------------------------------------------
    def _ensure_team(
        self,
        team_id: str,
        players_file: str | Path,
        roster_dir: str | Path,
    ) -> Dict[str, object]:
        # Within a sim day the roster/rotation inputs don't change between the
        # ~6 tracker calls a game makes — memoize the (expensive) rebuild.
        # Only active during simulation (start_day sets _current_date and
        # clears the memo), so API/dashboard callers always get a fresh view.
        memo_key = (str(team_id), str(players_file), str(roster_dir))
        if self._current_date is not None:
            cached = self._ensured.get(memo_key)
            if cached is not None:
                return cached

        teams = self.data.setdefault("teams", {})
        entry = teams.get(team_id)
        resolved_players = str(_resolve_path(players_file))
        roster = load_roster(team_id, roster_dir)
        all_players = {
            player.player_id: player
            for player in load_players_from_csv(resolved_players)
        }
        active_pitchers = [
            all_players[pid]
            for pid in roster.act
            if pid in all_players and getattr(all_players[pid], "is_pitcher", False)
        ]
        pitcher_ids = [p.player_id for p in active_pitchers]

        saved_rotation = self._load_saved_rotation(team_id, roster_dir, pitcher_ids)

        if entry is None:
            entry = self._build_team_entry(active_pitchers, saved_rotation)
            teams[team_id] = entry
            self._mark_dirty()
            if self._current_date is not None:
                self._ensured[memo_key] = entry
            return entry

        # Update rotation and pitcher list if the roster changed.
        entry_pitchers = entry.setdefault("pitchers", {})
        for pid in pitcher_ids:
            if pid not in entry_pitchers:
                pitcher = next((p for p in active_pitchers if p.player_id == pid), None)
                entry_pitchers[pid] = self._initial_status(pitcher).to_dict()
            else:
                current = _PitcherStatus.from_dict(entry_pitchers[pid])
                pitcher = next((p for p in active_pitchers if p.player_id == pid), None)
                role = self._role_key(current.last_role or self._assigned_role_for(pitcher))
                self._ensure_budget_initialized(current, pitcher, role)
                current.last_role = role
                entry_pitchers[pid] = current.to_dict()
        # Remove pitchers no longer on the roster.
        for pid in list(entry_pitchers.keys()):
            if pid in pitcher_ids:
                continue
            status = _PitcherStatus.from_dict(entry_pitchers[pid])
            if not status.recent:
                entry_pitchers.pop(pid, None)

        built = [
            getattr(p, "player_id", "")
            for p in self._build_rotation(active_pitchers)
            if getattr(p, "player_id", "")
        ]
        candidates: list[str] = []
        if saved_rotation:
            candidates.extend(saved_rotation)
        existing_rotation = entry.get("rotation") or []
        candidates.extend(existing_rotation)
        candidates.extend(built)
        candidates.extend([pid for pid in pitcher_ids])

        rotation: list[str] = []
        seen: set[str] = set()
        for pid in candidates:
            if len(rotation) >= 5:
                break
            if not pid or pid not in pitcher_ids or pid in seen:
                continue
            rotation.append(pid)
            seen.add(pid)

        entry["rotation"] = rotation
        if rotation:
            entry["next_index"] = int(entry.get("next_index", 0) or 0) % len(rotation)
        else:
            entry["next_index"] = 0
        if self._current_date is not None:
            self._ensured[memo_key] = entry
        return entry

    # ------------------------------------------------------------------
    def _build_team_entry(self, pitchers: Iterable[object], saved_rotation: list[str] | None = None) -> Dict[str, object]:
        pitcher_list = list(pitchers)
        rotation = saved_rotation or self._build_rotation(pitcher_list)
        status = {
            getattr(p, "player_id"): self._initial_status(p).to_dict()
            for p in pitcher_list
        }
        return {
            "rotation": rotation,
            "next_index": 0,
            "pitchers": status,
        }

    def _load_saved_rotation(
        self,
        team_id: str,
        roster_dir: str | Path,
        valid_pitchers: list[str],
    ) -> list[str]:
        path = _resolve_path(roster_dir) / f"{team_id}_pitching.csv"
        if not path.exists():
            return []
        order_priority = {"SP1": 0, "SP2": 1, "SP3": 2, "SP4": 3, "SP5": 4}
        assignments: list[tuple[int, str]] = []
        seen: set[str] = set()
        try:
            with path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    if len(row) < 2:
                        continue
                    pid = row[0].strip()
                    role = row[1].strip().upper()
                    order = order_priority.get(role)
                    if order is None or pid not in valid_pitchers or pid in seen:
                        continue
                    assignments.append((order, pid))
                    seen.add(pid)
        except OSError:
            return []
        assignments.sort(key=lambda item: item[0])
        return [pid for _, pid in assignments]

    def _build_rotation(self, pitchers: Iterable[object]) -> list[str]:
        starters: list[tuple[str, int]] = []
        relievers: list[tuple[str, int]] = []
        for pitcher in pitchers:
            role = get_role(pitcher)
            endurance = int(getattr(pitcher, "endurance", 0) or 0)
            pid = getattr(pitcher, "player_id", "")
            if not pid:
                continue
            if role == "SP":
                starters.append((pid, endurance))
            elif role == "RP":
                relievers.append((pid, endurance))
            else:
                # Treat unknowns as relievers to ensure inclusion.
                relievers.append((pid, endurance))
        starters.sort(key=lambda item: item[1], reverse=True)
        relievers.sort(key=lambda item: item[1], reverse=True)
        rotation = [pid for pid, _ in starters[:5]]
        for pid, _ in relievers:
            if len(rotation) >= 5:
                break
            if pid not in rotation:
                rotation.append(pid)
        if not rotation and relievers:
            rotation = [pid for pid, _ in relievers[:5]]
        return rotation

    def _initial_status(self, pitcher: object) -> _PitcherStatus:
        status = _PitcherStatus()
        role = self._assigned_role_for(pitcher)
        role_key = self._role_key(role)
        status.last_role = role_key
        self._ensure_budget_initialized(status, pitcher, role_key)
        return status


    # ------------------------------------------------------------------
    def ensure_team(
        self,
        team_id: str,
        players_file: str | Path,
        roster_dir: str | Path,
    ) -> None:
        # Ensure tracking exists for team even when starters are overridden.
        self._ensure_team(team_id, players_file, roster_dir)

    # ------------------------------------------------------------------
    def assign_starter(
        self,
        team_id: str,
        date_str: str,
        players_file: str | Path,
        roster_dir: str | Path,
    ) -> str | None:
        entry = self._ensure_team(team_id, players_file, roster_dir)
        rotation: list[str] = entry.get("rotation", []) or []
        if not rotation:
            return None
        next_index = int(entry.get("next_index", 0) or 0)
        pitchers = entry.get("pitchers", {})
        date_obj = _parse_date(date_str)
        chosen_index: Optional[int] = None
        total = len(rotation)
        for offset in range(total):
            idx = (next_index + offset) % total
            pid = rotation[idx]
            status = _PitcherStatus.from_dict(pitchers.get(pid, {}))
            if _parse_date(status.available_on) <= date_obj:
                chosen_index = idx
                break
        if chosen_index is None:
            # Everyone is tired; choose the least-rested pitcher.
            chosen_index = min(
                range(total),
                key=lambda idx: _parse_date(
                    _PitcherStatus.from_dict(pitchers.get(rotation[idx], {})).available_on
                ),
            )
        pid = rotation[chosen_index]
        entry["next_index"] = (chosen_index + 1) % total
        self._assignments[team_id] = pid
        self._mark_dirty()
        return pid

    # ------------------------------------------------------------------
    def assigned_starter(self, team_id: str) -> str | None:
        return self._assignments.get(team_id)

    # ------------------------------------------------------------------
    def bullpen_game_status(
        self,
        team_id: str,
        date_str: str,
        players_file: str | Path,
        roster_dir: str | Path,
    ) -> Dict[str, Dict[str, object]]:
        """Return bullpen availability and rest info for ``team_id`` on ``date_str``.

        Includes derived rolling-usage metrics when available: ``apps3``, ``apps7``,
        and ``consecutive_days`` (appearances).
        """

        entry = self._ensure_team(team_id, players_file, roster_dir)
        pitchers = entry.get("pitchers", {}) or {}
        date_obj = _parse_date(date_str)
        status_map: Dict[str, Dict[str, object]] = {}
        for pid, payload in pitchers.items():
            status = _PitcherStatus.from_dict(payload)
            available_on = _parse_date(status.available_on)
            last_used = _parse_date(status.last_used)
            role = self._role_key(status.last_role)
            self._ensure_budget_initialized(status, None, role)
            days_since = (date_obj - last_used).days if last_used != _EPOCH else 9999
            if days_since < 0:
                days_since = 0
            available_pct = 1.0
            if status.max_pitches > 0:
                available_pct = status.available_pitches / status.max_pitches if status.max_pitches else 0.0

            apps3 = apps7 = 0
            consec = 0
            if status.recent:
                for entry in status.recent:
                    d = _parse_date(str(entry.get("date")))
                    if not d or d == _EPOCH or d >= date_obj:
                        continue
                    if not bool(entry.get("appeared")):
                        continue
                    delta = (date_obj - d).days
                    if 1 <= delta <= 3:
                        apps3 += 1
                    if 1 <= delta <= 7:
                        apps7 += 1
                step = 1
                while True:
                    d = date_obj - timedelta(days=step)
                    if any(
                        _parse_date(str(entry.get("date"))) == d and bool(entry.get("appeared"))
                        for entry in status.recent
                    ):
                        consec += 1
                        step += 1
                    else:
                        break

            status_map[pid] = {
                "available": available_on <= date_obj,
                "days_since_use": days_since,
                "last_pitches": status.last_pitches,
                "available_on": available_on,
                "apps3": apps3,
                "apps7": apps7,
                "consecutive_days": consec,
                "available_pct": available_pct,
            }
            pitchers[pid] = status.to_dict()
        entry["pitchers"] = pitchers
        return status_map

    # ------------------------------------------------------------------
    def record_game(
        self,
        team_id: str,
        date_str: str,
        pitcher_stats: Iterable[object],
        players_file: str | Path,
        roster_dir: str | Path,
    ) -> None:
        entry = self._ensure_team(team_id, players_file, roster_dir)
        pitchers = entry.setdefault("pitchers", {})
        date_obj = _parse_date(date_str)
        updated = False
        for state in pitcher_stats:
            pitcher = getattr(state, "player", None)
            if pitcher is None:
                continue
            pid = getattr(pitcher, "player_id", None)
            if not pid:
                continue
            pitches = int(getattr(state, "pitches_thrown", 0) or 0)
            if pitches <= 0:
                continue
            # ``simulated_pitches`` is a legacy field from the phantom pitch era.
            # Calibration now records real waste/foul pitches so the value is
            # normally ``0``; keep the addition for backward compatibility with
            # archived schedules that still use phantom padding.
            simulated = int(getattr(state, "simulated_pitches", 0) or 0)
            role = self._role_key(self._assigned_role_for(pitcher))
            rest_days = _rest_days(pitches)
            available_on = date_obj + timedelta(days=rest_days)
            stored_status = pitchers.get(pid, {})
            prior_recent: list[dict] = []
            for recent_entry in stored_status.get("recent", []):
                if isinstance(recent_entry, dict):
                    prior_recent.append(dict(recent_entry))
            status = _PitcherStatus.from_dict(stored_status)
            status.recent = prior_recent
            self._ensure_budget_initialized(status, pitcher, role)
            status.available_on = _format_date(available_on)
            status.last_used = date_str
            status.last_pitches = pitches
            self._apply_budget_penalty(status, role, pitches + simulated)
            # Append to recent usage
            entry = {
                "date": date_str,
                "pitches": pitches,
                "appeared": True,
                "warmed_only": False,
                "available_pitches": status.available_pitches,
            }
            status.recent.append(entry)
            self._trim_recent(status, ref=date_obj)
            # Capture last role for analytics/caps
            status.last_role = role
            pitchers[pid] = status.to_dict()
            updated = True
        if updated:
            self._mark_dirty()

    # ------------------------------------------------------------------
    def record_warmups(
        self,
        team_id: str,
        date_str: str,
        bullpen_warmups: Dict[str, object] | None,
        players_file: str | Path,
        roster_dir: str | Path,
    ) -> None:
        """Record warmed-but-unused relievers as virtual workload for recovery.

        Applies ``warmupTaxPitches`` as a synthetic pitch count impacting ``available_on``
        but does not alter ``last_used``. Skips pitchers who already appeared today.
        """

        if not bullpen_warmups:
            return
        cfg = self._config()
        rest_tax = int(cfg.get("warmupTaxPitches", 10) or 10)

        entry = self._ensure_team(team_id, players_file, roster_dir)
        pitchers = entry.setdefault("pitchers", {})
        date_obj = _parse_date(date_str)
        updated = False

        items = []
        if isinstance(bullpen_warmups, dict):
            items = list(bullpen_warmups.items())
        elif hasattr(bullpen_warmups, "items"):
            items = list(bullpen_warmups.items())
        else:
            keys = list(getattr(bullpen_warmups, "keys", lambda: [])())
            items = [(pid, None) for pid in keys]

        for pid, tracker_obj in items:
            status = _PitcherStatus.from_dict(pitchers.get(pid, {}))
            # Skip if already recorded an appearance today
            appeared_today = False
            for r in status.recent:
                if _parse_date(str(r.get("date"))) == date_obj and bool(r.get("appeared")):
                    appeared_today = True
                    break
            if appeared_today:
                continue
            role = self._role_key(status.last_role)
            self._ensure_budget_initialized(status, None, role)
            warmup_cost = 0.0
            if tracker_obj is not None:
                pitches_thrown = getattr(tracker_obj, "pitches", 0) or 0
                required = getattr(tracker_obj, "required_pitches", pitches_thrown)
                warmup_cost = float(min(pitches_thrown, required))
            if warmup_cost <= 0:
                warmup_cost = float(rest_tax)
            role_token = role or "MR"
            if status.max_pitches > 0:
                cap_ratio = 0.5 if role_token in {"CL", "SU"} else 0.6 if role_token == "MR" else 0.75
                warmup_cap = status.max_pitches * cap_ratio
                if warmup_cap > 0:
                    warmup_cost = min(warmup_cost, warmup_cap)
            warmup_cost = max(warmup_cost, 1.0)
            # Add warmup entry and adjust available_on
            status.recent.append(
                {
                    "date": date_str,
                    "pitches": warmup_cost,
                    "appeared": False,
                    "warmed_only": True,
                    "available_pitches": status.available_pitches,
                }
            )
            self._trim_recent(status, ref=date_obj)
            rest_basis = max(1, int(round(warmup_cost)))
            rest_days = _rest_days(rest_basis)
            if role_token in {"CL", "SU", "MR"}:
                rest_days = min(rest_days, 1)
            available_on = date_obj + timedelta(days=rest_days)
            prev_available = _parse_date(status.available_on)
            # Take the max (latest) availability date
            if available_on > prev_available:
                status.available_on = _format_date(available_on)
            self._apply_budget_penalty(status, role, warmup_cost)
            pitchers[pid] = status.to_dict()
            updated = True
        if updated:
            self._mark_dirty()

    # ------------------------------------------------------------------
    def apply_penalties(
        self,
        team_id: str,
        date_str: str,
        penalties: Dict[str, int] | None,
        players_file: str | Path,
        roster_dir: str | Path,
    ) -> None:
        """Apply post-game recovery penalties as additional virtual pitches.

        ``penalties`` maps ``player_id`` to extra pitch counts that increase
        the rest requirement by extending ``available_on``. Penalties do not
        count as appearances and do not change ``last_used``.
        """

        if not penalties:
            return
        entry = self._ensure_team(team_id, players_file, roster_dir)
        pitchers = entry.setdefault("pitchers", {})
        date_obj = _parse_date(date_str)
        updated = False
        for pid, tax in penalties.items():
            status = _PitcherStatus.from_dict(pitchers.get(pid, {}))
            role = self._role_key(status.last_role)
            self._ensure_budget_initialized(status, None, role)
            rest_days = _rest_days(int(tax or 0))
            if rest_days > 0:
                available_on = date_obj + timedelta(days=rest_days)
                prev_available = _parse_date(status.available_on)
                if available_on > prev_available:
                    status.available_on = _format_date(available_on)
                    updated = True
            self._apply_budget_penalty(status, role, float(tax or 0))
            # Track penalty as non-appearance recent entry for auditability
            status.recent.append(
                {
                    "date": date_str,
                    "pitches": int(tax or 0),
                    "appeared": False,
                    "warmed_only": False,
                    "available_pitches": status.available_pitches,
                }
            )
            self._trim_recent(status, ref=date_obj)
            pitchers[pid] = status.to_dict()
            updated = True
        if updated:
            self._mark_dirty()

    # ------------------------------------------------------------------
    def is_available(
        self,
        team_id: str,
        pid: str,
        role: str,
        date_str: str,
        players_file: str | Path,
        roster_dir: str | Path,
    ) -> tuple[bool, str]:
        """Return availability for ``pid`` on ``date_str`` with a reason code.

        Applies pitch-count rest, back-to-back limits and rolling window caps
        when ``enableUsageModelV2`` is set. When disabled, returns legacy rest
        availability (based on ``available_on`` only).
        """

        entry = self._ensure_team(team_id, players_file, roster_dir)
        pitchers = entry.get("pitchers", {}) or {}
        status = _PitcherStatus.from_dict(pitchers.get(pid, {}))
        date_obj = _parse_date(date_str)
        available_on = _parse_date(status.available_on)

        cfg = self._config()

        legacy_avail = available_on <= date_obj
        if cfg is None or not int(cfg.get("enableUsageModelV2", 0)):
            return (legacy_avail, "legacy_rest" if not legacy_avail else "ok")

        role_key = self._role_key(role or status.last_role)
        self._ensure_budget_initialized(status, None, role_key)

        available_pct = 1.0
        if status.max_pitches > 0:
            available_pct = (
                status.available_pitches / status.max_pitches
                if status.max_pitches
                else 0.0
            )
        # Consecutive days and back-to-back checks
        consec = 0
        yday_pitches = 0
        if status.recent:
            step = 1
            while True:
                d = date_obj - timedelta(days=step)
                found = False
                for r in status.recent:
                    if _parse_date(str(r.get("date"))) == d and bool(r.get("appeared")):
                        found = True
                        if step == 1:
                            yday_pitches = int(r.get("pitches", 0) or 0)
                        break
                if found:
                    consec += 1
                    step += 1
                else:
                    break

        threshold = self._availability_threshold(role_key)
        relief_floor = float(cfg.get("reliefB2BBudgetFloor", 0.45) or 0.45)
        allow_relief_override = (
            role_key in {"CL", "SU"}
            and status.max_pitches > 0
            and available_pct >= relief_floor
        )

        if not legacy_avail and not (allow_relief_override and consec == 1):
            pitchers[pid] = status.to_dict()
            return False, "rest"

        if status.max_pitches > 0 and available_pct < threshold and role_key != "SP":
            if not (allow_relief_override and consec == 1):
                pitchers[pid] = status.to_dict()
                return False, "budget"

        if int(cfg.get("forbidThirdConsecutiveDay", 1)) and consec >= 2 and role_key != "SP":
            pitchers[pid] = status.to_dict()
            return False, "third_day_block"

        if consec >= 1 and role_key != "SP":
            max_b2b = int(cfg.get("b2bMaxPriorPitches", 20))
            if yday_pitches > max_b2b and not (allow_relief_override and consec == 1):
                pitchers[pid] = status.to_dict()
                return False, "b2b_block"

        # Rolling window caps (relievers only)
        if role_key != "SP":
            apps3 = apps7 = 0
            if status.recent:
                for r in status.recent:
                    d = _parse_date(str(r.get("date")))
                    if d >= date_obj or not bool(r.get("appeared")):
                        continue
                    delta = (date_obj - d).days
                    if 1 <= delta <= 3:
                        apps3 += 1
                    if 1 <= delta <= 7:
                        apps7 += 1
            cap3 = int(cfg.get(f"maxApps3Day_{role_key}", cfg.get("maxApps3Day_MR", 3)))
            cap7 = int(cfg.get(f"maxApps7Day_{role_key}", cfg.get("maxApps7Day_MR", 5)))
            if apps3 >= cap3:
                pitchers[pid] = status.to_dict()
                return False, "cap3"
            if apps7 >= cap7:
                pitchers[pid] = status.to_dict()
                return False, "cap7"

        pitchers[pid] = status.to_dict()
        return True, "ok"


__all__ = ["PitcherRecoveryTracker"]


