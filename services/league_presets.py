"""Helpers for rule presets, schedule templates, and quick-start setups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from playbalance.league_creator import MAX_LEAGUE_TEAMS
from playbalance.schedule_generator import generate_mlb_schedule, save_schedule
from playbalance.season_context import SeasonContext
from playbalance.playoffs_config import PlayoffsConfig, save_playoffs_config
from playbalance.draft_config import save_draft_config
from services.injury_settings import set_injury_level
from services.training_settings import update_league_training_defaults
from services.physics_tuning_settings import (
    reset_physics_tuning_overrides,
    save_physics_tuning_overrides,
)
from utils.path_utils import get_base_dir, get_data_dir
from playbalance.team_name_generator import CITIES, MASCOTS

PRESETS_DIR = get_base_dir() / "config"


@dataclass(frozen=True)
class RulePreset:
    preset_id: str
    name: str
    description: str
    physics_tuning_overrides: Dict[str, float]
    injury_level: Optional[str] = None
    playoffs_config: Optional[Dict[str, Any]] = None
    training_focus_defaults: Optional[Dict[str, Dict[str, float]]] = None
    draft_config: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ScheduleTemplate:
    template_id: str
    name: str
    description: str
    games_per_team: int
    start_month: int
    start_day: int
    include_all_star_break: bool = True
    # Travel/off-day cadence. weekday 0=Monday; None disables the
    # weekly-off rule. extra_off_every_n_rounds=0 disables the
    # periodic-rest rule.
    weekly_off_weekday: Optional[int] = 0
    extra_off_every_n_rounds: int = 4


@dataclass(frozen=True)
class QuickStartPreset:
    preset_id: str
    name: str
    description: str
    divisions: List[str]
    teams_per_division: int
    rule_preset_id: str
    schedule_template_id: str


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def load_rule_presets() -> List[RulePreset]:
    raw = _load_json_list(PRESETS_DIR / "rule_presets.json")
    presets: List[RulePreset] = []
    for entry in raw:
        presets.append(
            RulePreset(
                preset_id=str(entry.get("id", "")).strip(),
                name=str(entry.get("name", "")).strip(),
                description=str(entry.get("description", "")).strip(),
                physics_tuning_overrides=dict(
                    entry.get("physics_tuning_overrides", {}) or {}
                ),
                injury_level=entry.get("injury_level"),
                playoffs_config=entry.get("playoffs_config"),
                training_focus_defaults=entry.get("training_focus_defaults"),
                draft_config=entry.get("draft_config"),
            )
        )
    return [p for p in presets if p.preset_id]


def load_schedule_templates() -> List[ScheduleTemplate]:
    raw = _load_json_list(PRESETS_DIR / "schedule_templates.json")
    templates: List[ScheduleTemplate] = []
    for entry in raw:
        try:
            games_per_team = int(entry.get("games_per_team", 0))
        except Exception:
            games_per_team = 0
        weekly_off_raw = entry.get("weekly_off_weekday", 0)
        if weekly_off_raw is None:
            weekly_off: Optional[int] = None
        else:
            try:
                weekly_off = int(weekly_off_raw)
            except (TypeError, ValueError):
                weekly_off = 0
        try:
            extra_off = int(entry.get("extra_off_every_n_rounds", 4) or 0)
        except (TypeError, ValueError):
            extra_off = 4
        templates.append(
            ScheduleTemplate(
                template_id=str(entry.get("id", "")).strip(),
                name=str(entry.get("name", "")).strip(),
                description=str(entry.get("description", "")).strip(),
                games_per_team=games_per_team,
                start_month=int(entry.get("start_month", 4) or 4),
                start_day=int(entry.get("start_day", 1) or 1),
                include_all_star_break=bool(
                    entry.get("include_all_star_break", True)
                ),
                weekly_off_weekday=weekly_off,
                extra_off_every_n_rounds=extra_off,
            )
        )
    return [t for t in templates if t.template_id and t.games_per_team > 0]


def load_quickstart_presets() -> List[QuickStartPreset]:
    raw = _load_json_list(PRESETS_DIR / "quickstart_presets.json")
    presets: List[QuickStartPreset] = []
    for entry in raw:
        divisions = [str(val) for val in entry.get("divisions", []) if str(val)]
        try:
            teams_per_division = int(entry.get("teams_per_division", 0))
        except Exception:
            teams_per_division = 0
        presets.append(
            QuickStartPreset(
                preset_id=str(entry.get("id", "")).strip(),
                name=str(entry.get("name", "")).strip(),
                description=str(entry.get("description", "")).strip(),
                divisions=divisions,
                teams_per_division=teams_per_division,
                rule_preset_id=str(entry.get("rule_preset_id", "")).strip(),
                schedule_template_id=str(
                    entry.get("schedule_template_id", "")
                ).strip(),
            )
        )
    return [
        p
        for p in presets
        if p.preset_id and p.divisions and p.teams_per_division > 0
    ]


def get_rule_preset(preset_id: str) -> Optional[RulePreset]:
    for preset in load_rule_presets():
        if preset.preset_id == preset_id:
            return preset
    return None


def get_schedule_template(template_id: str) -> Optional[ScheduleTemplate]:
    for template in load_schedule_templates():
        if template.template_id == template_id:
            return template
    return None


def get_quickstart_preset(preset_id: str) -> Optional[QuickStartPreset]:
    for preset in load_quickstart_presets():
        if preset.preset_id == preset_id:
            return preset
    return None


def apply_rule_preset(preset_id: str) -> Optional[RulePreset]:
    preset = get_rule_preset(preset_id)
    if preset is None:
        return None

    overrides = preset.physics_tuning_overrides or {}
    if overrides:
        save_physics_tuning_overrides(overrides)
    else:
        reset_physics_tuning_overrides()

    if preset.injury_level:
        try:
            set_injury_level(str(preset.injury_level))
        except Exception:
            pass

    if preset.playoffs_config:
        try:
            cfg = PlayoffsConfig.from_dict(preset.playoffs_config)
            save_playoffs_config(cfg)
        except Exception:
            pass

    if preset.training_focus_defaults:
        try:
            hitters = preset.training_focus_defaults.get("hitters", {})
            pitchers = preset.training_focus_defaults.get("pitchers", {})
            update_league_training_defaults(hitters, pitchers)
        except Exception:
            pass

    if preset.draft_config:
        try:
            save_draft_config(preset.draft_config)
        except Exception:
            pass

    return preset


def generate_schedule_from_template(
    template_id: str,
    teams: Iterable[str],
    *,
    year: Optional[int] = None,
) -> List[Dict[str, str]]:
    template = get_schedule_template(template_id)
    if template is None:
        return []
    schedule_year = year if year is not None else date.today().year
    start = date(schedule_year, template.start_month, template.start_day)
    schedule = generate_mlb_schedule(
        teams,
        start,
        games_per_team=template.games_per_team,
        include_all_star_break=template.include_all_star_break,
        weekly_off_weekday=template.weekly_off_weekday,
        extra_off_every_n_rounds=template.extra_off_every_n_rounds,
    )
    return schedule


def save_schedule_from_template(
    template_id: str,
    teams: Iterable[str],
    *,
    year: Optional[int] = None,
    schedule_path: Optional[Path] = None,
) -> List[Dict[str, str]]:
    schedule = generate_schedule_from_template(
        template_id,
        teams,
        year=year,
    )
    if not schedule:
        return []
    target = schedule_path or get_data_dir() / "schedule.csv"
    save_schedule(schedule, target)
    return schedule


def set_preseason_schedule_done(done: bool = True) -> None:
    data_dir = get_data_dir()
    path = data_dir / "season_progress.json"
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, dict):
        return
    preseason = payload.setdefault("preseason_done", {})
    if isinstance(preseason, dict):
        preseason["schedule"] = bool(done)
    payload["preseason_done"] = preseason
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def record_league_metadata(**metadata: Any) -> None:
    try:
        ctx = SeasonContext.load()
        cleaned = {
            key: value
            for key, value in metadata.items()
            if value is not None and value != ""
        }
        if cleaned:
            ctx.ensure_current_season(metadata=cleaned)
    except Exception:
        pass


def build_quickstart_structure(preset: QuickStartPreset) -> Dict[str, List[tuple[str, str]]]:
    total_teams = len(preset.divisions) * preset.teams_per_division
    if total_teams > MAX_LEAGUE_TEAMS:
        raise ValueError(
            f"Quick-start preset requires {total_teams} teams, exceeding "
            f"the limit of {MAX_LEAGUE_TEAMS}."
        )

    teams = _generate_team_names(total_teams)
    iterator = iter(teams)
    structure: Dict[str, List[tuple[str, str]]] = {}
    for division in preset.divisions:
        entries: List[tuple[str, str]] = []
        for _ in range(preset.teams_per_division):
            try:
                entries.append(next(iterator))
            except StopIteration:
                break
        structure[division] = entries
    return structure


def _generate_team_names(count: int) -> List[tuple[str, str]]:
    cities = list(CITIES)
    mascots = list(MASCOTS)
    random.shuffle(cities)
    random.shuffle(mascots)

    if not cities:
        cities = [f"City {idx + 1}" for idx in range(count)]
    if not mascots:
        mascots = [f"Team {idx + 1}" for idx in range(count)]

    names: List[tuple[str, str]] = []
    city_len = len(cities)
    mascot_len = len(mascots)
    for idx in range(count):
        city = cities[idx % city_len]
        mascot = mascots[idx % mascot_len]
        suffix = idx // mascot_len
        if suffix > 0:
            mascot = f"{mascot} {suffix + 1}"
        names.append((city, mascot))
    return names


__all__ = [
    "RulePreset",
    "ScheduleTemplate",
    "QuickStartPreset",
    "load_rule_presets",
    "load_schedule_templates",
    "load_quickstart_presets",
    "get_rule_preset",
    "get_schedule_template",
    "get_quickstart_preset",
    "apply_rule_preset",
    "generate_schedule_from_template",
    "save_schedule_from_template",
    "set_preseason_schedule_done",
    "record_league_metadata",
    "build_quickstart_structure",
]
