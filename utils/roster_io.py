from __future__ import annotations

import csv
from pathlib import Path

from models.roster import Roster


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
            tier = (roster.dl_tiers or {}).get(player_id, "dl15")
            if tier == "dl15":
                writer.writerow([player_id, "DL15"])
            else:
                if player_id not in ir_ids:
                    writer.writerow([player_id, "IR"])

        for player_id in roster.ir:
            writer.writerow([player_id, "IR"])


__all__ = ["read_roster_csv", "write_roster_csv"]
