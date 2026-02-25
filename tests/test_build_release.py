from __future__ import annotations

import scripts.build_release as build_release


def test_build_release_runs_validation_gate_by_default(monkeypatch):
    calls: list[list[str]] = []

    def _fake_run_command(cmd: list[str], cwd=None) -> None:  # noqa: ANN001
        calls.append(list(cmd))

    monkeypatch.setattr(build_release, "run_command", _fake_run_command)

    exit_code = build_release.main(
        [
            "--skip-exe",
            "--skip-installer",
            "--skip-iss",
            "--skip-notes",
        ]
    )

    assert exit_code == 0
    assert len(calls) == 2
    help_cmd = calls[0]
    validate_cmd = calls[1]
    assert help_cmd[1] == str(build_release.VALIDATE_HELP_SURFACE)
    assert "--json-out" in help_cmd
    assert validate_cmd[1] == str(build_release.VALIDATE_RELEASE)
    assert "--seasons" in validate_cmd
    assert "--seed" in validate_cmd
    assert "--preset" in validate_cmd


def test_build_release_skip_validation_disables_gate(monkeypatch):
    calls: list[list[str]] = []

    def _fake_run_command(cmd: list[str], cwd=None) -> None:  # noqa: ANN001
        calls.append(list(cmd))

    monkeypatch.setattr(build_release, "run_command", _fake_run_command)

    exit_code = build_release.main(
        [
            "--skip-validation",
            "--skip-exe",
            "--skip-installer",
            "--skip-iss",
            "--skip-notes",
        ]
    )

    assert exit_code == 0
    assert len(calls) == 1
    help_cmd = calls[0]
    assert help_cmd[1] == str(build_release.VALIDATE_HELP_SURFACE)


def test_build_release_requires_ui_checklist_artifact(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def _fake_run_command(cmd: list[str], cwd=None) -> None:  # noqa: ANN001
        calls.append(list(cmd))

    artifact = tmp_path / "ui_checklist.md"
    artifact.write_text(
        (
            "# UI/Installer Checklist Archive - v5.0.74\n"
            "Checklist Result: PASS\n"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(build_release, "run_command", _fake_run_command)
    monkeypatch.setattr(build_release, "read_version", lambda: "5.0.74")

    exit_code = build_release.main(
        [
            "--require-ui-checklist",
            "--ui-checklist-artifact",
            str(artifact),
            "--skip-exe",
            "--skip-installer",
            "--skip-iss",
            "--skip-notes",
        ]
    )

    assert exit_code == 0
    assert len(calls) == 2
    assert calls[0][1] == str(build_release.VALIDATE_HELP_SURFACE)
    assert calls[1][1] == str(build_release.VALIDATE_RELEASE)


def test_build_release_rejects_missing_ui_checklist_artifact(monkeypatch):
    monkeypatch.setattr(build_release, "read_version", lambda: "5.0.74")
    try:
        build_release.main(
            [
                "--require-ui-checklist",
                "--skip-exe",
                "--skip-installer",
                "--skip-iss",
                "--skip-notes",
            ]
        )
    except ValueError as exc:
        assert "--require-ui-checklist requires --ui-checklist-artifact" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_release_can_skip_help_surface_validation(monkeypatch):
    calls: list[list[str]] = []

    def _fake_run_command(cmd: list[str], cwd=None) -> None:  # noqa: ANN001
        calls.append(list(cmd))

    monkeypatch.setattr(build_release, "run_command", _fake_run_command)

    exit_code = build_release.main(
        [
            "--skip-help-surface-validation",
            "--skip-validation",
            "--skip-exe",
            "--skip-installer",
            "--skip-iss",
            "--skip-notes",
        ]
    )

    assert exit_code == 0
    assert calls == []
