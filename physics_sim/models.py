from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


PITCH_KEYS = ["fb", "sl", "si", "cb", "cu", "scb", "kn"]


@dataclass
class BatterRatings:
    player_id: str
    bats: str
    primary_position: str
    other_positions: List[str]
    contact: float  # CH
    power: float  # PH
    gb_tendency: float  # GF
    pull_tendency: float  # PL
    vs_left: float  # VL
    fielding: float  # FA
    arm: float  # ARM
    speed: float  # SP
    eye: float
    height: float
    durability: float
    zone_bottom: Optional[float] = None
    zone_top: Optional[float] = None

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "BatterRatings":
        def f(key: str, default: float = 50.0) -> float:
            try:
                return float(row.get(key, default))
            except (TypeError, ValueError):
                return default
        def opt_float(key: str) -> Optional[float]:
            value = row.get(key)
            if value in (None, ""):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        other_positions = [
            p.strip()
            for p in (row.get("other_positions") or "").split(",")
            if p.strip()
        ]
        contact = f("ch")
        return cls(
            player_id=str(row.get("player_id", "")),
            bats=str(row.get("bats", "") or "R").upper(),
            primary_position=str(row.get("primary_position", "") or ""),
            other_positions=other_positions,
            contact=contact,
            power=f("ph"),
            gb_tendency=f("gf"),
            pull_tendency=f("pl"),
            vs_left=f("vl"),
            fielding=f("fa"),
            arm=f("arm"),
            speed=f("sp"),
            eye=f("eye", contact),
            height=f("height", 72.0),
            durability=f("durability", 50.0),
            zone_bottom=opt_float("zone_bottom"),
            zone_top=opt_float("zone_top"),
        )


@dataclass
class PitcherRatings:
    player_id: str
    bats: str
    throws: str  # pitching hand, "L" or "R"
    role: str
    preferred_role: str
    velocity: float  # derived from arm
    control: float
    movement: float
    gb_tendency: float
    vs_left: float
    hold_runner: float
    endurance: float
    durability: float
    fielding: float
    arm: float
    repertoire: Dict[str, float]

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> "PitcherRatings":
        def f(key: str, default: float = 50.0) -> float:
            try:
                return float(row.get(key, default))
            except (TypeError, ValueError):
                return default

        repertoire = {k: f(k) for k in PITCH_KEYS if f(k, 0.0) > 0.0}
        bats = str(row.get("bats", "") or "R").upper()
        throws = str(row.get("throws", "") or "").strip().upper()
        if throws not in {"L", "R"}:
            # players.csv only gained a throws column in 6.10.12; legacy league
            # CSVs lack it. Mirror utils/player_loader.py: most players throw
            # with the hand they bat; switch hitters default to "R".
            throws = "R" if bats == "S" else (bats if bats in {"L", "R"} else "R")
        return cls(
            player_id=str(row.get("player_id", "")),
            bats=bats,
            throws=throws,
            role=str(row.get("role", "") or "").upper(),
            preferred_role=str(row.get("preferred_pitching_role", "") or "").upper(),
            velocity=f("arm"),
            control=f("control"),
            movement=f("movement"),
            gb_tendency=f("gf"),
            vs_left=f("vl"),
            hold_runner=f("hold_runner", 50.0),
            endurance=f("endurance"),
            durability=f("durability", 50.0),
            fielding=f("fa"),
            arm=f("arm"),
            repertoire=repertoire,
        )


@dataclass
class FieldingAlignment:
    positions: Dict[str, str]  # player_id -> position code (e.g., "SS", "CF")


@dataclass
class TeamState:
    lineup: List[str]
    pitchers: List[str]
    defense: FieldingAlignment
