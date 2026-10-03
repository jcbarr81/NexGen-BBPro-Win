"""A traded player leaves his old team, whatever level he was on.

The trade screen offers AAA, Low-A and injured players, but the commit only
removed the player from the old team's ACTIVE roster. A traded minor leaguer
ended up on both teams: HOU traded Erich Zenk (AAA) to BAL on 9/1 and he was
still on HOU's AAA a month later. For a draft pick it was worse -- the
placeholder pool keeps a player's first owner, so the next reload of the new
team's roster dropped him and the trade was silently undone.
"""

import csv
from pathlib import Path

import pytest

import utils.roster_loader as RL
from models.trade import Trade
from services.trade_execution import commit_trade


def _league(root: Path, rosters: dict[str, list[tuple[str, str]]]) -> Path:
    data = root / "data"
    (data / "rosters").mkdir(parents=True)
    for team, rows in rosters.items():
        with (data / "rosters" / f"{team}.csv").open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
    return data


def _full(prefix: str, size: int = RL.ACTIVE_ROSTER_SIZE) -> list[tuple[str, str]]:
    """A full active roster. Short, the loader promotes a minor leaguer to
    fill it; over, it sends the extras down to AAA."""
    return [(f"{prefix}{i}", "ACT") for i in range(size)]


@pytest.fixture
def league(tmp_path, monkeypatch):
    RL._reset_placeholder_pool()
    RL.load_roster.cache_clear()
    recorded: list[dict] = []
    monkeypatch.setattr("services.trade_execution.record_transaction", lambda **kw: recorded.append(kw))
    # The fixture's ids are not real pitchers; leave the loader's pitcher-depth
    # top-up (placeholder arms, extras sent to AAA) out of a trade test.
    monkeypatch.setattr(RL, "_ensure_pitcher_depth", lambda *a, **k: False)

    def build(rosters):
        data = _league(tmp_path, rosters)
        monkeypatch.setattr(RL, "get_data_dir", lambda: data)
        return data, recorded

    yield build
    RL._reset_placeholder_pool()
    RL.load_roster.cache_clear()


def _ids(team: str, data: Path) -> set[str]:
    r = RL.load_roster(team, data / "rosters")
    return set(r.act + r.aaa + r.low + r.dl + r.ir)


def _file_ids(team: str, data: Path) -> set[str]:
    with (data / "rosters" / f"{team}.csv").open(newline="", encoding="utf-8") as fh:
        return {row[0] for row in csv.reader(fh) if row}


@pytest.mark.parametrize("level", ["ACT", "AAA", "LOW", "DL", "IR"])
def test_the_player_leaves_the_old_team_from_any_level(league, level):
    fillers = _full("H", RL.ACTIVE_ROSTER_SIZE - (level == "ACT"))
    data, _ = league({"HOU": fillers + [("P8037", level)], "BAL": _full("B")})
    assert "P8037" in getattr(RL.load_roster("HOU", data / "rosters"), level.lower())
    commit_trade(Trade("t", "HOU", "BAL", ["P8037"], []), data_dir=data)
    assert "P8037" not in _file_ids("HOU", data)
    assert "P8037" in _file_ids("BAL", data)


@pytest.mark.parametrize("level", ["AAA", "LOW"])
def test_a_traded_draft_pick_stays_traded_after_a_reload(league, level):
    data, _ = league({"CHA": _full("C") + [("D20260013", level)], "CHI": _full("X")})
    commit_trade(Trade("t", "CHA", "CHI", ["D20260013"], []), data_dir=data)

    assert "D20260013" in _ids("CHI", data)       # same process
    RL.load_roster.cache_clear()                   # a restart / any cache clear
    assert "D20260013" in _ids("CHI", data)
    assert "D20260013" not in _ids("CHA", data)


def test_a_reload_of_only_the_new_team_keeps_the_pick(league):
    """The ownership record moves with the trade, so even a roster re-read
    that does not rebuild the pool keeps the pick on his new team."""
    data, _ = league({"CHA": _full("C") + [("D20260013", "LOW")], "CHI": _full("X")})
    commit_trade(Trade("t", "CHA", "CHI", ["D20260013"], []), data_dir=data)
    RL.get_unified_data_service().invalidate_roster(team_id="CHI")
    assert "D20260013" in _ids("CHI", data)


def test_both_directions_and_the_log_names_the_real_level(league):
    data, recorded = league({
        "HOU": _full("H") + [("M1", "AAA")],
        "BAL": _full("B") + [("M2", "LOW")],
    })
    commit_trade(Trade("t", "HOU", "BAL", ["M1"], ["M2"]), data_dir=data)
    assert "M1" in _file_ids("BAL", data) and "M1" not in _file_ids("HOU", data)
    assert "M2" in _file_ids("HOU", data) and "M2" not in _file_ids("BAL", data)
    outs = {r["player_id"]: r["from_level"] for r in recorded if r["action"] == "trade_out"}
    assert outs == {"M1": "AAA", "M2": "LOW"}


def test_injured_tier_does_not_follow_him_off_the_old_team(league):
    data, _ = league({"HOU": _full("H") + [("P1", "DL45")], "BAL": _full("B")})
    commit_trade(Trade("t", "HOU", "BAL", ["P1"], []), data_dir=data)
    assert "P1" not in RL.load_roster("HOU", data / "rosters").dl_tiers


def test_a_bad_pick_leaves_the_rosters_untouched(league, monkeypatch):
    data, _ = league({"HOU": _full("H") + [("M1", "AAA")], "BAL": _full("B")})

    def _raise(*_a, **_k):
        raise ValueError("pick not owned")

    monkeypatch.setattr("services.trade_execution.transfer_pick", _raise)
    with pytest.raises(ValueError):
        commit_trade(Trade("t", "HOU", "BAL", ["M1"], [], give_pick_ids=["x"]), data_dir=data)
    assert "M1" in _ids("HOU", data)               # the cached roster too
    assert "M1" not in _ids("BAL", data)
