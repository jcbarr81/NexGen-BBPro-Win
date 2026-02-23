from __future__ import annotations


def _legacy_module():
    import ui.admin_dashboard  # noqa: F401
    import ui._admin_dashboard_legacy as admin_legacy

    return admin_legacy


def test_show_admin_league_setup_tutorial_dispatches_expected_payload():
    admin_dashboard = _legacy_module()
    captured: list[tuple[str, str, int, bool]] = []

    class _Dummy:
        _admin_tutorial_keys = {"league_setup": "admin_tutorial_league_setup"}

        def _run_admin_tutorial(self, key, title, steps, *, force=False):
            captured.append((key, title, len(steps), force))

    admin_dashboard.MainWindow.show_admin_league_setup_tutorial(_Dummy(), force=True)

    assert captured == [
        ("admin_tutorial_league_setup", "League Setup & Manager", 3, True)
    ]


def test_show_admin_transaction_tutorial_dispatches_expected_payload():
    admin_dashboard = _legacy_module()
    captured: list[tuple[str, str, int, bool]] = []

    class _Dummy:
        _admin_tutorial_keys = {"transactions": "admin_tutorial_transactions"}

        def _run_admin_tutorial(self, key, title, steps, *, force=False):
            captured.append((key, title, len(steps), force))

    admin_dashboard.MainWindow.show_admin_transaction_queues_tutorial(
        _Dummy(),
        force=False,
    )

    assert captured == [
        ("admin_tutorial_transactions", "Trade & Review Queues", 3, False)
    ]


def test_maybe_auto_show_admin_tutorials_calls_overview():
    admin_dashboard = _legacy_module()
    events: list[bool] = []

    class _Dummy:
        def show_admin_dashboard_overview_tutorial(self):
            events.append(True)

    admin_dashboard.MainWindow._maybe_auto_show_admin_tutorials(_Dummy())

    assert events == [True]


def test_run_admin_tutorial_marks_flag_and_saves(monkeypatch):
    admin_dashboard = _legacy_module()
    dialogs: list[tuple[str, int]] = []
    saves: list[bool] = []

    class _FakeTutorialDialog:
        def __init__(self, *, title, steps, parent=None):
            dialogs.append((title, len(steps)))

        def exec(self):
            return 0

    class _Dummy:
        _admin_tutorial_flags: dict[str, bool] = {}
        _admin_tutorial_dialog_open = False

        def _save_admin_tutorial_flags(self):
            saves.append(True)

    monkeypatch.setattr(admin_dashboard, "TutorialDialog", _FakeTutorialDialog)
    steps = [admin_dashboard.TutorialStep("Step", "<p>Body</p>")]
    admin_dashboard.MainWindow._run_admin_tutorial(
        _Dummy(),
        "admin_tutorial_overview",
        "Admin Dashboard Overview",
        steps,
        force=False,
    )

    assert dialogs == [("Admin Dashboard Overview", 1)]
    assert saves == [True]
