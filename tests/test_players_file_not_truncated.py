"""Writing one player must never destroy the rest of the league.

``services.players_repository.save_players`` REPLACES players.csv with exactly
the list it is handed — it is not an upsert. The injured-list endpoints called
it as ``save_players([player])``, so a single Place-on-IL or Activate rewrote a
1,000-player league file down to one row. Every other player was destroyed, and
the roster page filled with ids that no longer resolved to anybody.

Recovered from GCS object versioning. These stop it recurring.
"""

import csv
import inspect
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


class _P:
    def __init__(self, pid, first="A", last="B"):
        self.player_id = pid
        self.first_name = first
        self.last_name = last
        self.injured = False
        self.injury_list = None
        self.primary_position = "CF"
        self.is_pitcher = False


# --- the specific regression ------------------------------------------------


def test_persist_writes_every_player_not_just_the_changed_one(monkeypatch, tmp_path):
    import api.routers.injuries as inj

    everyone = [_P(f"P{i}") for i in range(50)]
    changed = everyone[7]
    changed.injured = True

    monkeypatch.setattr(inj, "load_players_from_csv", lambda *a, **k: everyone, raising=False)

    written = {}

    def fake_save(players, path=None):
        written["ids"] = [p.player_id for p in players]
        return players

    import services.players_repository as repo

    monkeypatch.setattr(repo, "save_players", fake_save)
    monkeypatch.setattr(
        "utils.player_loader.load_players_from_csv", lambda *a, **k: everyone
    )

    inj._persist("T", object(), lambda *a: None, changed)

    assert written.get("ids"), "nothing was written at all"
    assert len(written["ids"]) == 50, (
        f"wrote {len(written['ids'])} players instead of 50 — this is the wipe"
    )
    assert "P7" in written["ids"]


def test_persist_refuses_to_write_when_the_read_looks_wrong(monkeypatch):
    """A truncating write is worse than a lost injury flag: the flag is one
    field, the file is the league. If the read comes back empty or missing the
    player, leave the file alone."""
    import api.routers.injuries as inj
    import services.players_repository as repo

    calls = []
    monkeypatch.setattr(repo, "save_players", lambda *a, **k: calls.append(a))

    monkeypatch.setattr("utils.player_loader.load_players_from_csv", lambda *a, **k: [])
    inj._persist("T", object(), lambda *a: None, _P("P1"))
    assert not calls, "wrote to players.csv from an empty read"

    # Player absent from the loaded set — also refuse.
    monkeypatch.setattr(
        "utils.player_loader.load_players_from_csv",
        lambda *a, **k: [_P("PX"), _P("PY")],
    )
    inj._persist("T", object(), lambda *a: None, _P("P1"))
    assert not calls, "wrote when the changed player wasn't in the file"


# --- the general rule -------------------------------------------------------


def test_no_caller_passes_a_literal_single_player_list():
    """save_players([x]) is the shape of the bug. Every legitimate caller hands
    it the full set it just loaded."""
    offenders = []
    roots = ("api", "services", "playbalance", "utils", "scripts")
    for root in roots:
        for path in (REPO / root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                src = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for line_no, line in enumerate(src.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "save_players([" in stripped:
                    offenders.append(f"{path.relative_to(REPO)}:{line_no}: {stripped}")
    assert not offenders, (
        "save_players replaces the whole file; these pass a single-element "
        "list and would wipe every other player:\n  " + "\n  ".join(offenders)
    )


def test_save_players_really_does_replace_the_whole_file(tmp_path):
    """Documents the sharp edge, so the next reader doesn't assume upsert."""
    from services.players_repository import save_players
    from utils.player_writer import save_players_to_csv  # noqa: F401

    def real(pid):
        from models.player import Player

        return Player(
            player_id=pid, first_name="A", last_name="B", birthdate="2000-01-01",
            height=72, weight=180, bats="R", primary_position="CF",
            other_positions=[], gf=0,
        )

    target = tmp_path / "players.csv"
    save_players([real("P1"), real("P2"), real("P3")], target)
    assert len(list(csv.DictReader(target.open(newline="", encoding="utf-8")))) == 3

    save_players([real("P1")], target)
    rows = list(csv.DictReader(target.open(newline="", encoding="utf-8")))
    assert len(rows) == 1, (
        "if this ever becomes an upsert, the guards above can be relaxed"
    )
