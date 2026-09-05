"""Writing one player must never destroy the rest of the league.

``services.players_repository.save_players`` REPLACES players.csv with exactly
the list it is handed — it is not an upsert. The injured-list endpoints called
it as a single-element list, so one Place-on-IL or Activate rewrote a
1,000-player league file down to one row. Every other player was destroyed, and
the roster page filled with ids that no longer resolved to anybody. It was only
recoverable because the bucket had object versioning.

The specific call is fixed, but the trap was in the API: a function named
"save players" that quietly means "these are now ALL the players". So the guard
lives in the repository, where it protects every caller — including ones not
written yet — and ``update_players`` gives future code the right tool.
"""

import csv
import inspect
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _real(pid):
    from models.player import Player

    return Player(
        player_id=pid,
        first_name="A",
        last_name="B",
        birthdate="2000-01-01",
        height=72,
        weight=180,
        bats="R",
        primary_position="CF",
        other_positions=[],
        gf=0,
    )


def _rows(path):
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# --- the guard, at the source ----------------------------------------------


def test_save_players_refuses_to_wipe_the_league(tmp_path):
    """The incident, in miniature: most of the file replaced by a single row."""
    from services.players_repository import PlayersFileShrinkError, save_players

    target = tmp_path / "players.csv"
    save_players([_real(f"P{i}") for i in range(100)], target)

    with pytest.raises(PlayersFileShrinkError) as exc:
        save_players([_real("P1")], target)
    assert "REPLACES" in str(exc.value)

    # And crucially the file is untouched — it refuses BEFORE writing.
    assert len(_rows(target)) == 100


def test_a_deliberate_cull_is_still_possible(tmp_path):
    from services.players_repository import save_players

    target = tmp_path / "players.csv"
    save_players([_real(f"P{i}") for i in range(100)], target)
    save_players([_real("P1")], target, allow_shrink=True)
    assert len(_rows(target)) == 1


def test_ordinary_shrinkage_is_not_blocked(tmp_path):
    """Retirements and releases move a few percent, not most of the file."""
    from services.players_repository import save_players

    target = tmp_path / "players.csv"
    save_players([_real(f"P{i}") for i in range(100)], target)
    save_players([_real(f"P{i}") for i in range(95)], target)
    assert len(_rows(target)) == 95


def test_a_new_or_tiny_file_is_not_guarded(tmp_path):
    """A fresh league writing its first players must not trip the guard."""
    from services.players_repository import save_players

    target = tmp_path / "players.csv"
    save_players([_real("P1")], target)
    save_players([_real("P1"), _real("P2")], target)
    assert len(_rows(target)) == 2


# --- the tool callers should reach for -------------------------------------


def test_update_players_changes_one_and_keeps_the_rest(tmp_path):
    from services.players_repository import save_players, update_players
    from utils.player_loader import load_players_from_csv

    target = tmp_path / "players.csv"
    save_players([_real(f"P{i}") for i in range(50)], target)

    changed = _real("P7")
    changed.injured = True
    changed.injury_list = "il10"
    update_players([changed], target)

    everyone = list(load_players_from_csv(target))
    assert len(everyone) == 50
    assert {p.player_id for p in everyone} == {f"P{i}" for i in range(50)}
    assert str({p.player_id: p for p in everyone}["P7"].injury_list) == "il10"


def test_update_players_refuses_when_the_read_is_empty(tmp_path):
    """Otherwise the 'upsert' would create a file containing only the change."""
    from services.players_repository import PlayersFileShrinkError, update_players

    with pytest.raises(PlayersFileShrinkError):
        update_players([_real("P1")], tmp_path / "does-not-exist.csv")


# --- the endpoint that had the bug -----------------------------------------


def test_persist_uses_the_upsert_helper():
    import api.routers.injuries as inj

    src = inspect.getsource(inj._persist)
    assert "update_players" in src, "the injured-list persist must upsert"
    assert not re.search(r"\bsave_players\(", src), (
        "_persist reaching for save_players again is how the wipe happened"
    )


# --- the general rule -------------------------------------------------------


def test_no_caller_replaces_the_file_with_a_literal_list():
    """``save_players([...])`` as a STATEMENT is the shape of the bug.

    Matches actual calls only, so the repository's own documentation of the
    hazard doesn't flag itself.
    """
    call = re.compile(r"^(?:\w+\s*=\s*)?save_players\(\[")
    offenders = []
    for root in ("api", "services", "playbalance", "utils", "scripts"):
        for path in (REPO / root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                src = path.read_text(encoding="utf-8")
            except Exception:
                continue
            for line_no, line in enumerate(src.splitlines(), 1):
                if call.match(line.strip()):
                    offenders.append(f"{path.relative_to(REPO)}:{line_no}")
    assert not offenders, (
        "save_players REPLACES the file; these hand it a literal list and would "
        "delete every other player:\n  " + "\n  ".join(offenders)
    )


def test_save_players_really_does_replace(tmp_path):
    """Documents the sharp edge, so nobody reads it as an upsert again."""
    from services.players_repository import save_players

    target = tmp_path / "players.csv"
    save_players([_real("P1"), _real("P2"), _real("P3")], target)
    assert len(_rows(target)) == 3

    save_players([_real("P1")], target, allow_shrink=True)
    assert len(_rows(target)) == 1, (
        "if this ever becomes a true upsert, the guards above can be relaxed"
    )
