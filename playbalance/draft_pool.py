from __future__ import annotations

"""Draft pool generation and I/O helpers.

This module provides a minimal, deterministic draft pool generator so we can
exercise Draft Day pause/resume. It favors simplicity: names are sampled from
``data/names.csv`` (or ``data/players.csv`` if present), positions are
distributed across P/C/IF/OF buckets, and ratings are sampled from the
template-based player generator.

The file formats are intentionally simple and will evolve as the draft console
gains features:

- CSV: data/draft_pool_<year>.csv
- JSON: data/draft_pool_<year>.json (simple list of dicts)
"""

import csv
import json
import os
import random
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, Iterable, List

from utils.path_utils import get_data_dir
from playbalance import player_generator as pg


BASE = get_data_dir()
NAMES = BASE / "names.csv"
PLAYERS = BASE / "players.csv"


@dataclass
class DraftProspect:
    player_id: str
    first_name: str
    last_name: str
    bats: str
    throws: str
    primary_position: str
    other_positions: List[str] = field(default_factory=list)
    is_pitcher: bool = False
    birthdate: str = ""
    height: int = 72
    weight: int = 195
    ethnicity: str = "Anglo"
    skin_tone: str = "medium"
    hair_color: str = "brown"
    facial_hair: str = "clean_shaven"
    role: str = ""
    preferred_pitching_role: str = ""
    hitter_archetype: str = ""
    pitcher_archetype: str = ""
    ch: int = 50
    ph: int = 50
    sp: int = 50
    eye: int = 50
    gf: int = 50
    pl: int = 50
    vl: int = 50
    sc: int = 50
    fa: int = 50
    arm: int = 50
    endurance: int = 0
    control: int = 0
    movement: int = 0
    hold_runner: int = 0
    fb: int = 0
    cu: int = 0
    cb: int = 0
    sl: int = 0
    si: int = 0
    scb: int = 0
    kn: int = 0
    pot_ch: int = 0
    pot_ph: int = 0
    pot_sp: int = 0
    pot_eye: int = 0
    pot_gf: int = 0
    pot_pl: int = 0
    pot_vl: int = 0
    pot_sc: int = 0
    pot_fa: int = 0
    pot_arm: int = 0
    pot_control: int = 0
    pot_movement: int = 0
    pot_endurance: int = 0
    pot_hold_runner: int = 0
    pot_fb: int = 0
    pot_cu: int = 0
    pot_cb: int = 0
    pot_sl: int = 0
    pot_si: int = 0
    pot_scb: int = 0
    pot_kn: int = 0
    durability: int = 50


def _name_source() -> List[Dict[str, str]]:
    path = PLAYERS if PLAYERS.exists() else NAMES
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _id_gen(year: int) -> Iterable[str]:
    n = 1
    while True:
        yield f"D{year}{n:04d}"
        n += 1


def _pick_position() -> str:
    # Rough distribution: 45% P, 10% C, 30% IF, 15% OF
    r = random.random()
    if r < 0.45:
        return "P"
    if r < 0.55:
        return "C"
    if r < 0.85:
        return random.choice(["1B", "2B", "3B", "SS"])
    return random.choice(["LF", "CF", "RF"])


def _rating_profile(selection: str | None = None) -> str:
    profile = selection or os.getenv("PB_RATING_PROFILE", "normalized")
    profile = profile.strip().lower()
    if profile not in {"arr", "normalized"}:
        profile = "normalized"
    return profile


def _draft_birthdate(year: int) -> str:
    age = random.randint(17, 21)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return f"{year - age}-{month:02d}-{day:02d}"


def _coerce_list(value: object) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        if "|" in value:
            return [item for item in value.split("|") if item]
        value = value.strip()
        return [value] if value else []
    return []


def _coerce_int(value: object, default: int = 0) -> int:
    if value in ("", None):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _prospect_from_player(
    *,
    player: Dict[str, object],
    player_id: str,
    first: str,
    last: str,
    birthdate: str,
    is_pitcher: bool,
) -> DraftProspect:
    bats = str(player.get("bats", "R") or "R")
    throws = str(player.get("throws", bats) or bats)
    other_positions = _coerce_list(player.get("other_positions"))
    primary_position = str(
        player.get("primary_position", "P" if is_pitcher else "SS")
    )
    ch = _coerce_int(player.get("ch"), 50)
    ph = _coerce_int(player.get("ph"), 50)
    sp = _coerce_int(player.get("sp"), 50)
    eye = _coerce_int(player.get("eye"), ch)
    gf = _coerce_int(player.get("gf"), 50)
    pl = _coerce_int(player.get("pl"), 50)
    vl = _coerce_int(player.get("vl"), 50)
    sc = _coerce_int(player.get("sc"), 50)
    fa = _coerce_int(player.get("fa"), 50)
    arm = _coerce_int(player.get("arm"), 50)
    endurance = _coerce_int(player.get("endurance"), 0)
    control = _coerce_int(player.get("control"), 0)
    movement = _coerce_int(player.get("movement"), 0)
    hold_runner = _coerce_int(player.get("hold_runner"), 0)
    fb = _coerce_int(player.get("fb"), 0)
    cu = _coerce_int(player.get("cu"), 0)
    cb = _coerce_int(player.get("cb"), 0)
    sl = _coerce_int(player.get("sl"), 0)
    si = _coerce_int(player.get("si"), 0)
    scb = _coerce_int(player.get("scb"), 0)
    kn = _coerce_int(player.get("kn"), 0)

    return DraftProspect(
        player_id=player_id,
        first_name=first,
        last_name=last,
        bats=bats,
        throws=throws,
        primary_position=primary_position,
        other_positions=other_positions,
        is_pitcher=is_pitcher,
        birthdate=birthdate,
        height=_coerce_int(player.get("height"), 72),
        weight=_coerce_int(player.get("weight"), 195),
        ethnicity=str(player.get("ethnicity", "Anglo") or "Anglo"),
        skin_tone=str(player.get("skin_tone", "medium") or "medium"),
        hair_color=str(player.get("hair_color", "brown") or "brown"),
        facial_hair=str(player.get("facial_hair", "clean_shaven") or "clean_shaven"),
        role=str(player.get("role", "SP" if is_pitcher else "") or ""),
        preferred_pitching_role=str(
            player.get("preferred_pitching_role", "") or ""
        ),
        hitter_archetype=str(player.get("hitter_archetype", "") or ""),
        pitcher_archetype=str(player.get("pitcher_archetype", "") or ""),
        ch=ch,
        ph=ph,
        sp=sp,
        eye=eye,
        gf=gf,
        pl=pl,
        vl=vl,
        sc=sc,
        fa=fa,
        arm=arm,
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
        pot_ch=_coerce_int(player.get("pot_ch"), ch),
        pot_ph=_coerce_int(player.get("pot_ph"), ph),
        pot_sp=_coerce_int(player.get("pot_sp"), sp),
        pot_eye=_coerce_int(player.get("pot_eye"), eye),
        pot_gf=_coerce_int(player.get("pot_gf"), gf),
        pot_pl=_coerce_int(player.get("pot_pl"), pl),
        pot_vl=_coerce_int(player.get("pot_vl"), vl),
        pot_sc=_coerce_int(player.get("pot_sc"), sc),
        pot_fa=_coerce_int(player.get("pot_fa"), fa),
        pot_arm=_coerce_int(player.get("pot_arm"), arm),
        pot_control=_coerce_int(player.get("pot_control"), control),
        pot_movement=_coerce_int(player.get("pot_movement"), movement),
        pot_endurance=_coerce_int(player.get("pot_endurance"), endurance),
        pot_hold_runner=_coerce_int(player.get("pot_hold_runner"), hold_runner),
        pot_fb=_coerce_int(player.get("pot_fb"), fb),
        pot_cu=_coerce_int(player.get("pot_cu"), cu),
        pot_cb=_coerce_int(player.get("pot_cb"), cb),
        pot_sl=_coerce_int(player.get("pot_sl"), sl),
        pot_si=_coerce_int(player.get("pot_si"), si),
        pot_scb=_coerce_int(player.get("pot_scb"), scb),
        pot_kn=_coerce_int(player.get("pot_kn"), kn),
        durability=_coerce_int(player.get("durability"), 50),
    )


def generate_draft_pool(
    year: int,
    *,
    size: int = 200,
    seed: int | None = None,
    rating_profile: str | None = None,
) -> List[DraftProspect]:
    state = random.getstate()
    seed_value = seed
    if seed_value is None:
        seed_value = random.SystemRandom().randint(0, 2**32 - 1)
    random.seed(seed_value)
    profile = _rating_profile(rating_profile)
    rows = _name_source()
    if not rows:
        rows = [
            {"first_name": "Prospect", "last_name": f"{i}"} for i in range(size)
        ]

    ids = _id_gen(year)
    pool: List[DraftProspect] = []
    positions = [_pick_position() for _ in range(size)]
    required = ["C", "SS", "CF"]
    for req in required:
        if req not in positions:
            for idx, pos in enumerate(positions):
                if pos != "P":
                    positions[idx] = req
                    break
            else:
                positions[0] = req

    pitcher_indices = [idx for idx, pos in enumerate(positions) if pos == "P"]
    closer_indices: set[int] = set()
    if pitcher_indices:
        closer_quota = max(
            1, int(round(len(pitcher_indices) * pg.DRAFT_CLOSER_RATE))
        )
        closer_quota = min(closer_quota, len(pitcher_indices))
        closer_indices = set(random.sample(pitcher_indices, closer_quota))

    try:
        for idx, pos in enumerate(positions):
            row = random.choice(rows)
            first = row.get("first_name", "Prospect")
            last = row.get("last_name", "Unknown")
            is_pitcher = pos == "P"
            birthdate = _draft_birthdate(year)
            if is_pitcher:
                archetype = "closer" if idx in closer_indices else None
                player = pg.generate_player(
                    is_pitcher=True,
                    for_draft=True,
                    age_range=(17, 21),
                    pitcher_archetype=archetype,
                    rating_profile=profile,
                )
            else:
                player = pg.generate_player(
                    is_pitcher=False,
                    for_draft=True,
                    age_range=(17, 21),
                    primary_position=pos,
                    rating_profile=profile,
                )
            if player.get("birthdate"):
                birthdate = str(player.get("birthdate"))
            pool.append(
                _prospect_from_player(
                    player=player,
                    player_id=next(ids),
                    first=first,
                    last=last,
                    birthdate=birthdate,
                    is_pitcher=is_pitcher,
                )
            )
    finally:
        random.setstate(state)
    return pool


def save_draft_pool(year: int, prospects: List[DraftProspect]) -> None:
    base = BASE
    base.mkdir(parents=True, exist_ok=True)
    csv_path = base / f"draft_pool_{year}.csv"
    json_path = base / f"draft_pool_{year}.json"

    def _write_files():
        # CSV
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            fieldnames = list(asdict(prospects[0]).keys()) if prospects else [
                "player_id",
                "first_name",
                "last_name",
                "bats",
                "throws",
                "primary_position",
                "other_positions",
                "is_pitcher",
                "birthdate",
            ]
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for p in prospects:
                writer.writerow(asdict(p))
        # JSON
        with json_path.open("w", encoding="utf-8") as fh:
            json.dump([asdict(p) for p in prospects], fh, indent=2)
    _with_lock(json_path.with_suffix(json_path.suffix + ".lock"), _write_files)


def load_draft_pool(year: int) -> List[Dict[str, object]]:
    json_path = BASE / f"draft_pool_{year}.json"
    if not json_path.exists():
        return []
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return []


__all__ = [
    "DraftProspect",
    "generate_draft_pool",
    "save_draft_pool",
    "load_draft_pool",
]


def _with_lock(lock_path: Path, action) -> None:
    for _ in range(200):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            try:
                action()
            finally:
                os.close(fd)
                try:
                    os.remove(str(lock_path))
                except OSError:
                    pass
            return
        except FileExistsError:
            time.sleep(0.05)
    action()
