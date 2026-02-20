from __future__ import annotations

from pathlib import Path

import scripts.validate_finance_release as validate_finance_release


def test_validation_default_tests_include_ledger_and_contract_suites():
    expected = {
        "tests/test_finance_ledger.py",
        "tests/test_finance_ledger_usage.py",
        "tests/test_finance_budget_effects.py",
        "tests/test_finance_reporting.py",
        "tests/test_contracts_service.py",
        "tests/test_gm_finance_queue.py",
        "tests/test_owner_finance_engine.py",
        "tests/test_owner_finance_page.py",
        "tests/test_payroll_policy.py",
        "tests/test_aging_model.py",
        "tests/test_training_camp.py",
        "tests/test_player_development.py",
        "tests/test_offseason_finance_dialog.py",
        "tests/test_archive_ui_checklist.py",
        "tests/test_smoke_multi_league.py",
        "tests/test_phase5_path_isolation.py",
        "tests/test_league_registry.py",
        "tests/test_season_context_paths.py",
        "tests/test_build_release.py",
    }
    assert expected.issubset(set(validate_finance_release.DEFAULT_TESTS))


def test_validation_runs_multi_league_smoke_by_default(monkeypatch, tmp_path):
    calls: list[tuple[list[str], Path]] = []

    def _fake_run_command(cmd: list[str], *, cwd: Path | None = None) -> None:
        calls.append((cmd, cwd or Path.cwd()))

    monkeypatch.setattr(validate_finance_release, "run_command", _fake_run_command)

    exit_code = validate_finance_release.main(
        [
            "--skip-tests",
            "--skip-stability",
            "--python",
            "python.exe",
            "--report-dir",
            str(tmp_path / "reports"),
        ]
    )

    assert exit_code == 0
    assert len(calls) == 1
    smoke_cmd = calls[0][0]
    assert smoke_cmd[0] == "python.exe"
    assert smoke_cmd[1] == str(validate_finance_release.SMOKE_MULTI_LEAGUE_SCRIPT)
    assert "--json-out" in smoke_cmd


def test_validation_skip_smoke_flag(monkeypatch, tmp_path):
    calls: list[tuple[list[str], Path]] = []

    def _fake_run_command(cmd: list[str], *, cwd: Path | None = None) -> None:
        calls.append((cmd, cwd or Path.cwd()))

    monkeypatch.setattr(validate_finance_release, "run_command", _fake_run_command)

    exit_code = validate_finance_release.main(
        [
            "--skip-tests",
            "--skip-stability",
            "--skip-smoke",
            "--report-dir",
            str(tmp_path / "reports"),
        ]
    )

    assert exit_code == 0
    assert calls == []
