"""#14: the commissioner's chosen playoff format must actually drive the bracket.
generate_bracket reads PlayoffsConfig.num_playoff_teams_per_league, so a league
that stored 4 gets a 4-team bracket and one that stored 6 gets 6.
"""

from types import SimpleNamespace

from playbalance.playoffs import generate_bracket
from playbalance.playoffs_config import PlayoffsConfig


def _teams():
    divs = ["East"] * 4 + ["West"] * 4
    return [
        SimpleNamespace(team_id=f"T{i}", division=div, name=f"Team{i}", city="City")
        for i, div in enumerate(divs)
    ]


def _standings(teams):
    # Descending records so seeding is deterministic.
    out = {}
    for i, t in enumerate(teams):
        wins = 95 - i * 3
        losses = 162 - wins
        out[t.team_id] = {
            "wins": wins,
            "losses": losses,
            "pct": round(wins / 162, 3),
            "runs_for": 700,
            "runs_against": 650,
        }
    return out


def _seed_count(bracket) -> int:
    return sum(len(v) for v in (bracket.seeds_by_league or {}).values())


def _cfg(num, total):
    # How league_create stores the commissioner's choice: the slot count plus a
    # size-keyed map that bypasses _seed_league's "6 == unset" sentinel.
    return PlayoffsConfig(
        num_playoff_teams_per_league=num,
        playoff_slots_by_league_size={total: num},
    )


def test_every_chosen_playoff_size_is_honored():
    # 8-team, 2-division pool. Division-winners-only (2), +wildcards (4), and the
    # size that collides with the default sentinel (6) must ALL be honored.
    teams = _teams()
    standings = _standings(teams)
    for num in (2, 4, 6):
        bracket = generate_bracket(standings, teams, _cfg(num, len(teams)))
        assert _seed_count(bracket) == num, f"num={num}"


def test_default_config_without_choice_still_produces_a_bracket():
    # No explicit choice (bare defaults) still seeds a sane auto bracket.
    teams = _teams()
    standings = _standings(teams)
    bracket = generate_bracket(standings, teams, PlayoffsConfig())
    assert _seed_count(bracket) >= 2


def test_al_nl_split_seeds_two_leagues_into_a_world_series():
    # 4 divisions (3 teams each) split into two leagues; each seeds its own
    # bracket and they meet in a World Series.
    teams = []
    d2l = {}
    for div, league in (("D1", "AL"), ("D2", "AL"), ("D3", "NL"), ("D4", "NL")):
        d2l[div] = league
        for j in range(3):
            teams.append(
                SimpleNamespace(team_id=f"{div}_{j}", division=div, name=f"{div}{j}", city="C")
            )
    standings = _standings(teams)
    cfg = PlayoffsConfig(
        num_playoff_teams_per_league=2,
        playoff_slots_by_league_size={6: 2},  # 6 teams / league, division winners only
        division_to_league=d2l,
    )
    bracket = generate_bracket(standings, teams, cfg)
    assert set((bracket.seeds_by_league or {}).keys()) == {"AL", "NL"}
    assert len(bracket.seeds_by_league["AL"]) == 2
    assert len(bracket.seeds_by_league["NL"]) == 2
    assert any(str(getattr(r, "name", "")).upper() == "WS" for r in bracket.rounds)
