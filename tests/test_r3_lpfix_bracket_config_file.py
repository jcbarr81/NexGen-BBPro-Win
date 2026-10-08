"""Release 3 live-path fix: ``playoffs_config.json`` is not a bracket.

``load_bracket`` used to glob ``playoffs_*.json``, which also matched the
league wizard's ``playoffs_config.json``. That file parsed as an empty
year-0 bracket, so ``_ensure_playoff_bracket`` reported ``reused_existing``
and entering the playoffs saved no bracket at all; a playoff sim then ran on
the empty bracket and reported ``changed: true`` without playing a game.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

import playbalance.playoffs as pf
import playbalance.playoffs_config as pcfg
from api.routers import playoffs as playoffs_router
from api.routers import season
from models.team import Team
from playbalance.playoffs_config import PlayoffsConfig, save_playoffs_config


def _team(team_id: str, division: str) -> Team:
    return Team(
        team_id=team_id, name=team_id, city=team_id, abbreviation=team_id,
        division=division, stadium="Test Park", primary_color="#112233",
        secondary_color="#445566", owner_id="",
    )


@pytest.fixture
def league_dir(tmp_path, monkeypatch):
    """A scratch league dir holding the wizard's playoffs_config.json."""

    monkeypatch.setattr(pf, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(pcfg, "get_data_dir", lambda: tmp_path)
    (tmp_path / "schedule.csv").write_text(
        "date,home,away,result\n2026-04-01,A1,A2,1-0\n2026-09-27,A3,A4,2-1\n",
        encoding="utf-8",
    )
    cfg = PlayoffsConfig(num_playoff_teams_per_league=4)
    save_playoffs_config(cfg, tmp_path / "playoffs_config.json")
    assert (tmp_path / "playoffs_config.json").exists()

    teams = [_team(f"A{i}", "AL East") for i in range(1, 5)]
    teams += [_team(f"N{i}", "NL East") for i in range(1, 5)]
    standings = {
        t.team_id: {"wins": 90 - idx, "losses": 60 + idx,
                    "runs_for": 700, "runs_against": 650}
        for idx, t in enumerate(teams)
    }
    import utils.team_loader as team_loader

    monkeypatch.setattr(team_loader, "load_teams", lambda *a, **k: teams)
    monkeypatch.setattr(pf, "_load_standings_snapshot", lambda: standings)
    monkeypatch.setattr(pf, "_load_known_teams", lambda: (teams, set()))
    return tmp_path


def test_load_bracket_ignores_playoffs_config_file(league_dir):
    assert pf.load_bracket() is None


def test_load_bracket_still_finds_year_files(league_dir):
    bracket = pf.PlayoffBracket(year=2026, rounds=[pf.Round(name="WS")])
    pf.save_bracket(bracket)
    loaded = pf.load_bracket()
    assert loaded is not None
    assert loaded.year == 2026
    assert [r.name for r in loaded.rounds] == ["WS"]


def test_bracket_is_empty_helper():
    assert pf.bracket_is_empty(None)
    assert pf.bracket_is_empty(pf.PlayoffBracket(year=0, rounds=[]))
    assert pf.bracket_is_empty(
        pf.PlayoffBracket(year=0, rounds=[pf.Round(name="WS")])
    )
    assert pf.bracket_is_empty(pf.PlayoffBracket(year=2026, rounds=[]))
    assert not pf.bracket_is_empty(
        pf.PlayoffBracket(year=2026, rounds=[pf.Round(name="WS")])
    )


def test_ensure_playoff_bracket_saves_with_config_present(league_dir):
    summary = season._ensure_playoff_bracket()
    assert summary and summary.get("saved") is True, summary
    saved = league_dir / "playoffs_2026.json"
    assert saved.exists()
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["year"] == 2026
    assert data["rounds"]
    # The wizard's format file is untouched.
    cfg = json.loads((league_dir / "playoffs_config.json").read_text("utf-8"))
    assert cfg["num_playoff_teams_per_league"] == 4


def test_ensure_playoff_bracket_replaces_empty_bracket(league_dir):
    (league_dir / "playoffs_2026.json").write_text(
        json.dumps(pf.PlayoffBracket(year=2026, rounds=[]).to_dict()),
        encoding="utf-8",
    )
    summary = season._ensure_playoff_bracket()
    assert summary and summary.get("saved") is True, summary
    data = json.loads((league_dir / "playoffs_2026.json").read_text("utf-8"))
    assert data["rounds"]


def test_ensure_playoff_bracket_reuses_real_bracket(league_dir):
    first = season._ensure_playoff_bracket()
    assert first.get("saved") is True
    again = season._ensure_playoff_bracket()
    assert again == {"reused_existing": True}


def test_playoff_sim_refuses_empty_bracket(league_dir):
    (league_dir / "playoffs_2026.json").write_text(
        json.dumps(pf.PlayoffBracket(year=2026, rounds=[]).to_dict()),
        encoding="utf-8",
    )
    with pytest.raises(HTTPException) as exc:
        playoffs_router._run_playoff_sim("game")
    assert exc.value.status_code == 404


def test_playoff_sim_with_only_config_file_is_404(league_dir):
    with pytest.raises(HTTPException) as exc:
        playoffs_router._run_playoff_sim("game")
    assert exc.value.status_code == 404
