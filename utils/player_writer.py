import csv
import logging

from models.player import Player
from models.pitcher import Pitcher
from utils.atomic_write import atomic_text_writer
from utils.rating_scale import (
    LEGACY_RATING_SCALE,
    RATING_SCALE_FIELD,
    describe_rating_scales,
    rating_scale_counts,
    rating_scale_of,
)

_LOGGER = logging.getLogger(__name__)
# How many player ids of a minority scale a warning names.
_MIXED_IDS_SHOWN = 10


def save_players_to_csv(players, file_path):
    """Write ``players`` as a whole ``players.csv`` (the file is replaced).

    Ratings are written as the objects hold them: STORED values on the
    scale ``player.rating_scale`` names. A list on scale 1 (every league
    today) produces exactly the file it always did, with no ``rating_scale``
    column. When any player is on another scale the column is written, and
    every row carries its OWN scale. A list on mixed scales is written as it
    is, with a warning naming the rows off the majority scale: each row
    still reads correctly, and refusing would stop every save in the league
    over one stray row.
    """

    players = list(players)
    counts = rating_scale_counts(players)
    if len(counts) > 1:
        majority = max(counts, key=lambda scale: counts[scale])
        strays = [
            str(getattr(p, "player_id", "?"))
            for p in players
            if rating_scale_of(p) != majority
        ]
        _LOGGER.warning(
            "%s: players on mixed rating scales (%s); each row is written on "
            "its own scale. Off the majority scale: %s%s",
            file_path,
            describe_rating_scales(counts),
            ", ".join(strays[:_MIXED_IDS_SHOWN]),
            " ..." if len(strays) > _MIXED_IDS_SHOWN else "",
        )
    marked = any(scale != LEGACY_RATING_SCALE for scale in counts)
    fieldnames = [
        "player_id", "first_name", "last_name", "birthdate", "height", "weight",
        "ethnicity", "skin_tone", "hair_color", "facial_hair", "bats", "throws",
        "primary_position", "other_positions", "is_pitcher", "role", "preferred_pitching_role",
        "ch", "ph", "sp", "eye", "gf", "pl", "vl", "sc", "fa", "arm",
        "endurance", "control", "movement", "hold_runner",
        "fb", "cu", "cb", "sl", "si", "scb", "kn",
        "pot_ch", "pot_ph", "pot_sp", "pot_eye", "pot_gf", "pot_pl", "pot_vl", "pot_sc", "pot_fa", "pot_arm",
        "pot_control", "pot_movement", "pot_endurance", "pot_hold_runner",
        "pot_fb", "pot_cu", "pot_cb", "pot_sl", "pot_si", "pot_scb", "pot_kn",
        "injured", "injury_description", "return_date", "ready",
        "injury_list", "injury_start_date", "injury_minimum_days", "injury_eligible_date",
        "injury_rehab_assignment", "injury_rehab_days",
        "durability",
        "pitcher_archetype", "hitter_archetype",
    ]
    if marked:
        fieldnames.append(RATING_SCALE_FIELD)

    # Atomic: a parallel-day worker reading players.csv must never see a
    # half-written file (a cut on a row boundary silently drops players).
    with atomic_text_writer(file_path, newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for p in players:
            is_pitcher = isinstance(p, Pitcher)
            row = {
                "player_id": p.player_id,
                "first_name": p.first_name,
                "last_name": p.last_name,
                "birthdate": p.birthdate,
                "height": p.height,
                "weight": p.weight,
                "ethnicity": p.ethnicity,
                "skin_tone": p.skin_tone,
                "hair_color": p.hair_color,
                "facial_hair": p.facial_hair,
                "bats": p.bats,
                "throws": getattr(p, "throws", "") or "",
                "primary_position": p.primary_position,
                "other_positions": "|".join(p.other_positions),
                "is_pitcher": "1" if is_pitcher else "0",
                "role": p.role if is_pitcher else "",
                "preferred_pitching_role": getattr(p, "preferred_pitching_role", "") if is_pitcher else "",
                "injured": str(p.injured),
                "injury_description": p.injury_description or "",
                "return_date": p.return_date or "",
                "ready": "1" if getattr(p, "ready", False) else "0",
                "injury_list": (p.injury_list or ""),
                "injury_start_date": p.injury_start_date or "",
                "injury_minimum_days": "" if getattr(p, "injury_minimum_days", None) is None else str(p.injury_minimum_days),
                "injury_eligible_date": p.injury_eligible_date or "",
                "injury_rehab_assignment": p.injury_rehab_assignment or "",
                "injury_rehab_days": str(getattr(p, "injury_rehab_days", 0)),
                "durability": getattr(p, "durability", 50),
                "pitcher_archetype": getattr(p, "pitcher_archetype", ""),
                "hitter_archetype": getattr(p, "hitter_archetype", ""),
            }
            if marked:
                row[RATING_SCALE_FIELD] = rating_scale_of(p)

            if is_pitcher:
                row.update({
                    "gf": p.gf,
                    "arm": p.arm,
                    "fa": p.fa,
                    "endurance": p.endurance,
                    "control": p.control,
                    "movement": p.movement,
                    "hold_runner": p.hold_runner,
                    "fb": p.fb, "cu": p.cu, "cb": p.cb, "sl": p.sl,
                    "si": p.si, "scb": p.scb, "kn": p.kn,
                    "pot_gf": p.potential.get("gf", p.gf),
                    "pot_control": p.potential.get("control", p.control),
                    "pot_movement": p.potential.get("movement", p.movement),
                    "pot_endurance": p.potential.get("endurance", p.endurance),
                    "pot_hold_runner": p.potential.get("hold_runner", p.hold_runner),
                    "pot_fb": p.potential.get("fb", p.fb),
                    "pot_cu": p.potential.get("cu", p.cu),
                    "pot_cb": p.potential.get("cb", p.cb),
                    "pot_sl": p.potential.get("sl", p.sl),
                    "pot_si": p.potential.get("si", p.si),
                    "pot_scb": p.potential.get("scb", p.scb),
                    "pot_kn": p.potential.get("kn", p.kn),
                    "pot_arm": p.potential.get("arm", p.arm),
                    "pot_fa": p.potential.get("fa", p.fa)
                })
            else:
                row.update({
                    "ch": p.ch, "ph": p.ph, "sp": p.sp, "eye": getattr(p, "eye", 0),
                    "gf": p.gf, "pl": p.pl, "vl": p.vl, "sc": p.sc,
                    "fa": p.fa, "arm": p.arm,
                    "pot_ch": p.potential.get("ch", p.ch),
                    "pot_ph": p.potential.get("ph", p.ph),
                    "pot_sp": p.potential.get("sp", p.sp),
                    "pot_eye": p.potential.get(
                        "eye", getattr(p, "pot_eye", getattr(p, "eye", 0))
                    ),
                    "pot_gf": p.potential.get("gf", p.gf),
                    "pot_pl": p.potential.get("pl", p.pl),
                    "pot_vl": p.potential.get("vl", p.vl),
                    "pot_sc": p.potential.get("sc", p.sc),
                    "pot_fa": p.potential.get("fa", p.fa),
                    "pot_arm": p.potential.get("arm", p.arm)
                })

            writer.writerow(row)
