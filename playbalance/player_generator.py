# ARR-inspired Player Generator Script
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple, Set, Optional
import csv
from pathlib import Path

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover - optional dependency for CLI usage
    pd = None

from utils.path_utils import get_base_dir

# Constants
BASE_DIR = get_base_dir()
NAME_PATH = BASE_DIR / "data" / "names.csv"
PLAYER_PATH = BASE_DIR / "data" / "players.csv"
NORMALIZED_PLAYER_PATH = BASE_DIR / "data" / "players_normalized.csv"
POSITION_AVERAGE_PATH = (
    BASE_DIR
    / "data"
    / "MLB_avg"
    / "mlb_position_averages_2021-2025YTD.csv"
)


def _load_position_averages(path: Path) -> Dict[str, Dict[str, float]]:
    """Return MLB average hitting stats by position to guide rating guardrails."""

    data: Dict[str, Dict[str, float]] = {}
    if not path.exists():
        return data
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            position = (row.get("Position") or "").strip()
            if not position:
                continue
            stats: Dict[str, float] = {}
            for key in ("AVG", "OBP", "SLG", "OPS", "wRC+"):
                raw = row.get(key)
                if raw in (None, ""):
                    continue
                try:
                    stats[key] = float(raw)
                except ValueError:
                    continue
            if stats:
                data[position] = stats
    return data


POSITION_AVERAGES = _load_position_averages(POSITION_AVERAGE_PATH)

if not POSITION_AVERAGES:
    POSITION_AVERAGES = {
        "C": {"AVG": 0.233, "OBP": 0.302, "SLG": 0.383, "OPS": 0.685, "wRC+": 90.0},
        "1B": {"AVG": 0.251, "OBP": 0.328, "SLG": 0.427, "OPS": 0.755, "wRC+": 109.0},
        "2B": {"AVG": 0.247, "OBP": 0.313, "SLG": 0.384, "OPS": 0.698, "wRC+": 94.0},
        "3B": {"AVG": 0.245, "OBP": 0.314, "SLG": 0.404, "OPS": 0.719, "wRC+": 99.0},
        "SS": {"AVG": 0.253, "OBP": 0.315, "SLG": 0.401, "OPS": 0.716, "wRC+": 98.0},
        "LF": {"AVG": 0.244, "OBP": 0.319, "SLG": 0.404, "OPS": 0.723, "wRC+": 101.0},
        "CF": {"AVG": 0.242, "OBP": 0.309, "SLG": 0.398, "OPS": 0.708, "wRC+": 96.0},
        "RF": {"AVG": 0.247, "OBP": 0.320, "SLG": 0.425, "OPS": 0.745, "wRC+": 106.0},
        "DH": {"AVG": 0.249, "OBP": 0.330, "SLG": 0.442, "OPS": 0.772, "wRC+": 114.0},
        "P": {"AVG": 0.108, "OBP": 0.147, "SLG": 0.137, "OPS": 0.284},
    }


HITTER_RATING_KEYS = (
    "ch",
    "ph",
    "sp",
    "eye",
    "gf",
    "pl",
    "vl",
    "sc",
    "fa",
    "arm",
    "durability",
)
PITCHER_RATING_KEYS = (
    "endurance",
    "control",
    "movement",
    "hold_runner",
    "fa",
    "arm",
    "gf",
    "vl",
    "durability",
)
PITCHER_PITCH_KEYS = ("fb", "cu", "cb", "sl", "si", "scb", "kn")
_RATING_DISTRIBUTIONS: Optional[Dict[str, Any]] = None

PLAYER_CSV_DEFAULTS: Dict[str, Any] = {
    "player_id": "",
    "first_name": "",
    "last_name": "",
    "birthdate": "",
    "height": 72,
    "weight": 195,
    "ethnicity": "",
    "skin_tone": "",
    "hair_color": "",
    "facial_hair": "",
    "bats": "R",
    "primary_position": "",
    "other_positions": [],
    "is_pitcher": False,
    "role": "",
    "preferred_pitching_role": "",
    "pitcher_archetype": "",
    "hitter_archetype": "",
    "ch": 0,
    "ph": 0,
    "sp": 0,
    "eye": 0,
    "gf": 0,
    "pl": 0,
    "vl": 0,
    "sc": 0,
    "fa": 0,
    "arm": 0,
    "endurance": 0,
    "control": 0,
    "movement": 0,
    "hold_runner": 0,
    "fb": 0,
    "cu": 0,
    "cb": 0,
    "sl": 0,
    "si": 0,
    "scb": 0,
    "kn": 0,
    "pot_ch": 0,
    "pot_ph": 0,
    "pot_sp": 0,
    "pot_eye": 0,
    "pot_gf": 0,
    "pot_pl": 0,
    "pot_vl": 0,
    "pot_sc": 0,
    "pot_fa": 0,
    "pot_arm": 0,
    "pot_control": 0,
    "pot_movement": 0,
    "pot_endurance": 0,
    "pot_hold_runner": 0,
    "pot_fb": 0,
    "pot_cu": 0,
    "pot_cb": 0,
    "pot_sl": 0,
    "pot_si": 0,
    "pot_scb": 0,
    "pot_kn": 0,
    "injured": False,
    "injury_description": "",
    "return_date": "",
    "ready": False,
    "injury_list": "",
    "injury_start_date": "",
    "injury_minimum_days": "",
    "injury_eligible_date": "",
    "injury_rehab_assignment": "",
    "injury_rehab_days": 0,
    "durability": 50,
}


def _apply_player_defaults(player: Dict[str, Any]) -> None:
    for key, default in PLAYER_CSV_DEFAULTS.items():
        if key in player:
            continue
        if isinstance(default, list):
            player[key] = list(default)
        else:
            player[key] = default
    if not player.get("height"):
        player["height"] = PLAYER_CSV_DEFAULTS["height"]
    if not player.get("weight"):
        player["weight"] = PLAYER_CSV_DEFAULTS["weight"]


def _parse_int_field(row: Dict[str, str], key: str) -> Optional[int]:
    raw = row.get(key)
    if raw in (None, ""):
        return None
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return None


def _derive_eye_rating(ch: int, sc: int, jitter: float = 0.0) -> int:
    base = (ch * 0.6) + (sc * 0.4)
    if jitter:
        base += random.uniform(-jitter, jitter)
    return max(10, min(99, int(round(base))))


def _empty_rating_bucket(keys: Tuple[str, ...]) -> Dict[str, List[int]]:
    return {key: [] for key in keys}


def _load_rating_distributions(path: Path) -> Dict[str, Any]:
    pools: Dict[str, Any] = {
        "hitters": {"ALL": _empty_rating_bucket(HITTER_RATING_KEYS), "by_pos": {}},
        "pitchers": {
            "ALL": _empty_rating_bucket(PITCHER_RATING_KEYS),
            "SP": _empty_rating_bucket(PITCHER_RATING_KEYS),
            "RP": _empty_rating_bucket(PITCHER_RATING_KEYS),
        },
        "pitches": {
            "ALL": _empty_rating_bucket(PITCHER_PITCH_KEYS),
            "SP": _empty_rating_bucket(PITCHER_PITCH_KEYS),
            "RP": _empty_rating_bucket(PITCHER_PITCH_KEYS),
        },
    }
    for pos in PRIMARY_POSITION_WEIGHTS:
        pools["hitters"]["by_pos"][pos] = _empty_rating_bucket(HITTER_RATING_KEYS)
    if not path.exists():
        return pools
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            is_pitcher = str(row.get("is_pitcher", "0")).strip().lower() in {
                "1",
                "true",
                "yes",
            }
            if is_pitcher:
                endurance_val = _parse_int_field(row, "endurance")
                role = (
                    row.get("preferred_pitching_role")
                    or row.get("role")
                    or ""
                ).strip().upper()
                if role.startswith("SP"):
                    bucket = "SP"
                elif role in {"CL", "SU", "RP", "MR", "LR"}:
                    bucket = "RP"
                else:
                    bucket = "SP" if (endurance_val or 0) >= 60 else "RP"
                for key in PITCHER_RATING_KEYS:
                    value = _parse_int_field(row, key)
                    if value is None:
                        continue
                    pools["pitchers"]["ALL"][key].append(value)
                    pools["pitchers"][bucket][key].append(value)
                for key in PITCHER_PITCH_KEYS:
                    value = _parse_int_field(row, key)
                    if value is None or value <= 0:
                        continue
                    pools["pitches"]["ALL"][key].append(value)
                    pools["pitches"][bucket][key].append(value)
            else:
                pos = (row.get("primary_position") or "CF").strip().upper()
                pos_bucket = pools["hitters"]["by_pos"].setdefault(
                    pos, _empty_rating_bucket(HITTER_RATING_KEYS)
                )
                ch_val = _parse_int_field(row, "ch") or 50
                sc_val = _parse_int_field(row, "sc") or 50
                eye_val = _derive_eye_rating(ch_val, sc_val)
                for key in HITTER_RATING_KEYS:
                    if key == "eye":
                        value = eye_val
                    else:
                        value = _parse_int_field(row, key)
                    if value is None:
                        continue
                    pools["hitters"]["ALL"][key].append(value)
                    pos_bucket[key].append(value)
    for bucket in pools["hitters"]["ALL"].values():
        bucket.sort()
    for pos_bucket in pools["hitters"]["by_pos"].values():
        for values in pos_bucket.values():
            values.sort()
    for group in ("ALL", "SP", "RP"):
        for values in pools["pitchers"][group].values():
            values.sort()
        for values in pools["pitches"][group].values():
            values.sort()
    return pools


def _rating_distributions() -> Dict[str, Any]:
    global _RATING_DISTRIBUTIONS
    if _RATING_DISTRIBUTIONS is None:
        source_path = (
            NORMALIZED_PLAYER_PATH
            if NORMALIZED_PLAYER_PATH.exists()
            else PLAYER_PATH
        )
        _RATING_DISTRIBUTIONS = _load_rating_distributions(source_path)
    return _RATING_DISTRIBUTIONS


def _percentile_value(values: List[int], pct: float) -> int:
    if not values:
        return 50
    idx = int(round(pct * (len(values) - 1)))
    idx = max(0, min(idx, len(values) - 1))
    return values[idx]


def _sample_from_values(
    values: List[int],
    band: Tuple[float, float],
    *,
    jitter: float = 2.5,
    fallback: int = 50,
) -> int:
    if not values:
        base = fallback
    else:
        low, high = band
        if low > high:
            low, high = high, low
        pct = random.uniform(low, high)
        base = _percentile_value(values, pct)
    if jitter:
        base += random.uniform(-jitter, jitter)
    return max(10, min(99, int(round(base))))


def _sample_from_distribution(
    key: str,
    *,
    position: Optional[str] = None,
    role: Optional[str] = None,
    band: Tuple[float, float] = (0.35, 0.65),
    jitter: float = 2.5,
    fallback: int = 50,
) -> int:
    dist = _rating_distributions()
    values: List[int]
    if key in PITCHER_PITCH_KEYS:
        values = dist["pitches"].get(role or "ALL", {}).get(key, []) or dist["pitches"]["ALL"].get(key, [])
    elif role:
        values = dist["pitchers"].get(role, {}).get(key, []) or dist["pitchers"]["ALL"].get(key, [])
    elif position:
        values = (
            dist["hitters"]["by_pos"].get(position, {}).get(key, [])
            or dist["hitters"]["ALL"].get(key, [])
        )
    else:
        values = dist["hitters"]["ALL"].get(key, [])
    return _sample_from_values(values, band, jitter=jitter, fallback=fallback)


HITTER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "power": {
        "weight": 0.22,
        "bands": {
            "ph": (0.82, 0.98),
            "ch": (0.35, 0.65),
            "sp": (0.2, 0.6),
            "eye": (0.3, 0.6),
            "pl": (0.6, 0.9),
            "gf": (0.2, 0.45),
        },
    },
    "average": {
        "weight": 0.18,
        "bands": {
            "ch": (0.4, 0.65),
            "ph": (0.4, 0.65),
            "sp": (0.35, 0.6),
            "eye": (0.4, 0.65),
            "pl": (0.4, 0.65),
            "gf": (0.45, 0.7),
        },
    },
    "spray": {
        "weight": 0.18,
        "bands": {
            "ch": (0.7, 0.95),
            "ph": (0.3, 0.6),
            "sp": (0.45, 0.8),
            "eye": (0.6, 0.9),
            "pl": (0.1, 0.4),
            "gf": (0.55, 0.85),
        },
    },
    "balanced": {
        "weight": 0.26,
        "bands": {
            "ch": (0.48, 0.78),
            "ph": (0.48, 0.78),
            "sp": (0.4, 0.7),
            "eye": (0.45, 0.72),
            "pl": (0.4, 0.7),
            "gf": (0.4, 0.65),
        },
    },
    "gap": {
        "weight": 0.12,
        "bands": {
            "ch": (0.68, 0.92),
            "ph": (0.62, 0.88),
            "sp": (0.4, 0.7),
            "eye": (0.55, 0.82),
            "pl": (0.3, 0.6),
            "gf": (0.25, 0.55),
        },
    },
    "speed": {
        "weight": 0.15,
        "bands": {
            "ch": (0.55, 0.8),
            "ph": (0.2, 0.5),
            "sp": (0.85, 0.99),
            "eye": (0.55, 0.85),
            "pl": (0.2, 0.55),
            "gf": (0.6, 0.9),
        },
    },
    "elite_speed": {
        "weight": 0.05,
        "bands": {
            "ch": (0.5, 0.78),
            "ph": (0.15, 0.45),
            "sp": (0.92, 1.0),
            "eye": (0.5, 0.82),
            "pl": (0.2, 0.5),
            "gf": (0.45, 0.75),
        },
    },
}


HITTER_POSITION_TEMPLATE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "C": {
        "average": 0.3,
        "balanced": 0.25,
        "spray": 0.18,
        "power": 0.12,
        "speed": 0.07,
        "gap": 0.06,
        "elite_speed": 0.02,
    },
    "1B": {
        "power": 0.36,
        "balanced": 0.18,
        "average": 0.12,
        "spray": 0.1,
        "speed": 0.05,
        "gap": 0.18,
        "elite_speed": 0.01,
    },
    "2B": {
        "balanced": 0.27,
        "spray": 0.22,
        "speed": 0.18,
        "average": 0.12,
        "power": 0.08,
        "gap": 0.09,
        "elite_speed": 0.04,
    },
    "SS": {
        "spray": 0.24,
        "balanced": 0.24,
        "speed": 0.2,
        "average": 0.12,
        "power": 0.06,
        "gap": 0.1,
        "elite_speed": 0.04,
    },
    "3B": {
        "balanced": 0.26,
        "power": 0.22,
        "average": 0.18,
        "spray": 0.14,
        "speed": 0.08,
        "gap": 0.09,
        "elite_speed": 0.03,
    },
    "LF": {
        "power": 0.28,
        "balanced": 0.2,
        "average": 0.16,
        "spray": 0.14,
        "speed": 0.1,
        "gap": 0.09,
        "elite_speed": 0.03,
    },
    "CF": {
        "balanced": 0.24,
        "speed": 0.22,
        "spray": 0.18,
        "average": 0.14,
        "power": 0.08,
        "gap": 0.1,
        "elite_speed": 0.04,
    },
    "RF": {
        "power": 0.3,
        "balanced": 0.2,
        "average": 0.16,
        "spray": 0.13,
        "speed": 0.08,
        "gap": 0.1,
        "elite_speed": 0.03,
    },
    "DH": {
        "power": 0.34,
        "balanced": 0.18,
        "average": 0.18,
        "spray": 0.1,
        "speed": 0.05,
        "gap": 0.14,
        "elite_speed": 0.01,
    },
}


PITCHER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "power_sp": {
        "role": "SP",
        "weight": 0.25,
        "pitch_profile": "power",
        "bands": {
            "arm": (0.8, 0.98),
            "control": (0.45, 0.7),
            "movement": (0.55, 0.8),
            "endurance": (0.7, 0.92),
            "hold_runner": (0.4, 0.7),
            "gf": (0.35, 0.6),
        },
    },
    "finesse_sp": {
        "role": "SP",
        "weight": 0.2,
        "pitch_profile": "finesse",
        "bands": {
            "arm": (0.45, 0.7),
            "control": (0.75, 0.95),
            "movement": (0.7, 0.9),
            "endurance": (0.65, 0.88),
            "hold_runner": (0.6, 0.8),
            "gf": (0.4, 0.65),
        },
    },
    "groundball_sp": {
        "role": "SP",
        "weight": 0.18,
        "pitch_profile": "groundball",
        "bands": {
            "arm": (0.55, 0.8),
            "control": (0.55, 0.78),
            "movement": (0.65, 0.85),
            "endurance": (0.65, 0.88),
            "hold_runner": (0.5, 0.75),
            "gf": (0.75, 0.95),
        },
    },
    "balanced_sp": {
        "role": "SP",
        "weight": 0.22,
        "pitch_profile": "balanced",
        "bands": {
            "arm": (0.6, 0.82),
            "control": (0.6, 0.8),
            "movement": (0.6, 0.82),
            "endurance": (0.65, 0.88),
            "hold_runner": (0.45, 0.7),
            "gf": (0.45, 0.7),
        },
    },
    "workhorse_sp": {
        "role": "SP",
        "weight": 0.15,
        "pitch_profile": "balanced",
        "bands": {
            "arm": (0.55, 0.78),
            "control": (0.6, 0.8),
            "movement": (0.6, 0.82),
            "endurance": (0.82, 0.99),
            "hold_runner": (0.45, 0.7),
            "gf": (0.45, 0.7),
        },
    },
    "closer": {
        "role": "RP",
        "preferred_role": "CL",
        "weight": 0.12,
        "pitch_profile": "closer",
        "bands": {
            "arm": (0.9, 0.99),
            "control": (0.55, 0.75),
            "movement": (0.7, 0.92),
            "endurance": (0.2, 0.45),
            "hold_runner": (0.5, 0.75),
            "gf": (0.35, 0.6),
        },
    },
    "power_rp": {
        "role": "RP",
        "weight": 0.22,
        "pitch_profile": "power",
        "bands": {
            "arm": (0.78, 0.97),
            "control": (0.45, 0.7),
            "movement": (0.55, 0.8),
            "endurance": (0.32, 0.6),
            "hold_runner": (0.45, 0.7),
            "gf": (0.35, 0.6),
        },
    },
    "finesse_rp": {
        "role": "RP",
        "weight": 0.2,
        "pitch_profile": "finesse",
        "bands": {
            "arm": (0.5, 0.75),
            "control": (0.7, 0.92),
            "movement": (0.68, 0.88),
            "endurance": (0.32, 0.6),
            "hold_runner": (0.55, 0.78),
            "gf": (0.4, 0.65),
        },
    },
    "groundball_rp": {
        "role": "RP",
        "weight": 0.18,
        "pitch_profile": "groundball",
        "bands": {
            "arm": (0.6, 0.82),
            "control": (0.55, 0.78),
            "movement": (0.6, 0.84),
            "endurance": (0.32, 0.6),
            "hold_runner": (0.5, 0.75),
            "gf": (0.75, 0.95),
        },
    },
    "long_relief": {
        "role": "RP",
        "preferred_role": "LR",
        "weight": 0.08,
        "pitch_profile": "balanced",
        "bands": {
            "arm": (0.55, 0.78),
            "control": (0.6, 0.8),
            "movement": (0.6, 0.82),
            "endurance": (0.6, 0.82),
            "hold_runner": (0.45, 0.7),
            "gf": (0.45, 0.7),
        },
    },
}


PITCH_PROFILES: Dict[str, Dict[str, Any]] = {
    "power": {
        "primary": ["sl", "cb"],
        "secondary": ["si", "cu", "scb"],
        "fb_band": (0.8, 0.98),
        "primary_band": (0.7, 0.9),
        "secondary_band": (0.45, 0.7),
    },
    "finesse": {
        "primary": ["cu", "cb"],
        "secondary": ["sl", "si", "scb"],
        "fb_band": (0.55, 0.78),
        "primary_band": (0.68, 0.88),
        "secondary_band": (0.5, 0.75),
    },
    "groundball": {
        "primary": ["si"],
        "secondary": ["sl", "cb", "cu"],
        "fb_band": (0.6, 0.82),
        "primary_band": (0.7, 0.9),
        "secondary_band": (0.45, 0.7),
    },
    "balanced": {
        "primary": ["sl", "cb", "cu"],
        "secondary": ["si", "scb"],
        "fb_band": (0.6, 0.85),
        "primary_band": (0.6, 0.82),
        "secondary_band": (0.45, 0.7),
    },
    "closer": {
        "primary": ["sl"],
        "secondary": ["cb", "cu"],
        "fb_band": (0.9, 0.99),
        "primary_band": (0.75, 0.95),
        "secondary_band": (0.55, 0.78),
    },
}


def _choose_hitter_template(primary_pos: str, archetype: Optional[str] = None) -> str:
    if archetype and archetype in HITTER_TEMPLATES:
        return archetype
    weights = HITTER_POSITION_TEMPLATE_WEIGHTS.get(primary_pos)
    names = list(HITTER_TEMPLATES.keys())
    weight_list = []
    for name in names:
        if weights and name in weights:
            weight_list.append(weights[name])
        else:
            weight_list.append(HITTER_TEMPLATES[name]["weight"])
    return random.choices(names, weights=weight_list)[0]


def _adjust_hitter_constraints(
    template_name: str,
    ch: int,
    ph: int,
    sp: int,
    eye: int,
    pl: int,
    gf: int,
) -> Tuple[int, int, int, int, int, int]:
    if template_name in {"power"} and ph < ch + 6:
        ph = min(99, ch + random.randint(6, 12))
    if template_name in {"spray"} and ch < ph + 6:
        ch = min(99, ph + random.randint(6, 12))
    if template_name in {"balanced", "average"} and abs(ch - ph) > 10:
        mid = int(round((ch + ph) / 2))
        ch = min(99, max(10, mid + random.randint(-4, 4)))
        ph = min(99, max(10, mid + random.randint(-4, 4)))
    if template_name == "gap" and abs(ch - ph) > 8:
        mid = int(round((ch + ph) / 2))
        ch = min(99, max(10, mid + random.randint(-3, 3)))
        ph = min(99, max(10, mid + random.randint(-3, 3)))
    if template_name == "speed":
        sp = max(sp, 70)
    if template_name == "elite_speed":
        sp = max(sp, 85)
    eye = max(10, min(99, eye))
    pl = max(10, min(99, pl))
    gf = max(10, min(99, gf))
    return ch, ph, sp, eye, pl, gf


def _apply_hitter_tail_boost(
    template_name: str,
    ch: int,
    ph: int,
    sp: int,
    eye: int,
    pl: int,
    gf: int,
) -> Tuple[int, int, int, int, int, int]:
    roll = random.random()
    if template_name == "gap" and roll < 0.22:
        bump = random.randint(6, 12)
        ch = min(99, ch + bump)
        ph = min(99, ph + bump)
    elif template_name == "elite_speed" and roll < 0.15:
        sp = min(99, sp + random.randint(6, 10))
        ch = min(99, ch + random.randint(2, 5))
    elif template_name == "speed" and roll < 0.12:
        sp = min(99, sp + random.randint(4, 8))
    elif template_name == "spray" and roll < 0.12:
        ch = min(99, ch + random.randint(4, 8))
    return ch, ph, sp, eye, pl, gf


def _sample_normalized_hitter(
    primary_pos: str,
    bats: str,
    archetype: Optional[str] = None,
) -> Dict[str, Any] | None:
    template = _choose_hitter_template(primary_pos, archetype)
    bands = HITTER_TEMPLATES[template]["bands"]
    ch = _sample_from_distribution("ch", position=primary_pos, band=bands.get("ch", (0.4, 0.7)))
    ph = _sample_from_distribution("ph", position=primary_pos, band=bands.get("ph", (0.4, 0.7)))
    sp = _sample_from_distribution("sp", position=primary_pos, band=bands.get("sp", (0.35, 0.65)))
    pl = _sample_from_distribution("pl", position=primary_pos, band=bands.get("pl", (0.4, 0.7)))
    gf = _sample_from_distribution("gf", position=primary_pos, band=bands.get("gf", (0.4, 0.7)))
    sc = _sample_from_distribution("sc", position=primary_pos, band=bands.get("sc", (0.4, 0.7)))
    eye_raw = _sample_from_distribution("eye", position=primary_pos, band=bands.get("eye", (0.4, 0.7)))
    eye = int(round((eye_raw * 0.7) + (ch * 0.3)))
    fa = _sample_from_distribution("fa", position=primary_pos, band=bands.get("fa", (0.4, 0.7)))
    arm = _sample_from_distribution("arm", position=primary_pos, band=bands.get("arm", (0.4, 0.7)))
    vl = _sample_from_distribution("vl", position=primary_pos, band=bands.get("vl", (0.4, 0.7)))
    if bats == "L":
        vl = max(30, vl - 4)
    elif bats == "R":
        vl = min(99, vl + 4)
    ch, ph, sp, eye, pl, gf = _adjust_hitter_constraints(
        template, ch, ph, sp, eye, pl, gf
    )
    ch, ph, sp, eye, pl, gf = _apply_hitter_tail_boost(
        template, ch, ph, sp, eye, pl, gf
    )
    return {
        "ch": ch,
        "ph": ph,
        "sp": sp,
        "eye": eye,
        "gf": gf,
        "pl": pl,
        "vl": vl,
        "sc": sc,
        "fa": fa,
        "arm": arm,
        "hitter_archetype": template,
    }


def _choose_pitcher_template(archetype: Optional[str] = None) -> str:
    if archetype:
        normalized = archetype.strip().lower()
        aliases = {
            "power": "power_sp",
            "finesse": "finesse_sp",
            "groundball": "groundball_sp",
            "balanced": "balanced_sp",
            "workhorse": "workhorse_sp",
            "closer": "closer",
            "setup": "closer",
            "long_relief": "long_relief",
        }
        name = aliases.get(normalized, normalized)
        if name in PITCHER_TEMPLATES:
            return name
    role_pool = "SP" if random.random() < 0.6 else "RP"
    candidates = [
        name for name, spec in PITCHER_TEMPLATES.items() if spec["role"] == role_pool
    ]
    weights = [PITCHER_TEMPLATES[name]["weight"] for name in candidates]
    return random.choices(candidates, weights=weights)[0]


def _sample_pitch_mix(
    *,
    role: str,
    profile: str,
    arm: int,
    template_name: str,
) -> Dict[str, int]:
    profile_cfg = PITCH_PROFILES.get(profile, PITCH_PROFILES["balanced"])
    if role == "SP":
        pitch_count = random.randint(3, 5)
    else:
        pitch_count = random.randint(2, 4)
    selected: List[str] = ["fb"]
    primary_pool = list(profile_cfg.get("primary", []))
    secondary_pool = list(profile_cfg.get("secondary", []))
    if template_name == "closer" and "sl" in primary_pool and "sl" not in selected:
        selected.append("sl")
    while len(selected) < pitch_count:
        if primary_pool:
            pitch = random.choice(primary_pool)
            primary_pool.remove(pitch)
        elif secondary_pool:
            pitch = random.choice(secondary_pool)
            secondary_pool.remove(pitch)
        else:
            pitch = random.choice([p for p in PITCHER_PITCH_KEYS if p not in selected])
        if pitch not in selected:
            selected.append(pitch)
    ratings = {key: 0 for key in PITCHER_PITCH_KEYS}
    for pitch in selected:
        if pitch == "fb":
            band = profile_cfg.get("fb_band", (0.6, 0.85))
            rating = _sample_from_distribution(pitch, role=role, band=band, fallback=arm)
            rating = max(rating, arm - random.randint(0, 6))
        elif pitch in profile_cfg.get("primary", []):
            rating = _sample_from_distribution(
                pitch,
                role=role,
                band=profile_cfg.get("primary_band", (0.6, 0.82)),
                fallback=60,
            )
        else:
            rating = _sample_from_distribution(
                pitch,
                role=role,
                band=profile_cfg.get("secondary_band", (0.45, 0.7)),
                fallback=55,
            )
        ratings[pitch] = rating
    if template_name == "closer":
        ratings["sl"] = max(ratings.get("sl", 0), 65)
    return ratings


def _sample_normalized_pitcher(
    archetype: Optional[str],
    throws: str,
) -> Dict[str, Any] | None:
    template = _choose_pitcher_template(archetype)
    spec = PITCHER_TEMPLATES[template]
    role = spec["role"]
    bands = spec["bands"]
    arm = _sample_from_distribution("arm", role=role, band=bands.get("arm", (0.55, 0.85)))
    control = _sample_from_distribution(
        "control", role=role, band=bands.get("control", (0.55, 0.8))
    )
    movement = _sample_from_distribution(
        "movement", role=role, band=bands.get("movement", (0.55, 0.85))
    )
    endurance = _sample_from_distribution(
        "endurance", role=role, band=bands.get("endurance", (0.55, 0.85))
    )
    hold_runner = _sample_from_distribution(
        "hold_runner", role=role, band=bands.get("hold_runner", (0.45, 0.7))
    )
    gf = _sample_from_distribution("gf", role=role, band=bands.get("gf", (0.4, 0.7)))
    fa = _sample_from_distribution("fa", role=role, band=bands.get("fa", (0.4, 0.7)))
    vl = _sample_from_distribution("vl", role=role, band=bands.get("vl", (0.4, 0.7)))
    if throws == "L":
        vl = min(99, vl + 4)
    else:
        vl = max(30, vl - 2)
    control = max(50, control)
    movement = max(52, movement)
    if template == "closer":
        endurance = min(endurance, 55)
        if movement < control:
            movement = min(99, control + random.randint(2, 8))
    pitch_profile = spec.get("pitch_profile", "balanced")
    pitch_ratings = _sample_pitch_mix(
        role=role,
        profile=pitch_profile,
        arm=arm,
        template_name=template,
    )
    preferred_role = spec.get("preferred_role", "")
    data: Dict[str, Any] = {
        "endurance": endurance,
        "control": control,
        "movement": movement,
        "hold_runner": hold_runner,
        "arm": arm,
        "fa": fa,
        "gf": gf,
        "vl": vl,
        "role": role,
        "preferred_pitching_role": preferred_role,
        "pitcher_archetype": template,
    }
    data.update(pitch_ratings)
    return data


def _stat_bounds(field: str, include_pitchers: bool = False) -> Tuple[float, float]:
    values = [
        stats[field]
        for pos, stats in POSITION_AVERAGES.items()
        if field in stats and (include_pitchers or pos != "P")
    ]
    if not values:
        return 0.0, 1.0
    return min(values), max(values)


def _scale_stat(
    value: float,
    min_src: float,
    max_src: float,
    min_dest: float,
    max_dest: float,
) -> float:
    if max_src <= min_src:
        return (min_dest + max_dest) / 2.0
    normalized = (value - min_src) / (max_src - min_src)
    normalized = max(0.0, min(1.0, normalized))
    return min_dest + normalized * (max_dest - min_dest)


def _sample_rating(
    center: float,
    *,
    floor: int,
    ceiling: int,
    spread: float = 6.0,
    outlier_chance: float = 0.04,
    outlier_bounds: Tuple[int, int] = (72, 90),
) -> Tuple[int, bool]:
    rating = int(round(random.gauss(center, spread)))
    rating = max(floor, min(ceiling, rating))
    outlier = False
    if random.random() < outlier_chance:
        outlier = True
        rating = random.randint(outlier_bounds[0], outlier_bounds[1])
    rating = max(20, min(95, rating))
    return rating, outlier


def _build_hitter_guardrails() -> Dict[str, Dict[str, float]]:
    guardrails: Dict[str, Dict[str, float]] = {}
    avg_min, avg_max = _stat_bounds("AVG")
    slg_min, slg_max = _stat_bounds("SLG")
    ops_min, ops_max = _stat_bounds("OPS")
    for pos, stats in POSITION_AVERAGES.items():
        if pos == "P":
            continue
        contact_center = _scale_stat(stats["AVG"], avg_min, avg_max, 52, 70)
        power_center = _scale_stat(stats["SLG"], slg_min, slg_max, 50, 72)
        speed_center = _scale_stat(stats["OPS"], ops_min, ops_max, 48, 68)
        if pos in {"CF", "SS"}:
            speed_center += 4
        elif pos in {"2B", "LF"}:
            speed_center += 2
        elif pos in {"C", "1B", "DH"}:
            speed_center -= 5
        guardrails[pos] = {
            "contact_center": contact_center,
            "power_center": power_center,
            "speed_center": max(45, min(70, speed_center)),
        }
    return guardrails


HITTER_GUARDRAILS = _build_hitter_guardrails()
DEFAULT_HITTER_GUARDRAIL = {"contact_center": 52.0, "power_center": 52.0, "speed_center": 50.0}


def _load_name_pool() -> Dict[str, List[Tuple[str, str]]]:
    pool: Dict[str, List[Tuple[str, str]]] = {}
    source = PLAYER_PATH if PLAYER_PATH.exists() else NAME_PATH
    if source.exists():
        with source.open(newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ethnicity = row.get("ethnicity", "").strip()
                first = row.get("first_name")
                last = row.get("last_name")
                if ethnicity and first and last:
                    pool.setdefault(ethnicity, []).append((first, last))
    return pool


name_pool = _load_name_pool()
used_names: Set[Tuple[str, str]] = set()

# Age generation tables derived from the original ARR configuration.  Each
# entry maps a player type to a ``(base, num_dice, num_sides)`` tuple used when
# rolling the player's age.  The final age is ``base`` plus the total of the
# dice rolls.
AGE_TABLES: Dict[str, Tuple[int, int, int]] = {
    "amateur": (14, 3, 3),
    "fictional": (14, 4, 6),
    "filler": (17, 4, 6),
}


def reset_name_cache():
    global name_pool, used_names
    name_pool = _load_name_pool()
    used_names = set()

    
# Helper Functions

def generate_birthdate(
    age_range: Optional[Tuple[int, int]] = None,
    player_type: str = "fictional",
):
    """Generate a birthdate and age.

    Parameters
    ----------
    age_range:
        Optional explicit ``(min_age, max_age)`` bounds.  If provided the age
        is chosen uniformly from within the range.
    player_type:
        When ``age_range`` is not supplied the player's age is determined by
        rolling dice according to the table for the given ``player_type``.
    """

    today = datetime.today()
    if age_range is not None:
        age = random.randint(*age_range)
    else:
        base, num_dice, num_sides = AGE_TABLES[player_type]
        age = base + sum(random.randint(1, num_sides) for _ in range(num_dice))

    days_old = age * 365 + random.randint(0, 364)
    birthdate = (today - timedelta(days=days_old)).date()
    return birthdate, age

def bounded_rating(min_val=10, max_val=99):
    return random.randint(min_val, max_val)

def bounded_potential(actual, age):
    if age < 22:
        pot = actual + random.randint(10, 30)
    elif age < 28:
        pot = actual + random.randint(5, 15)
    elif age < 32:
        pot = actual + random.randint(-5, 5)
    else:
        pot = actual - random.randint(0, 10)
    return max(10, min(99, pot))


_DRAFT_RATING_KEYS = (
    "ch",
    "ph",
    "sp",
    "eye",
    "gf",
    "pl",
    "vl",
    "sc",
    "fa",
    "arm",
    "endurance",
    "control",
    "movement",
    "hold_runner",
    "fb",
    "cu",
    "cb",
    "sl",
    "si",
    "scb",
    "kn",
)
_DRAFT_MIN_RATING = 20


def _draft_rating_scale(age: int) -> float:
    if age <= 18:
        return 0.75
    if age == 19:
        return 0.8
    if age == 20:
        return 0.84
    if age == 21:
        return 0.88
    return 0.9


def _apply_draft_rating_scale(player: Dict[str, Any], age: int) -> None:
    """Reduce draft ratings so young players start below their potentials."""

    scale = _draft_rating_scale(age)
    for key in _DRAFT_RATING_KEYS:
        value = player.get(key)
        if not isinstance(value, (int, float)):
            continue
        if value <= 0:
            continue
        scaled = int(round(value * scale))
        player[key] = max(_DRAFT_MIN_RATING, min(99, scaled))


def roll_dice(base: int, count: int, faces: int) -> int:
    """Return ``base`` plus the total from rolling ``count`` ``faces``-sided dice."""

    return base + sum(random.randint(1, faces) for _ in range(count))


def _generate_durability(age: int, is_pitcher: bool) -> int:
    """
    Generate a durability rating (0-99) with subtle age/role adjustments.
    Young players skew higher, older veterans and heavy-use pitchers skew lower.
    """

    # Base between roughly 40-80 with a modest spread.
    base = roll_dice(35, 10, 5)
    if age > 30:
        base -= int((age - 30) * 1.25)
    else:
        base += int((30 - age) * 0.3)
    if is_pitcher:
        base -= roll_dice(5, 2, 1)
    return max(20, min(95, base))

def generate_name() -> tuple[str, str, str]:
    """Return a unique ``(first, last, ethnicity)`` tuple."""

    if name_pool:
        total_names = sum(len(v) for v in name_pool.values())
        if len(used_names) >= total_names:
            return "John", "Doe", "Unknown"
        while True:
            ethnicity = random.choice(list(name_pool.keys()))
            first, last = random.choice(name_pool[ethnicity])
            if (first, last) not in used_names:
                used_names.add((first, last))
                return first, last, ethnicity
    return "John", "Doe", "Unknown"


def _adjust_endurance(endurance: int) -> int:
    """Apply ARR-based endurance adjustments (lines 176-180).

    Pitchers with endurance between 30 and 69 have a 50% chance to have their
    rating adjusted by adding or subtracting 1–20 points.  The result is always
    clamped to the 1–99 range.
    """

    if 30 <= endurance <= 69 and random.randint(1, 100) <= 50:
        delta = random.randint(1, 20)
        if random.choice([-1, 1]) < 0:
            endurance -= delta
        else:
            endurance += delta
    return max(1, min(99, endurance))

PRIMARY_POSITION_WEIGHTS = {
    "C": 19,
    "1B": 15,
    "2B": 14,
    "SS": 13,
    "3B": 14,
    "LF": 16,
    "CF": 13,
    "RF": 16,
}

DRAFT_CLOSER_RATE = 0.18

# Weights used for distributing rating points among player attributes.  These
# values were taken from the original ARR data file (lines 71-86) and represent
# how many parts of a shared rating pool should be assigned to each attribute.
HITTER_RATING_WEIGHTS: Dict[str, Dict[str, int]] = {
    "P": {"ch": 40, "ph": 107, "sp": 393, "fa": 557, "arm": 0},
    "C": {"ch": 189, "ph": 163, "sp": 166, "fa": 214, "arm": 269},
    "1B": {"ch": 213, "ph": 178, "sp": 163, "fa": 226, "arm": 221},
    "2B": {"ch": 200, "ph": 135, "sp": 206, "fa": 220, "arm": 239},
    "SS": {"ch": 187, "ph": 133, "sp": 199, "fa": 225, "arm": 256},
    "3B": {"ch": 201, "ph": 162, "sp": 175, "fa": 221, "arm": 240},
    "LF": {"ch": 195, "ph": 165, "sp": 202, "fa": 218, "arm": 220},
    "CF": {"ch": 202, "ph": 144, "sp": 235, "fa": 206, "arm": 213},
    "RF": {"ch": 193, "ph": 175, "sp": 187, "fa": 212, "arm": 233},
}

PITCHER_RATING_WEIGHTS: Dict[str, int] = {
    "endurance": 196,
    "control": 206,
    "hold_runner": 184,
    "movement": 184,
    "arm": 228,
}


def distribute_rating_points(total: int, weights: Dict[str, int]) -> Dict[str, int]:
    """Distribute ``total`` rating points according to ``weights``.

    Parameters
    ----------
    total: int
        Total number of rating points to distribute.
    weights: Dict[str, int]
        Mapping of attribute name to weight.  The resulting dictionary will
        contain the same keys with integer values summing to ``total``.
    """

    total_weight = sum(weights.values())
    remaining = total
    items = list(weights.items())
    allocations: Dict[str, int] = {}

    for attr, weight in items[:-1]:
        value = round(total * weight / total_weight)
        allocations[attr] = value
        remaining -= value

    # The final attribute takes whatever points remain so the totals match.
    last_attr = items[-1][0]
    allocations[last_attr] = remaining
    return allocations

PITCHER_RATE = 0.4  # Fraction of draft pool that should be pitchers

# Appearance tables keyed by ethnicity. The ``"Default"`` entry is used when an
# ethnicity is not explicitly listed.
SKIN_TONE_WEIGHTS: Dict[str, Dict[str, int]] = {
    "Anglo": {"light": 60, "medium": 30, "dark": 10},
    "African": {"light": 5, "medium": 15, "dark": 80},
    "Asian": {"light": 40, "medium": 55, "dark": 5},
    "Hispanic": {"light": 30, "medium": 50, "dark": 20},
    "Default": {"light": 33, "medium": 34, "dark": 33},
}

HAIR_COLOR_WEIGHTS: Dict[str, Dict[str, int]] = {
    "Anglo": {"blonde": 25, "brown": 40, "black": 25, "red": 10},
    "African": {"black": 80, "brown": 20},
    "Asian": {"black": 90, "brown": 10},
    "Hispanic": {"black": 40, "brown": 40, "blonde": 15, "red": 5},
    "Default": {"black": 40, "brown": 40, "blonde": 15, "red": 5},
}

FACIAL_HAIR_WEIGHTS: Dict[str, Dict[str, int]] = {
    "Anglo": {"clean_shaven": 60, "mustache": 10, "goatee": 10, "beard": 20},
    "African": {"clean_shaven": 55, "mustache": 15, "goatee": 10, "beard": 20},
    "Asian": {"clean_shaven": 70, "mustache": 10, "goatee": 10, "beard": 10},
    "Hispanic": {"clean_shaven": 55, "mustache": 15, "goatee": 15, "beard": 15},
    "Default": {"clean_shaven": 60, "mustache": 10, "goatee": 10, "beard": 20},
}


def assign_primary_position() -> str:
    """Select a primary position using weights from the ARR tables."""
    return random.choices(
        list(PRIMARY_POSITION_WEIGHTS.keys()),
        weights=PRIMARY_POSITION_WEIGHTS.values(),
    )[0]


def _lookup_weights(table: Dict[str, Dict[str, int]], ethnicity: str) -> Dict[str, int]:
    """Return the weight mapping for ``ethnicity`` falling back to ``Default``."""

    return table.get(ethnicity, table["Default"])


def assign_skin_tone(ethnicity: str) -> str:
    """Select a skin tone using ethnicity-specific weights."""

    weights = _lookup_weights(SKIN_TONE_WEIGHTS, ethnicity)
    return random.choices(list(weights.keys()), weights=weights.values())[0]


def assign_hair_color(ethnicity: str) -> str:
    """Select a hair color using ethnicity-specific weights."""

    weights = _lookup_weights(HAIR_COLOR_WEIGHTS, ethnicity)
    return random.choices(list(weights.keys()), weights=weights.values())[0]


def assign_facial_hair(ethnicity: str, age: int) -> str:
    """Select facial hair style using ethnicity-specific weights.

    Younger players tend to be clean shaven while older players are more likely
    to sport mustaches or beards.
    """

    weights = _lookup_weights(FACIAL_HAIR_WEIGHTS, ethnicity).copy()
    if age < 25:
        weights["clean_shaven"] += 20
        weights["beard"] = max(0, weights.get("beard", 0) - 10)
    elif age > 35:
        weights["mustache"] += 10
        weights["beard"] += 10
        weights["clean_shaven"] = max(0, weights.get("clean_shaven", 0) - 20)
    return random.choices(list(weights.keys()), weights=weights.values())[0]


BATS_THROWS: Dict[str, List[Tuple[str, str, int]]] = {
    "P": [
        ("R", "L", 1),
        ("R", "R", 50),
        ("L", "L", 25),
        ("L", "R", 10),
        ("S", "L", 4),
        ("S", "R", 10),
    ],
    "C": [
        ("R", "L", 0),
        ("R", "R", 75),
        ("L", "L", 0),
        ("L", "R", 15),
        ("S", "L", 0),
        ("S", "R", 10),
    ],
    "1B": [
        ("R", "L", 1),
        ("R", "R", 40),
        ("L", "L", 32),
        ("L", "R", 13),
        ("S", "L", 4),
        ("S", "R", 10),
    ],
    "2B": [
        ("R", "L", 0),
        ("R", "R", 75),
        ("L", "L", 0),
        ("L", "R", 15),
        ("S", "L", 0),
        ("S", "R", 10),
    ],
    "3B": [
        ("R", "L", 0),
        ("R", "R", 75),
        ("L", "L", 0),
        ("L", "R", 15),
        ("S", "L", 0),
        ("S", "R", 10),
    ],
    "SS": [
        ("R", "L", 0),
        ("R", "R", 75),
        ("L", "L", 0),
        ("L", "R", 15),
        ("S", "L", 0),
        ("S", "R", 10),
    ],
    "LF": [
        ("R", "L", 1),
        ("R", "R", 50),
        ("L", "L", 25),
        ("L", "R", 10),
        ("S", "L", 4),
        ("S", "R", 10),
    ],
    "CF": [
        ("R", "L", 1),
        ("R", "R", 50),
        ("L", "L", 25),
        ("L", "R", 10),
        ("S", "L", 4),
        ("S", "R", 10),
    ],
    "RF": [
        ("R", "L", 1),
        ("R", "R", 50),
        ("L", "L", 25),
        ("L", "R", 10),
        ("S", "L", 4),
        ("S", "R", 10),
    ],
}


FIELDING_POTENTIAL_MATRIX: Dict[str, Dict[str, int]] = {
    "P": {"P": 0, "C": 10, "1B": 100, "2B": 20, "3B": 60, "SS": 10, "LF": 90, "CF": 40, "RF": 80},
    "C": {"P": 60, "C": 0, "1B": 100, "2B": 20, "3B": 60, "SS": 10, "LF": 90, "CF": 40, "RF": 80},
    "1B": {"P": 60, "C": 10, "1B": 0, "2B": 20, "3B": 60, "SS": 10, "LF": 90, "CF": 40, "RF": 80},
    "2B": {"P": 130, "C": 10, "1B": 160, "2B": 0, "3B": 130, "SS": 90, "LF": 150, "CF": 120, "RF": 140},
    "3B": {"P": 100, "C": 10, "1B": 140, "2B": 90, "3B": 0, "SS": 80, "LF": 130, "CF": 100, "RF": 120},
    "SS": {"P": 140, "C": 10, "1B": 170, "2B": 100, "3B": 140, "SS": 0, "LF": 160, "CF": 120, "RF": 150},
    "LF": {"P": 90, "C": 10, "1B": 120, "2B": 60, "3B": 90, "SS": 40, "LF": 0, "CF": 80, "RF": 100},
    "CF": {"P": 110, "C": 10, "1B": 150, "2B": 80, "3B": 110, "SS": 70, "LF": 140, "CF": 0, "RF": 130},
    "RF": {"P": 90, "C": 10, "1B": 130, "2B": 60, "3B": 90, "SS": 40, "LF": 110, "CF": 80, "RF": 0},
}

ALL_POSITIONS = list(FIELDING_POTENTIAL_MATRIX["P"].keys())


def assign_bats_throws(primary: str) -> Tuple[str, str]:
    combos = BATS_THROWS.get(primary, BATS_THROWS["1B"])
    bats, throws, _ = random.choices(
        combos, weights=[c[2] for c in combos]
    )[0]
    return bats, throws


SECONDARY_POSITIONS: Dict[str, Dict[str, Dict[str, int]]] = {
    "P": {"chance": 1, "weights": {"1B": 30, "LF": 25, "RF": 45}},
    "C": {"chance": 2, "weights": {"1B": 30, "3B": 20, "LF": 20, "RF": 30}},
    "1B": {"chance": 2, "weights": {"C": 5, "3B": 15, "LF": 50, "RF": 30}},
    "2B": {"chance": 5, "weights": {"3B": 40, "SS": 50, "CF": 10}},
    "3B": {
        "chance": 5,
        "weights": {"C": 5, "1B": 15, "2B": 20, "SS": 10, "LF": 25, "RF": 25},
    },
    "SS": {"chance": 5, "weights": {"2B": 50, "3B": 40, "CF": 10}},
    "LF": {"chance": 9, "weights": {"C": 5, "1B": 25, "3B": 15, "CF": 20, "RF": 35}},
    "CF": {"chance": 6, "weights": {"2B": 10, "SS": 10, "LF": 40, "RF": 40}},
    "RF": {"chance": 9, "weights": {"C": 5, "1B": 25, "3B": 15, "LF": 35, "CF": 20}},
}


def assign_secondary_positions(primary: str) -> List[str]:
    info = SECONDARY_POSITIONS.get(primary)
    if not info:
        return []
    if random.randint(1, 100) > info["chance"]:
        return []
    positions = list(info["weights"].keys())
    weights = list(info["weights"].values())
    return [random.choices(positions, weights=weights)[0]]

PITCH_LIST = ["fb", "si", "cu", "cb", "sl", "kn", "sc"]


def _guardrail_for_position(position: str) -> Dict[str, float]:
    return HITTER_GUARDRAILS.get(position, HITTER_GUARDRAILS.get("CF", DEFAULT_HITTER_GUARDRAIL))


def _generate_hitter_ratings(primary_pos: str) -> Dict[str, int]:
    """Derive hitter ratings anchored to MLB positional averages with mild variance."""
    guardrail = _guardrail_for_position(primary_pos)
    contact, contact_outlier = _sample_rating(
        guardrail["contact_center"],
        floor=42,
        ceiling=78,
        spread=6.0,
        outlier_bounds=(75, 92),
    )
    power, _ = _sample_rating(
        guardrail["power_center"],
        floor=40,
        ceiling=78,
        spread=6.2,
        outlier_bounds=(74, 92),
    )
    speed, speed_outlier = _sample_rating(
        guardrail["speed_center"],
        floor=38,
        ceiling=72,
        spread=5.8,
        outlier_bounds=(74, 90),
    )
    if contact > 85 and speed > 85:
        if contact_outlier and speed_outlier:
            if guardrail["speed_center"] >= guardrail["contact_center"]:
                contact = max(
                    65,
                    min(
                        83,
                        int(round(random.gauss(guardrail["contact_center"], 4.0))),
                    ),
                )
            else:
                speed = max(
                    65,
                    min(
                        83,
                        int(round(random.gauss(guardrail["speed_center"], 4.0))),
                    ),
                )
        else:
            speed = max(
                65,
                min(83, int(round(random.gauss(guardrail["speed_center"], 4.0)))),
            )
    fielding_center = guardrail["speed_center"]
    if primary_pos in {"SS", "CF"}:
        fielding_center += 2
    elif primary_pos in {"2B", "LF"}:
        fielding_center += 1
    elif primary_pos in {"1B", "DH"}:
        fielding_center -= 5
    fielding, _ = _sample_rating(
        fielding_center,
        floor=32,
        ceiling=72,
        spread=5.2,
        outlier_bounds=(70, 86),
    )
    arm_center = guardrail["power_center"]
    if primary_pos in {"RF", "C"}:
        arm_center += 5
    elif primary_pos in {"3B", "LF"}:
        arm_center += 2
    elif primary_pos in {"1B"}:
        arm_center -= 5
    arm, _ = _sample_rating(
        arm_center,
        floor=38,
        ceiling=80,
        spread=5.5,
        outlier_bounds=(74, 92),
    )
    eye = _derive_eye_rating(contact, int(round((contact + power) / 2)), jitter=4.0)
    return {
        "ch": contact,
        "ph": power,
        "sp": speed,
        "eye": eye,
        "fa": fielding,
        "arm": arm,
    }


def _generate_pitcher_core_ratings(throws: str, *, archetype: str | None = None) -> Dict[str, int]:
    """Return core pitcher ratings tailored to the requested archetype."""

    if archetype == "closer":
        endurance_center = 38
        endurance_floor = 24
        endurance_ceiling = 58
        endurance_spread = 4.5
        endurance_outliers = (55, 68)
        control_center = 60
        control_floor = 48
        control_ceiling = 78
        control_spread = 4.8
        control_outliers = (72, 86)
        movement_center = 72
        movement_floor = 60
        movement_ceiling = 92
        movement_spread = 5.2
        movement_outliers = (82, 95)
        hold_center = 60
        hold_floor = 48
        hold_ceiling = 82
        arm_center = 78
        arm_floor = 62
        arm_ceiling = 95
    else:
        endurance_center = 60
        endurance_floor = 48
        endurance_ceiling = 80
        endurance_spread = 6.0
        endurance_outliers = (78, 92)
        control_center = 62
        control_floor = 50
        control_ceiling = 80
        control_spread = 5.2
        control_outliers = (76, 92)
        movement_center = 64
        movement_floor = 52
        movement_ceiling = 82
        movement_spread = 5.4
        movement_outliers = (78, 94)
        hold_center = 54
        hold_floor = 42
        hold_ceiling = 72
        arm_center = 64
        arm_floor = 50
        arm_ceiling = 85

    endurance, _ = _sample_rating(
        endurance_center,
        floor=endurance_floor,
        ceiling=endurance_ceiling,
        spread=endurance_spread,
        outlier_bounds=endurance_outliers,
    )
    endurance = _adjust_endurance(endurance)
    control, _ = _sample_rating(
        control_center,
        floor=control_floor,
        ceiling=control_ceiling,
        spread=control_spread,
        outlier_bounds=control_outliers,
    )
    movement, _ = _sample_rating(
        movement_center,
        floor=movement_floor,
        ceiling=movement_ceiling,
        spread=movement_spread,
        outlier_bounds=movement_outliers,
    )
    if throws == "L":
        movement = min(92, movement + 4)
        control = max(50, control - 4)
    hold_runner, _ = _sample_rating(
        hold_center,
        floor=hold_floor,
        ceiling=hold_ceiling,
        spread=5.0,
        outlier_bounds=(70, 86),
    )
    arm, _ = _sample_rating(
        arm_center,
        floor=arm_floor,
        ceiling=arm_ceiling,
        spread=5.8,
        outlier_bounds=(80, 94),
    )
    fielding, _ = _sample_rating(
        54,
        floor=40,
        ceiling=74,
        spread=5.0,
        outlier_bounds=(72, 86),
    )
    return {
        "endurance": endurance,
        "control": control,
        "movement": movement,
        "hold_runner": hold_runner,
        "arm": arm,
        "fa": fielding,
    }


def generate_fielding_potentials(primary: str, others: List[str]) -> Dict[str, int]:
    matrix = FIELDING_POTENTIAL_MATRIX.get(primary, {})
    potentials: Dict[str, int] = {}
    for pos, value in matrix.items():
        if pos == primary or pos in others:
            continue
        potentials[pos] = value
    return potentials

PITCH_WEIGHTS = {
    ("L", "overhand"): {"fb": 512, "si": 112, "cu": 168, "cb": 164, "sl": 138, "kn": 1, "sc": 13},
    ("L", "sidearm"): {"fb": 512, "si": 168, "cu": 112, "cb": 138, "sl": 164, "kn": 1, "sc": 11},
    ("R", "overhand"): {"fb": 512, "si": 112, "cu": 168, "cb": 164, "sl": 138, "kn": 13, "sc": 1},
    ("R", "sidearm"): {"fb": 512, "si": 168, "cu": 112, "cb": 138, "sl": 164, "kn": 13, "sc": 1},
}


def _weighted_choice(weight_dict: Dict[str, int]) -> str:
    total = sum(weight_dict.values())
    r = random.uniform(0, total)
    upto = 0
    for item, weight in weight_dict.items():
        if upto + weight >= r:
            return item
        upto += weight
    return item  # pragma: no cover


def _estimate_zone_bounds(height_in: int) -> tuple[float, float]:
    base_bottom = 1.5
    base_top = 3.5
    bottom = base_bottom + (height_in - 72) * 0.01
    top = base_top + (height_in - 72) * 0.015
    bottom = max(1.2, bottom)
    top = min(4.3, top)
    if top - bottom < 1.8:
        top = bottom + 1.8
    return round(bottom, 3), round(top, 3)


def generate_pitches(throws: str, delivery: str, age: int):
    """Generate pitch ratings without exceeding rating caps.

    The previous implementation allocated points from a large pool which often
    resulted in fastball (``fb``) ratings above 99 that were immediately capped,
    producing identical ``fb`` and ``arm`` values for every pitcher.  This
    version assigns ratings to each selected pitch independently using bounded
    random values so that fastball and arm strength vary naturally.
    """

    weights = PITCH_WEIGHTS[(throws, delivery)]
    num_pitches = random.randint(2, 5)

    selected = ["fb"]
    available = list(weights.keys())
    available.remove("fb")
    for _ in range(num_pitches - 1):
        pitch = random.choices(available, weights=[weights[p] for p in available])[0]
        selected.append(pitch)
        available.remove(pitch)

    ratings = {}
    for pitch in selected:
        if pitch == "fb":
            ratings[pitch] = bounded_rating(40, 99)
        else:
            ratings[pitch] = bounded_rating(20, 95)

    for p in PITCH_LIST:
        ratings.setdefault(p, 0)

    potentials = {
        f"pot_{p}": bounded_potential(ratings[p], age) if ratings[p] else 0
        for p in PITCH_LIST
    }
    return ratings, potentials


def _maybe_add_hitting(player: Dict, age: int, allocation: float = 0.75) -> None:
    """Occasionally give a pitcher credible hitting attributes.

    According to the ARR tables there is a 1 in 100 chance that a pitcher is
    also a good hitter.  When triggered we allocate ``allocation`` percent of
    the usual rating points to hitting related attributes.
    """

    if random.randint(1, 100) != 1:
        return

    attrs = {}
    for key in ["ch", "ph", "sp", "eye", "gf", "pl", "vl", "sc"]:
        rating = int(bounded_rating() * allocation)
        attrs[key] = rating
        if key in {"ch", "ph", "sp", "eye", "gf", "sc"}:
            attrs[f"pot_{key}"] = bounded_potential(rating, age)

    player.update(attrs)


def _maybe_add_pitching(player: Dict, age: int, throws: str, allocation: float = 0.75) -> None:
    """Occasionally give a position player credible pitching attributes."""

    if random.randint(1, 1000) != 1:
        return

    endurance = _adjust_endurance(int(bounded_rating() * allocation))
    control = int(bounded_rating() * allocation)
    movement = int(bounded_rating() * allocation)
    hold_runner = int(bounded_rating() * allocation)
    delivery = random.choices(["overhand", "sidearm"], weights=[95, 5])[0]

    pitch_ratings, _ = generate_pitches(throws, delivery, age)
    pitch_ratings = {p: int(r * allocation) for p, r in pitch_ratings.items()}
    pitch_pots = {
        f"pot_{p}": bounded_potential(pitch_ratings[p], age) if pitch_ratings[p] else 0
        for p in PITCH_LIST
    }

    player.update(
        {
            "endurance": endurance,
            "control": control,
            "movement": movement,
            "hold_runner": hold_runner,
            "role": "SP" if endurance > 55 else "RP",
            "delivery": delivery,
            "pot_endurance": bounded_potential(endurance, age),
            "pot_control": bounded_potential(control, age),
            "pot_movement": bounded_potential(movement, age),
            "pot_hold_runner": bounded_potential(hold_runner, age),
        }
    )
    player.update(pitch_ratings)
    player.update(pitch_pots)
    for key in list(pitch_ratings.keys()) + list(pitch_pots.keys()):
        player.setdefault(key, 0)
    player.setdefault("other_positions", [])
    if "P" not in player["other_positions"]:
        player["other_positions"].append("P")

def generate_player(
    is_pitcher: bool,
    for_draft: bool = False,
    age_range: Optional[Tuple[int, int]] = None,
    primary_position: Optional[str] = None,
    player_type: Optional[str] = None,
    pitcher_archetype: Optional[str] = None,
    hitter_archetype: Optional[str] = None,
    rating_profile: str = "normalized",
) -> Dict:
    """Generate a single player record.

    Parameters
    ----------
    is_pitcher: bool
        If True a pitcher is created, otherwise a hitter.
    for_draft: bool
        When generating players for the draft pool the typical age range is
        narrower.  This flag preserves that behaviour when ``age_range`` is not
        supplied.
    age_range: Optional[Tuple[int, int]]
        Optional ``(min_age, max_age)`` tuple.  If provided it is forwarded to
        :func:`generate_birthdate` and takes precedence over ``player_type``.
    primary_position: Optional[str]
        When generating hitters this can be used to force a specific primary
        position rather than selecting one at random.
    player_type: Optional[str]
        Explicit player type to select the age table from
        :data:`AGE_TABLES`.  If not supplied ``for_draft`` determines whether
        the ``"amateur"`` or ``"fictional"`` table is used.

    pitcher_archetype: Optional[str]
        When generating pitchers, optionally choose a specific archetype such
        as ``\"closer\"`` to bias the ratings/traits toward that profile.
    hitter_archetype: Optional[str]
        When generating hitters, optionally choose a specific archetype
        (power, balanced, spray, etc.) to bias ratings toward that profile.
    rating_profile: str
        Rating profile to use for core attributes. Supports ``\"arr\"`` or
        ``\"normalized\"``.

    Returns
    -------
    Dict
        A dictionary describing the generated player.
    """

    # Determine the player's age using either an explicit ``age_range`` or the
    # appropriate age table based on ``player_type``/``for_draft``.
    if age_range is not None:
        birthdate, age = generate_birthdate(age_range=age_range)
    else:
        if player_type is None:
            player_type = "amateur" if for_draft else "fictional"
        birthdate, age = generate_birthdate(player_type=player_type)
    first_name, last_name, ethnicity = generate_name()
    player_id = f"P{random.randint(1000, 9999)}"
    height = random.randint(68, 78)
    weight = random.randint(160, 250)
    skin_tone = assign_skin_tone(ethnicity)
    hair_color = assign_hair_color(ethnicity)
    facial_hair = assign_facial_hair(ethnicity, age)
    profile = (rating_profile or "normalized").strip().lower()
    if profile not in {"arr", "normalized"}:
        profile = "normalized"
    use_normalized = profile == "normalized"

    # Situational modifiers derived from ARR tables (lines 199-225)
    mo = roll_dice(35, 5, 5)  # monthly
    gf = roll_dice(25, 10, 4)  # ground/fly
    cl = roll_dice(35, 5, 5)  # close/late
    hm = roll_dice(35, 5, 5)  # home
    sc = roll_dice(35, 5, 5)  # scoring position
    # Widen pull rating distribution for greater variance
    pl = roll_dice(25, 5, 10)  # pull rating

    if is_pitcher:
        bats, throws = assign_bats_throws("P")
        # Expand pitcher platoon splits for more variation
        vl = roll_dice(20, 10, 6) if throws == "L" else roll_dice(10, 10, 6)
        pitcher_archetype_label = ""
        normalized_pitcher = (
            _sample_normalized_pitcher(pitcher_archetype, throws)
            if use_normalized
            else None
        )
        if normalized_pitcher:
            endurance = normalized_pitcher["endurance"]
            control = normalized_pitcher["control"]
            movement = normalized_pitcher["movement"]
            hold_runner = normalized_pitcher["hold_runner"]
            arm = normalized_pitcher["arm"]
            fa = normalized_pitcher["fa"]
            gf = normalized_pitcher["gf"]
            vl = normalized_pitcher["vl"]
            durability = normalized_pitcher.get("durability") or _generate_durability(
                age, True
            )
            preferred_pitching_role = (
                str(
                    normalized_pitcher.get("preferred_pitching_role")
                    or normalized_pitcher.get("role")
                    or ""
                )
                .strip()
                .upper()
            )
            role = "SP" if endurance > 55 else "RP"
            if preferred_pitching_role in {"CL", "SU", "RP", "MR", "LR"}:
                role = "RP"
            if pitcher_archetype == "closer" and not preferred_pitching_role:
                preferred_pitching_role = "CL"
                role = "RP"
            delivery = random.choices(["overhand", "sidearm"], weights=[95, 5])[0]
            pitcher_archetype_label = str(
                normalized_pitcher.get("pitcher_archetype") or ""
            )
            pitch_ratings = {
                key: int(normalized_pitcher.get(key, 0))
                for key in PITCHER_PITCH_KEYS
            }
            pitch_pots = {
                f"pot_{p}": bounded_potential(pitch_ratings[p], age)
                if pitch_ratings[p]
                else 0
                for p in PITCHER_PITCH_KEYS
            }
        else:
            # Allocate pitching related ratings from a shared pool using the ARR
            # derived weights.  A second pool is used to determine the pitcher's
            # fielding ability.
            core_ratings = _generate_pitcher_core_ratings(
                throws, archetype=pitcher_archetype
            )
            endurance = core_ratings["endurance"]
            control = core_ratings["control"]
            movement = core_ratings["movement"]
            hold_runner = core_ratings["hold_runner"]
            arm = core_ratings["arm"]
            fa = core_ratings["fa"]

            role = "SP" if endurance > 55 else "RP"
            preferred_pitching_role = ""
            if pitcher_archetype == "closer":
                role = "RP"
                preferred_pitching_role = "CL"
                endurance = min(endurance, 55)
            delivery = random.choices(["overhand", "sidearm"], weights=[95, 5])[0]
            pitch_ratings, pitch_pots = generate_pitches(throws, delivery, age)
            if pitcher_archetype == "closer":
                pitch_ratings["fb"] = max(pitch_ratings.get("fb", 0), 85)
                slider_floor = bounded_rating(65, 90)
                pitch_ratings["sl"] = max(pitch_ratings.get("sl", 0), slider_floor)
                pitch_ratings["si"] = max(pitch_ratings.get("si", 0), 60)

            durability = _generate_durability(age, True)
            if pitcher_archetype:
                pitcher_archetype_label = pitcher_archetype
        zone_bottom, zone_top = _estimate_zone_bounds(height)

        player = {
            "first_name": first_name,
            "last_name": last_name,
            "injured": 0,
            "injury_description": 0,
            "return_date": 0,
            "player_id": player_id,
            "is_pitcher": True,
            "birthdate": birthdate,
            "bats": bats,
            "throws": throws,
            "arm": arm,
            "fa": fa,
            "control": control,
            "movement": movement,
            "endurance": endurance,
            "hold_runner": hold_runner,
            "role": role,
            "delivery": delivery,
            "mo": mo,
            "gf": gf,
            "cl": cl,
            "hm": hm,
            "pl": pl,
            "vl": vl,
            "durability": durability,
            "height": height,
            "weight": weight,
            "zone_bottom": zone_bottom,
            "zone_top": zone_top,
            "pitcher_archetype": pitcher_archetype_label,
            "ethnicity": ethnicity,
            "skin_tone": skin_tone,
            "hair_color": hair_color,
            "facial_hair": facial_hair,
            "primary_position": "P",
            "other_positions": assign_secondary_positions("P"),
            "pot_control": bounded_potential(control, age),
            "pot_movement": bounded_potential(movement, age),
            "pot_endurance": bounded_potential(endurance, age),
            "pot_hold_runner": bounded_potential(hold_runner, age),
            "pot_arm": bounded_potential(arm, age),
            "pot_fa": bounded_potential(fa, age),
            "preferred_pitching_role": preferred_pitching_role,
        }
        player.update(pitch_ratings)
        player.update(pitch_pots)
        for key in list(pitch_ratings.keys()) + list(pitch_pots.keys()):
            player.setdefault(key, 0)
        _maybe_add_hitting(player, age)
        player["pot_fielding"] = generate_fielding_potentials("P", player["other_positions"])
        if pitcher_archetype == "closer":
            player["cl"] = max(player["cl"], 65)
            player["gf"] = max(player["gf"], 55)
        if for_draft:
            _apply_draft_rating_scale(player, age)
        _apply_player_defaults(player)
        return player

    else:
        # If the caller specifies a primary position we honour it and bypass
        # the usual random assignment.
        primary_pos = primary_position or assign_primary_position()
        bats, throws = assign_bats_throws(primary_pos)
        if bats == "L":
            vl = roll_dice(15, 10, 6)
        elif bats == "R":
            vl = roll_dice(20, 10, 6)
        else:
            vl = roll_dice(18, 10, 6)
        other_pos = assign_secondary_positions(primary_pos)
        hitter_archetype_label = ""
        normalized_hitter = (
            _sample_normalized_hitter(primary_pos, bats, hitter_archetype)
            if use_normalized
            else None
        )
        if normalized_hitter:
            ch = normalized_hitter["ch"]
            ph = normalized_hitter["ph"]
            sp = normalized_hitter["sp"]
            eye = normalized_hitter["eye"]
            gf = normalized_hitter["gf"]
            pl = normalized_hitter["pl"]
            vl = normalized_hitter["vl"]
            sc = normalized_hitter["sc"]
            fa = normalized_hitter["fa"]
            arm = normalized_hitter["arm"]
            durability = normalized_hitter.get("durability") or _generate_durability(
                age, False
            )
            hitter_archetype_label = str(
                normalized_hitter.get("hitter_archetype") or ""
            )
        else:
            ratings = _generate_hitter_ratings(primary_pos)
            ch = ratings["ch"]
            ph = ratings["ph"]
            sp = ratings["sp"]
            eye = ratings["eye"]
            fa = ratings["fa"]
            arm = ratings["arm"]
            durability = _generate_durability(age, False)
            if hitter_archetype:
                hitter_archetype_label = hitter_archetype
        zone_bottom, zone_top = _estimate_zone_bounds(height)

        player = {
            "first_name": first_name,
            "last_name": last_name,
            "injured": 0,
            "injury_description": 0,
            "return_date": 0,
            "player_id": player_id,
            "is_pitcher": False,
            "birthdate": birthdate,
            "bats": bats,
            "throws": throws,
            "ch": ch,
            "ph": ph,
            "sp": sp,
            "eye": eye,
            "gf": gf,
            "pl": pl,
            "vl": vl,
            "sc": sc,
            "mo": mo,
            "cl": cl,
            "hm": hm,
            "fa": fa,
            "arm": arm,
            "durability": durability,
            "height": height,
            "weight": weight,
            "zone_bottom": zone_bottom,
            "zone_top": zone_top,
            "hitter_archetype": hitter_archetype_label,
            "ethnicity": ethnicity,
            "skin_tone": skin_tone,
            "hair_color": hair_color,
            "facial_hair": facial_hair,
            "primary_position": primary_pos,
            "other_positions": other_pos,
            "pot_ch": bounded_potential(ch, age),
            "pot_ph": bounded_potential(ph, age),
            "pot_sp": bounded_potential(sp, age),
            "pot_eye": bounded_potential(eye, age),
            "pot_fa": bounded_potential(fa, age),
            "pot_arm": bounded_potential(arm, age),
            "pot_sc": sc,
            "pot_gf": gf
        }
        all_keys = [
            "ch",
            "ph",
            "sp",
            "eye",
            "gf",
            "pl",
            "vl",
            "sc",
            "fa",
            "arm",
            "durability",
            "pot_ch",
            "pot_ph",
            "pot_sp",
            "pot_eye",
            "pot_fa",
            "pot_arm",
            "pot_sc",
            "pot_gf",
        ]
        for key in all_keys:
            player.setdefault(key, 0)
        _maybe_add_pitching(player, age, throws)
        player["pot_fielding"] = generate_fielding_potentials(primary_pos, player["other_positions"])
        if for_draft:
            _apply_draft_rating_scale(player, age)
        _apply_player_defaults(player)
        return player


def generate_draft_pool(
    num_players: int = 75,
    rating_profile: str = "normalized",
) -> List[Dict]:
    players = []
    hitter_weight = sum(PRIMARY_POSITION_WEIGHTS.values())
    pitcher_weight = hitter_weight * (PITCHER_RATE / (1 - PITCHER_RATE))
    # Derive pitcher probability from position weights
    pitcher_rate = pitcher_weight / (pitcher_weight + hitter_weight)
    pitcher_slots = max(1, min(num_players, int(round(num_players * pitcher_rate))))
    hitter_slots = max(0, num_players - pitcher_slots)
    role_flags = ["pitcher"] * pitcher_slots + ["hitter"] * hitter_slots
    random.shuffle(role_flags)
    closer_quota = 0
    if pitcher_slots > 0:
        closer_quota = max(1, int(round(pitcher_slots * DRAFT_CLOSER_RATE)))
        closer_quota = min(closer_quota, pitcher_slots)
    pitcher_indices = [idx for idx, flag in enumerate(role_flags) if flag == "pitcher"]
    closer_indices: set[int] = set()
    if closer_quota and pitcher_indices:
        closer_indices = set(random.sample(pitcher_indices, closer_quota))
    for idx, flag in enumerate(role_flags):
        if flag == "pitcher":
            archetype = "closer" if idx in closer_indices else None
            players.append(
                generate_player(
                    is_pitcher=True,
                    for_draft=True,
                    pitcher_archetype=archetype,
                    rating_profile=rating_profile,
                )
            )
        else:
            players.append(
                generate_player(
                    is_pitcher=False,
                    for_draft=True,
                    rating_profile=rating_profile,
                )
            )
    # Ensure all players have all keys filled
    all_keys = set(k for player in players for k in player.keys())
    for player in players:
        for key in all_keys:
            player.setdefault(key, 0)

    return players

if __name__ == "__main__":  # pragma: no cover - manual script usage
    if pd is None:
        raise SystemExit("pandas is required to export the draft pool")
    draft_pool = generate_draft_pool()
    df = pd.DataFrame(draft_pool)
    df.to_csv("draft_pool.csv", index=False)
    print(f"Draft pool of {len(draft_pool)} players saved to draft_pool.csv")
