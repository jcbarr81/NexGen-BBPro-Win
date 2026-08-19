"""Tests for S1-10 parallel day simulation (playbalance.parallel_day).

The release gate is byte-parity: a season simulated with PB_PARALLEL_GAMES>=2
must produce digests identical to the serial run of the same code. The
``test_parallel_matches_serial_digests`` case exercises that end-to-end via the
benchmark harness (which pins PYTHONHASHSEED=0 in both the parent and the spawned
workers); the rest are fast unit tests of the moving parts.
"""
from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from playbalance import parallel_day


# ---------------------------------------------------------------------------
# resolve_worker_count (D1)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "env, num_games, cpu, expected",
    [
        (None, 6, 8, 0),        # unset -> serial (the default)
        ("0", 6, 8, 0),
        ("1", 6, 8, 0),         # 1 worker is serial
        ("off", 6, 8, 0),
        ("4", 6, 8, 4),
        ("4", 3, 8, 3),         # capped at num_games
        ("4", 1, 8, 0),         # <2 games -> serial
        ("garbage", 6, 8, 0),   # unparseable -> serial
    ],
)
def test_resolve_worker_count(monkeypatch, env, num_games, cpu, expected):
    if env is None:
        monkeypatch.delenv("PB_PARALLEL_GAMES", raising=False)
    else:
        monkeypatch.setenv("PB_PARALLEL_GAMES", env)
    monkeypatch.setattr(os, "cpu_count", lambda: cpu)
    assert parallel_day.resolve_worker_count(num_games) == expected


def test_resolve_worker_count_auto_degrades_on_one_cpu(monkeypatch):
    monkeypatch.setenv("PB_PARALLEL_GAMES", "auto")
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    # auto -> cpu-1 = 0 -> serial (Cloud Run 1 vCPU safety)
    assert parallel_day.resolve_worker_count(6) == 0


def test_resolve_worker_count_auto_uses_cpus(monkeypatch):
    monkeypatch.setenv("PB_PARALLEL_GAMES", "auto")
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert parallel_day.resolve_worker_count(6) == 6  # min(8-1, 6)


# ---------------------------------------------------------------------------
# Picklability across the spawn boundary (Windows-critical guardrail)
# ---------------------------------------------------------------------------
def test_payload_and_job_are_picklable():
    payload = parallel_day.build_payload(
        home="TOR",
        away="BOS",
        seed=123456,
        date="2026-05-01",
        home_starter=None,
        away_starter=None,
        data_root="/tmp/league",
        league_id="cbl",
        usage_in={"game_day": 0, "current_day": None, "workloads": {}, "batter_workloads": {}},
    )
    # The pool pickles both the entry-point function and the payload dict.
    assert pickle.loads(pickle.dumps(parallel_day.simulate_game_job)) is parallel_day.simulate_game_job
    assert pickle.loads(pickle.dumps(payload)) == payload
    # Payload must also be JSON-safe (the journal size guard round-trips JSON).
    assert json.loads(json.dumps(payload)) == payload


# ---------------------------------------------------------------------------
# UsageState serialization helpers (D7)
# ---------------------------------------------------------------------------
def test_usage_state_roundtrip():
    from physics_sim.usage import UsageState

    state = UsageState(current_day=3)
    state.workload_for("P1").fatigue_debt = 42.0
    state.workload_for("P1").last_update_day = 3
    state.batter_workload_for("B1").fatigue_debt = 7.5

    payload = parallel_day.usage_state_to_payload(state, game_day=3)
    assert payload["game_day"] == 3
    assert payload["current_day"] == 3
    assert payload["workloads"]["P1"]["fatigue_debt"] == 42.0

    rebuilt = parallel_day.usage_payload_to_state(payload)
    assert rebuilt.current_day == 3
    assert rebuilt.workloads["P1"].fatigue_debt == 42.0
    assert rebuilt.workloads["P1"].last_update_day == 3
    assert rebuilt.batter_workloads["B1"].fatigue_debt == 7.5


def test_diff_usage_out_keeps_only_changed():
    usage_in = {
        "game_day": 1,
        "current_day": 0,
        "workloads": {"P1": {"fatigue_debt": 0.0}, "P2": {"fatigue_debt": 10.0}},
        "batter_workloads": {"B1": {"fatigue_debt": 0.0}},
    }
    usage_out = {
        "game_day": 1,
        "current_day": 1,
        "workloads": {"P1": {"fatigue_debt": 55.0}, "P2": {"fatigue_debt": 10.0}},  # P2 unchanged
        "batter_workloads": {"B1": {"fatigue_debt": 6.0}},  # changed
    }
    diff = parallel_day.diff_usage_out(usage_in, usage_out)
    assert set(diff["workloads"]) == {"P1"}  # only the changed pitcher
    assert set(diff["batter_workloads"]) == {"B1"}
    assert diff["current_day"] == 1


def test_merge_usage_into_state_overwrites_and_advances_day():
    from physics_sim.usage import UsageState

    state = UsageState(current_day=0)
    state.workload_for("P1").fatigue_debt = 5.0
    parallel_day.merge_usage_into_state(
        state,
        {"current_day": 1, "workloads": {"P1": {"fatigue_debt": 99.0}}, "batter_workloads": {}},
    )
    assert state.workloads["P1"].fatigue_debt == 99.0
    assert state.current_day == 1  # advanced to the max seen


# ---------------------------------------------------------------------------
# D6: per-day seed generator decoupled from the global random stream
# ---------------------------------------------------------------------------
def test_seed_rng_decoupled_from_global():
    import random

    from playbalance.season_simulator import SeasonSimulator

    schedule = [
        {"date": "2026-05-01", "home": "A", "away": "B"},
        {"date": "2026-05-02", "home": "A", "away": "B"},
    ]

    def make_seeds(trash_global: bool):
        seen = []

        def stub(home, away, seed=None, game_date=None, **kw):
            seen.append(seed)
            if trash_global:
                random.seed(0)  # emulate the physics engine reseeding global random
            return (1, 0, "", {})

        random.seed(1234)
        sim = SeasonSimulator(schedule, simulate_game=stub)
        sim.simulate_next_day()
        sim.simulate_next_day()
        return seen

    # Whether or not the game callable trashes global random, the per-day seed
    # sequence is identical -> serial and parallel days draw the same seeds.
    assert make_seeds(trash_global=True) == make_seeds(trash_global=False)


# ---------------------------------------------------------------------------
# The release gate: parallel digests == serial digests (byte-parity)
# ---------------------------------------------------------------------------
def test_parallel_matches_serial_digests(tmp_path):
    """Run the benchmark harness serially and in parallel; digests must match.

    The harness self-re-execs with PYTHONHASHSEED=0 (parent + spawned workers),
    so this is deterministic regardless of the caller's hash seed.
    """
    source = BASE_DIR / "data" / "leagues" / "cbl" / "data"
    if not source.exists():
        pytest.skip("cbl fixture league not present")

    def run(workers: int, sandbox: Path) -> dict:
        env = dict(os.environ)
        if workers:
            env["PB_PARALLEL_GAMES"] = str(workers)
        else:
            env.pop("PB_PARALLEL_GAMES", None)
        out = subprocess.run(
            [
                sys.executable,
                str(BASE_DIR / "scripts" / "benchmark_sim_days.py"),
                "--source", str(source),
                "--sandbox", str(sandbox),
                "--days", "3",
                "--seed", "123",
                "--json",
            ],
            env=env,
            capture_output=True,
            text=True,
            cwd=str(BASE_DIR),
        )
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)["digests"]

    serial = run(0, tmp_path / "serial")
    parallel = run(4, tmp_path / "parallel")
    assert serial == parallel, f"digests diverged: serial={serial} parallel={parallel}"
