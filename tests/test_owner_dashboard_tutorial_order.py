from __future__ import annotations

import ui.owner_dashboard as owner_dashboard


def test_nav_change_updates_page_before_tutorial(monkeypatch):
    events: list[tuple[str, object]] = []

    class _Dummy:
        def _on_nav_changed(self, key):
            events.append(("nav", key))

        def _maybe_show_roster_tutorial(self, key):
            events.append(("tutorial", key))

    class _ImmediateTimer:
        @staticmethod
        def singleShot(ms, callback):
            events.append(("timer", ms))
            callback()

    monkeypatch.setattr(owner_dashboard, "QTimer", _ImmediateTimer)

    owner_dashboard.OwnerDashboard._on_nav_changed_with_tutorial(_Dummy(), "roster")

    assert events == [
        ("nav", "roster"),
        ("timer", 0),
        ("tutorial", "roster"),
    ]


def test_nav_change_tutorial_fallback_when_timer_unavailable(monkeypatch):
    events: list[tuple[str, object]] = []

    class _Dummy:
        def _on_nav_changed(self, key):
            events.append(("nav", key))

        def _maybe_show_roster_tutorial(self, key):
            events.append(("tutorial", key))

    monkeypatch.setattr(owner_dashboard, "QTimer", None)

    owner_dashboard.OwnerDashboard._on_nav_changed_with_tutorial(_Dummy(), "roster")

    assert events == [
        ("nav", "roster"),
        ("tutorial", "roster"),
    ]
