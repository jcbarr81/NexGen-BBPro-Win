from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from utils.park_utils import list_ballpark_names
from services.team_strategy_profiles import (
    DEFAULT_PROFILE,
    STRATEGY_PROFILES,
    TeamStrategyProfile,
    load_team_strategy_settings,
    resolve_team_strategy_profile,
)
from services.team_auto_reassign_settings import (
    DEFAULT_ENABLED as AUTO_REASSIGN_DEFAULT_ENABLED,
    TeamAutoReassignPreference,
    load_team_auto_reassign_settings,
    resolve_team_auto_reassign,
)
from .park_selector_dialog import (
    ParkSelectorDialog,
    _load_latest_parks,
    _park_config_path,
    _project_root,
)

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_CACHE_MISS = object()


def _normalize_hex_color(value: str, fallback: str) -> str:
    candidate = (value or "").strip()
    if HEX_COLOR_RE.fullmatch(candidate):
        return candidate.upper()
    return fallback.upper()


def _park_lookup_key(name: str) -> str:
    return (name or "").strip().lower()


def _build_park_lookup(parks: list[Any]) -> Dict[str, Any]:
    lookup: Dict[str, Any] = {}
    for park in parks:
        key = _park_lookup_key(getattr(park, "name", ""))
        if key and key not in lookup:
            lookup[key] = park
    return lookup


def _match_park_by_name(lookup: Dict[str, Any], name: str) -> Optional[Any]:
    key = _park_lookup_key(name)
    if not key:
        return None
    exact = lookup.get(key)
    if exact is not None:
        return exact
    for known_name, park in lookup.items():
        if known_name.startswith(key) or key.startswith(known_name):
            return park
    return None


class TeamSettingsDialog(QDialog):
    """Dialog allowing an owner to configure basic team properties."""

    def __init__(self, team, parent=None):
        super().__init__(parent)
        self.team = team
        self.setWindowTitle("Team Settings")
        self._stadium_source_pixmap = None
        self._uniform_source_pixmap = None
        self._parks_by_name = _build_park_lookup(_load_latest_parks())
        self._park_preview_cache: Dict[str, Optional[Path]] = {}
        try:
            self._strategy_settings = load_team_strategy_settings()
            self._resolved_strategy = resolve_team_strategy_profile(
                getattr(team, "team_id", None)
            )
        except Exception:
            self._strategy_settings = {"default_profile": DEFAULT_PROFILE}
            meta = STRATEGY_PROFILES[DEFAULT_PROFILE]
            self._resolved_strategy = TeamStrategyProfile(
                team_id=str(getattr(team, "team_id", "") or "").strip(),
                profile=DEFAULT_PROFILE,
                label=str(meta.get("label", "Balanced")),
                description=str(meta.get("description", "")),
                source="league_default",
            )
        try:
            self._auto_reassign_settings = load_team_auto_reassign_settings()
            self._resolved_auto_reassign = resolve_team_auto_reassign(
                getattr(team, "team_id", None)
            )
        except Exception:
            self._auto_reassign_settings = {"default_enabled": AUTO_REASSIGN_DEFAULT_ENABLED}
            self._resolved_auto_reassign = TeamAutoReassignPreference(
                team_id=str(getattr(team, "team_id", "") or "").strip(),
                enabled=AUTO_REASSIGN_DEFAULT_ENABLED,
                source="league_default",
            )

        layout = QVBoxLayout()

        # Colors
        color_row = QHBoxLayout()
        from PyQt6.QtCore import QRegularExpression
        from PyQt6.QtGui import QRegularExpressionValidator

        hex_regex = QRegularExpression(r"#[0-9A-Fa-f]{6}")
        validator = QRegularExpressionValidator(hex_regex, self)

        color_row.addWidget(QLabel("Primary Color:"))
        self.primary_edit = QLineEdit(team.primary_color)
        self.primary_edit.setValidator(validator)
        color_row.addWidget(self.primary_edit)
        primary_btn = QPushButton("Choose")
        primary_btn.clicked.connect(lambda: self.choose_color(self.primary_edit))
        color_row.addWidget(primary_btn)

        color_row.addWidget(QLabel("Secondary Color:"))
        self.secondary_edit = QLineEdit(team.secondary_color)
        self.secondary_edit.setValidator(validator)
        color_row.addWidget(self.secondary_edit)
        secondary_btn = QPushButton("Choose")
        secondary_btn.clicked.connect(lambda: self.choose_color(self.secondary_edit))
        color_row.addWidget(secondary_btn)

        layout.addLayout(color_row)

        # Stadium selection
        stadium_row = QHBoxLayout()
        stadium_row.addWidget(QLabel("Stadium:"))
        self.stadium_combo = QComboBox()
        self.stadium_combo.setEditable(True)
        self.stadium_combo.addItems(list_ballpark_names())
        if team.stadium:
            self.stadium_combo.setCurrentText(team.stadium)
        stadium_row.addWidget(self.stadium_combo)

        browse_btn = QPushButton("Browse MLB Parks...")
        browse_btn.clicked.connect(self._open_park_selector)
        stadium_row.addWidget(browse_btn)
        layout.addLayout(stadium_row)

        # Team strategy profile
        strategy_row = QHBoxLayout()
        strategy_row.addWidget(QLabel("Team Strategy:"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem("Use League Default", "")
        for profile_id, meta in STRATEGY_PROFILES.items():
            label = str(meta.get("label", profile_id.title()))
            self.strategy_combo.addItem(label, profile_id)
        if self._resolved_strategy.source == "team_override":
            idx = self.strategy_combo.findData(self._resolved_strategy.profile)
            self.strategy_combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.strategy_combo.setCurrentIndex(0)
        strategy_row.addWidget(self.strategy_combo)
        layout.addLayout(strategy_row)

        self.strategy_label = QLabel()
        self.strategy_label.setWordWrap(True)
        layout.addWidget(self.strategy_label)

        # Team auto-reassign profile
        auto_reassign_row = QHBoxLayout()
        auto_reassign_row.addWidget(QLabel("Roster Auto-Reassign:"))
        self.auto_reassign_combo = QComboBox()
        self.auto_reassign_combo.addItem("Use League Default", "")
        self.auto_reassign_combo.addItem("Enabled", "enabled")
        self.auto_reassign_combo.addItem("Disabled", "disabled")
        if self._resolved_auto_reassign.source == "team_override":
            selected = "enabled" if self._resolved_auto_reassign.enabled else "disabled"
            idx = self.auto_reassign_combo.findData(selected)
            self.auto_reassign_combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            self.auto_reassign_combo.setCurrentIndex(0)
        auto_reassign_row.addWidget(self.auto_reassign_combo)
        layout.addLayout(auto_reassign_row)

        self.auto_reassign_label = QLabel()
        self.auto_reassign_label.setWordWrap(True)
        layout.addWidget(self.auto_reassign_label)

        # Live visual previews
        preview_row = QHBoxLayout()
        stadium_col = QVBoxLayout()
        uniform_col = QVBoxLayout()

        stadium_col.addWidget(QLabel("Stadium Preview"))
        self.stadium_preview = QLabel()
        self.stadium_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stadium_preview.setMinimumSize(420, 240)
        self.stadium_preview.setStyleSheet(
            "background:#111; color:#ddd; border:1px solid #555; border-radius:4px;"
        )
        stadium_col.addWidget(self.stadium_preview)

        self.stadium_label = QLabel()
        stadium_col.addWidget(self.stadium_label)

        uniform_col.addWidget(QLabel("Uniform Preview"))
        self.uniform_preview = QLabel()
        self.uniform_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.uniform_preview.setMinimumSize(250, 240)
        self.uniform_preview.setStyleSheet(
            "background:#eef1f4; border:1px solid #c3c8ce; border-radius:4px;"
        )
        uniform_col.addWidget(self.uniform_preview)

        self.uniform_palette_label = QLabel()
        uniform_col.addWidget(self.uniform_palette_label)

        preview_row.addLayout(stadium_col, 3)
        preview_row.addLayout(uniform_col, 2)
        layout.addLayout(preview_row)

        # Action buttons
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.setLayout(layout)

        self.stadium_combo.currentTextChanged.connect(self._on_stadium_changed)
        self.primary_edit.textChanged.connect(self._update_uniform_preview)
        self.secondary_edit.textChanged.connect(self._update_uniform_preview)
        self.strategy_combo.currentIndexChanged.connect(self._update_strategy_label)
        self.auto_reassign_combo.currentIndexChanged.connect(
            self._update_auto_reassign_label
        )
        self._on_stadium_changed(self.stadium_combo.currentText())
        self._update_uniform_preview()
        self._update_strategy_label()
        self._update_auto_reassign_label()

    def choose_color(self, edit):
        """Open a color dialog and set the selected color on the given line edit."""
        from PyQt6.QtWidgets import QColorDialog
        from PyQt6.QtGui import QColor

        current = edit.text() or "#ffffff"
        color = QColorDialog.getColor(QColor(current), self, "Select Color")
        if color.isValid():
            edit.setText(color.name())

    def get_settings(self):
        primary = self.primary_edit.text().strip()
        secondary = self.secondary_edit.text().strip()
        return {
            "primary_color": primary if self.primary_edit.hasAcceptableInput() else "",
            "secondary_color": secondary if self.secondary_edit.hasAcceptableInput() else "",
            "stadium": self.stadium_combo.currentText(),
            "strategy_profile_override": str(self.strategy_combo.currentData() or ""),
            "auto_reassign_override": str(self.auto_reassign_combo.currentData() or ""),
        }

    def _open_park_selector(self):
        dlg = ParkSelectorDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.selected_name:
            # Set the chosen park NAME as the stadium string
            self.stadium_combo.setCurrentText(dlg.selected_name)

    def _on_stadium_changed(self, text: str) -> None:
        self._update_stadium_label(text)
        self._update_stadium_preview(text)

    def _update_stadium_label(self, text: str) -> None:
        name = (text or "").strip()
        if name:
            self.stadium_label.setText(f"Current MLB park: {name}")
        else:
            self.stadium_label.setText("Current MLB park: Not set")

    def _strategy_default_label(self) -> str:
        profile_id = str(
            self._strategy_settings.get("default_profile", DEFAULT_PROFILE) or DEFAULT_PROFILE
        )
        meta = STRATEGY_PROFILES.get(profile_id, STRATEGY_PROFILES[DEFAULT_PROFILE])
        return str(meta.get("label", "Balanced"))

    def _update_strategy_label(self) -> None:
        selected = str(self.strategy_combo.currentData() or "").strip().lower()
        if selected:
            resolved = selected
            source = "Team Override"
        else:
            resolved = str(
                self._strategy_settings.get("default_profile", DEFAULT_PROFILE)
                or DEFAULT_PROFILE
            )
            source = "League Default"
        meta = STRATEGY_PROFILES.get(resolved, STRATEGY_PROFILES[DEFAULT_PROFILE])
        label = str(meta.get("label", "Balanced"))
        description = str(meta.get("description", ""))
        default_label = self._strategy_default_label()
        self.strategy_label.setText(
            f"Effective strategy: {label} ({source}). League default: {default_label}. {description}"
        )

    def _auto_reassign_default_label(self) -> str:
        enabled = bool(
            self._auto_reassign_settings.get(
                "default_enabled",
                AUTO_REASSIGN_DEFAULT_ENABLED,
            )
        )
        return "Enabled" if enabled else "Disabled"

    def _update_auto_reassign_label(self) -> None:
        selected = str(self.auto_reassign_combo.currentData() or "").strip().lower()
        if selected == "enabled":
            enabled = True
            source = "Team Override"
        elif selected == "disabled":
            enabled = False
            source = "Team Override"
        else:
            enabled = bool(
                self._auto_reassign_settings.get(
                    "default_enabled",
                    AUTO_REASSIGN_DEFAULT_ENABLED,
                )
            )
            source = "League Default"
        effective = "Enabled" if enabled else "Disabled"
        default_label = self._auto_reassign_default_label()
        self.auto_reassign_label.setText(
            "Effective auto-reassign: "
            f"{effective} ({source}). League default: {default_label}. "
            "When enabled, the game auto-balances ACT/AAA/LOW after injury, "
            "promotion, and transaction roster updates."
        )

    def _park_preview_path(self, park: Any) -> Optional[Path]:
        park_id = (getattr(park, "park_id", "") or "").strip()
        year = int(getattr(park, "year", 0) or 0)
        if not park_id or year <= 0:
            return None
        return _project_root() / "images" / "parks" / f"{park_id}_{year}.png"

    def _ensure_park_preview_image(self, park: Any) -> Optional[Path]:
        img_path = self._park_preview_path(park)
        if img_path is None:
            return None
        park_id = (getattr(park, "park_id", "") or "").strip()
        year = int(getattr(park, "year", 0) or 0)
        cache_key = f"{park_id}:{year}"
        cached = self._park_preview_cache.get(cache_key, _CACHE_MISS)
        if cached is not _CACHE_MISS:
            return cached
        if img_path.exists():
            self._park_preview_cache[cache_key] = img_path
            return img_path
        try:
            from scripts import generate_park_diagrams as gen

            parks = gen.load_parks(_park_config_path())
            candidates = [r for r in parks if r.park_id == park_id and r.year == year]
            if candidates:
                img_path.parent.mkdir(parents=True, exist_ok=True)
                gen.draw_diagram(candidates[0], img_path)
        except Exception:
            self._park_preview_cache[cache_key] = None
            return None
        if img_path.exists():
            self._park_preview_cache[cache_key] = img_path
            return img_path
        self._park_preview_cache[cache_key] = None
        return None

    def _set_stadium_preview_placeholder(self, name: str) -> None:
        from PyQt6.QtGui import QPixmap

        self._stadium_source_pixmap = None
        self.stadium_preview.setPixmap(QPixmap())
        label = (name or "").strip()
        if label:
            self.stadium_preview.setText(f"{label}\n(No stadium preview available)")
        else:
            self.stadium_preview.setText("Select a stadium to preview")

    def _apply_stadium_preview_scale(self) -> None:
        if self._stadium_source_pixmap is None:
            return
        scaled = self._stadium_source_pixmap.scaled(
            self.stadium_preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.stadium_preview.setPixmap(scaled)

    def _update_stadium_preview(self, text: str) -> None:
        from PyQt6.QtGui import QPixmap

        park = _match_park_by_name(self._parks_by_name, text)
        if park is None:
            self._set_stadium_preview_placeholder(text)
            return

        img_path = self._ensure_park_preview_image(park)
        if img_path is None:
            self._set_stadium_preview_placeholder(text)
            return

        pix = QPixmap(str(img_path))
        if pix.isNull():
            self._set_stadium_preview_placeholder(text)
            return

        self._stadium_source_pixmap = pix
        self.stadium_preview.setText("")
        self._apply_stadium_preview_scale()

    def _apply_uniform_preview_scale(self) -> None:
        if self._uniform_source_pixmap is None:
            return
        scaled = self._uniform_source_pixmap.scaled(
            self.uniform_preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.uniform_preview.setPixmap(scaled)

    def _render_uniform_preview(self, primary_hex: str, secondary_hex: str):
        from PyQt6.QtGui import QColor, QPainter, QPixmap

        pix = QPixmap(300, 240)
        pix.fill(QColor("#EEF1F4"))
        painter = QPainter(pix)

        if not all(
            callable(getattr(painter, method, None))
            for method in (
                "setPen",
                "setBrush",
                "drawRoundedRect",
                "drawRect",
                "drawLine",
                "drawEllipse",
            )
        ):
            if callable(getattr(painter, "end", None)):
                painter.end()
            return pix

        primary = QColor(primary_hex)
        secondary = QColor(secondary_hex)
        outline = QColor("#394048")

        set_render_hint = getattr(painter, "setRenderHint", None)
        render_hint = getattr(getattr(QPainter, "RenderHint", None), "Antialiasing", None)
        if callable(set_render_hint) and render_hint is not None:
            set_render_hint(render_hint, True)

        painter.setPen(outline)
        painter.setBrush(primary)
        painter.drawRoundedRect(80, 44, 140, 168, 18, 18)

        painter.setPen(secondary)
        painter.setBrush(secondary)
        painter.drawRoundedRect(122, 44, 56, 24, 8, 8)
        painter.drawRect(84, 94, 20, 14)
        painter.drawRect(196, 94, 20, 14)
        painter.drawRect(110, 182, 80, 8)
        painter.drawLine(150, 68, 150, 182)

        painter.setPen(outline)
        painter.setBrush(primary)
        painter.drawEllipse(212, 18, 62, 30)
        painter.setPen(secondary)
        painter.setBrush(secondary)
        painter.drawEllipse(232, 34, 22, 8)

        if callable(getattr(painter, "end", None)):
            painter.end()
        return pix

    def _update_uniform_preview(self) -> None:
        primary = _normalize_hex_color(self.primary_edit.text(), "#1F4E79")
        secondary = _normalize_hex_color(self.secondary_edit.text(), "#C9A14A")
        self.uniform_palette_label.setText(f"Primary: {primary} | Secondary: {secondary}")
        self._uniform_source_pixmap = self._render_uniform_preview(primary, secondary)
        self.uniform_preview.setText("")
        self._apply_uniform_preview_scale()

    def resizeEvent(self, event):  # noqa: N802 - Qt signature
        super().resizeEvent(event)
        self._apply_stadium_preview_scale()
        self._apply_uniform_preview_scale()

