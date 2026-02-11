"""Dialog allowing owners to tune hitter/pitcher training allocations."""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Optional

try:  # pragma: no cover - PyQt fallback stubs for headless tests
    from PyQt6.QtWidgets import (
        QDialog,
        QVBoxLayout,
        QLabel,
        QGroupBox,
        QGridLayout,
        QSpinBox,
        QDialogButtonBox,
        QPushButton,
        QMessageBox,
    )
except Exception:  # pragma: no cover - lightweight stubs
    class DummySignal:
        def __init__(self) -> None:
            self._slot = None

        def connect(self, slot):
            self._slot = slot

        def emit(self, *args, **kwargs):
            if self._slot:
                self._slot(*args, **kwargs)

    class _WidgetDummy:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __getattr__(self, name):
            def _noop(*_args, **_kwargs):
                return None

            return _noop

    class QDialog(_WidgetDummy):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._result = 0

        def exec(self):
            return self._result

        def accept(self):
            self._result = 1

        def reject(self):
            self._result = 0

    class QLabel(_WidgetDummy):
        def __init__(self, text: str = "", *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._text = text

        def setText(self, text: str) -> None:
            self._text = text

        def text(self) -> str:
            return self._text

        def setWordWrap(self, *_args, **_kwargs) -> None:
            pass

    class QGroupBox(_WidgetDummy):
        pass

    class QGridLayout(_WidgetDummy):
        def addWidget(self, *args, **kwargs):
            pass

    class QVBoxLayout(_WidgetDummy):
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def addWidget(self, *_args, **_kwargs) -> None:
            pass

        def addSpacing(self, *_args, **_kwargs) -> None:
            pass

    class QSpinBox(_WidgetDummy):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self._value = 0
            self.valueChanged = DummySignal()

        def setRange(self, *_args, **_kwargs) -> None:
            pass

        def setSuffix(self, *_args, **_kwargs) -> None:
            pass

        def setSingleStep(self, *_args, **_kwargs) -> None:
            pass

        def value(self) -> int:
            return int(self._value)

        def setValue(self, value: int) -> None:
            self._value = int(value)
            self.valueChanged.emit(self._value)

        def blockSignals(self, *_args, **_kwargs) -> None:
            pass

    class QPushButton(_WidgetDummy):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.clicked = DummySignal()

    class QDialogButtonBox(_WidgetDummy):
        class ButtonRole:
            AcceptRole = 0
            RejectRole = 1
            ResetRole = 2

        class StandardButton:
            Cancel = 0

        def __init__(self, *_args, **_kwargs) -> None:
            self.rejected = DummySignal()

        def addButton(self, button, *_args, **_kwargs) -> None:
            pass

    class QMessageBox(_WidgetDummy):
        @staticmethod
        def warning(*_args, **_kwargs) -> None:
            pass

from services.training_settings import (
    MIN_PERCENT,
    HITTER_TRACKS,
    PITCHER_TRACKS,
    load_training_settings,
    set_player_training_weights,
    clear_player_training_weights,
    set_team_training_weights,
    clear_team_training_weights,
    update_league_training_defaults,
)

HITTER_LABELS = {
    "contact": "Contact",
    "power": "Power",
    "speed": "Speed",
    "discipline": "Discipline",
    "defense": "Defense",
}

PITCHER_LABELS = {
    "command": "Command",
    "movement": "Movement",
    "stamina": "Stamina",
    "velocity": "Velocity",
    "hold": "Hold Runner",
    "pitch_lab": "Pitch Design",
}


class TrainingFocusDialog(QDialog):
    """Dialog used by owners/commissioners to tune training allocations."""

    def __init__(
        self,
        *,
        team_id: Optional[str] = None,
        team_name: Optional[str] = None,
        player_id: Optional[str] = None,
        player_name: Optional[str] = None,
        mode: str = "team",
        bulk_label: Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if mode not in {"team", "league", "player", "bulk"}:
            if player_id:
                mode = "player"
            elif team_id:
                mode = "team"
            else:
                mode = "league"
        if mode == "player" and not player_id:
            mode = "team" if team_id else "league"
        if mode == "bulk":
            player_id = None
        self._mode = mode
        self._team_id = (
            team_id if self._mode in {"team", "player", "bulk"} else None
        )
        self._player_id = player_id if self._mode == "player" else None
        self._player_name = player_name or player_id or "Player"
        self._team_name = team_name or team_id or "Team"
        self._bulk_label = bulk_label
        self._result_message: Optional[str] = None
        self._result_weights: Optional[tuple[Dict[str, int], Dict[str, int]]] = None
        self._settings = load_training_settings()
        self._team_override_active = (
            self._mode == "team"
            and self._team_id is not None
            and self._team_id in self._settings.team_overrides
        )
        self._player_override_active = (
            self._mode == "player"
            and self._player_id is not None
            and self._player_id in self._settings.player_overrides
        )

        self.hitter_spins: Dict[str, QSpinBox] = {}
        self.pitcher_spins: Dict[str, QSpinBox] = {}
        self.hitter_total_label: Optional[QLabel] = None
        self.pitcher_total_label: Optional[QLabel] = None

        self._build_ui()
        self._load_initial_values()
        self._update_totals()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        if self._mode == "team":
            title = f"{self._team_name} Training Focus"
        elif self._mode == "player":
            title = f"{self._player_name} Training Focus"
        elif self._mode == "bulk":
            title = "Bulk Training Focus"
        else:
            title = "League Training Focus"
        self.setWindowTitle(title)

        root = QVBoxLayout(self)

        intro = QLabel(
            "Adjust how offseason training time is split across focus tracks. "
            "Hitters and pitchers each need allocations that total 100%."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        if self._mode in {"team", "player", "bulk"}:
            self.status_label = QLabel()
            self.status_label.setWordWrap(True)
            root.addWidget(self.status_label)
        else:
            self.status_label = None

        hitters_group, hitter_total = self._build_group(
            "Hitters", HITTER_TRACKS, HITTER_LABELS, self.hitter_spins
        )
        self.hitter_total_label = hitter_total
        root.addWidget(hitters_group)

        pitchers_group, pitcher_total = self._build_group(
            "Pitchers", PITCHER_TRACKS, PITCHER_LABELS, self.pitcher_spins
        )
        self.pitcher_total_label = pitcher_total
        root.addWidget(pitchers_group)

        root.addSpacing(6)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save_button = QPushButton("Save")
        button_box.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_button.clicked.connect(self._on_save_clicked)
        button_box.rejected.connect(self.reject)

        if self._mode in {"team", "player"} and (self._team_id or self._player_id):
            default_label = (
                "Use Team Default"
                if self._mode == "player" and self._team_id
                else "Use League Default"
            )
            self.use_default_button = QPushButton(default_label)
            button_box.addButton(
                self.use_default_button, QDialogButtonBox.ButtonRole.ResetRole
            )
            self.use_default_button.clicked.connect(self._on_use_default_clicked)
        else:
            self.use_default_button = None

        root.addWidget(button_box)
        self.save_button.setEnabled(False)

    def _build_group(
        self,
        title: str,
        tracks: Iterable[str],
        labels: Mapping[str, str],
        store: Dict[str, QSpinBox],
    ):
        track_list = tuple(tracks)
        group = QGroupBox(title)
        layout = QGridLayout(group)
        for row, track in enumerate(track_list):
            label = QLabel(labels.get(track, track.replace("_", " ").title()))
            layout.addWidget(label, row, 0)
            spin = QSpinBox()
            spin.setRange(MIN_PERCENT, 100)
            spin.setSingleStep(1)
            spin.setSuffix("%")
            spin.valueChanged.connect(self._update_totals)
            layout.addWidget(spin, row, 1)
            store[track] = spin
        total_label = QLabel("Total: 0%")
        layout.addWidget(total_label, len(track_list), 0, 1, 2)
        return group, total_label

    # ------------------------------------------------------------------
    def _load_initial_values(self) -> None:
        if self._mode == "team":
            weights = self._settings.for_team(self._team_id)
            if self.status_label is not None:
                if self._team_override_active:
                    self.status_label.setText("Custom allocation active for this team.")
                else:
                    self.status_label.setText("Currently using league default allocations.")
        elif self._mode == "player":
            weights = self._settings.for_player(self._player_id, self._team_id)
            if self.status_label is not None:
                if self._player_override_active:
                    self.status_label.setText(
                        "Custom allocation active for this player."
                    )
                elif self._team_id and self._team_id in self._settings.team_overrides:
                    self.status_label.setText("Currently using team default allocations.")
                else:
                    self.status_label.setText("Currently using league default allocations.")
        elif self._mode == "bulk":
            weights = self._settings.for_team(self._team_id)
            if self.status_label is not None:
                label = self._bulk_label or "Apply these allocations to the selected players."
                self.status_label.setText(label)
        else:
            weights = self._settings.defaults

        self._apply_weights(weights)
        self._sync_use_default_button()

    def _apply_weights(self, weights) -> None:
        for track, spin in self.hitter_spins.items():
            value = int(round(float(weights.hitters.get(track, MIN_PERCENT))))
            try:
                spin.blockSignals(True)
            except Exception:
                pass
            spin.setValue(value)
            try:
                spin.blockSignals(False)
            except Exception:
                pass
        for track, spin in self.pitcher_spins.items():
            value = int(round(float(weights.pitchers.get(track, MIN_PERCENT))))
            try:
                spin.blockSignals(True)
            except Exception:
                pass
            spin.setValue(value)
            try:
                spin.blockSignals(False)
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _update_totals(self, *_args) -> None:
        hitter_total = sum(spin.value() for spin in self.hitter_spins.values())
        pitcher_total = sum(spin.value() for spin in self.pitcher_spins.values())
        if self.hitter_total_label is not None:
            self.hitter_total_label.setText(f"Hitters total: {hitter_total}%")
        if self.pitcher_total_label is not None:
            self.pitcher_total_label.setText(f"Pitchers total: {pitcher_total}%")
        self.save_button.setEnabled(hitter_total == 100 and pitcher_total == 100)

    # ------------------------------------------------------------------
    def _collect_values(self) -> tuple[Dict[str, int], Dict[str, int]]:
        hitters = {track: spin.value() for track, spin in self.hitter_spins.items()}
        pitchers = {track: spin.value() for track, spin in self.pitcher_spins.items()}
        return hitters, pitchers

    def _on_save_clicked(self) -> None:
        hitters, pitchers = self._collect_values()
        try:
            if self._mode == "team" and self._team_id:
                set_team_training_weights(self._team_id, hitters, pitchers)
                self._team_override_active = True
                self._result_message = f"{self._team_name} training focus saved."
                if self.status_label is not None:
                    self.status_label.setText("Custom allocation active for this team.")
            elif self._mode == "player" and self._player_id:
                set_player_training_weights(self._player_id, hitters, pitchers)
                self._player_override_active = True
                self._result_message = f"{self._player_name} training focus saved."
                if self.status_label is not None:
                    self.status_label.setText(
                        "Custom allocation active for this player."
                    )
            elif self._mode == "bulk":
                self._result_weights = (hitters, pitchers)
                self._result_message = "Training focus ready to apply."
            else:
                update_league_training_defaults(hitters, pitchers)
                self._result_message = "League training focus defaults saved."
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid allocations", str(exc))
            return
        self._sync_use_default_button()
        self.accept()

    def _on_use_default_clicked(self) -> None:
        if self._mode == "team":
            if not self._team_id:
                return
            clear_team_training_weights(self._team_id)
            self._team_override_active = False
            self._result_message = (
                f"{self._team_name} reverted to the league training focus."
            )
            if self.status_label is not None:
                self.status_label.setText(
                    "Currently using league default allocations."
                )
        elif self._mode == "player":
            if not self._player_id:
                return
            clear_player_training_weights(self._player_id)
            self._player_override_active = False
            default_label = "team" if self._team_id else "league"
            self._result_message = (
                f"{self._player_name} reverted to the {default_label} training focus."
            )
            if self.status_label is not None:
                if self._team_id and self._team_id in self._settings.team_overrides:
                    self.status_label.setText("Currently using team default allocations.")
                else:
                    self.status_label.setText(
                        "Currently using league default allocations."
                    )
        else:
            return
        self._sync_use_default_button()
        self.accept()

    # ------------------------------------------------------------------
    @property
    def result_message(self) -> Optional[str]:
        return self._result_message

    @property
    def result_weights(self) -> Optional[tuple[Dict[str, int], Dict[str, int]]]:
        return self._result_weights

    def _sync_use_default_button(self) -> None:
        if self.use_default_button is not None:
            try:
                if self._mode == "player":
                    active = self._player_override_active
                else:
                    active = self._team_override_active
                self.use_default_button.setEnabled(active)
            except Exception:
                pass
