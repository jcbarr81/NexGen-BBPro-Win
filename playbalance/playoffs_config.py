from __future__ import annotations

"""Playoffs configuration with sensible MLB-style defaults.

This module centralizes knobs for postseason shape so leagues of different
sizes can opt into brackets of 4, 6, or 8 teams per league and customize
series lengths and home/away patterns.

Defaults are chosen to mirror modern MLB conventions while staying flexible
enough for fictional leagues:

- 6 teams per league (top 2 division winners get a bye; wild-card round)
- BO3 wildcard, BO5 division series, BO7 LCS and World Series
- Home/away patterns: BO3 1-1-1, BO5 2-2-1, BO7 2-3-2

If a config file exists at ``data/playoffs_config.json`` it will be loaded to
override these defaults. Missing keys fall back to defaults.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import json

from utils.path_utils import get_data_dir


DEFAULT_PLAYOFF_TEAMS_PER_LEAGUE = 6
DEFAULT_SLOTS_BY_LEAGUE_SIZE = {
    4: 2,
    5: 4,
    6: 4,
    7: 6,
    8: 6,
    9: 6,
    10: 6,
    11: 6,
    12: 6,
    13: 6,
    14: 6,
}


@dataclass
class PlayoffsConfig:
    """Configuration for postseason structure and seeding rules."""

    # Number of playoff teams per league. Supported shapes: 4, 6, 8.
    num_playoff_teams_per_league: int = DEFAULT_PLAYOFF_TEAMS_PER_LEAGUE

    # Series lengths per round
    series_lengths: Dict[str, int] = field(
        default_factory=lambda: {
            "wildcard": 3,
            "ds": 5,
            "cs": 7,
            "ws": 7,
        }
    )

    # Home/away patterns by best-of length (counts per home stretches)
    # BO3 -> [1, 1, 1] means higher seed home in G1, away G2, home G3.
    home_away_patterns: Dict[int, List[int]] = field(
        default_factory=lambda: {
            3: [1, 1, 1],
            5: [2, 2, 1],
            7: [2, 3, 2],
        }
    )

    # Division winners seeded above wildcards regardless of total wins
    division_winners_priority: bool = True

    # Optional override for how many playoff slots each league gets based on its size
    playoff_slots_by_league_size: Dict[int, int] = field(default_factory=dict)

    # Optional override mapping from division name to league name
    # Example: {"AL East": "AL", "NL Central": "NL"}
    division_to_league: Dict[str, str] = field(default_factory=dict)

    # Optional path for config persistence
    _path: Optional[Path] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "num_playoff_teams_per_league": self.num_playoff_teams_per_league,
            "series_lengths": dict(self.series_lengths),
            "home_away_patterns": {int(k): list(v) for k, v in self.home_away_patterns.items()},
            "division_winners_priority": bool(self.division_winners_priority),
            "playoff_slots_by_league_size": {int(k): int(v) for k, v in self.playoff_slots_by_league_size.items()},
            "division_to_league": dict(self.division_to_league),
        }

    def slots_for_league(self, num_teams: int) -> int:
        """Return the number of playoff slots for a league with ``num_teams`` clubs."""

        if num_teams <= 0:
            return 0

        source = self.playoff_slots_by_league_size or DEFAULT_SLOTS_BY_LEAGUE_SIZE
        eligible_keys = [size for size in source if size <= num_teams]
        if eligible_keys:
            best_key = max(eligible_keys)
            slots = int(source.get(best_key, 0))
        else:
            slots = num_teams

        slots = min(slots or num_teams, self.num_playoff_teams_per_league, num_teams)
        if slots < 2 and num_teams >= 2:
            slots = min(2, num_teams)
        return slots

    @staticmethod
    def from_dict(data: Dict[str, object]) -> "PlayoffsConfig":
        base = PlayoffsConfig()
        if not isinstance(data, dict):
            return base
        base.num_playoff_teams_per_league = int(
            data.get("num_playoff_teams_per_league", base.num_playoff_teams_per_league)
        )
        sl = data.get("series_lengths")
        if isinstance(sl, dict):
            merged = dict(base.series_lengths)
            for k, v in sl.items():
                try:
                    merged[str(k)] = int(v)
                except Exception:
                    pass
            base.series_lengths = merged
        hap = data.get("home_away_patterns")
        if isinstance(hap, dict):
            merged: Dict[int, List[int]] = dict(base.home_away_patterns)
            for k, v in hap.items():
                try:
                    key = int(k)
                    arr = [int(x) for x in (v or [])]
                    if sum(arr) == key:  # simple sanity check
                        merged[key] = arr
                except Exception:
                    pass
            base.home_away_patterns = merged
        dwp = data.get("division_winners_priority")
        if isinstance(dwp, bool):
            base.division_winners_priority = dwp
        slots = data.get("playoff_slots_by_league_size")
        if isinstance(slots, dict):
            parsed: Dict[int, int] = {}
            for k, v in slots.items():
                try:
                    parsed[int(k)] = int(v)
                except Exception:
                    continue
            base.playoff_slots_by_league_size = parsed
        d2l = data.get("division_to_league")
        if isinstance(d2l, dict):
            base.division_to_league = {str(k): str(v) for k, v in d2l.items()}
        return base


def _config_path() -> Path:
    return get_data_dir() / "playoffs_config.json"


def load_playoffs_config(path: Optional[Path] = None) -> PlayoffsConfig:
    """Load playoffs configuration from disk with defaults.

    If the file is missing or malformed, default values are returned.
    """

    p = path or _config_path()
    try:
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            cfg = PlayoffsConfig.from_dict(raw)
            cfg._path = p
            return cfg
    except Exception:
        pass
    cfg = PlayoffsConfig()
    cfg._path = p
    return cfg


def save_playoffs_config(cfg: PlayoffsConfig, path: Optional[Path] = None) -> None:
    """Persist playoffs configuration to disk (best-effort)."""

    p = path or cfg._path or _config_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception:
        # Non-fatal; consumers can continue with in-memory cfg
        pass


__all__ = ["PlayoffsConfig", "load_playoffs_config", "save_playoffs_config"]

