from __future__ import annotations

import csv
from pathlib import Path

from models.roster import Roster

# Tier names that belong on the 60-day level. Every other injured-list tier
# (MLB's 7/10/15-day lists, and the legacy "dl15") shares the short-list level,
# whose on-disk token stays "DL15" so every existing reader keeps working.
_SIXTY_DAY_TIERS = {"il60", "ir", "dl45"}


def read_roster_csv(path: str | Path, team_id: str) -> Roster:
    """Load a roster CSV without applying placeholder or depth logic."""
    file_path = Path(path)
    act: list[str] = []
    aaa: list[str] = []
    low: list[str] = []
    dl: list[str] = []
    ir: list[str] = []
    dl_tiers: dict[str, str] = {}

    if not file_path.exists():
        return Roster(team_id=team_id)

    with file_path.open(mode="r", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 2:
                continue
            pid = row[0].strip()
            level = row[1].strip().upper()
            if not pid:
                continue
            if level == "ACT":
                act.append(pid)
            elif level == "AAA":
                aaa.append(pid)
            elif level == "LOW":
                low.append(pid)
            elif level in {"DL", "DL15"}:
                dl.append(pid)
                dl_tiers[pid] = "dl15"
            elif level == "DL45":
                ir.append(pid)
            elif level == "IR":
                ir.append(pid)

    return Roster(
        team_id=team_id,
        act=act,
        aaa=aaa,
        low=low,
        dl=dl,
        ir=ir,
        dl_tiers=dl_tiers,
    )


def write_roster_csv(roster: Roster, path: str | Path) -> None:
    """Write roster data to the provided CSV path."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open(mode="w", newline="") as handle:
        writer = csv.writer(handle)
        for level, group in [
            ("ACT", roster.act),
            ("AAA", roster.aaa),
            ("LOW", roster.low),
        ]:
            for player_id in group:
                writer.writerow([player_id, level])

        ir_ids = set(roster.ir)
        for player_id in roster.dl:
            tier = str((roster.dl_tiers or {}).get(player_id, "dl15") or "").lower()
            # The roster file records the LEVEL a player occupies, not which
            # injured list he is on: that lives on the player record
            # (``injury_list``), which is the single source of truth and is what
            # the UI labels from. Everything short of the 60-day list is the
            # same roster level.
            #
            # This used to be `if tier == "dl15" ... else IR`, which meant that
            # once the tiers were renamed to MLB's (il10 / il15), the first save
            # after an injury silently wrote those players to the 60-day level —
            # a 10-day stint became a 60-day one on reload.
            if tier in _SIXTY_DAY_TIERS:
                if player_id not in ir_ids:
                    writer.writerow([player_id, "IR"])
            else:
                writer.writerow([player_id, "DL15"])

        for player_id in roster.ir:
            writer.writerow([player_id, "IR"])


__all__ = ["read_roster_csv", "write_roster_csv"]
