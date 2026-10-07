"""The roster size rules (owner decision 8, 7.46.0) in one place.

Every other test sizes rosters from these constants; this is the one test
that pins the MLB numbers themselves.
"""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from utils import roster_loader, roster_rules
from utils.roster_rules import counts_as_pitcher


def test_mlb_numbers():
    assert roster_rules.ACTIVE_ROSTER_SIZE == 26
    assert roster_rules.MAX_ACTIVE_PITCHERS == 13
    assert roster_rules.SEPTEMBER_ROSTER_SIZE == 28
    assert roster_rules.SEPTEMBER_MAX_ACTIVE_PITCHERS == 14
    assert roster_rules.ACT_HITTER_TARGET == 13
    # Owner decision: the organisation grows to 51 so nobody has to cut.
    assert roster_rules.ORG_LIMIT == 51 == 26 + 15 + 10


def test_every_copy_reads_the_rules():
    from models.roster import Roster
    from services import roster_auto_assign, roster_validation

    assert roster_loader.ACTIVE_ROSTER_SIZE == roster_rules.ACTIVE_ROSTER_SIZE
    assert roster_validation.DEFAULT_LEVEL_CAPS == {"act": 26, "aaa": 15, "low": 10}
    assert roster_validation.DEFAULT_PITCHER_CAP == 13
    assert roster_auto_assign.ACTIVE_MAX == 26
    assert roster_auto_assign.ORG_LIMIT == 51
    import inspect

    default = inspect.signature(Roster.promote_replacements).parameters["target_size"].default
    assert default == 26


@pytest.mark.parametrize(
    "player, expected",
    [
        ({"is_pitcher": "1", "primary_position": "P"}, True),
        ({"is_pitcher": "", "primary_position": "SP"}, True),  # flag missing
        ({"is_pitcher": "0", "primary_position": "RP"}, True),
        ({"is_pitcher": "true", "primary_position": "CF"}, True),
        ({"is_pitcher": "0", "primary_position": "SS"}, False),
        # the stale role column never makes a hitter a pitcher
        ({"is_pitcher": "0", "primary_position": "1B", "role": "RP"}, False),
        (SimpleNamespace(is_pitcher=True, primary_position="P"), True),
        (SimpleNamespace(is_pitcher=False, primary_position="C"), False),
        (None, False),
    ],
)
def test_counts_as_pitcher(player, expected):
    assert counts_as_pitcher(player) is expected


@pytest.mark.parametrize(
    "date, september, act, pitchers",
    [
        ("2026-08-31", False, 26, 13),
        ("2026-09-01", True, 28, 14),
        ("2026-09-30", True, 28, 14),
    ],
)
def test_september_caps_in_the_regular_season(monkeypatch, date, september, act, pitchers):
    from playbalance import season_manager as sm

    class _Mgr:
        phase = sm.SeasonPhase.REGULAR_SEASON

    monkeypatch.setattr(sm, "SeasonManager", lambda *a, **k: _Mgr())
    assert roster_loader.in_september_window(date) is september
    assert roster_loader.active_roster_cap(date) == act
    assert roster_loader.active_pitcher_cap(date) == pitchers
    assert roster_loader.effective_level_caps(date) == {"act": act, "aaa": 15, "low": 10}


def test_no_september_caps_in_the_playoffs(monkeypatch):
    from playbalance import season_manager as sm

    class _Mgr:
        phase = sm.SeasonPhase.PLAYOFFS

    monkeypatch.setattr(sm, "SeasonManager", lambda *a, **k: _Mgr())
    assert roster_loader.active_roster_cap("2026-09-20") == 26
    assert roster_loader.active_pitcher_cap("2026-09-20") == 13


def test_roster_validation_stays_dependency_free():
    code = (
        "import sys, services.roster_validation; "
        "bad = [m for m in sys.modules if m.split('.')[0] in "
        "('fastapi', 'pydantic', 'playbalance', 'physics_sim', 'numpy')]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
