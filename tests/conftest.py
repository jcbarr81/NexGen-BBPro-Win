import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Environment keys that tests commonly set (directly, not via monkeypatch) and
# that would otherwise leak into the next test's data-dir / sim-date resolution.
_ENV_KEYS = (
    "NEXGEN_DATA_ROOT",
    "NEXGEN_DATA_DIR",
    "NEXGEN_ACTIVE_LEAGUE",
    "PB_SIM_DATE",
    "PB_SIM_YEAR",
)


def pytest_sessionstart(session):
    """Ensure a non-deterministic RNG for tests depending on randomness."""
    random.seed()
    os.environ.setdefault("PB_DISABLE_ROLLOVER", "1")


def _reset_shared_state() -> None:
    """Reset process-wide caches / singletons that leak between tests.

    Only touches modules that are already imported (via ``sys.modules``) so we
    never force a heavy import — an unimported module holds no leaked state.
    """

    m = sys.modules.get("utils.path_utils")
    if m is not None:
        try:
            m._DATA_DIR_CACHE.clear()
        except Exception:
            pass
        try:
            m._REQUEST_LEAGUE.set(None)
        except Exception:
            pass

    m = sys.modules.get("utils.pitcher_recovery")
    if m is not None:
        try:
            m.PitcherRecoveryTracker._instance = None
        except Exception:
            pass

    m = sys.modules.get("services.unified_data_service")
    if m is not None:
        try:
            svc = getattr(m, "_SERVICE", None)
            if svc is not None:
                for attr in ("_player_cache", "_roster_cache", "_document_cache"):
                    cache = getattr(svc, attr, None)
                    if cache is not None:
                        cache.clear()
        except Exception:
            pass

    m = sys.modules.get("playbalance.player_generator")
    if m is not None:
        try:
            m.reset_name_cache()
        except Exception:
            pass

    m = sys.modules.get("playbalance.game_runner")
    if m is not None:
        try:
            m._teams_by_id.cache_clear()
        except Exception:
            pass

    m = sys.modules.get("utils.roster_loader")
    if m is not None:
        try:
            m.load_roster.cache_clear()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def _isolate_env():
    """Restore leaked NEXGEN_*/PB_SIM_* env vars around each test (cheap). Full
    cross-file isolation is provided by ``scripts/run_tests_isolated.py``, which
    runs each test file in its own process — the reliable green gate on Windows,
    where the suite's shared process-global state (active data dir, module-level
    singletons, and tests that importlib.reload modules) otherwise makes a single
    ``pytest`` invocation flaky across files even though every file passes alone."""

    env_snapshot = {key: os.environ.get(key) for key in _ENV_KEYS}
    try:
        yield
    finally:
        for key, value in env_snapshot.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def pytest_sessionfinish(session, exitstatus):
    """Leave the working tree clean: revert any data/ pollution a run produced
    (untracked league files + tracked-file edits) in one shot at the end."""

    try:
        _reset_shared_state()
        subprocess.run(["git", "checkout", "--", "data"], cwd=_REPO_ROOT,
                       capture_output=True, timeout=60)
        subprocess.run(["git", "clean", "-fdq", "--", "data/leagues"], cwd=_REPO_ROOT,
                       capture_output=True, timeout=60)
    except Exception:
        pass
