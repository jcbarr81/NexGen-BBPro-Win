from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict

from services.transaction_log import record_transaction, reset_player_cache
from utils.exceptions import DraftRosterError
from utils.news_logger import log_news_event
from utils.path_utils import get_base_dir
from utils.roster_loader import load_roster, save_roster

LOW_MAX = 10


BASE = get_base_dir()
DATA = BASE / "data"


def _players_csv_path() -> Path:
    return DATA / "players.csv"


def _results_path(year: int) -> Path:
    return DATA / f"draft_results_{year}.csv"


def _pool_path(year: int) -> Path:
    return DATA / f"draft_pool_{year}.csv"


def _load_pool_map(year: int) -> Dict[str, Dict[str, Any]]:
    path = _pool_path(year)
    pool: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return pool
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pool[row.get("player_id", "")] = row
    return pool


def _read_players_header() -> list[str]:
    path = _players_csv_path()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
    return header


def _default_row_from_pool(pool_row: Dict[str, Any]) -> Dict[str, Any]:
    # Map DraftProspect fields to players.csv schema; fill with defaults where needed
    row: Dict[str, Any] = {}

    def _as_int(key: str, default: int = 0) -> int:
        value = pool_row.get(key, default)
        if value in ("", None):
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    def _as_text(key: str, default: str = "") -> str:
        value = pool_row.get(key, default)
        if value is None:
            return default
        return str(value)

    pid = pool_row.get("player_id", "")
    first = pool_row.get("first_name", "Prospect")
    last = pool_row.get("last_name", "")
    birthdate = pool_row.get("birthdate", "2006-01-01")
    is_pitcher = str(pool_row.get("is_pitcher", "0")).lower() in {"1", "true", "yes"}
    primary = pool_row.get("primary_position", "P" if is_pitcher else "SS")
    other = pool_row.get("other_positions", "")
    ch = _as_int("ch", 50)
    ph = _as_int("ph", 50)
    sp = _as_int("sp", 50)
    eye = _as_int("eye", ch)
    gf = _as_int("gf", 50)
    pl = _as_int("pl", 50)
    vl = _as_int("vl", 50)
    sc = _as_int("sc", 50)
    fa = _as_int("fa", 50)
    arm = _as_int("arm", 50)
    endurance = _as_int("endurance", 0)
    control = _as_int("control", 0)
    movement = _as_int("movement", 0)
    hold = _as_int("hold_runner", 0)
    fb = _as_int("fb", 0)
    cu = _as_int("cu", 0)
    cb = _as_int("cb", 0)
    sl = _as_int("sl", 0)
    si = _as_int("si", 0)
    scb = _as_int("scb", 0)
    kn = _as_int("kn", 0)
    durability = _as_int("durability", 50)
    preferred_role = _as_text("preferred_pitching_role", "").strip()
    if not preferred_role:
        archetype = _as_text("pitcher_archetype", "").strip().lower()
        if archetype == "closer":
            preferred_role = "CL"

    # Defaults
    height = _as_int("height", 72)
    weight = _as_int("weight", 195)
    ethnicity = _as_text("ethnicity", "Anglo")
    skin_tone = _as_text("skin_tone", "medium")
    hair_color = _as_text("hair_color", "brown")
    facial_hair = _as_text("facial_hair", "clean_shaven")
    bats = _as_text("bats", "R")
    role = _as_text("role", "").strip()
    if not role:
        role = "SP" if is_pitcher and endurance >= 55 else ("RP" if is_pitcher else "")

    row.update(
        {
            "player_id": pid,
            "first_name": first,
            "last_name": last,
            "birthdate": birthdate,
            "height": height,
            "weight": weight,
            "ethnicity": ethnicity,
            "skin_tone": skin_tone,
            "hair_color": hair_color,
            "facial_hair": facial_hair,
            "bats": bats,
            "primary_position": primary,
            "other_positions": (
                other if isinstance(other, str) else "|".join(other or [])
            ),
            "is_pitcher": 1 if is_pitcher else 0,
            "role": role,
            "preferred_pitching_role": preferred_role,
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
            "endurance": endurance,
            "control": control,
            "movement": movement,
            "hold_runner": hold,
            "durability": durability,
            # Pitches (defaults)
            "fb": fb,
            "cu": cu,
            "cb": cb,
            "sl": sl,
            "si": si,
            "scb": scb,
            "kn": kn,
            # Potentials: mirror current ratings as a baseline
            "pot_ch": _as_int("pot_ch", ch),
            "pot_ph": _as_int("pot_ph", ph),
            "pot_sp": _as_int("pot_sp", sp),
            "pot_eye": _as_int("pot_eye", eye),
            "pot_gf": _as_int("pot_gf", gf),
            "pot_pl": _as_int("pot_pl", pl),
            "pot_vl": _as_int("pot_vl", vl),
            "pot_sc": _as_int("pot_sc", sc),
            "pot_fa": _as_int("pot_fa", fa),
            "pot_arm": _as_int("pot_arm", arm),
            "pot_control": _as_int("pot_control", control),
            "pot_movement": _as_int("pot_movement", movement),
            "pot_endurance": _as_int("pot_endurance", endurance),
            "pot_hold_runner": _as_int("pot_hold_runner", hold),
            "pot_fb": _as_int("pot_fb", fb),
            "pot_cu": _as_int("pot_cu", cu),
            "pot_cb": _as_int("pot_cb", cb),
            "pot_sl": _as_int("pot_sl", sl),
            "pot_si": _as_int("pot_si", si),
            "pot_scb": _as_int("pot_scb", scb),
            "pot_kn": _as_int("pot_kn", kn),
            "injured": False,
            "injury_description": "",
            "return_date": "",
        }
    )
    return row


def _players_index() -> Dict[str, Dict[str, Any]]:
    path = _players_csv_path()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return {row.get("player_id", ""): row for row in reader}


def _append_players(rows: list[Dict[str, Any]]) -> None:
    if not rows:
        return
    path = _players_csv_path()
    header = _read_players_header()
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header)
        for row in rows:
            # Ensure all columns exist
            payload = {k: row.get(k, "") for k in header}
            writer.writerow(payload)
    reset_player_cache()


def _assign_to_low(team_id: str, player_id: str) -> tuple[bool, str | None, bool]:
    try:
        roster = load_roster(team_id)
    except FileNotFoundError:
        return False, f"{team_id}: roster file not found", False
    except Exception as exc:
        return False, f"{team_id}: {exc}", False

    if player_id in roster.act or player_id in roster.aaa or player_id in roster.low:
        return True, None, False

    compliance_note = None
    appended = False
    try:
        roster.low.append(player_id)
        appended = True
        if len(roster.low) > LOW_MAX:
            compliance_note = f"{team_id}: LOW roster exceeds {LOW_MAX} players (fix before resuming)."
        save_roster(team_id, roster)
        try:
            load_roster.cache_clear()
        except Exception:
            pass
    except PermissionError:
        if appended and player_id in roster.low:
            roster.low.remove(player_id)
        return False, f"{team_id}: roster file is read-only (unlock data/rosters/{team_id}.csv)", False
    except Exception as exc:
        if appended and player_id in roster.low:
            roster.low.remove(player_id)
        return False, f"{team_id}: {exc}", False
    return True, compliance_note, bool(compliance_note)


def _prospect_name(pool_row: Dict[str, Any], players_index: Dict[str, Dict[str, Any]], pid: str) -> str:
    first = str(pool_row.get("first_name", "")).strip()
    last = str(pool_row.get("last_name", "")).strip()
    if first or last:
        return f"{first} {last}".strip()
    existing = players_index.get(pid, {})
    first = str(existing.get("first_name", "")).strip()
    last = str(existing.get("last_name", "")).strip()
    if first or last:
        return f"{first} {last}".strip()
    return pid


def _safe_positive_int(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _pick_suffix(round_value: Any, overall_value: Any) -> str:
    rnd = _safe_positive_int(round_value)
    overall = _safe_positive_int(overall_value)
    if rnd and overall:
        return f" (R{rnd}, #{overall})"
    if rnd:
        return f" (R{rnd})"
    if overall:
        return f" (#{overall})"
    return ""


def commit_draft_results(
    year: int,
    *,
    season_date: str | None = None,
) -> dict[str, object]:
    """Append drafted players to players.csv and place them on LOW rosters."""

    res_path = _results_path(year)
    if not res_path.exists():
        return {"players_added": 0, "roster_assigned": 0, "failures": []}
    pool_map = _load_pool_map(year)
    players_index = _players_index()
    to_append: list[Dict[str, Any]] = []
    assigned = 0
    failures: list[str] = []
    compliance_issues: list[str] = []

    with res_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pid = row.get("player_id", "")
            tid = row.get("team_id", "")
            if not pid or not tid:
                continue
            pool_row = pool_map.get(pid, {})
            if pid not in players_index:
                to_append.append(_default_row_from_pool(pool_row | {"player_id": pid}))
            ok, note, compliance = _assign_to_low(tid, pid)
            if ok:
                assigned += 1
                if compliance and note:
                    compliance_issues.append(note)
            else:
                failures.append(note or f"{tid}: unable to assign {pid}")
            player_name = _prospect_name(pool_row, players_index, pid)
            detail = f"Drafted in {year} Amateur Draft"
            if compliance and note:
                detail += f" ({note})"
            elif not ok:
                detail += " (pending roster space)"
            try:
                record_transaction(
                    action="draft",
                    team_id=tid,
                    player_id=pid,
                    player_name=player_name,
                    to_level="LOW",
                    details=detail,
                    season_date=season_date,
                )
            except Exception:
                pass
            try:
                pos = str(pool_row.get("primary_position", "")).strip()
                if pos:
                    player_label = f"{pos} {player_name}".strip()
                else:
                    player_label = player_name or pid
                pick_suffix = _pick_suffix(row.get("round"), row.get("overall_pick"))
                log_news_event(
                    f"{tid} drafted {player_label}{pick_suffix}.",
                    category="draft",
                    team_id=tid,
                    file_path=DATA / "news_feed.txt",
                )
            except Exception:
                pass

    _append_players(to_append)

    summary: dict[str, object] = {
        "players_added": len(to_append),
        "roster_assigned": assigned,
        "failures": [msg for msg in failures if msg],
        "compliance_issues": [msg for msg in compliance_issues if msg],
    }
    blocking = summary["failures"] or summary["compliance_issues"]
    if blocking:
        raise DraftRosterError(blocking, summary)
    return summary


__all__ = ["commit_draft_results"]
